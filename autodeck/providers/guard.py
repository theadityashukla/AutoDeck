"""Say which role and model a provider failure belongs to.

A `RateLimitError` says "gemini: rate limited (429)". It does not say *which of five roles
on which of five models* ran out, and in the dev tier that is the whole question: each role
has its own daily bucket (B25). The agents are no help — `content`, `outline` and the
others wrap every provider exception in their own error type, and the evidence and
validation passes swallow them on purpose (an unjudged claim is reported as unjudged, not
as judged) — so by the time a failure reaches the CLI the role is gone.

`ProviderGuard` hands out providers for roles and remembers, at the moment of failure, which
role and model raised. It re-raises the **original** exception, so every agent keeps
behaving exactly as it did (including the ones that swallow it), and the CLI asks the guard
afterwards what it saw.

Only `RateLimitError` and `ProviderAuthError` are recorded: they are the two failures where
the right response is to stop, say what to do, and resume later. A malformed reply or a
transient 5xx is not.

Owning phase: 3b (the owner's run).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autodeck.providers.base import ProviderAuthError, RateLimitError
from autodeck.providers.cache import ResponseCache
from autodeck.providers.registry import ModelRegistry, api_key_env


@dataclass(frozen=True)
class ProviderFailureRecord:
    """One rate-limit or credential failure, with the role it happened in."""

    role: str
    provider: str
    model: str
    kind: str
    """`rate_limit`, `missing_key` (no key at all, before any call) or `rejected_key`."""
    env_var: str
    message: str
    exception: BaseException


class _RoleBound:
    """A provider whose rate-limit and credential failures are recorded against a role."""

    def __init__(self, inner: Any, guard: ProviderGuard, role: str) -> None:
        self._inner = inner
        self._guard = guard
        self._role = role

    def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._inner.complete_structured(*args, **kwargs)
        except (RateLimitError, ProviderAuthError) as exc:
            self._guard.record(self._role, exc, constructing=False)
            raise

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._inner.complete(*args, **kwargs)
        except (RateLimitError, ProviderAuthError) as exc:
            self._guard.record(self._role, exc, constructing=False)
            raise

    def vision(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._inner.vision(*args, **kwargs)
        except (RateLimitError, ProviderAuthError) as exc:
            self._guard.record(self._role, exc, constructing=False)
            raise


class ProviderGuard:
    """Providers for roles, all sharing one `ResponseCache`, with failures attributed.

    The cache is the existing `ResponseCache`; this class only passes it to
    `ModelRegistry.provider_for`. A call that completed is on disk before the next one
    starts, so a run that dies on a quota resumes by being run again.
    """

    def __init__(self, registry: ModelRegistry, *, cache: ResponseCache | None) -> None:
        self.registry = registry
        self.cache = cache
        self.failures: list[ProviderFailureRecord] = []

    def provider(self, role: str) -> Any:
        """The provider bound to `role`. Records and re-raises a missing API key."""
        try:
            inner = self.registry.provider_for(role, cache=self.cache)
        except ProviderAuthError as exc:
            self.record(role, exc, constructing=True)
            raise
        return _RoleBound(inner, self, role)

    def record(self, role: str, exc: BaseException, *, constructing: bool) -> None:
        binding = self.registry.binding(role)
        if isinstance(exc, RateLimitError):
            kind = "rate_limit"
        else:
            kind = "missing_key" if constructing else "rejected_key"
        self.failures.append(
            ProviderFailureRecord(
                role=role,
                provider=binding.provider,
                model=binding.model,
                kind=kind,
                env_var=api_key_env(binding.provider),
                message=str(exc),
                exception=exc,
            )
        )

    def failure_behind(self, error: BaseException) -> ProviderFailureRecord | None:
        """The recorded failure that caused `error`, found by walking its cause chain."""
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            for record in self.failures:
                if record.exception is current:
                    return record
            current = current.__cause__ or current.__context__
        return None
