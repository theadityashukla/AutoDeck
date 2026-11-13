"""Canonical serialisation, digests and atomic writes for studio files.

**Exact undo rests on this module.** "After undo the artifact equals its previous state
byte for byte" is only testable if one state has exactly one serialisation. So every
studio JSON file is written by `dump_model`: `model_dump(mode="json")` (all fields,
defaults included, declaration order), `json.dumps(..., indent=2, ensure_ascii=False)`,
then one trailing newline. That is the same convention as v2's `ir/store._dump`, kept so a
`git diff` of two files reads the same way. Keys are *not* sorted: pydantic's declaration
order is stable and reads better.

Invariant every implementer and test relies on: for any valid model `m`,
`dump_model(type(m).model_validate_json(dump_model(m))) == dump_model(m)`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from autodeck.studio.models import ChangeLog, DeckArtifact, EngagementRecord

ENCODING = "utf-8"


def dump_model(model: BaseModel) -> str:
    """The canonical text of any studio model (see module docstring). Pure."""
    raise NotImplementedError


def dump_artifact(deck: DeckArtifact) -> str:
    """`dump_model(deck)`. Named separately because it is what digests and snapshots use."""
    raise NotImplementedError


def load_artifact(text: str) -> DeckArtifact:
    """Parse and validate a deck artifact.

    Raises:
        pydantic.ValidationError: the text is not JSON or not a valid `DeckArtifact`.
    """
    raise NotImplementedError


def load_changelog(text: str) -> ChangeLog:
    """Parse and validate a change log (its invariants run on load).

    Raises:
        pydantic.ValidationError: not JSON, or not a valid, self-consistent `ChangeLog`.
    """
    raise NotImplementedError


def load_engagement_record(text: str) -> EngagementRecord:
    """Parse and validate an engagement record.

    Raises:
        pydantic.ValidationError: not JSON or not a valid `EngagementRecord`.
    """
    raise NotImplementedError


def text_digest(text: str) -> str:
    """Lower-case SHA-256 hex of `text` encoded as UTF-8. Pure."""
    raise NotImplementedError


def artifact_digest(deck: DeckArtifact) -> str:
    """`text_digest(dump_artifact(deck))`: the identity of a deck state."""
    raise NotImplementedError


def atomic_write_text(path: Path, text: str) -> Path:
    """Write `text` (UTF-8, no newline translation) to `path` atomically and return `path`.

    Write to a sibling temporary file in the same directory (so the rename stays on one
    filesystem), flush and `os.fsync` it, then `os.replace` it over `path`. The parent
    directory must already exist; a missing parent raises `FileNotFoundError`. On any
    failure the temporary file is removed and `path` is left as it was. Writing must use
    `newline=""` (or bytes) so the bytes on disk equal `text.encode("utf-8")` on every OS.
    """
    raise NotImplementedError


def read_text(path: Path) -> str:
    """Read a studio file as UTF-8 with no newline translation (`newline=""`), so that
    `read_text(atomic_write_text(p, t)) == t` exactly.

    Raises:
        FileNotFoundError: `path` does not exist.
    """
    raise NotImplementedError
