"""The studio's own model-call path for OpenAI's Responses endpoint (Phase 2-3).

The 5.6 models reject function tools together with reasoning on Chat Completions ("Function
tools with reasoning_effort are not supported ... use /v1/responses"). The slide bench called
them through `/v1/responses` with a small adapter (`bench/slides/run.py`,
`_BenchResponsesMixin`) that proved the wire format on real runs: tools, reasoning effort,
an output cap, and image input. This module is that adapter moved into the product. v2's
provider code is not edited, and the product never imports from `bench/`.

**Shape.** `ResponsesModel` subclasses v2's `OpenAICompatProvider` (via the `openai`
provider class in `registry.PROVIDERS`) and overrides only the two methods the base class's
`converse` calls: `build_converse_request` and `parse_converse_response`. HTTP, retries,
timeouts, the response cache and auth stay v2's. The call is stateless (`store: false`):
every call resends the whole conversation as input items; reasoning items are not carried
between calls (as on the bench).

**Images.** A user message that is an `ImageMessage` (a v2 `Message` with an `images` field)
is sent as one `input_text` part followed by one `input_image` part per image (a data URL,
built with the provider's own `_image_part`). No studio caller sends images in this phase
(the model seeing renders is out of scope); the path exists and is tested so the reviewer
phase can use it.

**Usage.** `input_tokens` / `output_tokens` from the response's `usage`; reasoning tokens are
inside `output_tokens` (recorded separately in `StudioUsage.reasoning_tokens`, for
information, never added again).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from autodeck.ir.schema import export_schema
from autodeck.providers.base import (
    AssistantTurn,
    ImageInput,
    Message,
    ProviderConfig,
    ProviderResponseError,
    ToolCall,
    ToolSpec,
    Usage,
)
from autodeck.providers.cache import ResponseCache
from autodeck.providers.openai_compat import OpenAICompatProvider
from autodeck.providers.registry import PROVIDERS
from autodeck.studio.errors import StudioConfigError

if TYPE_CHECKING:
    from autodeck.studio.bindings import RoleBinding

RESPONSES_MODEL_PREFIXES: tuple[str, ...] = ("gpt-5.6",)
"""Model ids (the part after the provider) that `api="auto"` sends to the Responses
endpoint."""

RESPONSES_PROVIDERS: tuple[str, ...] = ("openai",)
"""Providers the Responses path supports."""

DEFAULT_REASONING = "medium"
"""The effort sent when the binding sets none."""

CALL_TIMEOUT_SECONDS = 300.0
"""Designer calls with reasoning take tens of seconds; the bench used this timeout."""

DEFAULT_MAX_OUTPUT_TOKENS = 32000
"""The output cap when the binding sets none (reasoning tokens count against it)."""


@dataclass(frozen=True)
class ImageMessage(Message):
    """A user message that also carries images (PNG or JPEG bytes)."""

    images: tuple[ImageInput, ...] = ()


@dataclass(frozen=True)
class StudioUsage(Usage):
    """`Usage` plus what OpenAI reports inside the counts, for information only."""

    reasoning_tokens: int = 0
    cached_tokens: int = 0


def uses_responses(binding: RoleBinding) -> bool:
    """Whether a binding goes through `ResponsesModel`.

    `binding.provider` not in `RESPONSES_PROVIDERS` → False whatever `api` says. Else
    `api == "responses"` → True; `api == "chat"` → False; `api == "auto"` → True exactly
    when `binding.model` starts with one of `RESPONSES_MODEL_PREFIXES`.
    """
    if binding.provider not in RESPONSES_PROVIDERS:
        return False
    if binding.api == "responses":
        return True
    if binding.api == "chat":
        return False
    return binding.model.startswith(RESPONSES_MODEL_PREFIXES)


def build_request_body(
    *,
    model: str,
    messages: list[Message],
    tools: list[ToolSpec],
    system: str | None,
    reasoning: str,
    max_output_tokens: int,
    image_url: Any,
) -> dict[str, Any]:
    """The JSON body of one `/responses` call, exactly as the bench sent it. Pure.

    `image_url(image: ImageInput) -> str` returns a data URL (the provider passes
    `lambda image: self._image_part(image)["image_url"]["url"]`).

    Input items, one per message in order:

    * `tool` → `{"type": "function_call_output", "call_id": m.tool_call_id,
      "output": m.content}`;
    * `assistant` → `{"role": "assistant", "content": m.content}` when the content is
      non-empty, then one `{"type": "function_call", "call_id": c.id, "name": c.name,
      "arguments": json.dumps(c.arguments, ensure_ascii=False)}` per tool call;
    * `user` with images (an `ImageMessage` with a non-empty `images`) →
      `{"role": "user", "content": [{"type": "input_text", "text": m.content},
      {"type": "input_image", "image_url": <url>}, ...]}`;
    * any other user message → `{"role": "user", "content": m.content}`.

    Body: `{"model", "input": items, "max_output_tokens", "reasoning": {"effort":
    reasoning}, "store": False}`, plus `"instructions": system` when `system` is truthy,
    plus, when `tools` is non-empty, `"tools": [{"type": "function", "name", "description",
    "parameters": autodeck.ir.schema.export_schema(t.args_model, "strict"), "strict":
    False} ...]` and `"tool_choice": "auto"`. No `temperature` key.
    """
    items: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            items.append(
                {"type": "function_call_output", "call_id": m.tool_call_id, "output": m.content}
            )
        elif m.role == "assistant":
            if m.content:
                items.append({"role": "assistant", "content": m.content})
            for c in m.tool_calls:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": c.id,
                        "name": c.name,
                        "arguments": json.dumps(c.arguments, ensure_ascii=False),
                    }
                )
        else:
            images = getattr(m, "images", ())
            if images:
                parts: list[dict[str, Any]] = [{"type": "input_text", "text": m.content}]
                parts += [
                    {"type": "input_image", "image_url": image_url(image)} for image in images
                ]
                items.append({"role": "user", "content": parts})
            else:
                items.append({"role": "user", "content": m.content})
    body: dict[str, Any] = {
        "model": model,
        "input": items,
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": reasoning},
        "store": False,
    }
    if system:
        body["instructions"] = system
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": export_schema(t.args_model, "strict"),
                "strict": False,
            }
            for t in tools
        ]
        body["tool_choice"] = "auto"
    return body


def parse_response(payload: dict[str, Any]) -> AssistantTurn:
    """An `AssistantTurn` from one `/responses` payload. Pure.

    * `payload["error"]` truthy or `payload["status"] == "failed"` →
      `ProviderResponseError("responses API error: <error or status>")` (v2's).
    * For each item of `payload["output"]` (missing → none): a `message` item contributes
      each `output_text` part's `text`, and each `refusal` part as `"[refusal] <refusal>"`;
      a `function_call` item becomes a `ToolCall(id=call_id or id or "", name, arguments)`
      where `arguments` is the JSON-decoded `arguments` string when that decodes to a dict,
      else `{"__invalid__": <the raw string>}` (v2's convention for unreadable arguments).
    * `status == "incomplete"` with no tool calls appends
      `"[response incomplete: <incomplete_details.reason or 'unknown'>]"` to the text.
    * Text parts are joined with `""`. Usage: `StudioUsage(input_tokens, output_tokens,
      reasoning_tokens=output_tokens_details.reasoning_tokens or 0,
      cached_tokens=input_tokens_details.cached_tokens or 0)`, every missing count 0.
    """
    error = payload.get("error")
    if error or payload.get("status") == "failed":
        raise ProviderResponseError(f"responses API error: {error or payload.get('status')}")
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for item in payload.get("output") or []:
        kind = item.get("type")
        if kind == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    text_parts.append(part.get("text", ""))
                elif part.get("type") == "refusal":
                    text_parts.append(f"[refusal] {part.get('refusal', '')}")
        elif kind == "function_call":
            raw_args = item.get("arguments")
            try:
                parsed = json.loads(raw_args) if raw_args else {}
            except (TypeError, ValueError):
                parsed = None
            calls.append(
                ToolCall(
                    id=str(item.get("call_id") or item.get("id") or ""),
                    name=item.get("name", ""),
                    arguments=parsed if isinstance(parsed, dict) else {"__invalid__": raw_args},
                )
            )
    if payload.get("status") == "incomplete" and not calls:
        reason = (payload.get("incomplete_details") or {}).get("reason") or "unknown"
        text_parts.append(f"[response incomplete: {reason}]")
    usage = payload.get("usage") or {}
    out_details = usage.get("output_tokens_details") or {}
    in_details = usage.get("input_tokens_details") or {}
    return AssistantTurn(
        text="".join(text_parts),
        tool_calls=calls,
        usage=StudioUsage(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            reasoning_tokens=int(out_details.get("reasoning_tokens") or 0),
            cached_tokens=int(in_details.get("cached_tokens") or 0),
        ),
    )


def make_responses_model(
    binding: RoleBinding, *, api_key: str, cache: ResponseCache | None = None
) -> Any:
    """A provider for `binding` that talks to `/responses`.

    Build a subclass of `registry.PROVIDERS[binding.provider]` (an `OpenAICompatProvider`)
    named `Responses<ClassName>` whose `build_converse_request(*, messages, tools, system)`
    returns `(f"{self.base_url.rstrip('/')}/responses", self._headers(),
    build_request_body(...))` and whose `parse_converse_response(payload)` is
    `parse_response(payload)`. Instantiate it with `ProviderConfig(model=binding.model,
    api_key=api_key, timeout=CALL_TIMEOUT_SECONDS, max_output_tokens=binding.
    max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS, cache=cache)`; the reasoning effort is
    `binding.reasoning or DEFAULT_REASONING`, kept on the instance.

    Raises:
        StudioConfigError: the provider is not in `RESPONSES_PROVIDERS` or its class is not
            an `OpenAICompatProvider`.
        ProviderAuthError: (v2's) the key is empty; raised by the provider's constructor.
    """
    base = PROVIDERS.get(binding.provider)
    if binding.provider not in RESPONSES_PROVIDERS or base is None:
        raise StudioConfigError(
            f"provider {binding.provider!r} has no Responses endpoint path; "
            f"supported: {', '.join(RESPONSES_PROVIDERS)}"
        )
    if not issubclass(base, OpenAICompatProvider):
        raise StudioConfigError(f"provider {binding.provider!r} is not OpenAI-compatible")

    class _Responses(base):  # type: ignore[misc, valid-type]
        reasoning_effort: str = binding.reasoning or DEFAULT_REASONING

        def build_converse_request(
            self,
            *,
            messages: list[Message],
            tools: list[ToolSpec],
            system: str | None,
        ) -> tuple[str, dict[str, str], dict[str, Any]]:
            body = build_request_body(
                model=self.config.model,
                messages=messages,
                tools=tools,
                system=system,
                reasoning=self.reasoning_effort,
                max_output_tokens=self.config.max_output_tokens,
                image_url=lambda image: self._image_part(image)["image_url"]["url"],
            )
            return f"{self.base_url.rstrip('/')}/responses", self._headers(), body

        def parse_converse_response(self, payload: dict[str, Any]) -> AssistantTurn:
            return parse_response(payload)

    _Responses.__name__ = _Responses.__qualname__ = f"Responses{base.__name__}"
    return _Responses(
        ProviderConfig(
            model=binding.model,
            api_key=api_key,
            timeout=CALL_TIMEOUT_SECONDS,
            max_output_tokens=binding.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
            cache=cache,
        )
    )
