"""`autodeck meeting notes`: one agent session writes a meeting's notes (plan step 10, B80).

The deck agent (`deck_agent.py`, B71) writes slides through tools; this one writes meeting
notes the same way, from a transcript instead of a corpus. It reads the transcript, fills the
notes' sections one tool call at a time, sees each edit's result, has the whole notes read
cold by the advisor (B73), fixes what the advisor finds, and finishes. What code decides does
not change: every item's quotes resolve through the deck's own resolver against the turns the
session showed (A1, B75), and `notes_workspace.write_notes` turns the workspace into
`notes.md` and `notes.json`.

What the agent starts with:
- **system**: `prompts/notes_agent.md`, the `meeting-notes` skill and an index of the few other
  skills worth loading (loaded on demand with `load_skill`). Saved as
  `session/notes_system.md`, so a resumed session speaks under the instructions it started with.
- **opening message**: the meeting's date and the people the person says were there, the
  client context, what earlier runs remember (B77) and the transcript: every turn when it is
  short (all citable at once), otherwise its size and the tools to read it.

Session files live in the run's `session/` folder under notes-specific names
(`notes_transcript.jsonl`, `notes_system.md`, `notes_workspace.json`, `notes_meta.json`) beside
the shared `memory/`, so the deck session a meeting run can later have (`meeting_deck.py`,
B82) keeps its own `transcript.jsonl`, `system.md` and `workspace.json` there. A step-10 run
used the deck names for the notes; `migrate_notes_session` renames them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodeck.agents.advisor import AdvisorModel
from autodeck.agents.compose import PROMPT_SEPARATOR, ComposeError, read_prompt
from autodeck.agents.notes_workspace import NotesError, NotesWorkspace, notes_text
from autodeck.agents.session import (
    SessionLimits,
    SessionState,
    TranscriptLog,
    compact,
    run_session,
)
from autodeck.agents.skills import _without_project, available_skills, load_skill
from autodeck.agents.tools.memory import memory_tools
from autodeck.agents.tools.notes import (
    notes_advisor_tools,
    notes_tools,
    transcript_index,
    turn_line,
)
from autodeck.agents.tools.registry import ToolBox
from autodeck.agents.tools.skills import skill_tools
from autodeck.audit.report import meeting_stamp
from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.knowledge.memory import MemoryStore
from autodeck.providers.base import Message

NOTES_PROMPT = Path("prompts/notes_agent.md")
ALWAYS_LOADED = "meeting-notes"
INDEXED_SKILLS: tuple[str, ...] = ("writing-style", "fidelity", "meeting-readout")
"""The skills the notes agent is told it can load, beside the one it always has."""

PRELOAD_TOKENS = 20_000
"""A transcript estimated (`len // 4`) at or under this is put in the opening message whole,
and every turn is citable from the start."""

RESEED_TOKENS = 60_000
"""When the (compacted) session is estimated above this, a resume starts a fresh transcript
seeded with the notes as they stand, instead of continuing."""


@dataclass
class SessionFiles:
    """Where a run's notes session lives: `runs/<run>/session/`."""

    root: Path

    @property
    def transcript(self) -> Path:
        return self.root / "notes_transcript.jsonl"

    @property
    def workspace(self) -> Path:
        return self.root / "notes_workspace.json"

    @property
    def system(self) -> Path:
        return self.root / "notes_system.md"

    @property
    def meta(self) -> Path:
        return self.root / "notes_meta.json"

    @property
    def memory(self) -> Path:
        return self.root / "memory"


def migrate_notes_session(session_dir: Path) -> list[str]:
    """Rename a step-10 notes session's files to the notes names; returns what it renamed.

    Step 10 wrote the notes session as `transcript.jsonl`, `system.md` and `meta.json` (plus
    archives `transcript.N.jsonl`) beside `notes_workspace.json`. Those names belong to the deck
    session now. The old names are the notes' only while `notes_workspace.json` exists and no
    `workspace.json` does (no deck session has taken them); a file is never overwritten.
    """
    root = Path(session_dir)
    if not (root / "notes_workspace.json").is_file() or (root / "workspace.json").exists():
        return []
    pairs = [("transcript.jsonl", "notes_transcript.jsonl"), ("system.md", "notes_system.md")]
    meta = root / "meta.json"
    try:
        notes_meta = (
            meta.is_file()
            and json.loads(meta.read_text(encoding="utf-8")).get("kind") == "notes"
        )
    except (OSError, ValueError, AttributeError):
        notes_meta = False
    if notes_meta:
        pairs.append(("meta.json", "notes_meta.json"))
    for archived in sorted(root.glob("transcript.*.jsonl")):
        pairs.append((archived.name, "notes_" + archived.name))
    moved = []
    for old, new in pairs:
        if (root / old).is_file() and not (root / new).exists():
            (root / old).replace(root / new)
            moved.append(f"{old} -> {new}")
    return moved


@dataclass
class NotesRun:
    """A finished (or stopped) session: the notes workspace and the session behind it."""

    workspace: NotesWorkspace
    state: SessionState


# -- what the agent is told -------------------------------------------------------


def notes_system(*, project: str | None) -> str:
    """The session's system prompt. Every part is a file, so every part is hashed (A6)."""
    skill = load_skill(ALWAYS_LOADED)
    indexed = []
    for name in INDEXED_SKILLS:
        if name in available_skills():
            s = load_skill(name)
            indexed.append(f"- `{s.name}` — {s.summary} (use when: {s.use_when})")
    return PROMPT_SEPARATOR.join(
        [
            read_prompt(NOTES_PROMPT),
            f"# Skill: `{skill.name}`\n\n{_without_project(skill.body, project)}",
            "# Skills you can load with `load_skill`\n\n" + "\n".join(indexed),
        ]
    )


def transcript_text(
    doc: Document, times: Mapping[int, float], pages: Sequence[int] | None = None
) -> str:
    """`turn N [mm:ss]: text` lines for the given turns (default: all)."""
    by_page: dict[int, list[str]] = {}
    for element in doc.elements:
        by_page.setdefault(element.page, []).append(element.text)
    wanted = list(pages) if pages is not None else sorted(by_page)
    return "\n".join(turn_line(p, " ".join(by_page.get(p, [])), times) for p in wanted)


def _duration(times: Mapping[int, float]) -> str:
    return f", about {meeting_stamp(max(times.values()))} long" if times else ""


def notes_opening_message(
    *,
    transcript: Document,
    times: Mapping[int, float],
    context: AssembledContext,
    memory_text: str,
    meeting_date: str | None,
    attendees: Sequence[str],
    preload: bool,
) -> str:
    meeting = [f"# The meeting\n\nDate: {meeting_date or 'not given'}"]
    if attendees:
        meeting.append(
            "People the person says were there (spellings and context, not evidence): "
            + ", ".join(attendees)
        )
    parts = ["\n\n".join(meeting), "# Client context\n\n" + context.to_prompt_context()]
    if memory_text:
        parts.append(memory_text)
    if preload:
        parts.append(
            "# The transcript (every turn; all citable now)\n\n"
            + transcript_text(transcript, times)
        )
    else:
        parts.append(
            f"# The transcript\n\n{transcript.page_count} turns{_duration(times)}. It is too "
            "long to show here. Read it with `read_transcript`, in order and in ranges, "
            "before you write anything; `search_transcript` finds turns about a topic."
        )
    return PROMPT_SEPARATOR.join(parts)


# -- the session ------------------------------------------------------------------


def make_notes_toolbox(
    ws: NotesWorkspace,
    *,
    times: Mapping[int, float],
    project: str | None,
    advisor: AdvisorModel | None = None,
    memory: MemoryStore | None = None,
) -> ToolBox:
    tools = [
        *skill_tools(project=project),
        *notes_tools(
            ws,
            times=times,
            index=transcript_index(ws, project=project or ""),
            require_cold_read=advisor is not None,
        ),
    ]
    if advisor is not None:
        tools.extend(notes_advisor_tools(ws, model=advisor, times=times, project=project))
    if memory is not None:
        memory.shown_texts = lambda: [ws.page_text(p) for p in sorted(ws.shown_pages)]
        tools.extend(memory_tools(memory))
    return ToolBox(tools, state_key=lambda: ws.revision)


def compose_notes_agent(
    *,
    transcript: Document,
    store: DocumentStore,
    times: Mapping[int, float],
    context: AssembledContext,
    model: Any,
    advisor: AdvisorModel | None = None,
    project: str,
    meeting_date: str | None = None,
    attendees: Sequence[str] = (),
    session_dir: Path | None = None,
    limits: SessionLimits | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
    memory: MemoryStore | None = None,
) -> NotesRun:
    """Run a fresh notes session over a transcript and return its workspace (B80).

    `model` is a converse-capable provider (`guard.provider("composer")`); `advisor`, when
    given, adds `ask_advisor` and makes a cold read of the whole notes a condition of
    `finish_notes`. With `session_dir` the session's files are written there; without it the
    session runs in memory (tests). The workspace is saved even when the session fails.
    """
    ws = NotesWorkspace(
        transcript=transcript,
        store=store,
        meeting_date=meeting_date,
        attendees_hint=list(attendees),
    )
    preload = len(transcript_text(transcript, times)) // 4 <= PRELOAD_TOKENS
    if preload:
        ws.show_pages(range(1, ws.page_count + 1))
    system = notes_system(project=project)
    snapshot = memory.snapshot() if memory is not None else None
    opening = notes_opening_message(
        transcript=transcript,
        times=times,
        context=context,
        memory_text=memory.context_text(snapshot) if memory is not None else "",
        meeting_date=meeting_date,
        attendees=attendees,
        preload=preload,
    )

    files = SessionFiles(session_dir) if session_dir is not None else None
    log = None
    if files is not None:
        files.root.mkdir(parents=True, exist_ok=True)
        migrate_notes_session(files.root)
        if files.transcript.exists():
            files.transcript.unlink()  # fresh notes are a fresh session; deck files stay
        files.system.write_text(system, encoding="utf-8")
        if snapshot is not None:
            files.memory.mkdir(exist_ok=True)
            for scope, text in snapshot.items():
                (files.memory / f"{scope}.md").write_text(text, encoding="utf-8")
        log = TranscriptLog(files.transcript)

    state = SessionState(messages=[], summaries={})
    first = Message(role="user", content=opening)
    state.messages.append(first)
    if log is not None:
        log.append(first, summary="opening message", step=0)
    toolbox = make_notes_toolbox(
        ws, times=times, project=project, advisor=advisor, memory=memory
    )
    try:
        state = run_session(
            model,
            system=system,
            state=state,
            toolbox=toolbox,
            limits=limits or SessionLimits(),
            log=log,
            on_step=on_step,
        )
    finally:
        if files is not None:
            ws.save(files.workspace)
    return NotesRun(workspace=ws, state=state)


# -- resume: revise-notes continues the same session --------------------------------


def revision_message(instruction: str) -> str:
    return (
        "# The person asks for a change\n\n"
        f"{instruction.strip()}\n\n"
        "Change only what this touches. Fix every item a correction affects, not just the "
        "first one you find. If it corrects a name or term, `remember` it. If it changes "
        "what was decided or who does what, ask the advisor to read the notes again "
        "(`ask_advisor` with whole_notes true). Then `finish_notes`, with a one-line note "
        "to the person on what changed."
    )


def _context_tokens(state: SessionState, limits: SessionLimits) -> int:
    messages = compact(state.messages, state.summaries, limits.keep_recent_results)
    return sum(len(m.content) for m in messages) // 4


def reseed_message(
    ws: NotesWorkspace, times: Mapping[int, float], memory_text: str = ""
) -> str:
    """A fresh start that carries the session's memory: the notes as they stand, and the
    engagement and owner memory as they are now (B77)."""
    parts = ["# You are continuing meeting notes you wrote earlier in another session."]
    if memory_text:
        parts.append(memory_text)
    parts.append("# The notes as they stand\n\n" + notes_text(ws, times))
    parts.append(
        "Every turn you cited before is still citable. Read it again with `read_transcript` "
        "before quoting it, since its words are not shown here."
    )
    return PROMPT_SEPARATOR.join(parts)


def resume_notes_agent(
    instruction: str,
    *,
    session_dir: Path,
    transcript: Document,
    store: DocumentStore,
    times: Mapping[int, float],
    model: Any,
    advisor: AdvisorModel | None = None,
    project: str | None = None,
    limits: SessionLimits | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
    memory: MemoryStore | None = None,
) -> NotesRun:
    """Continue a run's notes session with one instruction from the person.

    The session speaks under the system prompt it started with (`session/notes_system.md`), from
    the workspace it left (`session/notes_workspace.json`), with the same citable turns. A
    session over `RESEED_TOKENS` is archived and replaced by a fresh one seeded from the notes.

    Raises:
        ComposeError: there is no notes session to resume, or its notes no longer match the
            transcript.
    """
    migrate_notes_session(session_dir)
    files = SessionFiles(session_dir)
    for required in (files.system, files.workspace, files.transcript):
        if not required.exists():
            raise ComposeError(
                f"no notes session to resume: {required} is missing. Write the notes with "
                "`autodeck meeting notes` first."
            )
    limits = limits or SessionLimits()
    system = files.system.read_text(encoding="utf-8")
    try:
        ws = NotesWorkspace.load(files.workspace, transcript=transcript, store=store)
    except NotesError as exc:
        raise ComposeError(str(exc)) from exc
    state = TranscriptLog.load(files.transcript)
    if _context_tokens(state, limits) > RESEED_TOKENS:
        n = 1
        while (archived := files.root / f"notes_transcript.{n}.jsonl").exists():
            n += 1
        files.transcript.replace(archived)
        state = SessionState(messages=[], summaries={})
        log = TranscriptLog(files.transcript)
        memory_text = memory.context_text() if memory is not None else ""
        seed = Message(role="user", content=reseed_message(ws, times, memory_text))
        state.messages.append(seed)
        log.append(seed, summary=f"reseeded from the notes (old: {archived.name})", step=0)
    else:
        log = TranscriptLog(files.transcript)
    ask = Message(role="user", content=revision_message(instruction))
    state.messages.append(ask)
    said = " ".join(instruction.split())[:80]
    log.append(ask, summary=f"the person: {said}", step=state.steps)
    toolbox = make_notes_toolbox(
        ws, times=times, project=project, advisor=advisor, memory=memory
    )
    try:
        state = run_session(
            model,
            system=system,
            state=state,
            toolbox=toolbox,
            limits=limits,
            log=log,
            on_step=on_step,
        )
    finally:
        ws.save(files.workspace)
    return NotesRun(workspace=ws, state=state)


__all__ = [
    "ALWAYS_LOADED",
    "NOTES_PROMPT",
    "PRELOAD_TOKENS",
    "NotesRun",
    "SessionFiles",
    "compose_notes_agent",
    "migrate_notes_session",
    "notes_opening_message",
    "notes_system",
    "resume_notes_agent",
    "transcript_text",
]
