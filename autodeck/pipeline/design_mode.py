"""A run's design mode, snapshotted once (B69).

A run is designed either `structured` (the composer picks catalog layouts) or `creative`
(the writer places every slide). The environment supplies the default (`design_mode:` in
`config/models.yaml`), the person may override it when the run starts, and the choice is then
fixed: the first command that needs it writes `runs/<run>/design_mode.json` and every later
command reads that file. Mirrors `provenance.py` (B55).

`run_root` is the run directory (`run_paths(runs_root, run_id).root`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from autodeck.ir.models import DesignMode

DESIGN_MODE_FILE = "design_mode.json"

_MODES: tuple[str, ...] = get_args(DesignMode)


class DesignModeError(RuntimeError):
    """The snapshot is unreadable, or a mode change was requested after it was fixed."""


def design_mode_path(run_root: Path) -> Path:
    return Path(run_root) / DESIGN_MODE_FILE


def _read(run_root: Path) -> DesignMode | None:
    path = design_mode_path(run_root)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("design_mode")
    except (OSError, ValueError, AttributeError) as exc:
        raise DesignModeError(f"{path} cannot be read: {exc}") from exc
    if value not in _MODES:
        raise DesignModeError(f"{path}: design_mode must be one of {_MODES}, got {value!r}")
    return value  # type: ignore[no-any-return]


def snapshot_design_mode(run_root: Path, mode: DesignMode) -> DesignMode:
    """Fix this run's mode to `mode` if none is set; otherwise return the stored one."""
    stored = _read(run_root)
    if stored is not None:
        return stored
    if mode not in _MODES:
        raise DesignModeError(f"design_mode must be one of {_MODES}, got {mode!r}")
    path = design_mode_path(run_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"design_mode": mode}) + "\n", encoding="utf-8")
    temporary.replace(path)
    return mode


def load_design_mode(run_root: Path) -> DesignMode:
    """The run's mode. A run with no snapshot is `structured`.

    Fail-safe: a run created before B69 was designed from catalog layouts, which is what
    `structured` means.
    """
    return _read(run_root) or "structured"


def resolve_design_mode(
    run_root: Path, default: DesignMode, override: DesignMode | None = None
) -> DesignMode:
    """The mode for a run: the snapshot if one exists, else `override`, else `default`.

    Snapshots the result. An `override` is only allowed before a snapshot exists.

    Raises:
        DesignModeError: an override that differs from the run's fixed mode (repeating the
            same value is accepted).
    """
    stored = _read(run_root)
    if stored is not None:
        if override is not None and override != stored:
            raise DesignModeError(
                f"this run is already fixed to design_mode={stored!r}; it cannot be "
                f"changed to {override!r}. Start a new run to use a different mode."
            )
        return stored
    return snapshot_design_mode(run_root, override or default)
