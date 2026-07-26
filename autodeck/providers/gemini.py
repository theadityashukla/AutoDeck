"""Gemini adapter (Google Generative Language REST API).

Structured output goes through `responseMimeType: application/json` plus `responseSchema`.
The schema must be in the Gemini dialect — no `$ref`, no `additionalProperties`, no
`default` — which is why `autodeck.ir.schema` exports one.

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

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseProvider):
    """Gemini — every dev-tier role except `content`, and `ingest_vlm` in all environments."""

    schema_flavor = "gemini"

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def api_key_env(self) -> str:
        return "GEMINI_API_KEY"

    def build_request(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: dict[str, Any] | None,
        images: list[ImageInput],
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": image.media_type,
                        "data": base64.b64encode(image.data).decode("ascii"),
                    }
                }
            )

        generation_config: dict[str, Any] = {
            "temperature": self.config.temperature,
            "maxOutputTokens": self.config.max_output_tokens,
        }
        if schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = schema

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        url = f"{_BASE_URL}/{self.config.model}:generateContent"
        headers = {
            "x-goog-api-key": self.config.api_key,
            "content-type": "application/json",
        }
        return url, headers, body

    def parse_response(self, payload: dict[str, Any]) -> RawResponse:
        candidates = payload.get("candidates") or []
        if not candidates:
            # Almost always a safety block or a prompt-feedback rejection. Surface the
            # reason rather than an empty string, which would fail later as a JSON error.
            feedback = payload.get("promptFeedback", {})
            raise ProviderResponseError(
                f"gemini returned no candidates (promptFeedback={feedback})"
            )

        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)

        metadata = payload.get("usageMetadata", {})
        usage = Usage(
            input_tokens=int(metadata.get("promptTokenCount", 0)),
            output_tokens=int(metadata.get("candidatesTokenCount", 0)),
        )
        return RawResponse(text=text, usage=usage)
