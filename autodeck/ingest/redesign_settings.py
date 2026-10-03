"""A redesign run's settings, as `runs/<run>/redesign.json` (Phase 3d, B41, B49).

`{deck_doc_id, source_file, wording, layouts, check_papers}`. Its presence is what makes a run
a redesign: `draft`, `revise` and `validate` look for the file and, if it is there, build the
deck-as-evidence pack and the two-source store instead of the paper corpus. The defaults are
B49's: keep the person's words, layouts may change, the paper check is **off**.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

REDESIGN_FILE = "redesign.json"

Wording = Literal["keep", "light"]


class RedesignSettingsError(RuntimeError):
    pass


def redesign_path(run_root: Path) -> Path:
    return Path(run_root) / REDESIGN_FILE


def normalise(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validated settings; raises `RedesignSettingsError` on a value that is not allowed."""
    wording = str(raw.get("wording", "keep"))
    if wording not in ("keep", "light"):
        raise RedesignSettingsError(f"wording must be 'keep' or 'light', not {wording!r}.")
    doc_id = str(raw.get("deck_doc_id", "")).strip()
    if not doc_id:
        raise RedesignSettingsError("redesign settings need a deck_doc_id.")
    return {
        "deck_doc_id": doc_id,
        "source_file": str(raw.get("source_file", "")),
        "wording": wording,
        "layouts": bool(raw.get("layouts", True)),
        "check_papers": bool(raw.get("check_papers", False)),
    }


def save_redesign(run_root: Path, settings: Mapping[str, Any]) -> Path:
    path = redesign_path(run_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(normalise(settings), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def load_redesign(run_root: Path) -> dict[str, Any] | None:
    """The settings, or None when this is not a redesign run."""
    path = redesign_path(run_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return normalise(data)
    except (OSError, ValueError, RedesignSettingsError) as exc:
        raise RedesignSettingsError(f"{path} cannot be read: {exc}") from exc


def settings_text(settings: Mapping[str, Any]) -> str:
    """The settings as the plain lines the model is shown."""
    wording = (
        "keep my words (reuse the client's sentences, trim only to fit a budget)"
        if settings.get("wording") == "keep"
        else "light rewording allowed (same meaning, every number and condition intact)"
    )
    layouts = (
        "layouts may change where a different component shows the point better"
        if settings.get("layouts", True)
        else "layouts may not change: map each slide to its closest component"
    )
    papers = (
        "on: the project's papers are in the evidence, to support what the deck states"
        if settings.get("check_papers")
        else "off: the deck is the only source"
    )
    return f"- wording: {wording}\n- layouts: {layouts}\n- check against papers: {papers}"
