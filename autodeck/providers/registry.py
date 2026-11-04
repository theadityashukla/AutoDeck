"""Environment-tiered role registry (D6, B8).

Bindings live in `config/models.yaml`, never in code, so a model swap is a config edit and
the resolved IDs can be recorded in the build manifest (A6). The registry's other job is to
make the environment *explicit*: `dev-mistral` runs on small paid Mistral models, `sit` and
`prod` run on Claude, and because A3 and A8 are model-sensitive an accuracy result from one
does not transfer to the other. Anything that reports a result records `env` alongside it.

Owning phase: 0 (task 0.3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from autodeck.providers.base import BaseProvider, ProviderConfig, ProviderError
from autodeck.providers.cache import ResponseCache
from autodeck.providers.claude import ClaudeProvider
from autodeck.providers.mistral import MistralProvider
from autodeck.providers.nebius import NebiusProvider
from autodeck.providers.openai import OpenAIProvider

DEFAULT_CONFIG_PATH = Path("config/models.yaml")

#: The six agent roles of plan §6.2, plus `composer` (B45: one call writes brief, outline
#: and slides on a draft-first run; it also asks the clarifying questions and makes scoped
#: revisions) and `advisor` (B73: the deck agent's fresh-context second reader). A config
#: missing one of these is rejected at load rather than at the moment that role is first
#: invoked, halfway through a build.
ROLES: tuple[str, ...] = (
    "planner",
    "outline",
    "content",
    "composer",
    "validation",
    "aesthetic",
    "ingest_vlm",
    "advisor",
)

PROVIDERS: dict[str, type[BaseProvider]] = {
    "claude": ClaudeProvider,
    "mistral": MistralProvider,
    "nebius": NebiusProvider,
    "openai": OpenAIProvider,
}

#: Roles whose invariants are model-sensitive (B8). A `dev` pass on these is a smoke test.
MODEL_SENSITIVE_ROLES: frozenset[str] = frozenset({"validation", "content", "composer"})

#: Roles that send images. `aesthetic` critiques true renders (§6.9); `ingest_vlm`
#: describes figures (§6.3). Binding a text-only provider to either is a config error.
VISION_ROLES: frozenset[str] = frozenset({"aesthetic", "ingest_vlm"})


class RegistryError(ProviderError):
    """Malformed config, unknown environment, unknown role, or unknown provider."""


@dataclass(frozen=True)
class Binding:
    """One role's resolved provider and model, as recorded in the manifest."""

    role: str
    provider: str
    model: str


class ModelRegistry:
    """Resolves a role to a configured provider instance for one environment."""

    def __init__(
        self,
        bindings: dict[str, Binding],
        env: str,
        design_mode: str = "structured",
        confidential_ok: bool = False,
    ) -> None:
        self.env = env
        self._bindings = bindings
        #: Whether this environment may be sent a meeting transcript (B81). Absent means no.
        self.confidential_ok = confidential_ok
        #: The environment's default design mode (B69): "structured" or "creative".
        self.design_mode = design_mode

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, env: str | None = None, path: Path = DEFAULT_CONFIG_PATH) -> ModelRegistry:
        """Load `config/models.yaml` and select an environment.

        Args:
            env: environment name; falls back to the config's `default_env`.
            path: config location.

        Raises:
            RegistryError: file missing, environment unknown, or a role unbound.
        """
        if not path.exists():
            raise RegistryError(f"model config not found: {path}")

        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        environments = raw.get("environments") or {}
        if not isinstance(environments, dict):
            raise RegistryError(f"{path}: `environments` must be a mapping")

        chosen = env or raw.get("default_env")
        if not chosen:
            raise RegistryError(f"{path}: no env given and no `default_env` set")
        if chosen not in environments:
            known = ", ".join(sorted(environments)) or "none"
            raise RegistryError(f"unknown environment {chosen!r}. Known environments: {known}")

        return cls(
            _parse_bindings(environments[chosen], chosen, path),
            chosen,
            _parse_design_mode(environments[chosen], chosen, path),
            _parse_confidential_ok(environments[chosen], chosen, path),
        )

    # -- lookup ------------------------------------------------------------

    def binding(self, role: str) -> Binding:
        try:
            return self._bindings[role]
        except KeyError:
            raise RegistryError(
                f"role {role!r} is not bound in environment {self.env!r}"
            ) from None

    def bindings(self) -> dict[str, Binding]:
        """Every binding, for the build manifest (A6)."""
        return dict(self._bindings)

    def manifest_entry(self) -> dict[str, Any]:
        """The environment and resolved model IDs, shaped for `build_manifest.json`."""
        return {
            "env": self.env,
            "roles": {
                role: {"provider": b.provider, "model": b.model}
                for role, b in sorted(self._bindings.items())
            },
        }

    def provider_for(
        self, role: str, *, cache: ResponseCache | None = None, **overrides: Any
    ) -> BaseProvider:
        """Instantiate the provider bound to `role`.

        Raises:
            ProviderAuthError: the provider's API key is absent from the environment.
        """
        binding = self.binding(role)
        provider_class = PROVIDERS[binding.provider]
        key_env = _api_key_env(binding.provider)
        # `model` is passed through `overrides` rather than pinned, so a caller can point a
        # role at a different model of the same provider without editing config. It is the
        # field most worth overriding — a role whose daily quota is spent, or a one-off
        # comparison between two models — and hard-coding it here made the only useful
        # override raise TypeError.
        settings: dict[str, Any] = {
            "model": binding.model,
            "api_key": os.environ.get(key_env, ""),
            "cache": cache,
        }
        settings.update(overrides)
        return provider_class(ProviderConfig(**settings))

    def missing_credentials(self) -> list[str]:
        """Environment variables this environment needs but does not have set.

        Lets the CLI fail before a build starts rather than at the first call to whichever
        role happens to run third.
        """
        needed = {_api_key_env(b.provider) for b in self._bindings.values()}
        return sorted(name for name in needed if not os.environ.get(name))


def default_env_name(path: Path = DEFAULT_CONFIG_PATH) -> str:
    """The config's `default_env`; "dev-mistral" if the file is unreadable."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return str(raw.get("default_env") or "dev-mistral")
    except Exception:
        return "dev-mistral"


def api_key_env(provider: str) -> str:
    """The environment variable that holds `provider`'s API key."""
    return _api_key_env(provider)


def _api_key_env(provider: str) -> str:
    return {
        "claude": "ANTHROPIC_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "nebius": "NEBIUS_API_KEY",
        "openai": "OPENAI_API_KEY",
    }[provider]


#: Non-role keys an environment may carry beside its role bindings.
_ENV_SETTINGS: frozenset[str] = frozenset({"design_mode", "confidential_ok"})


def _parse_design_mode(raw: Any, env: str, path: Path) -> str:
    """The environment's default design mode; a missing key means "structured" (B69)."""
    value = raw.get("design_mode", "structured") if isinstance(raw, dict) else "structured"
    if value not in ("structured", "creative"):
        raise RegistryError(
            f"{path}: {env}.design_mode must be 'structured' or 'creative', got {value!r}"
        )
    return str(value)


def _parse_confidential_ok(raw: Any, env: str, path: Path) -> bool:
    """Whether the environment may be sent client-confidential text (B81); absent is False."""
    value = raw.get("confidential_ok", False) if isinstance(raw, dict) else False
    if not isinstance(value, bool):
        raise RegistryError(
            f"{path}: {env}.confidential_ok must be true or false, got {value!r}"
        )
    return value


def _parse_bindings(raw: Any, env: str, path: Path) -> dict[str, Binding]:
    if not isinstance(raw, dict):
        raise RegistryError(f"{path}: environment {env!r} must be a mapping of role -> binding")

    missing = [role for role in ROLES if role not in raw]
    if missing:
        raise RegistryError(
            f"{path}: environment {env!r} does not bind {', '.join(missing)}. "
            "Every role is bound explicitly — an unbound role would fail partway through a "
            "build rather than at startup."
        )

    bindings: dict[str, Binding] = {}
    for role, entry in raw.items():
        if role in _ENV_SETTINGS:
            continue
        if not isinstance(entry, dict) or "provider" not in entry or "model" not in entry:
            raise RegistryError(
                f"{path}: {env}.{role} must specify both `provider` and `model`"
            )
        provider = str(entry["provider"])
        if provider not in PROVIDERS:
            known = ", ".join(sorted(PROVIDERS))
            raise RegistryError(
                f"{path}: {env}.{role} names unknown provider {provider!r}. Known: {known}"
            )
        if role in VISION_ROLES and not PROVIDERS[provider].supports_vision:
            raise RegistryError(
                f"{path}: {env}.{role} binds {provider!r}, which serves no model that "
                "accepts image input. This role sends images, so the binding would fail "
                "at the first call rather than here."
            )
        bindings[role] = Binding(role=role, provider=provider, model=str(entry["model"]))
    _check_advisor_independent(bindings, env, path)
    return bindings


def _check_advisor_independent(bindings: dict[str, Binding], env: str, path: Path) -> None:
    """The advisor may share the composer's model, never the validator's (B44, B73).

    The validator is the independent check on what the writer produced. An advisor that the
    writer consults while writing, running on the validator's model, would let the writer
    tune its slides to that model's judgement before the check that is meant to be blind.
    """
    advisor, validation = bindings.get("advisor"), bindings.get("validation")
    if advisor and validation and (advisor.provider, advisor.model) == (
        validation.provider,
        validation.model,
    ):
        raise RegistryError(
            f"{path}: {env}.advisor binds the validation model ({validation.provider}/"
            f"{validation.model}). The advisor must be a different model from the validator "
            "(B44, B73); the composer's model is fine."
        )
