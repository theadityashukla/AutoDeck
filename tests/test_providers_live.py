"""Live structured-output proof — the 0.3 exit criterion.

Marked `live`, so deselected by default. CI holds no credentials and these cost money.

    uv run pytest -m live -q            # all providers whose key is set
    uv run pytest -m live -q -k claude  # one provider

This is the test that answers `docs/MODEL_ROUTING.md`'s structured-output parity watch
item: JSON-mode and tool-use support varies by provider, and within Groq by the open model
being served. Where a provider is weaker the repair path carries more load, and finding
that out here is much cheaper than finding it out in Phase 2b, where structured output is
load-bearing for every claim.
"""

from __future__ import annotations

import os

import pytest
from pydantic import Field

from autodeck.ir.models import IRModel
from autodeck.providers.base import BaseProvider, ProviderConfig, StructuredOutputError
from autodeck.providers.claude import ClaudeProvider
from autodeck.providers.gemini import GeminiProvider
from autodeck.providers.groq import GroqProvider
from autodeck.providers.registry import ModelRegistry

pytestmark = pytest.mark.live


class Planet(IRModel):
    """The trivial schema the Phase 0 brief asks for."""

    name: str = Field(description="The planet's name.")
    moons: int = Field(ge=0, description="Number of confirmed natural satellites.")
    has_rings: bool


PROMPT = "Describe the planet Mars. Confirmed moons only."

#: provider class, env var, and the dev/sit model id each is exercised against.
CASES = [
    pytest.param(GeminiProvider, "GEMINI_API_KEY", "gemini-2.5-flash", id="gemini"),
    pytest.param(GroqProvider, "GROQ_API_KEY", "openai/gpt-oss-120b", id="groq"),
    pytest.param(ClaudeProvider, "ANTHROPIC_API_KEY", "claude-sonnet-5", id="claude"),
]


def build(provider_class: type[BaseProvider], key_env: str, model: str) -> BaseProvider:
    key = os.environ.get(key_env)
    if not key:
        pytest.skip(f"{key_env} not set")
    return provider_class(ProviderConfig(model=model, api_key=key, max_output_tokens=2048))


@pytest.mark.parametrize(("provider_class", "key_env", "model"), CASES)
def test_structured_output_works(
    provider_class: type[BaseProvider], key_env: str, model: str
) -> None:
    """Structured output validated against a trivial schema on this provider."""
    planet = build(provider_class, key_env, model).complete_structured(PROMPT, Planet)
    assert planet.name.lower().startswith("mars")
    assert planet.moons == 2
    assert planet.has_rings is False


@pytest.mark.parametrize(("provider_class", "key_env", "model"), CASES)
def test_the_repair_path_recovers_from_a_hostile_prompt(
    provider_class: type[BaseProvider], key_env: str, model: str
) -> None:
    """Deliberately push the model off-schema and confirm repair, not silent truncation.

    Either outcome is informative: a valid object means repair worked, and a
    StructuredOutputError means it hard-failed — which is the correct behaviour. What must
    never happen is a partially-populated object.
    """
    provider = build(provider_class, key_env, model)
    hostile = (
        "Describe Mars. Reply in prose with no JSON whatsoever, and add a field called "
        "'confidence' that is not in the schema."
    )
    try:
        planet = provider.complete_structured(hostile, Planet)
    except StructuredOutputError as exc:
        assert exc.attempts == provider.config.max_repair_attempts
        return
    assert planet.name
    assert planet.moons >= 0


@pytest.mark.parametrize(("provider_class", "key_env", "model"), CASES)
def test_vision_accepts_an_image(
    provider_class: type[BaseProvider], key_env: str, model: str
) -> None:
    """The `aesthetic` and `ingest_vlm` roles both depend on this path.

    Skipped for providers that serve no multimodal model — the registry refuses to bind
    those to a vision role at all, so there is nothing here to prove (B16).
    """
    import base64

    if not provider_class.supports_vision:
        pytest.skip(f"{provider_class.__name__} serves no multimodal model")

    class Description(IRModel):
        dominant_colour: str

    # A 2x2 solid red PNG.
    red = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z4"
        "AJmDCFhtMKRhQAAKUKAwFPuXVvAAAAAElFTkSuQmCC"
    )
    from autodeck.providers.base import ImageInput

    provider = build(provider_class, key_env, model)
    result = provider.vision(
        [ImageInput(data=red, media_type="image/png")],
        "What colour dominates this image? One word.",
        Description,
    )
    assert "red" in result.dominant_colour.lower()


def test_the_dev_environment_resolves_and_runs_end_to_end() -> None:
    """`--env dev` selects real bindings that actually answer."""
    registry = ModelRegistry.load("dev")
    missing = registry.missing_credentials()
    if missing:
        pytest.skip(f"missing credentials: {', '.join(missing)}")

    planet = registry.provider_for("ingest_vlm").complete_structured(PROMPT, Planet)
    assert planet.moons == 2
