"""Versioned IR persistence and diffing under `runs/<run_id>/`.

Every IR version is a file on disk, inspectable and diffable, because the gates are
review events and a reviewer needs to see *what changed* between the outline they approved
and the content they are being asked to approve. Plan §4: all intermediate artifacts are
files — inspectable, diffable, resumable.

The diff is deliberately dependency-free and **identity-aware**: lists of objects carrying
an `id` are matched by id rather than by position. Positional diffing would report a slide
inserted at index 2 as a change to every slide after it, which makes a gate review read as
a rewrite and trains the reviewer to skim. That would be an accuracy problem, not a
cosmetic one.

Owning phase: 0 (task 0.2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from autodeck.ir.models import Deck, DeckBrief

_VERSION_FILE = re.compile(r"^v(\d+)\.json$")
_BRIEF_FILE = re.compile(r"^v(\d+)\.yaml$")

#: Written with a trailing newline and stable key order so a git diff of two IR versions is
#: readable and so A6's byte-comparability has a fixed target.
_JSON_KWARGS: dict[str, Any] = {"indent": 2, "ensure_ascii": False}


class IRStoreError(RuntimeError):
    """Raised for a missing run, a missing version, or a malformed store layout."""


# ---------------------------------------------------------------------------
# Run directory layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunPaths:
    """The on-disk layout of a single build.

    One place defines these names. Phase 1 onwards adds sibling directories; nothing
    should be constructing `runs/<id>/...` paths by string concatenation.
    """

    root: Path

    @property
    def ir(self) -> Path:
        return self.root / "ir"

    @property
    def brief(self) -> Path:
        return self.root / "brief"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def llm_cache(self) -> Path:
        return self.root / "llm_cache"

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    @property
    def manifest_file(self) -> Path:
        return self.root / "build_manifest.json"

    def ensure(self) -> RunPaths:
        """Create the directory tree if it does not exist."""
        for path in (self.root, self.ir, self.brief, self.artifacts, self.logs, self.llm_cache):
            path.mkdir(parents=True, exist_ok=True)
        return self


def run_paths(runs_root: Path, run_id: str) -> RunPaths:
    """Resolve the paths for one run beneath `runs_root`."""
    if not run_id or "/" in run_id or run_id in (".", ".."):
        raise IRStoreError(f"invalid run_id: {run_id!r}")
    return RunPaths(Path(runs_root) / run_id)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class IRStore:
    """Load, save and enumerate IR versions for one run.

    Versions are immutable once written. `save` refuses to overwrite an existing version,
    because an IR version that changed after a gate approved it would silently invalidate
    the approval — the reviewer signed off on bytes, not on a version number.
    """

    def __init__(self, runs_root: Path, run_id: str) -> None:
        self.run_id = run_id
        self.paths = run_paths(runs_root, run_id)

    # -- decks ------------------------------------------------------------

    def version_path(self, version: int) -> Path:
        if version < 1:
            raise IRStoreError(f"IR versions start at 1, got {version}")
        return self.paths.ir / f"v{version}.json"

    def versions(self) -> list[int]:
        """Existing IR version numbers, ascending."""
        if not self.paths.ir.is_dir():
            return []
        found = [
            int(match.group(1))
            for path in self.paths.ir.iterdir()
            if (match := _VERSION_FILE.match(path.name))
        ]
        return sorted(found)

    def latest_version(self) -> int | None:
        versions = self.versions()
        return versions[-1] if versions else None

    def next_version(self) -> int:
        """The version number a new IR should carry."""
        latest = self.latest_version()
        return 1 if latest is None else latest + 1

    def save(self, deck: Deck, *, overwrite: bool = False) -> Path:
        """Write `deck` at its own `version`. Returns the path written.

        Raises:
            IRStoreError: the deck's run_id does not match this store, or the version
                already exists and `overwrite` is not set.
        """
        if deck.run_id != self.run_id:
            raise IRStoreError(
                f"deck.run_id {deck.run_id!r} does not match store run {self.run_id!r}"
            )
        path = self.version_path(deck.version)
        if path.exists() and not overwrite:
            raise IRStoreError(
                f"IR v{deck.version} already exists for run {self.run_id!r}. "
                "IR versions are immutable — write the next version instead."
            )
        self.paths.ensure()
        path.write_text(_dump(deck), encoding="utf-8")
        return path

    def load(self, version: int | None = None) -> Deck:
        """Load an IR version, defaulting to the latest."""
        if version is None:
            version = self.latest_version()
            if version is None:
                raise IRStoreError(f"run {self.run_id!r} has no IR versions")
        path = self.version_path(version)
        if not path.exists():
            raise IRStoreError(f"IR v{version} not found for run {self.run_id!r}: {path}")
        return Deck.model_validate_json(path.read_text(encoding="utf-8"))

    # -- brief (§6.13, first A7 approval) ---------------------------------
    #
    # Versioned exactly like the IR, and for the same reason: a brief that changed after
    # sign-off would silently invalidate the approval. GATE 1 reviews the outline against
    # a specific brief version, so that version has to still exist afterwards.
    #
    # Stored as YAML rather than JSON because a human reads, edits and signs this one.
    # It is the only artifact in a run with that property — the IR is machine-authored and
    # machine-diffed, the brief is a document two people argue over.

    def brief_version_path(self, version: int) -> Path:
        if version < 1:
            raise IRStoreError(f"brief versions start at 1, got {version}")
        return self.paths.brief / f"v{version}.yaml"

    def brief_versions(self) -> list[int]:
        if not self.paths.brief.is_dir():
            return []
        found = [
            int(match.group(1))
            for path in self.paths.brief.iterdir()
            if (match := _BRIEF_FILE.match(path.name))
        ]
        return sorted(found)

    def latest_brief_version(self) -> int | None:
        versions = self.brief_versions()
        return versions[-1] if versions else None

    def next_brief_version(self) -> int:
        latest = self.latest_brief_version()
        return 1 if latest is None else latest + 1

    def save_brief(self, brief: DeckBrief, *, overwrite: bool = False) -> Path:
        """Write `brief` at its own `version` as YAML. Returns the path written.

        Raises:
            IRStoreError: the run_id does not match, or the version exists and `overwrite`
                is not set.
        """
        if brief.run_id != self.run_id:
            raise IRStoreError(
                f"brief.run_id {brief.run_id!r} does not match store run {self.run_id!r}"
            )
        path = self.brief_version_path(brief.version)
        if path.exists() and not overwrite:
            raise IRStoreError(
                f"brief v{brief.version} already exists for run {self.run_id!r}. "
                "Brief versions are immutable — write the next version instead."
            )
        self.paths.ensure()
        path.write_text(dump_brief_yaml(brief), encoding="utf-8")
        return path

    def load_brief(self, version: int | None = None) -> DeckBrief:
        """Load a brief version, defaulting to the latest."""
        if version is None:
            version = self.latest_brief_version()
            if version is None:
                raise IRStoreError(f"run {self.run_id!r} has no brief")
        path = self.brief_version_path(version)
        if not path.exists():
            raise IRStoreError(f"brief v{version} not found for run {self.run_id!r}: {path}")
        return load_brief_yaml(path.read_text(encoding="utf-8"))


def dump_brief_yaml(brief: DeckBrief) -> str:
    """Serialise a brief to YAML a human can read and edit.

    `sort_keys=False` deliberately: pydantic emits fields in declaration order, which runs
    objective → audience → key messages → constraints, and that is the order someone reads
    a brief in. Alphabetising it would put `approved_by` first and bury the objective.
    """
    return yaml.safe_dump(
        brief.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=88,
    )


def load_brief_yaml(text: str) -> DeckBrief:
    """Parse a brief from YAML, validating it.

    Hand-edited briefs are expected — a planning session ends with the owner editing this
    file — so a malformed one must fail with pydantic's message rather than half-load.

    Raises:
        IRStoreError: the YAML is invalid or is not a mapping.
        ValidationError: the mapping is not a valid brief, including the A8 rule that an
            unsupported key message needs a matching open risk.
    """
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise IRStoreError(f"brief is not valid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise IRStoreError(
            f"brief must be a YAML mapping, got {type(payload).__name__}. An empty or "
            "list-shaped file usually means an editor mangled it."
        )
    return DeckBrief.model_validate(payload)


def _dump(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), **_JSON_KWARGS) + "\n"


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

ChangeKind = Literal["added", "removed", "changed"]


@dataclass(frozen=True)
class Change:
    """One difference between two IR versions."""

    path: str
    kind: ChangeKind
    before: Any = None
    after: Any = None

    def __str__(self) -> str:
        if self.kind == "added":
            return f"+ {self.path} = {_brief(self.after)}"
        if self.kind == "removed":
            return f"- {self.path} = {_brief(self.before)}"
        return f"~ {self.path}: {_brief(self.before)} -> {_brief(self.after)}"


def _brief(value: Any, limit: int = 70) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def diff_decks(before: Deck, after: Deck) -> list[Change]:
    """Structural diff between two IR versions, for gate review.

    Objects in a list are matched by their `id` where every element has one, so an
    insertion reads as one addition rather than as a cascade of positional changes.
    """
    return _diff(before.model_dump(mode="json"), after.model_dump(mode="json"), "")


def _diff(before: Any, after: Any, path: str) -> list[Change]:
    if isinstance(before, dict) and isinstance(after, dict):
        return _diff_dict(before, after, path)
    if isinstance(before, list) and isinstance(after, list):
        return _diff_list(before, after, path)
    if before != after:
        return [Change(path or ".", "changed", before, after)]
    return []


def _diff_dict(before: dict[str, Any], after: dict[str, Any], path: str) -> list[Change]:
    changes: list[Change] = []
    for key in sorted(set(before) | set(after)):
        child = f"{path}.{key}" if path else key
        if key not in after:
            changes.append(Change(child, "removed", before=before[key]))
        elif key not in before:
            changes.append(Change(child, "added", after=after[key]))
        else:
            changes.extend(_diff(before[key], after[key], child))
    return changes


def _keyed(items: list[Any]) -> dict[str, Any] | None:
    """Index a list by element `id`, or None when that is not possible."""
    if not items or not all(
        isinstance(i, dict) and isinstance(i.get("id"), str) for i in items
    ):
        return None
    keyed = {item["id"]: item for item in items}
    return keyed if len(keyed) == len(items) else None


def _diff_list(before: list[Any], after: list[Any], path: str) -> list[Change]:
    keyed_before, keyed_after = _keyed(before), _keyed(after)

    if keyed_before is not None and keyed_after is not None:
        changes: list[Change] = []
        for key in sorted(set(keyed_before) | set(keyed_after)):
            child = f"{path}[{key}]"
            if key not in keyed_after:
                changes.append(Change(child, "removed", before=keyed_before[key]))
            elif key not in keyed_before:
                changes.append(Change(child, "added", after=keyed_after[key]))
            else:
                changes.extend(_diff(keyed_before[key], keyed_after[key], child))
        # Reordering is a real change for slides, and invisible to an id-keyed comparison.
        order_before = [i["id"] for i in before if i["id"] in keyed_after]
        order_after = [i["id"] for i in after if i["id"] in keyed_before]
        if order_before != order_after:
            changes.append(Change(f"{path}[order]", "changed", order_before, order_after))
        return changes

    changes = []
    for index in range(max(len(before), len(after))):
        child = f"{path}[{index}]"
        if index >= len(after):
            changes.append(Change(child, "removed", before=before[index]))
        elif index >= len(before):
            changes.append(Change(child, "added", after=after[index]))
        else:
            changes.extend(_diff(before[index], after[index], child))
    return changes
