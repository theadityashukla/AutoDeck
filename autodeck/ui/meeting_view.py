"""The meeting screen's read model and the notes file's one write (step 12, B83).

Everything here reads files the CLI wrote (`meeting/transcript.json`, `settings.json`,
`notes.md`, `notes.rendered.md`, `agent-note.md`) and returns plain JSON. The only write is
`save_notes`: the person's edit of `meeting/notes.md`, which is how the CLI's own review works
too (`meeting revise-notes --apply-edits` compares that file with `notes.rendered.md`). No
model is called, and nothing in here logs or prints a word of the transcript or the notes: a
meeting is client-confidential (B78).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from autodeck.ui.api import Roots, UIError, _open

NOTES_FILE = "notes.md"
RENDERED_FILE = "notes.rendered.md"
AGENT_NOTE_FILE = "agent-note.md"
MAX_NOTES = 200_000
"""Bytes of notes text the editor may save. Real notes are a few KB; this is a sanity cap."""

_HEADING = re.compile(r"^##\s+(.+?)\s*$")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def meeting_dir(roots: Roots, run_id: str) -> Path:
    return _open(roots, run_id).paths.root / "meeting"


def _settings(roots: Roots, run_id: str) -> dict[str, Any]:
    from autodeck.ingest.transcript_source import MeetingSettingsError, load_meeting_settings

    run_root = _open(roots, run_id).paths.root
    try:
        settings = load_meeting_settings(run_root)
    except MeetingSettingsError as exc:
        raise UIError(str(exc), status=409) from None
    if settings is None:
        raise UIError(f"Run {run_id!r} has no meeting yet.", status=404)
    return settings


def note_counts(markdown: str | None) -> dict[str, int]:
    """Bullets per `##` section of the notes, `{section: n}` in file order."""
    counts: dict[str, int] = {}
    section: str | None = None
    for line in (markdown or "").splitlines():
        heading = _HEADING.match(line)
        if heading:
            section = heading.group(1)
            counts[section] = 0
        elif section is not None and line.lstrip().startswith("- "):
            counts[section] += 1
    return counts


def notes_edited(directory: Path) -> bool:
    """Whether `notes.md` differs from `notes.rendered.md` (the copy as the agent wrote it)."""
    current, rendered = _read(directory / NOTES_FILE), _read(directory / RENDERED_FILE)
    return current is not None and rendered is not None and current != rendered


def meeting_view(roots: Roots, run_id: str) -> dict[str, Any]:
    """What the meeting screen shows for a run: the recording's facts and the notes."""
    orch = _open(roots, run_id)
    settings = _settings(roots, run_id)
    directory = orch.paths.root / "meeting"
    duration, turns, labelled = 0.0, 0, False
    try:
        transcript = json.loads((directory / "transcript.json").read_text(encoding="utf-8"))
        duration = float(transcript["audio"]["duration_s"])
        turns = sum(1 for s in transcript["segments"] if str(s.get("text", "")).strip())
        labelled = bool(transcript.get("speakers_labelled"))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    markdown = _read(directory / NOTES_FILE)
    note = (_read(directory / AGENT_NOTE_FILE) or "").strip()
    return {
        "has_meeting": True,
        "audio_name": settings["audio_name"],
        "duration_s": duration,
        "turns": turns,
        "speakers_labelled": labelled,
        "check_papers": settings["check_papers"],
        "notes": {
            "markdown": markdown,
            "edited": notes_edited(directory),
            "counts": note_counts(markdown),
            "agent_note": note or None,
            "has_session": (orch.paths.root / "session" / "notes_transcript.jsonl").is_file(),
        },
        "has_deck": orch.state.is_complete("compose"),
    }


def _stamp(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    from autodeck.audit.report import meeting_stamp

    return meeting_stamp(seconds)


def transcript_view(roots: Roots, run_id: str) -> dict[str, Any]:
    """`{"turns": [{page, time, text}]}`: the citable turns, with their times for display."""
    from autodeck.ingest.document_store import DocumentStore, IngestError
    from autodeck.ingest.transcript_source import meeting_times

    orch = _open(roots, run_id)
    settings = _settings(roots, run_id)
    run_root = orch.paths.root
    try:
        document = DocumentStore(run_root / "source").get(settings["doc_id"])
    except (IngestError, OSError, ValueError, KeyError):
        raise UIError("The transcript has not been read yet.", status=409) from None
    times = meeting_times(run_root).get(settings["doc_id"], {})
    turns = [
        {"page": e.page, "time": _stamp(times.get(e.page)), "text": e.text}
        for e in sorted(document.elements, key=lambda e: e.reading_order)
        if e.page is not None
    ]
    return {"turns": turns}


def save_notes(roots: Roots, run_id: str, markdown: Any) -> dict[str, Any]:
    """Write the person's edited text to `meeting/notes.md`, atomically.

    Refused before there are notes (nothing to edit), for anything that is not text, and over
    `MAX_NOTES`. `notes.rendered.md` and `notes.json` are never touched: the difference between
    `notes.md` and the rendered copy is exactly "my edits".
    """
    directory = meeting_dir(roots, run_id)
    if not (directory / NOTES_FILE).is_file():
        raise UIError("There are no notes to edit yet.", status=409)
    if not isinstance(markdown, str) or "\x00" in markdown:
        raise UIError("The notes must be plain text.")
    data = markdown.encode("utf-8")
    if len(data) > MAX_NOTES:
        raise UIError("Those notes are over the 200 KB limit.", status=413)
    target = directory / NOTES_FILE
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return {
        "markdown": markdown,
        "edited": notes_edited(directory),
        "counts": note_counts(markdown),
    }
