"""Environment-tiered role registry (B8).

The shipped `config/models.yaml` is validated here rather than only in a live run, because
a missing role binding would otherwise surface partway through a build — after the
expensive steps, not before them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.providers.base import ProviderAuthError
from autodeck.providers.claude import ClaudeProvider
from autodeck.providers.mistral import MistralProvider
from autodeck.providers.openai import OpenAIProvider
from autodeck.providers.registry import (
    DEFAULT_CONFIG_PATH,
    PROVIDERS,
    ROLES,
    VISION_ROLES,
    ModelRegistry,
    RegistryError,
)

CONFIG = Path(__file__).resolve().parents[1] / DEFAULT_CONFIG_PATH


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = """
default_env: dev
environments:
  dev:
    planner:    {provider: mistral, model: m-pro}
    outline:    {provider: mistral, model: m-pro}
    content:    {provider: openai, model: m-fast}
    composer:   {provider: mistral, model: m-long}
    validation: {provider: mistral, model: m-pro}
    aesthetic:  {provider: mistral, model: m-vision}
    advisor:    {provider: mistral, model: m-long}
    ingest_vlm: {provider: mistral, model: m-flash}
  prod:
    planner:    {provider: claude, model: c-strong}
    outline:    {provider: claude, model: c-strong}
    content:    {provider: claude, model: c-mid}
    composer:   {provider: claude, model: c-mid}
    validation: {provider: claude, model: c-strong}
    aesthetic:  {provider: claude, model: c-strong}
    ingest_vlm: {provider: mistral, model: m-flash}
    advisor:    {provider: claude, model: c-mid}
"""


# ---------------------------------------------------------------------------
# The shipped config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev-mistral", "sit", "prod"])
def test_the_shipped_config_binds_every_role_in_every_environment(env: str) -> None:
    registry = ModelRegistry.load(env, CONFIG)
    assert set(registry.bindings()) == set(ROLES)


def test_dev_mistral_runs_on_mistral_only() -> None:
    """B51: small paid Mistral models back dev; Claude is reserved for sit and prod."""
    bindings = ModelRegistry.load("dev-mistral", CONFIG).bindings()
    assert {b.provider for b in bindings.values()} == {"mistral"}


@pytest.mark.parametrize("env", ["sit", "prod"])
def test_judgment_heavy_roles_run_on_claude_in_sit_and_prod(env: str) -> None:
    bindings = ModelRegistry.load(env, CONFIG).bindings()
    assert bindings["validation"].provider == "claude"
    assert bindings["planner"].provider == "claude"


@pytest.mark.parametrize("env", ["dev-mistral", "sit", "prod"])
def test_ingest_vlm_is_vision_capable_everywhere(env: str) -> None:
    """Interim: Mistral everywhere until Nebius/OpenAI keys and model ids exist."""
    provider = ModelRegistry.load(env, CONFIG).binding("ingest_vlm").provider
    assert PROVIDERS[provider].supports_vision


def test_no_shipped_environment_names_a_removed_provider() -> None:
    import yaml

    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    used = {b["provider"] for env in raw["environments"].values() for b in env.values() if isinstance(b, dict)}
    assert used <= set(PROVIDERS)
    assert not {"gemini", "groq"} & set(PROVIDERS)
    assert set(raw["environments"]) == {"dev-mistral", "sit", "prod"}


def test_the_default_environment_is_dev_mistral() -> None:
    assert ModelRegistry.load(None, CONFIG).env == "dev-mistral"


# ---------------------------------------------------------------------------
# Selection and manifest
# ---------------------------------------------------------------------------


def test_env_selects_the_bindings(tmp_path: Path) -> None:
    path = write_config(tmp_path, MINIMAL)
    assert ModelRegistry.load("dev", path).binding("content").model == "m-fast"
    assert ModelRegistry.load("prod", path).binding("content").model == "c-mid"


def test_manifest_entry_records_env_and_every_resolved_model(tmp_path: Path) -> None:
    """A6: an audit report must always state which bindings produced it."""
    entry = ModelRegistry.load("dev", write_config(tmp_path, MINIMAL)).manifest_entry()
    assert entry["env"] == "dev"
    assert set(entry["roles"]) == set(ROLES)
    assert entry["roles"]["validation"] == {"provider": "mistral", "model": "m-pro"}


def test_provider_for_returns_the_bound_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    path = write_config(tmp_path, MINIMAL)

    dev = ModelRegistry.load("dev", path)
    assert isinstance(dev.provider_for("validation"), MistralProvider)
    assert isinstance(dev.provider_for("content"), OpenAIProvider)
    assert isinstance(ModelRegistry.load("prod", path).provider_for("content"), ClaudeProvider)


def test_a_missing_key_fails_before_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    registry = ModelRegistry.load("dev", write_config(tmp_path, MINIMAL))
    with pytest.raises(ProviderAuthError, match="MISTRAL_API_KEY"):
        registry.provider_for("planner")


def test_missing_credentials_are_reported_up_front(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So a build fails at startup rather than at whichever role happens to run third."""
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    registry = ModelRegistry.load("dev", write_config(tmp_path, MINIMAL))
    assert registry.missing_credentials() == ["MISTRAL_API_KEY"]


# ---------------------------------------------------------------------------
# Malformed config
# ---------------------------------------------------------------------------


def test_an_unknown_environment_lists_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="Known environments: dev, prod"):
        ModelRegistry.load("staging", write_config(tmp_path, MINIMAL))


def test_a_missing_config_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="model config not found"):
        ModelRegistry.load("dev", tmp_path / "absent.yaml")


def test_an_unbound_role_is_rejected_at_load(tmp_path: Path) -> None:
    partial = """
default_env: dev
environments:
  dev:
    planner: {provider: mistral, model: m}
"""
    with pytest.raises(RegistryError, match="does not bind"):
        ModelRegistry.load("dev", write_config(tmp_path, partial))


def test_an_unknown_provider_is_rejected(tmp_path: Path) -> None:
    bogus = MINIMAL.replace("{provider: openai, model: m-fast}", "{provider: acme, model: m}")
    with pytest.raises(RegistryError, match="unknown provider 'acme'"):
        ModelRegistry.load("dev", write_config(tmp_path, bogus))


def test_binding_a_text_only_provider_to_a_vision_role_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider with no multimodal model (B16). Catching it here beats catching it at the
    first figure of an ingestion run."""

    class TextOnly(OpenAIProvider):
        supports_vision = False

    monkeypatch.setitem(PROVIDERS, "openai", TextOnly)
    bad = MINIMAL.replace(
        "ingest_vlm: {provider: mistral, model: m-flash}\n  prod",
        "ingest_vlm: {provider: openai, model: m-fast}\n  prod",
    )
    with pytest.raises(RegistryError, match="accepts image input"):
        ModelRegistry.load("dev", write_config(tmp_path, bad))


def test_the_shipped_config_never_binds_a_text_only_provider_to_a_vision_role() -> None:
    for env in ("dev-mistral", "sit", "prod"):
        bindings = ModelRegistry.load(env, CONFIG).bindings()
        for role in VISION_ROLES:
            assert PROVIDERS[bindings[role].provider].supports_vision, f"{env}.{role}"


def test_a_binding_without_a_model_is_rejected(tmp_path: Path) -> None:
    bad = MINIMAL.replace("{provider: openai, model: m-fast}", "{provider: openai}")
    with pytest.raises(RegistryError, match="must specify both"):
        ModelRegistry.load("dev", write_config(tmp_path, bad))


def test_a_role_can_be_pointed_at_another_model(monkeypatch) -> None:
    """The override that matters: a role whose daily quota is spent, or a one-off
    comparison, without editing config.

    Regression — `model` used to be pinned before `**overrides` was expanded, so passing it
    raised TypeError. The only override anyone would reach for was the one that could not
    be used.
    """
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    registry = ModelRegistry.load("dev-mistral")
    default = registry.provider_for("planner")
    swapped = registry.provider_for("planner", model="ministral-8b-2512")

    assert swapped.config.model == "ministral-8b-2512"
    assert default.config.model != "ministral-8b-2512", "the binding itself must not change"


def test_other_config_fields_are_still_overridable(monkeypatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    provider = ModelRegistry.load("dev-mistral").provider_for("planner", temperature=0.7)
    assert provider.config.temperature == 0.7


def test_the_advisor_may_not_share_the_validation_model(tmp_path: Path) -> None:
    """B73: the writer's second reader is never the independent checker (B44)."""
    bad = MINIMAL.replace(
        "advisor:    {provider: mistral, model: m-long}",
        "advisor:    {provider: mistral, model: m-pro}",
    )
    with pytest.raises(RegistryError, match="advisor binds the validation model"):
        ModelRegistry.load("dev", write_config(tmp_path, bad))
