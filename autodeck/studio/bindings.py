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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import Field, ValidationError, model_validator

from autodeck.providers.base import AssistantTurn, Message, ProviderConfig, ToolSpec
from autodeck.providers.cache import ResponseCache
from autodeck.providers.registry import PROVIDERS, api_key_env
from autodeck.studio import responses
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.models import StudioModel
from autodeck.studio.paths import REPO_ROOT

DEFAULT_STUDIO_CONFIG = REPO_ROOT / "config" / "studio.yaml"

StudioRole = Literal["lead", "system", "designer", "mechanic", "router", "reviewer"]
"""Phase 2-3: one role per layer (plan §6.1). `lead` = Direction, `system` = System (a
concept into a palette and roles), `designer` = Composition (and Placement, in this phase),
`mechanic` = Mechanics (small edits), `router` = deciding where a message goes. `reviewer`
is reserved and unused in this phase."""

STUDIO_ROLES: tuple[StudioRole, ...] = ("lead", "system", "designer", "mechanic", "router")
"""The roles every environment must bind."""

RESERVED_ROLES: tuple[StudioRole, ...] = ("reviewer",)
"""Roles an environment may bind but nothing calls yet."""

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]
"""Sent as `reasoning.effort` on the Responses endpoint (`responses.py`)."""

ApiChoice = Literal["auto", "chat", "responses"]
"""Which OpenAI endpoint a binding uses. `auto`: Responses for model ids starting with one
of `responses.RESPONSES_MODEL_PREFIXES` on the `openai` provider, Chat Completions (v2's
provider) otherwise. Ignored for other providers, which always use v2's provider."""


class ConverseModel(Protocol):
    """What the loop needs from a model: v2's `BaseProvider.converse` signature."""

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn: ...


class RoleBinding(StudioModel):
    """One role's provider and model, as written in `config/studio.yaml`."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning: ReasoningEffort | None = Field(
        default=None, description="Reasoning effort; only sent on the Responses endpoint."
    )
    max_output_tokens: int | None = Field(
        default=None, ge=256, description="Output-token cap per call; None keeps the default."
    )
    api: ApiChoice = "auto"

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
    """One environment's bindings: every role in `STUDIO_ROLES`, and optionally the
    reserved `reviewer`."""

    lead: RoleBinding
    system: RoleBinding
    designer: RoleBinding
    mechanic: RoleBinding
    router: RoleBinding
    reviewer: RoleBinding | None = None


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


@dataclass(frozen=True)
class StudioBindings:
    """Every role's `BoundModel` for one studio (Phase 2-3). The session reads these at the
    start of every turn, so a test may replace one between turns."""

    lead: BoundModel
    system: BoundModel
    designer: BoundModel
    mechanic: BoundModel
    router: BoundModel

    def for_role(self, role: str) -> BoundModel:
        """The binding of `role`. Raises KeyError for `reviewer` or an unknown role."""
        if role not in STUDIO_ROLES:
            raise KeyError(f"no binding for role {role!r}")
        return getattr(self, role)

    @classmethod
    def single(cls, bound: BoundModel) -> StudioBindings:
        """Every role filled by one model (Phase 1 behaviour, and environments with one
        model): `replace(bound, role=<role>)` for each role, so each records its own role
        and the same model id."""
        return cls(**{role: replace(bound, role=role) for role in STUDIO_ROLES})


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
) -> tuple[str, RoleBinding | None]:
    """The environment name used and the binding for `role` in it.

    `env=None` means `config.default_env`. The binding is None only for a reserved role
    the environment does not bind.

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
    if binding is None:
        raise StudioConfigError(f"environment {env_name!r} does not bind the role {role!r}")
    cache = ResponseCache(cache_dir) if cache_dir is not None else None
    api_key = os.environ.get(api_key_env(binding.provider), "")
    if binding.provider in responses.RESPONSES_PROVIDERS and responses.uses_responses(binding):
        model: ConverseModel = responses.make_responses_model(
            binding, api_key=api_key, cache=cache
        )
        return BoundModel(role=role, model_id=binding.model_id, model=model, env=env_name)
    provider_class = PROVIDERS[binding.provider]
    config_kwargs: dict[str, object] = {}
    if binding.max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = binding.max_output_tokens
    provider = provider_class(
        ProviderConfig(
            model=binding.model,
            api_key=api_key,
            cache=cache,
            **config_kwargs,  # type: ignore[arg-type]
        )
    )
    return BoundModel(role=role, model_id=binding.model_id, model=provider, env=env_name)


def bind_all(
    config: StudioConfig, *, env: str | None = None, cache_dir: Path | None = None
) -> StudioBindings:
    """`bind_model` for every role in `STUDIO_ROLES`, in that order, as `StudioBindings`.

    Raises:
        StudioConfigError, ProviderAuthError: as `bind_model`, for the first role that fails.
    """
    return StudioBindings(
        **{
            role: bind_model(config, env=env, role=role, cache_dir=cache_dir)
            for role in STUDIO_ROLES
        }
    )
