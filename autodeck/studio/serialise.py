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

import hashlib
import json
import os
import uuid
from pathlib import Path

from pydantic import BaseModel

from autodeck.studio.models import ChangeLog, DeckArtifact, EngagementRecord

ENCODING = "utf-8"


def dump_model(model: BaseModel) -> str:
    """The canonical text of any studio model (see module docstring). Pure."""
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def dump_artifact(deck: DeckArtifact) -> str:
    """`dump_model(deck)`. Named separately because it is what digests and snapshots use."""
    return dump_model(deck)


def load_artifact(text: str) -> DeckArtifact:
    """Parse and validate a deck artifact.

    Raises:
        pydantic.ValidationError: the text is not JSON or not a valid `DeckArtifact`.
    """
    return DeckArtifact.model_validate_json(text)


def load_changelog(text: str) -> ChangeLog:
    """Parse and validate a change log (its invariants run on load).

    Raises:
        pydantic.ValidationError: not JSON, or not a valid, self-consistent `ChangeLog`.
    """
    return ChangeLog.model_validate_json(text)


def load_engagement_record(text: str) -> EngagementRecord:
    """Parse and validate an engagement record.

    Raises:
        pydantic.ValidationError: not JSON or not a valid `EngagementRecord`.
    """
    return EngagementRecord.model_validate_json(text)


def text_digest(text: str) -> str:
    """Lower-case SHA-256 hex of `text` encoded as UTF-8. Pure."""
    return hashlib.sha256(text.encode(ENCODING)).hexdigest()


def artifact_digest(deck: DeckArtifact) -> str:
    """`text_digest(dump_artifact(deck))`: the identity of a deck state."""
    return text_digest(dump_artifact(deck))


def atomic_write_text(path: Path, text: str) -> Path:
    """Write `text` (UTF-8, no newline translation) to `path` atomically and return `path`.

    Write to a sibling temporary file in the same directory (so the rename stays on one
    filesystem), flush and `os.fsync` it, then `os.replace` it over `path`. The parent
    directory must already exist; a missing parent raises `FileNotFoundError`. On any
    failure the temporary file is removed and `path` is left as it was. Writing must use
    `newline=""` (or bytes) so the bytes on disk equal `text.encode("utf-8")` on every OS.
    """
    data = text.encode(ENCODING)
    # Exclusive create ("xb") so an existing file is never clobbered by accident; the name
    # is unique per call. Default permissions apply (no 0600 from mkstemp).
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def read_text(path: Path) -> str:
    """Read a studio file as UTF-8 with no newline translation (`newline=""`), so that
    `read_text(atomic_write_text(p, t)) == t` exactly.

    Raises:
        FileNotFoundError: `path` does not exist.
    """
    with path.open(encoding=ENCODING, newline="") as handle:
        return handle.read()
