"""Environment-tiered role registry (D6, B8).

Bindings live in `config/models.yaml`, never in code, so a model swap is a config edit and
the resolved IDs can be recorded in the build manifest (A6). The registry's other job is to
make the environment *explicit*: `dev` runs on free-tier Gemini and Groq, `sit` and `prod`
run on Claude, and because A3 and A8 are model-sensitive an accuracy result from one does
not transfer to the other. Anything that reports a result records `env` alongside it.

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
from autodeck.providers.gemini import GeminiProvider
from autodeck.providers.groq import GroqProvider

DEFAULT_CONFIG_PATH = Path("config/models.yaml")

#: The six agent roles of plan §6.2. A config missing one of these is rejected at load
#: rather than at the moment that role is first invoked, halfway through a build.
ROLES: tuple[str, ...] = (
    "planner",
    "outline",
    "content",
    "validation",
    "aesthetic",
    "ingest_vlm",
)

PROVIDERS: dict[str, type[BaseProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "claude": ClaudeProvider,
}

#: Roles whose invariants are model-sensitive (B8). A `dev` pass on these is a smoke test.
MODEL_SENSITIVE_ROLES: frozenset[str] = frozenset({"validation", "content"})

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

    def __init__(self, bindings: dict[str, Binding], env: str) -> None:
        self.env = env
        self._bindings = bindings

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

        return cls(_parse_bindings(environments[chosen], chosen, path), chosen)

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
        config = ProviderConfig(
            model=binding.model,
            api_key=os.environ.get(key_env, ""),
            cache=cache,
            **overrides,
        )
        return provider_class(config)

    def missing_credentials(self) -> list[str]:
        """Environment variables this environment needs but does not have set.

        Lets the CLI fail before a build starts rather than at the first call to whichever
        role happens to run third.
        """
        needed = {_api_key_env(b.provider) for b in self._bindings.values()}
        return sorted(name for name in needed if not os.environ.get(name))


def _api_key_env(provider: str) -> str:
    return {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }[provider]


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
    return bindings
