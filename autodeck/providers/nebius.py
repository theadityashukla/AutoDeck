"""Nebius Token Factory adapter (OpenAI-compatible).

Nebius's docs recommend also stating the schema in the prompt, so `schema_in_prompt` is on.
Vision support depends on the model bound; the registry's check is per provider class.
"""

from __future__ import annotations

from autodeck.providers.openai_compat import OpenAICompatProvider


class NebiusProvider(OpenAICompatProvider):
    """Nebius Token Factory."""

    base_url = "https://api.tokenfactory.nebius.com/v1"
    provider_name = "nebius"
    api_key_env_var = "NEBIUS_API_KEY"
    schema_in_prompt = True
