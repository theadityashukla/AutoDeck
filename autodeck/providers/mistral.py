"""Mistral adapter (La Plateforme chat completions, OpenAI-shaped).

The request is the OpenAI chat-completions shape with two differences that fail at request
time if missed: the output cap is `max_tokens` (not `max_completion_tokens`), and an image
part's `image_url` is the data URL itself rather than an `{"url": ...}` object.

Structured output uses `response_format: json_schema` with `strict: true`, in the same
strict dialect Groq takes. Every response is still re-validated against the pydantic model.

Owning phase: 3c (the `dev-mistral` environment).
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

_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralProvider(BaseProvider):
    """Mistral — every role of the `dev-mistral` environment, on small paid models."""

    schema_flavor = "strict"

    @property
    def name(self) -> str:
        return "mistral"

    @property
    def api_key_env(self) -> str:
        return "MISTRAL_API_KEY"

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
                data_url = f"data:{image.media_type};base64,{encoded}"
                content.append({"type": "image_url", "image_url": data_url})
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
            "max_tokens": self.config.max_output_tokens,
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
            raise ProviderResponseError(f"mistral returned no choices: {payload}")

        content = choices[0].get("message", {}).get("content") or ""
        # Reasoning models return a list of typed chunks; only the text chunks are the answer.
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if part.get("type") == "text"
            )

        usage_payload = payload.get("usage", {})
        usage = Usage(
            input_tokens=int(usage_payload.get("prompt_tokens", 0)),
            output_tokens=int(usage_payload.get("completion_tokens", 0)),
        )
        return RawResponse(text=content, usage=usage)
