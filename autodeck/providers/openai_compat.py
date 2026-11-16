"""OpenAI-compatible Chat Completions base (Mistral, OpenAI, Nebius).

One implementation of the wire format; subclasses set `base_url`, `api_key_env` and the
few knobs on which vendors differ (output-cap field name, whether the schema is repeated in
the prompt, the shape of an image part). Retry, backoff, repair and caching stay in
`BaseProvider` (B14: one shared transport, no vendor SDKs).

Owning phase: 4b.
"""

from __future__ import annotations

import base64
import json
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


class OpenAICompatProvider(BaseProvider):
    """Chat Completions wire format. Not registered itself; subclass it."""

    schema_flavor = "strict"

    base_url: str = ""
    api_key_env_var: str = ""
    provider_name: str = ""
    #: Name of the output-cap field in the request body.
    max_tokens_field: str = "max_tokens"
    #: Also append the schema to the system message (Nebius's docs recommend it).
    schema_in_prompt: bool = False
    #: Whether an image part is `{"url": data_url}` (OpenAI) or the bare data URL string.
    image_url_as_object: bool = True

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def api_key_env(self) -> str:
        return self.api_key_env_var

    # -- helpers -----------------------------------------------------------

    @property
    def _url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
        }

    def _image_part(self, image: ImageInput) -> dict[str, Any]:
        encoded = base64.b64encode(image.data).decode("ascii")
        data_url = f"data:{image.media_type};base64,{encoded}"
        return {
            "type": "image_url",
            "image_url": {"url": data_url} if self.image_url_as_object else data_url,
        }

    # -- structured / free-text ---------------------------------------------

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
            content.extend(self._image_part(image) for image in images)
        else:
            content = prompt

        system_text = system
        if schema is not None and self.schema_in_prompt:
            hint = f"Respond with JSON matching this schema:\n{json_dumps(schema)}"
            system_text = f"{system}\n\n{hint}" if system else hint

        messages: list[dict[str, Any]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": content})

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            self.max_tokens_field: self.config.max_output_tokens,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "autodeck_response", "schema": schema, "strict": True},
            }
        return self._url, self._headers(), body

    @staticmethod
    def _content_text(content: Any) -> str:
        # Reasoning models return a list of typed chunks; only the text chunks are the answer.
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if part.get("type") == "text"
            )
        return content or ""

    @staticmethod
    def _usage(payload: dict[str, Any]) -> Usage:
        usage_payload = payload.get("usage") or {}
        return Usage(
            input_tokens=int(usage_payload.get("prompt_tokens", 0)),
            output_tokens=int(usage_payload.get("completion_tokens", 0)),
        )

    def parse_response(self, payload: dict[str, Any]) -> RawResponse:
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderResponseError(f"{self.name} returned no choices: {payload}")
        content = self._content_text((choices[0].get("message") or {}).get("content"))
        return RawResponse(text=content, usage=self._usage(payload))

    # -- tool calling -------------------------------------------------------

    def build_converse_request(
        self,
        *,
        messages: list[Message],
        tools: list[ToolSpec],
        system: str | None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        wire: list[dict[str, Any]] = []
        if system:
            wire.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "tool":
                wire.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
                )
            elif m.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json_dumps(c.arguments)},
                        }
                        for c in m.tool_calls
                    ]
                wire.append(entry)
            else:
                wire.append({"role": "user", "content": m.content})

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": wire,
            "temperature": self.config.temperature,
            self.max_tokens_field: self.config.max_output_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": export_schema(t.args_model, "strict"),
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"
        return self._url, self._headers(), body

    def parse_converse_response(self, payload: dict[str, Any]) -> AssistantTurn:
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderResponseError(f"{self.name} returned no choices: {payload}")
        message = choices[0].get("message") or {}
        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            raw_args = function.get("arguments")
            arguments: dict[str, Any]
            if isinstance(raw_args, dict):
                arguments = raw_args
            else:
                try:
                    parsed = json.loads(raw_args) if raw_args else {}
                except (TypeError, ValueError):
                    parsed = None
                arguments = parsed if isinstance(parsed, dict) else {"__invalid__": raw_args}
            calls.append(
                ToolCall(
                    id=str(raw.get("id", "")),
                    name=function.get("name", ""),
                    arguments=arguments,
                )
            )
        return AssistantTurn(
            text=self._content_text(message.get("content")),
            tool_calls=calls,
            usage=self._usage(payload),
        )
