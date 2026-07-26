"""Provider protocol, structured-output repair, backoff, and resumability.

Three things live here because all three are judgment-heavy and must behave identically
across providers (D6, and `docs/MODEL_ROUTING.md` keeps repair semantics at Opus tier):

1. **Schema enforcement with repair-retry.** `complete_structured` validates against a
   pydantic model. On failure it feeds the validation error back and retries a bounded
   number of times, then **hard-fails**. It never returns a partially-parsed object and
   never drops a field — a silently dropped citation is an A1 violation that no downstream
   check would catch, because the object would look well-formed.

2. **Backoff.** Development runs on free tiers (B8), so 429s are the normal case rather
   than the exceptional one. Retry-After is honoured when the provider sends it.

3. **Resumability.** Responses are cached on disk by (provider, model, prompt, schema).
   A run interrupted by a rate limit resumes without re-paying for the calls that already
   succeeded. Plan §7 asks for this in Phase 0 precisely because retrofitting it *under* a
   live rate limit is painful.

Owning phase: 0 (task 0.3).
"""

from __future__ import annotations

import json
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from autodeck.ir.schema import SchemaFlavor, export_schema, schema_digest
from autodeck.providers.cache import ResponseCache

ModelT = TypeVar("ModelT", bound=BaseModel)

DEFAULT_MAX_REPAIR_ATTEMPTS = 3
DEFAULT_MAX_RATE_LIMIT_RETRIES = 5
DEFAULT_TIMEOUT_SECONDS = 120.0

#: Cap on a single backoff sleep. A free-tier daily-quota 429 will not clear inside any
#: sleep we are willing to take, so the run should fail and be resumed later from cache.
MAX_BACKOFF_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """Base class for every provider failure."""


class ProviderAuthError(ProviderError):
    """Missing or rejected credentials. Never retried — retrying cannot help."""


class RateLimitError(ProviderError):
    """A 429. Carries the provider's Retry-After hint when one was supplied."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderResponseError(ProviderError):
    """The provider replied, but the reply is unusable — a safety block, a refusal, no
    candidates, a body in an unexpected shape.

    **Not retried.** Unlike a 429 or a 503, this outcome is deterministic for a given
    request: re-sending identical input gets the identical block, and on a free tier that
    is quota spent to learn nothing. The repair loop, which changes the prompt, is the
    layer that can actually make progress here.
    """


class StructuredOutputError(ProviderError):
    """The model could not produce output matching the schema within the retry budget.

    This is deliberately terminal. The alternative — returning whatever parsed — is how an
    invented field or a dropped citation reaches the IR looking legitimate.
    """

    def __init__(self, message: str, *, attempts: int, last_error: str, last_raw: str) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.last_raw = last_raw


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """Token counts, when the provider reports them."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class RawResponse:
    """One provider reply, before schema validation."""

    text: str
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class ImageInput:
    """An image for a vision call."""

    data: bytes
    media_type: str = "image/png"


@dataclass
class ProviderConfig:
    """Everything a provider instance needs that is not per-call.

    `api_key` is resolved by the registry from the environment; it is never read from
    config files, and never written to a manifest.
    """

    model: str
    api_key: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS
    max_rate_limit_retries: int = DEFAULT_MAX_RATE_LIMIT_RETRIES
    temperature: float = 0.0
    max_output_tokens: int = 8192
    cache: ResponseCache | None = None
    transport: httpx.BaseTransport | None = None
    """Injected in tests so the repair and backoff paths are exercised without a network."""


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------


class BaseProvider(ABC):
    """Shared behaviour for every adapter.

    Subclasses describe *how to talk to one API*: build a request, pull text out of a
    response, and say which schema dialect the API speaks. Everything about correctness —
    repair, backoff, caching — is implemented once, here.
    """

    #: Which `SchemaFlavor` this provider's API accepts.
    schema_flavor: SchemaFlavor = "standard"

    #: Whether this provider's served models accept image input. Checked by the registry
    #: when binding the vision roles, so an unsupported binding fails at config load rather
    #: than deep inside an ingestion run.
    supports_vision: bool = True

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        if not config.api_key:
            raise ProviderAuthError(
                f"{self.name} has no API key. Set {self.api_key_env} in the environment."
            )

    # -- subclass contract -------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short provider name as used in config/models.yaml."""

    @property
    @abstractmethod
    def api_key_env(self) -> str:
        """Environment variable holding this provider's key."""

    @abstractmethod
    def build_request(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: dict[str, Any] | None,
        images: list[ImageInput],
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Return `(url, headers, json_body)` for one completion."""

    @abstractmethod
    def parse_response(self, payload: dict[str, Any]) -> RawResponse:
        """Pull the completion text (and usage, if reported) out of a response body."""

    # -- public API --------------------------------------------------------

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        images: list[ImageInput] | None = None,
    ) -> str:
        """Free-text completion."""
        return self._request(
            prompt=prompt, system=system, schema=None, images=images or []
        ).text

    def complete_structured(
        self,
        prompt: str,
        response_model: type[ModelT],
        *,
        system: str | None = None,
        images: list[ImageInput] | None = None,
    ) -> ModelT:
        """Generate output validated against `response_model`.

        Retries with the validation error appended to the prompt, then raises. The returned
        object is always fully valid — there is no partial-success path.

        Raises:
            StructuredOutputError: no attempt produced schema-valid output.
            RateLimitError: rate limited beyond the retry budget.
        """
        schema = export_schema(response_model, self.schema_flavor)
        attempt_prompt = prompt
        last_error = "no attempt was made"
        last_raw = ""

        for attempt in range(1, self.config.max_repair_attempts + 1):
            raw = self._request(
                prompt=attempt_prompt,
                system=system,
                schema=schema,
                images=images or [],
                # A repair attempt must not be served the cached reply that just failed.
                cache_salt=f"repair={attempt}" if attempt > 1 else "",
            )
            last_raw = raw.text
            try:
                return response_model.model_validate_json(_extract_json(raw.text))
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                attempt_prompt = _repair_prompt(prompt, raw.text, last_error)

        raise StructuredOutputError(
            f"{self.name}/{self.config.model} did not produce output matching "
            f"{response_model.__name__} in {self.config.max_repair_attempts} attempts. "
            "Failing rather than returning a partially-valid object — a dropped field here "
            "is an accuracy defect that looks like a clean result.",
            attempts=self.config.max_repair_attempts,
            last_error=last_error,
            last_raw=last_raw,
        )

    def vision(
        self,
        images: list[ImageInput],
        prompt: str,
        response_model: type[ModelT],
        *,
        system: str | None = None,
    ) -> ModelT:
        """Structured output over one or more images (the aesthetic and ingest_vlm roles)."""
        if not images:
            raise ValueError("vision() needs at least one image")
        return self.complete_structured(prompt, response_model, system=system, images=images)

    # -- transport ---------------------------------------------------------

    def _request(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: dict[str, Any] | None,
        images: list[ImageInput],
        cache_salt: str = "",
    ) -> RawResponse:
        cache_key = self._cache_key(prompt, system, schema, images, cache_salt)
        cache = self.config.cache
        if cache is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return RawResponse(text=cached)

        url, headers, body = self.build_request(
            prompt=prompt, system=system, schema=schema, images=images
        )
        response = self._send_with_backoff(url, headers, body)
        if cache is not None:
            cache.put(cache_key, response.text)
        return response

    def _send_with_backoff(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> RawResponse:
        """POST with exponential backoff on 429 and on transient 5xx."""
        last_error: ProviderError | None = None

        for attempt in range(self.config.max_rate_limit_retries + 1):
            try:
                return self._send_once(url, headers, body)
            except RateLimitError as exc:
                last_error = exc
                delay = exc.retry_after if exc.retry_after is not None else _backoff(attempt)
            except (ProviderAuthError, ProviderResponseError):
                # Neither improves on retry: a rejected key stays rejected, and an
                # unusable reply is deterministic for an identical request.
                raise
            except ProviderError as exc:
                last_error = exc
                delay = _backoff(attempt)

            if attempt < self.config.max_rate_limit_retries:
                self._sleep(min(delay, MAX_BACKOFF_SECONDS))

        assert last_error is not None
        raise last_error

    def _send_once(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> RawResponse:
        with httpx.Client(
            timeout=self.config.timeout, transport=self.config.transport
        ) as client:
            try:
                response = client.post(url, headers=headers, json=body)
            except httpx.RequestError as exc:
                raise ProviderError(f"{self.name}: request failed: {exc}") from exc

        if response.status_code == 429:
            raise RateLimitError(
                f"{self.name}: rate limited ({response.status_code})",
                retry_after=_retry_after(response),
            )
        if response.status_code in (401, 403):
            raise ProviderAuthError(
                f"{self.name}: credentials rejected ({response.status_code}). "
                f"Check {self.api_key_env}."
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}: {response.text[:500]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(f"{self.name}: response was not JSON: {exc}") from exc

        try:
            return self.parse_response(payload)
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            # An adapter must never let a raw parsing error escape the transport layer —
            # it would bypass the retry policy and surface as a stack trace about dicts.
            # A provider is free to change its response shape without telling us, so this
            # is a live path, not defensive padding.
            raise ProviderResponseError(f"{self.name}: unusable response: {exc}") from exc

    def _sleep(self, seconds: float) -> None:
        """Overridden in tests so backoff behaviour can be asserted without waiting."""
        time.sleep(seconds)

    def _cache_key(
        self,
        prompt: str,
        system: str | None,
        schema: dict[str, Any] | None,
        images: list[ImageInput],
        salt: str,
    ) -> str:
        parts = [
            self.name,
            self.config.model,
            f"temp={self.config.temperature}",
            f"system={system or ''}",
            f"prompt={prompt}",
            f"schema={schema_digest(schema) if schema else ''}",
            f"images={len(images)}",
            salt,
        ]
        return ResponseCache.make_key("\n".join(parts))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _extract_json(text: str) -> str:
    """Strip a markdown code fence if the model wrapped its JSON in one.

    Deliberately the *only* tolerance offered. Anything cleverer — hunting for the first
    balanced brace, repairing truncated JSON — risks silently reinterpreting the model's
    output, and a repair attempt with the parse error fed back is both safer and more
    likely to succeed.
    """
    match = _FENCE.match(text)
    return match.group(1) if match else text.strip()


def _repair_prompt(original: str, bad_output: str, error: str) -> str:
    """Re-ask with the validation error attached.

    Naming the failure is what makes the second attempt work; a bare "try again" mostly
    reproduces the same output.
    """
    return (
        f"{original}\n\n"
        "---\n"
        "Your previous response did not satisfy the required schema.\n\n"
        f"Previous response:\n{bad_output[:4000]}\n\n"
        f"Validation error:\n{error[:2000]}\n\n"
        "Return the corrected JSON only. Include every required field — omitting a field "
        "is not an acceptable way to resolve the error."
    )


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter: roughly 1s, 2s, 4s, 8s, 16s."""
    return (2.0**attempt) * (0.5 + random.random() * 0.5)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None  # HTTP-date form; fall back to exponential backoff


def json_dumps(value: Any) -> str:
    """Compact deterministic JSON, for building request bodies in adapters."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
