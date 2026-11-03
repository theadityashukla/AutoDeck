"""A run's provenance mode, snapshotted once (B55).

The mode is a *project* setting (`knowledge/projects/<p>/settings.yaml`), but a run must not
change mode under the person: the evidence the draft was written from and the verdicts it
was validated against assume one mode. So the first command that needs the mode writes it to
`runs/<run>/provenance.json` and every later command reads that file, ignoring later edits to
the project setting.

`run_root` is the run directory (`run_paths(runs_root, run_id).root`). The path is computed
here rather than added to `RunPaths` because `autodeck/ir/` is guardrail territory for this
change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from autodeck.ir.models import ProvenanceMode
from autodeck.knowledge.loader import ProjectSettings

PROVENANCE_FILE = "provenance.json"

_MODES: tuple[str, ...] = get_args(ProvenanceMode)


class ProvenanceModeError(RuntimeError):
    """The snapshot is unreadable, or a mode change was requested after it was fixed."""


def provenance_path(run_root: Path) -> Path:
    return Path(run_root) / PROVENANCE_FILE


def _read(run_root: Path) -> ProvenanceMode | None:
    path = provenance_path(run_root)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("provenance")
    except (OSError, ValueError, AttributeError) as exc:
        raise ProvenanceModeError(f"{path} cannot be read: {exc}") from exc
    if value not in _MODES:
        raise ProvenanceModeError(f"{path}: provenance must be one of {_MODES}, got {value!r}")
    return value  # type: ignore[no-any-return]


def snapshot_mode(run_root: Path, mode: ProvenanceMode) -> ProvenanceMode:
    """Fix this run's mode to `mode` if none is set; otherwise return the stored one.

    A run's mode is fixed once set, so a stored value always wins over `mode`.
    """
    stored = _read(run_root)
    if stored is not None:
        return stored
    if mode not in _MODES:
        raise ProvenanceModeError(f"provenance must be one of {_MODES}, got {mode!r}")
    path = provenance_path(run_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"provenance": mode}) + "\n", encoding="utf-8")
    temporary.replace(path)
    return mode


def load_mode(run_root: Path) -> ProvenanceMode:
    """The run's mode. A run with no snapshot is `strict`.

    Fail-safe: a run created before B55 was built under A1 as it then stood — document spans
    only — and `strict` is exactly that. Defaulting such a run to `normal` would let a resume
    admit conversation or unsourced content into a deck that was never checked for it.
    """
    return _read(run_root) or "strict"


def resolve_mode(
    run_root: Path, settings: ProjectSettings, override: ProvenanceMode | None = None
) -> ProvenanceMode:
    """The mode for a run: the snapshot if one exists, else `override`, else the project's.

    Snapshots the result. An `override` is only allowed before a snapshot exists.

    Raises:
        ProvenanceModeError: an override that differs from the run's fixed mode (or any
            override once the run has a snapshot — repeating the same value is accepted).
    """
    stored = _read(run_root)
    if stored is not None:
        if override is not None and override != stored:
            raise ProvenanceModeError(
                f"this run is already fixed to provenance={stored!r}; it cannot be "
                f"changed to {override!r}. Start a new run to use a different mode."
            )
        return stored
    return snapshot_mode(run_root, override or settings.provenance)
