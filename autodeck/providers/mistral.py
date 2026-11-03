"""Mistral adapter (La Plateforme chat completions, OpenAI-shaped).

Built on `OpenAICompatProvider`. Mistral differences that fail at request time if missed:
the output cap is `max_tokens`, and an image part's `image_url` is the data URL string
itself rather than an `{"url": ...}` object.

Owning phase: 3c (the `dev-mistral` environment); rebased onto the compat base in 4b.
"""

from __future__ import annotations

from autodeck.providers.openai_compat import OpenAICompatProvider


class MistralProvider(OpenAICompatProvider):
    """Mistral — every role of the `dev-mistral` environment, on small paid models."""

    base_url = "https://api.mistral.ai/v1"
    provider_name = "mistral"
    api_key_env_var = "MISTRAL_API_KEY"
    max_tokens_field = "max_tokens"
    image_url_as_object = False
