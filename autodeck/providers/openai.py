"""OpenAI adapter (Chat Completions)."""

from __future__ import annotations

from autodeck.providers.openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    """OpenAI. Newer models reject `max_tokens`; the cap is `max_completion_tokens`."""

    base_url = "https://api.openai.com/v1"
    provider_name = "openai"
    api_key_env_var = "OPENAI_API_KEY"
    max_tokens_field = "max_completion_tokens"
