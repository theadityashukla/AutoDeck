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
from autodeck.providers.gemini import GeminiProvider
from autodeck.providers.groq import GroqProvider
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
    planner:    {provider: gemini, model: m-pro}
    outline:    {provider: gemini, model: m-pro}
    content:    {provider: groq,   model: m-fast}
    validation: {provider: gemini, model: m-pro}
    aesthetic:  {provider: gemini, model: m-vision}
    ingest_vlm: {provider: gemini, model: m-flash}
  prod:
    planner:    {provider: claude, model: c-strong}
    outline:    {provider: claude, model: c-strong}
    content:    {provider: claude, model: c-mid}
    validation: {provider: claude, model: c-strong}
    aesthetic:  {provider: claude, model: c-strong}
    ingest_vlm: {provider: gemini, model: m-flash}
"""


# ---------------------------------------------------------------------------
# The shipped config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "sit", "prod"])
def test_the_shipped_config_binds_every_role_in_every_environment(env: str) -> None:
    registry = ModelRegistry.load(env, CONFIG)
    assert set(registry.bindings()) == set(ROLES)


def test_dev_runs_on_the_free_tier_providers() -> None:
    """B8: Gemini and Groq back dev; Claude is reserved for sit and prod."""
    bindings = ModelRegistry.load("dev", CONFIG).bindings()
    assert {b.provider for b in bindings.values()} == {"gemini", "groq"}


@pytest.mark.parametrize("env", ["sit", "prod"])
def test_judgment_heavy_roles_run_on_claude_in_sit_and_prod(env: str) -> None:
    bindings = ModelRegistry.load(env, CONFIG).bindings()
    assert bindings["validation"].provider == "claude"
    assert bindings["planner"].provider == "claude"


@pytest.mark.parametrize("env", ["dev", "sit", "prod"])
def test_ingest_vlm_stays_on_gemini_everywhere(env: str) -> None:
    """Its output is metadata that can never back a claim, so there is nothing to buy."""
    assert ModelRegistry.load(env, CONFIG).binding("ingest_vlm").provider == "gemini"


def test_the_default_environment_is_dev() -> None:
    assert ModelRegistry.load(None, CONFIG).env == "dev"


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
    assert entry["roles"]["validation"] == {"provider": "gemini", "model": "m-pro"}


def test_provider_for_returns_the_bound_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    path = write_config(tmp_path, MINIMAL)

    dev = ModelRegistry.load("dev", path)
    assert isinstance(dev.provider_for("validation"), GeminiProvider)
    assert isinstance(dev.provider_for("content"), GroqProvider)
    assert isinstance(ModelRegistry.load("prod", path).provider_for("content"), ClaudeProvider)


def test_a_missing_key_fails_before_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    registry = ModelRegistry.load("dev", write_config(tmp_path, MINIMAL))
    with pytest.raises(ProviderAuthError, match="GEMINI_API_KEY"):
        registry.provider_for("planner")


def test_missing_credentials_are_reported_up_front(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So a build fails at startup rather than at whichever role happens to run third."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    registry = ModelRegistry.load("dev", write_config(tmp_path, MINIMAL))
    assert registry.missing_credentials() == ["GEMINI_API_KEY"]


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
    planner: {provider: gemini, model: m}
"""
    with pytest.raises(RegistryError, match="does not bind"):
        ModelRegistry.load("dev", write_config(tmp_path, partial))


def test_an_unknown_provider_is_rejected(tmp_path: Path) -> None:
    bogus = MINIMAL.replace("{provider: groq,   model: m-fast}", "{provider: acme, model: m}")
    with pytest.raises(RegistryError, match="unknown provider 'acme'"):
        ModelRegistry.load("dev", write_config(tmp_path, bogus))


def test_binding_a_text_only_provider_to_a_vision_role_is_rejected(tmp_path: Path) -> None:
    """Groq serves no multimodal model (B16). Catching it here beats catching it at the
    first figure of an ingestion run."""
    bad = MINIMAL.replace(
        "ingest_vlm: {provider: gemini, model: m-flash}\n  prod",
        "ingest_vlm: {provider: groq, model: m-fast}\n  prod",
    )
    with pytest.raises(RegistryError, match="accepts image input"):
        ModelRegistry.load("dev", write_config(tmp_path, bad))


def test_the_shipped_config_never_binds_a_text_only_provider_to_a_vision_role() -> None:
    for env in ("dev", "sit", "prod"):
        bindings = ModelRegistry.load(env, CONFIG).bindings()
        for role in VISION_ROLES:
            assert PROVIDERS[bindings[role].provider].supports_vision, f"{env}.{role}"


def test_a_binding_without_a_model_is_rejected(tmp_path: Path) -> None:
    bad = MINIMAL.replace("{provider: groq,   model: m-fast}", "{provider: groq}")
    with pytest.raises(RegistryError, match="must specify both"):
        ModelRegistry.load("dev", write_config(tmp_path, bad))
