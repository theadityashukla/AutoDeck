"""The studio's own model bindings (`config/studio.yaml`), resolved through v2's providers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from autodeck.providers.base import ProviderAuthError
from autodeck.studio.bindings import (
    DEFAULT_STUDIO_CONFIG,
    STUDIO_ROLES,
    RoleBinding,
    StudioConfig,
    bind_model,
    load_studio_config,
    resolve_binding,
    tokens_path,
)
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.paths import REPO_ROOT


def _v2_bindings() -> dict[str, set[tuple[str, str]]]:
    raw = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    out: dict[str, set[tuple[str, str]]] = {}
    for env, roles in raw["environments"].items():
        out[env] = {(b["provider"], b["model"]) for b in roles.values() if isinstance(b, dict)}
    return out


def test_the_shipped_config_loads_and_reuses_v2_model_ids() -> None:
    config = load_studio_config()
    v2 = _v2_bindings()
    assert set(config.environments) == set(v2)
    assert config.default_env == "dev-mistral"
    for env, bindings in config.environments.items():
        for role in STUDIO_ROLES:
            binding = getattr(bindings, role)
            assert (binding.provider, binding.model) in v2[env], (env, role)


def test_tokens_path_points_at_an_existing_token_file() -> None:
    path = tokens_path(load_studio_config())
    assert path == REPO_ROOT / "config" / "tokens" / "dev.json" and path.is_file()


def test_resolve_binding_defaults_and_unknown_env() -> None:
    config = load_studio_config()
    env, binding = resolve_binding(config)
    assert env == "dev-mistral" and binding.model_id == "mistral/ministral-14b-2512"
    env, binding = resolve_binding(config, env="prod")
    assert env == "prod" and binding.provider == "claude"
    with pytest.raises(StudioConfigError, match="dev-mistral, prod, sit"):
        resolve_binding(config, env="staging")


def test_load_errors_are_studio_config_errors(tmp_path: Path) -> None:
    with pytest.raises(StudioConfigError, match=r"missing\.yaml"):
        load_studio_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("default_env: [unclosed\n", encoding="utf-8")
    with pytest.raises(StudioConfigError):
        load_studio_config(bad)
    wrong = tmp_path / "wrong.yaml"
    wrong.write_text(
        "default_env: x\ntokens: t.json\nenvironments:\n"
        "  y:\n    lead: {provider: mistral, model: m}\n",
        encoding="utf-8",
    )
    with pytest.raises(StudioConfigError, match="default_env"):
        load_studio_config(wrong)


def test_models_reject_unknown_providers_and_missing_roles() -> None:
    with pytest.raises(ValidationError, match="unknown provider"):
        RoleBinding(provider="acme", model="m")
    with pytest.raises(ValidationError):
        StudioConfig.model_validate(
            {"default_env": "a", "tokens": "t", "environments": {"a": {}}}
        )


def test_bind_model_without_a_key_raises_the_providers_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(ProviderAuthError, match="MISTRAL_API_KEY"):
        bind_model(load_studio_config(), env="dev-mistral")


def test_bind_model_with_a_key_records_role_env_and_model_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "dummy")
    bound = bind_model(load_studio_config(), cache_dir=tmp_path / "cache")
    assert (bound.role, bound.env, bound.model_id) == (
        "lead",
        "dev-mistral",
        "mistral/ministral-14b-2512",
    )
    assert bound.model.config.model == "ministral-14b-2512"  # type: ignore[attr-defined]
    assert bound.model.config.cache is not None  # type: ignore[attr-defined]


def test_default_path_is_config_studio_yaml() -> None:
    assert DEFAULT_STUDIO_CONFIG == REPO_ROOT / "config" / "studio.yaml"
