"""The studio's model bindings: role -> provider and model, per environment (Phase 1).

v2's `config/models.yaml`, `ROLES` and `ModelRegistry` are left untouched: they bind v2's
pipeline roles, and every one of them must be present for v2 to load. The studio has its
own small file, `config/studio.yaml`, that binds the studio's roles. Phase 1 has one role,
`lead`, which does every layer (plan §12 Phase 1: one model, no routing). Phase 2 adds a
role per layer here, and the loop asks for a binding by role, so routing a call elsewhere
does not rewrite the loop (`BoundModel.role`).

A binding is resolved through v2's own provider classes (`registry.PROVIDERS`), API-key
variables (`registry.api_key_env`) and response cache (`providers.cache.ResponseCache`).
No model id appears in code: `config/studio.yaml` reuses ids already in
`config/models.yaml` for the matching environments.

There are no provider keys in the build environment, so every test runs on the scripted
stand-in (`scripted.ScriptedModel`), which the server can also be started with.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import Field, ValidationError, model_validator

from autodeck.providers.base import AssistantTurn, Message, ProviderConfig, ToolSpec
from autodeck.providers.cache import ResponseCache
from autodeck.providers.registry import PROVIDERS, api_key_env
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.models import StudioModel
from autodeck.studio.paths import REPO_ROOT

DEFAULT_STUDIO_CONFIG = REPO_ROOT / "config" / "studio.yaml"

StudioRole = Literal["lead"]
STUDIO_ROLES: tuple[StudioRole, ...] = ("lead",)
"""Phase 1: one role. Every environment must bind every role."""


class ConverseModel(Protocol):
    """What the loop needs from a model: v2's `BaseProvider.converse` signature."""

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn: ...


class RoleBinding(StudioModel):
    """One role's provider and model, as written in `config/studio.yaml`."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _known_provider(self) -> RoleBinding:
        if self.provider not in PROVIDERS:
            known = ", ".join(sorted(PROVIDERS))
            raise ValueError(f"unknown provider {self.provider!r}; known: {known}")
        if self.model != self.model.strip():
            raise ValueError(f"model id {self.model!r} has surrounding whitespace")
        return self

    @property
    def model_id(self) -> str:
        """`"<provider>/<model>"`: what change-log entries and messages record (V5)."""
        return f"{self.provider}/{self.model}"


class StudioEnvironment(StudioModel):
    """One environment's bindings. Phase 1: `lead` only."""

    lead: RoleBinding


class StudioConfig(StudioModel):
    """`config/studio.yaml`.

    `tokens` is the design-token file the studio renders and checks layouts with, relative
    to the repository root (the design system that will decide tokens is Phase 3).
    `default_env` must name one of `environments`.
    """

    default_env: str = Field(min_length=1)
    tokens: str = Field(min_length=1, description="Token file, relative to the repo root.")
    environments: dict[str, StudioEnvironment] = Field(min_length=1)

    @model_validator(mode="after")
    def _default_env_exists(self) -> StudioConfig:
        if self.default_env not in self.environments:
            known = ", ".join(sorted(self.environments))
            raise ValueError(f"default_env {self.default_env!r} is not one of: {known}")
        return self


@dataclass(frozen=True)
class BoundModel:
    """A model ready for the loop: what to call, and what to record about it."""

    role: StudioRole
    model_id: str
    """Recorded on every change-log entry and assistant line (V5)."""
    model: ConverseModel
    env: str
    """The environment it was bound in; `"scripted"` for the scripted stand-in."""


def load_studio_config(path: Path = DEFAULT_STUDIO_CONFIG) -> StudioConfig:
    """Read and validate `config/studio.yaml` (YAML, parsed with `yaml.safe_load`).

    Raises:
        StudioConfigError: the file is missing (message names the path), is not valid YAML,
            is not a mapping, or fails `StudioConfig` validation (message includes the
            pydantic error text). Never a bare `ValidationError`.
    """
    if not path.is_file():
        raise StudioConfigError(f"studio config not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise StudioConfigError(f"{path}: not readable as YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise StudioConfigError(f"{path}: must be a mapping at the top level")
    try:
        return StudioConfig.model_validate(raw)
    except ValidationError as exc:
        raise StudioConfigError(f"{path}: invalid studio config: {exc}") from exc


def resolve_binding(
    config: StudioConfig, *, env: str | None = None, role: StudioRole = "lead"
) -> tuple[str, RoleBinding]:
    """The environment name used and the binding for `role` in it.

    `env=None` means `config.default_env`.

    Raises:
        StudioConfigError: unknown environment (the message lists the known ones, sorted).
    """
    name = config.default_env if env is None else env
    if name not in config.environments:
        known = ", ".join(sorted(config.environments))
        raise StudioConfigError(f"unknown environment {name!r}. Known environments: {known}")
    return name, getattr(config.environments[name], role)


def tokens_path(config: StudioConfig) -> Path:
    """`REPO_ROOT / config.tokens`. Not checked for existence here."""
    return REPO_ROOT / config.tokens


def bind_model(
    config: StudioConfig,
    *,
    env: str | None = None,
    role: StudioRole = "lead",
    cache_dir: Path | None = None,
) -> BoundModel:
    """Instantiate the provider bound to `role` in `env`.

    `resolve_binding`, then `PROVIDERS[binding.provider](ProviderConfig(model=binding.model,
    api_key=os.environ.get(registry.api_key_env(binding.provider), ""), cache=cache))`
    where `cache` is `ResponseCache(cache_dir)` when `cache_dir` is given, else None.
    Returns `BoundModel(role, binding.model_id, provider, env_name)`.

    Raises:
        StudioConfigError: as `resolve_binding`.
        ProviderAuthError: (v2's) the provider's API key is not set; raised by the
            provider's constructor, not caught here, so the caller can say which variable.
    """
    env_name, binding = resolve_binding(config, env=env, role=role)
    cache = ResponseCache(cache_dir) if cache_dir is not None else None
    provider_class = PROVIDERS[binding.provider]
    provider = provider_class(
        ProviderConfig(
            model=binding.model,
            api_key=os.environ.get(api_key_env(binding.provider), ""),
            cache=cache,
        )
    )
    return BoundModel(role=role, model_id=binding.model_id, model=provider, env=env_name)
