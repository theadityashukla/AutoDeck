"""Claude adapter (Anthropic Messages API).

Structured output is expressed as a forced single-tool call: the schema becomes the tool's
`input_schema` and `tool_choice` pins it, so the model must emit an argument object rather
than prose that happens to look like JSON. That is a stronger constraint than JSON mode,
which is part of why Claude backs the judgment-critical roles in `sit` and `prod` (B8).

Owning phase: 0 (task 0.3).
"""

from __future__ import annotations

import base64
from typing import Any

from autodeck.ir.schema import export_schema
from autodeck.providers.base import (
    AssistantTurn,
    BaseProvider,
    ImageInput,
    Message,
    ProviderResponseError,
    RawResponse,
    ToolCall,
    ToolSpec,
    Usage,
    json_dumps,
)

_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"

#: The forced tool. Its name reaches the model, so it is descriptive rather than internal.
_TOOL_NAME = "emit_structured_response"


class ClaudeProvider(BaseProvider):
    """Claude — the `sit` and `prod` bindings for judgment-heavy roles (B8)."""

    schema_flavor = "standard"

    @property
    def name(self) -> str:
        return "claude"

    @property
    def api_key_env(self) -> str:
        return "ANTHROPIC_API_KEY"

    def build_request(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: dict[str, Any] | None,
        images: list[ImageInput],
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        content: list[dict[str, Any]] = []
        for image in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": base64.b64encode(image.data).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        body: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_output_tokens,
            "temperature": self.config.temperature,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            body["system"] = system
        if schema is not None:
            body["tools"] = [
                {
                    "name": _TOOL_NAME,
                    "description": "Return the response as structured data matching "
                    "the schema.",
                    "input_schema": schema,
                }
            ]
            body["tool_choice"] = {"type": "tool", "name": _TOOL_NAME}

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        return _URL, headers, body

    def parse_response(self, payload: dict[str, Any]) -> RawResponse:
        blocks = payload.get("content") or []

        usage_payload = payload.get("usage", {})
        usage = Usage(
            input_tokens=int(usage_payload.get("input_tokens", 0)),
            output_tokens=int(usage_payload.get("output_tokens", 0)),
        )

        # A structured call returns the object in the tool_use block's `input`. Serialising
        # it back to JSON keeps one validation path for all three providers.
        for block in blocks:
            if block.get("type") == "tool_use" and block.get("name") == _TOOL_NAME:
                return RawResponse(text=json_dumps(block.get("input", {})), usage=usage)

        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text:
            stop_reason = payload.get("stop_reason")
            raise ProviderResponseError(
                f"claude returned no usable content (stop_reason={stop_reason})"
            )
        return RawResponse(text=text, usage=usage)

    # -- tool calling -------------------------------------------------------

    def build_converse_request(
        self,
        *,
        messages: list[Message],
        tools: list[ToolSpec],
        system: str | None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        wire: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content,
                }
                # Results for one assistant turn must share a single user message.
                if wire and wire[-1]["role"] == "user" and _is_results(wire[-1]["content"]):
                    wire[-1]["content"].append(block)
                else:
                    wire.append({"role": "user", "content": [block]})
            elif m.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                blocks.extend(
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                    for c in m.tool_calls
                )
                wire.append({"role": "assistant", "content": blocks})
            else:
                wire.append({"role": "user", "content": m.content})

        body: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_output_tokens,
            "temperature": self.config.temperature,
            "messages": wire,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": export_schema(t.args_model, "standard"),
                }
                for t in tools
            ]
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        return _URL, headers, body

    def parse_converse_response(self, payload: dict[str, Any]) -> AssistantTurn:
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ProviderResponseError(
                f"claude returned no content (stop_reason={payload.get('stop_reason')})"
            )
        usage_payload = payload.get("usage", {})
        usage = Usage(
            input_tokens=int(usage_payload.get("input_tokens", 0)),
            output_tokens=int(usage_payload.get("output_tokens", 0)),
        )
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls: list[ToolCall] = []
        for b in blocks:
            if b.get("type") == "tool_use":
                args = b.get("input")
                calls.append(
                    ToolCall(
                        id=str(b.get("id", "")),
                        name=b.get("name", ""),
                        arguments=args if isinstance(args, dict) else {"__invalid__": args},
                    )
                )
        return AssistantTurn(text=text, tool_calls=calls, usage=usage)


def _is_results(content: Any) -> bool:
    return (
        isinstance(content, list)
        and bool(content)
        and all(b.get("type") == "tool_result" for b in content)
    )
