"""Groq adapter (OpenAI-compatible chat completions).

Groq serves open models, and **structured-output support varies by the model being
served**, not just by the provider — the specific watch item `docs/MODEL_ROUTING.md` flags
for this task. Where `response_format: json_schema` is unsupported the request fails
outright rather than degrading, so the registry's configured model matters more here than
it does for the closed-model providers.

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
)

_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(BaseProvider):
    """Groq — the dev-tier `content` role, where token volume dominates."""

    schema_flavor = "strict"

    # Verified against the live model list on 2026-07-26: Groq serves no multimodal model,
    # and gpt-oss-120b rejects an OpenAI content-array outright ("messages[0].content must
    # be a string"). Groq is therefore text-only here, and the registry refuses to bind it
    # to a vision role. See DECISIONS.md B16.
    supports_vision = False

    @property
    def name(self) -> str:
        return "groq"

    @property
    def api_key_env(self) -> str:
        return "GROQ_API_KEY"

    def build_request(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: dict[str, Any] | None,
        images: list[ImageInput],
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        content: list[dict[str, Any]] | str
        if images:
            content = [{"type": "text", "text": prompt}]
            for image in images:
                encoded = base64.b64encode(image.data).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{image.media_type};base64,{encoded}"},
                    }
                )
        else:
            content = prompt

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_completion_tokens": self.config.max_output_tokens,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "autodeck_response", "schema": schema, "strict": True},
            }

        headers = {
            "authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
        }
        return _URL, headers, body

    def parse_response(self, payload: dict[str, Any]) -> RawResponse:
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderResponseError(f"groq returned no choices: {payload}")

        message = choices[0].get("message", {})
        text = message.get("content") or ""

        # Some served models emit a refusal instead of content; that is a real failure and
        # must not reach the repair loop as an empty string.
        refusal = message.get("refusal")
        if refusal:
            raise ProviderResponseError(f"groq model refused the request: {refusal}")

        usage_payload = payload.get("usage", {})
        usage = Usage(
            input_tokens=int(usage_payload.get("prompt_tokens", 0)),
            output_tokens=int(usage_payload.get("completion_tokens", 0)),
        )
        return RawResponse(text=text, usage=usage)
