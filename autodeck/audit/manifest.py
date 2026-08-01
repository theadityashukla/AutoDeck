"""Build manifest (A6) — what produced this deck.

A6 requires every deck to ship a manifest recording model IDs and versions, prompt file
hashes, the knowledge folder's git commit, and the component library version, such that the
same manifest plus the same IR re-renders byte-comparable output.

Phase 0 produces a *blank but valid* manifest: the schema is fixed now so later phases fill
fields rather than inventing structure, and the `env` plus resolved model IDs are recorded
from the first run. That last part matters immediately — B8 makes `dev` and `prod` results
non-transferable, so a deck that does not state which bindings produced it cannot be
interpreted at all.

Owning phase: 0 (skeleton) / Phase 2b (populated). Opus tier — `autodeck/audit/` is a path
guardrail in docs/MODEL_ROUTING.md.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_VERSION = 1


class Manifest(BaseModel):
    """The reproducibility record shipped with every deck."""

    model_config = ConfigDict(extra="forbid")

    manifest_version: int = MANIFEST_VERSION
    run_id: str = Field(min_length=1)
    env: str = Field(min_length=1, description="Which provider bindings produced this (B8).")
    created_at: str

    models: dict[str, Any] = Field(default_factory=dict)
    """Resolved provider and model per role, from `ModelRegistry.manifest_entry()`."""

    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    """Prompt file path -> SHA-256. Plan §0.5 versions prompts; A6 pins which version ran."""

    knowledge_commit: str | None = None
    """Git commit of the knowledge folder, when one is in use (Phase 1)."""

    component_lib_version: str = "0.0.0"
    ir_sha256: str | None = None
    autodeck_version: str = "2.0.0.dev0"

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.model_dump(mode="json"), indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def reproducibility_key(self) -> dict[str, Any]:
        """The fields that must match for two builds to be considered the same build.

        `created_at` is excluded on purpose — A6 says byte-comparable *excluding
        timestamps*, and comparing a build against itself an hour later must succeed.
        """
        return self.model_dump(mode="json", exclude={"created_at"})

    def matches(self, other: Manifest) -> bool:
        """Whether `other` describes the same build, ignoring timestamps."""
        return self.reproducibility_key() == other.reproducibility_key()


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's contents."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


#: Documentation living under `prompts/` is not itself a prompt. Hashing it would make an
#: edit to the README change every build's reproducibility key, which would turn a real A6
#: signal into noise.
_NOT_A_PROMPT: frozenset[str] = frozenset({"README.md"})


def hash_prompts(prompts_dir: Path) -> dict[str, str]:
    """Hash every prompt file, keyed by path relative to `prompts_dir`.

    Sorted so the manifest is stable between runs — an unordered dict would make two
    identical builds produce different JSON and break the A6 comparison for no reason.
    """
    prompts_dir = Path(prompts_dir)
    if not prompts_dir.is_dir():
        return {}
    return {
        str(path.relative_to(prompts_dir)): file_sha256(path)
        for path in sorted(prompts_dir.rglob("*.md"))
        if path.name not in _NOT_A_PROMPT
    }


def git_commit(repo_dir: Path) -> str | None:
    """Current commit of `repo_dir`, or None if it is not a git working tree."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def build_manifest(
    *,
    run_id: str,
    env: str,
    models: dict[str, Any] | None = None,
    prompts_dir: Path | None = None,
    knowledge_dir: Path | None = None,
    component_lib_version: str = "0.0.0",
    ir_path: Path | None = None,
) -> Manifest:
    """Assemble a manifest from the current build's inputs."""
    return Manifest(
        run_id=run_id,
        env=env,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        models=models or {},
        prompt_hashes=hash_prompts(prompts_dir) if prompts_dir else {},
        knowledge_commit=git_commit(knowledge_dir) if knowledge_dir else None,
        component_lib_version=component_lib_version,
        ir_sha256=file_sha256(ir_path) if ir_path else None,
    )
