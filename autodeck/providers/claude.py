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

from autodeck.providers.base import (
    BaseProvider,
    ImageInput,
    ProviderResponseError,
    RawResponse,
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
