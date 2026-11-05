"""Meeting notes under construction (plan step 10, B80): what the notes agent edits.

The notes agent reads a meeting transcript (`transcript--`, B79) and writes the notes one
tool call at a time, the way the deck agent writes slides (B71). This module is the notes'
equivalent of `DeckWorkspace`: it holds the notes, decides nothing about their content, and
refuses only what the invariants refuse.

**Every item is cited (A1).** An item carries one or more citations into the transcript,
each a verbatim quote inside one turn (page). A point made across several turns carries one
citation per turn; a quote never runs across two, because that would be a splice. Citations
resolve through `content._resolve_citation`, the one resolver the deck uses, against the
pages this session has shown (B75), so a quote from a turn the agent never read fails with
`doc_not_shown` exactly as it would on a slide.

**The words of an item may differ from the words of its quote.** The transcript mishears:
"Shikta" for Shikha, "data bricks" for Databricks. Engagement memory's Terms (B77) give the
right spelling, and the item uses it; the quote stays what the transcript says. The
validator is shown the same Terms (B79).

**Sections are fixed, their contents are not.** Seven sections, in a fixed order, because the
person reading notes looks for decisions and actions in the same place every time. What goes
in them, how many items, and the Summary's wording are the agent's judgement, guided by the
`meeting-notes` skill. Two sections carry structured fields: an action item has an owner
(absent means "Owner TBD", never a guess) and an optional due date; a key date has the date
as said and its precision ("the sixteenth" is a day, "first week of February" a week).

**Nothing here carries a time.** Times come from the run's `meeting/segments.json` sidecar
at render time (B79, A6); `notes.json` holds pages and quotes only.

`render_notes` writes `notes.md` (for people: times, "Owner TBD", one bullet per item tagged
with its id so an edited file can be mapped back) and `notes.json` (for code: every
citation with its hash). Both are deterministic in the workspace and the time map.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.content import (
    CitationResolutionError,
    ProposedCitation,
    _resolve_citation,
    loose_snapping,
)
from autodeck.agents.evidence_pack import document_spans
from autodeck.agents.workspace import WorkspaceError
from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.ir.models import Citation
from autodeck.retrieval.hybrid import RetrievedSpan

NOTES_VERSION = 1

NOTES_SECTIONS: tuple[str, ...] = (
    "Summary",
    "Attendees",
    "Themes",
    "Decisions",
    "Key dates",
    "Action items",
    "Open questions and risks",
)

ACTION_SECTION = "Action items"
DATES_SECTION = "Key dates"
OWNER_TBD = "Owner TBD"

DatePrecision = Literal["day", "week", "month", "quarter", "year", "relative", "unclear"]
"""How precisely a date was said. `relative`: "next Tuesday", "in two weeks" — kept as said,
never resolved against a calendar the meeting did not name. `unclear`: a date is meant but
the words do not fix it."""


class NotesError(WorkspaceError):
    """An edit the notes cannot take. The message goes back to the agent as a tool error."""


# -- what the agent proposes ----------------------------------------------------------


class CiteDraft(BaseModel):
    """One citation as the agent writes it: which turn, and the words copied from it."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="The turn (page) the quote is in.")
    quote: str = Field(
        min_length=1,
        description=(
            "Copied VERBATIM from that turn, mishearings and missing punctuation included. "
            "The shortest run that proves the item. Never joins two turns."
        ),
    )


class NoteItemDraft(BaseModel):
    """One note as the agent writes it."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=1,
        description=(
            "The note, in plain words, with names and terms spelled as the engagement "
            "spells them. Keeps the speaker's hedge: a plan is a plan, a guess a guess."
        ),
    )
    cites: list[CiteDraft] = Field(
        min_length=1, description="One citation per turn the note rests on."
    )
    owner: str | None = Field(
        default=None,
        description=(
            "Action items only: who took it on, only if the transcript says so. "
            "Leave null rather than guess; it shows as 'Owner TBD'."
        ),
    )
    due: str | None = Field(
        default=None, description="Action items only: when it is due, as said. Else null."
    )
    date: str | None = Field(
        default=None,
        description="Key dates only (required there): the date as said, e.g. 'the sixteenth'.",
    )
    precision: DatePrecision | None = Field(
        default=None, description="Key dates only (required there): how precise the date is."
    )


# -- what the workspace holds -----------------------------------------------------------


@dataclass(frozen=True)
class NoteItem:
    """A note whose every citation resolved."""

    id: str
    section: str
    text: str
    citations: tuple[Citation, ...]
    owner: str | None = None
    due: str | None = None
    date: str | None = None
    precision: DatePrecision | None = None

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(sorted({c.page for c in self.citations}))

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "cites": [
                {
                    "page": c.page,
                    "quote": c.quote,
                    "quote_sha256": c.quote_sha256,
                }
                for c in self.citations
            ],
        }
        if self.section == ACTION_SECTION:
            data["owner"] = self.owner
            data["due"] = self.due
        if self.section == DATES_SECTION:
            data["date"] = self.date
            data["precision"] = self.precision
        return data


def _section(name: str) -> str:
    """The canonical section name, matched without regard to case."""
    for section in NOTES_SECTIONS:
        if section.casefold() == name.strip().casefold():
            return section
    raise NotesError(
        f"there is no section {name!r}. The sections are: {', '.join(NOTES_SECTIONS)}."
    )


def _check_fields(section: str, draft: NoteItemDraft) -> None:
    """Structured fields belong to their section; a key date must say its date and precision."""
    problems: list[str] = []
    if section != ACTION_SECTION and (draft.owner is not None or draft.due is not None):
        problems.append(f"owner and due belong to {ACTION_SECTION} only")
    if section != DATES_SECTION and (draft.date is not None or draft.precision is not None):
        problems.append(f"date and precision belong to {DATES_SECTION} only")
    if section == DATES_SECTION and (not draft.date or draft.precision is None):
        problems.append(f"a {DATES_SECTION} item needs date (as said) and precision")
    if draft.owner is not None and not draft.owner.strip():
        problems.append("owner is empty; use null for 'Owner TBD'")
    if problems:
        raise NotesError("; ".join(problems) + ".")


@dataclass
class NotesWorkspace:
    """The notes as the agent has written them so far, and the turns it may cite."""

    transcript: Document
    store: DocumentStore
    sections: dict[str, list[NoteItem]] = field(
        default_factory=lambda: {name: [] for name in NOTES_SECTIONS}
    )
    shown_pages: set[int] = field(default_factory=set)
    """The turns put in front of the agent (B75): the preload, or what it read or found."""
    meeting_date: str | None = None
    """The date the person gave (`--date`), as given. Never inferred."""
    attendees_hint: list[str] = field(default_factory=list)
    """Names the person gave (`--attendees`): spellings and context, not evidence."""
    cold_read_revision: int | None = None
    """The revision the advisor last read the whole notes at (B80). `finish` needs one."""
    note_to_person: str = ""
    """Set by `finish`: what the agent tells the person about these notes."""
    revision: int = 0
    next_id: int = 1

    # -- the citable set --------------------------------------------------------------

    @property
    def doc_id(self) -> str:
        return self.transcript.doc_id

    @property
    def page_count(self) -> int:
        return self.transcript.page_count

    def show_pages(self, pages: Iterable[int]) -> list[int]:
        """Add turns to the citable set; returns the ones that were new. Unknown pages are
        refused, so a typo is an error rather than a silent no-op."""
        wanted = sorted(set(pages))
        bad = [p for p in wanted if not 1 <= p <= self.page_count]
        if bad:
            raise NotesError(
                f"the transcript has turns 1 to {self.page_count}; there is no turn "
                + ", ".join(str(p) for p in bad)
                + "."
            )
        new = [p for p in wanted if p not in self.shown_pages]
        if new:
            self.shown_pages.update(new)
            self.revision += 1
        return new

    def page_text(self, page: int) -> str:
        return " ".join(e.text for e in self.transcript.elements if e.page == page)

    def shown_spans(self) -> list[RetrievedSpan]:
        return [s for s in document_spans(self.transcript) if s.page in self.shown_pages]

    # -- resolution -------------------------------------------------------------------

    def _resolve(self, cite: CiteDraft) -> Citation:
        """One citation through the deck's resolver. The page is a hint that disambiguates a
        short quote; the quote is the key."""
        if cite.page not in self.shown_pages:
            raise NotesError(
                f"turn {cite.page} has not been shown in this session. Read it with "
                "read_transcript (or find it with search_transcript) before quoting it."
            )
        spans = self.shown_spans()
        on_page = [s for s in spans if s.page == cite.page]
        proposed = ProposedCitation(doc_id=self.doc_id, quote=cite.quote)
        # B86: notes are written the normal-mode way; a quote that points at the turn
        # resolves to the turn's exact words without being copied character for character.
        with loose_snapping():
            try:
                return _resolve_citation(proposed, store=self.store, claims=(), spans=on_page)
            except CitationResolutionError:
                pass
            try:
                found = _resolve_citation(proposed, store=self.store, claims=(), spans=spans)
            except CitationResolutionError as exc:
                raise NotesError(
                    f"the quote cited from turn {cite.page} does not match that turn (or any "
                    f"turn shown): {exc}. Use the words the transcript has, within one turn; "
                    "close is enough, code finds the exact words."
                ) from None
        raise NotesError(
            f"that quote is in turn {found.page}, not turn {cite.page}. Cite it with page "
            f"{found.page}."
        )

    def _build(self, section: str, draft: NoteItemDraft, item_id: str) -> NoteItem:
        _check_fields(section, draft)
        citations = tuple(self._resolve(c) for c in draft.cites)
        return NoteItem(
            id=item_id,
            section=section,
            text=" ".join(draft.text.split()),
            citations=citations,
            owner=draft.owner.strip() if draft.owner else None,
            due=draft.due.strip() if draft.due else None,
            date=draft.date.strip() if draft.date else None,
            precision=draft.precision,
        )

    def _new_id(self) -> str:
        item_id = f"n{self.next_id}"
        self.next_id += 1
        return item_id

    # -- edits ------------------------------------------------------------------------

    def find(self, item_id: str) -> NoteItem:
        for items in self.sections.values():
            for item in items:
                if item.id == item_id:
                    return item
        raise NotesError(
            f"there is no note {item_id!r}. Current ids: {', '.join(self.ids()) or 'none'}."
        )

    def ids(self) -> list[str]:
        return [item.id for name in NOTES_SECTIONS for item in self.sections[name]]

    def set_section(self, section: str, drafts: Sequence[NoteItemDraft]) -> list[str]:
        """Replace a whole section. All items resolve or none are written."""
        section = _section(section)
        built = [self._build(section, d, f"pending-{i}") for i, d in enumerate(drafts)]
        items = [
            NoteItem(**{**item.__dict__, "id": self._new_id()})  # type: ignore[arg-type]
            for item in built
        ]
        self.sections[section] = items
        self.revision += 1
        return [item.id for item in items]

    def add_item(self, section: str, draft: NoteItemDraft) -> str:
        section = _section(section)
        item = self._build(section, draft, "pending")
        item = NoteItem(**{**item.__dict__, "id": self._new_id()})  # type: ignore[arg-type]
        self.sections[section].append(item)
        self.revision += 1
        return item.id

    def edit_item(self, item_id: str, draft: NoteItemDraft) -> None:
        """Rewrite one item in place: same id, same section, same position."""
        old = self.find(item_id)
        new = self._build(old.section, draft, old.id)
        items = self.sections[old.section]
        items[items.index(old)] = new
        self.revision += 1

    def remove_item(self, item_id: str) -> None:
        old = self.find(item_id)
        self.sections[old.section].remove(old)
        self.revision += 1

    # -- finishing --------------------------------------------------------------------

    def record_cold_read(self) -> None:
        self.cold_read_revision = self.revision

    def finish_problems(self, *, require_cold_read: bool) -> list[str]:
        """Why `finish` must wait, if it must. Empty means the notes may be finished."""
        problems: list[str] = []
        if not self.sections["Summary"]:
            problems.append("the Summary is empty")
        if not any(self.sections[name] for name in NOTES_SECTIONS if name != "Summary"):
            problems.append("every section but the Summary is empty")
        if require_cold_read and self.cold_read_revision is None:
            problems.append(
                "the advisor has not read the whole notes against the transcript yet "
                "(ask_advisor with whole_notes=true)"
            )
        return problems

    # -- persistence ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "version": NOTES_VERSION,
            "doc_id": self.doc_id,
            "meeting_date": self.meeting_date,
            "attendees_hint": list(self.attendees_hint),
            "sections": {
                name: [item.to_json() for item in self.sections[name]]
                for name in NOTES_SECTIONS
            },
        }

    def state_json(self) -> dict[str, Any]:
        """Everything a resumed session needs: the notes plus the session's own state."""
        return {
            **self.to_json(),
            "shown_pages": sorted(self.shown_pages),
            "cold_read_revision": self.cold_read_revision,
            "note_to_person": self.note_to_person,
            "revision": self.revision,
            "next_id": self.next_id,
        }

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.state_json(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        return path

    @classmethod
    def load(cls, path: Path, *, transcript: Document, store: DocumentStore) -> NotesWorkspace:
        """Rebuild a saved workspace. Every citation is resolved again against the store, so a
        transcript that changed under the notes is an error, not a silent mismatch."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != NOTES_VERSION:
            raise NotesError(f"{path}: unknown notes version {data.get('version')!r}")
        if data.get("doc_id") != transcript.doc_id:
            raise NotesError(
                f"{path} is notes on {data.get('doc_id')!r}, not on {transcript.doc_id!r}"
            )
        ws = cls(
            transcript=transcript,
            store=store,
            meeting_date=data.get("meeting_date"),
            attendees_hint=list(data.get("attendees_hint") or []),
        )
        ws.shown_pages = set(int(p) for p in data.get("shown_pages", []))
        for name in NOTES_SECTIONS:
            for raw in data["sections"].get(name, []):
                draft = NoteItemDraft(
                    text=raw["text"],
                    cites=[CiteDraft(page=c["page"], quote=c["quote"]) for c in raw["cites"]],
                    owner=raw.get("owner"),
                    due=raw.get("due"),
                    date=raw.get("date"),
                    precision=raw.get("precision"),
                )
                item = ws._build(name, draft, raw["id"])
                if any(
                    c.quote_sha256 != r["quote_sha256"]
                    for c, r in zip(item.citations, raw["cites"], strict=True)
                ):
                    raise NotesError(f"{path}: a citation of {raw['id']} no longer matches")
                ws.sections[name].append(item)
        ws.cold_read_revision = data.get("cold_read_revision")
        ws.note_to_person = data.get("note_to_person", "")
        ws.revision = int(data.get("revision", 0))
        ws.next_id = int(data.get("next_id", 1))
        return ws


# -- rendering ------------------------------------------------------------------------


def _stamp(seconds: float) -> str:
    from autodeck.audit.report import meeting_stamp

    return meeting_stamp(seconds)


def _where(item: NoteItem, times: Mapping[int, float]) -> str:
    """`[00:12, 01:03]` from the sidecar; `[turn 3]` for a page with no time."""
    parts = [_stamp(times[page]) if page in times else f"turn {page}" for page in item.pages]
    return "[" + ", ".join(parts) + "]"


def notes_text(ws: NotesWorkspace, times: Mapping[int, float] | None = None) -> str:
    """The notes as people read them, and as the advisor and a reseeded session see them.

    One bullet per item, tagged `<!-- n3 -->` so an edited copy can be mapped back to its
    items. With `times`, each bullet ends with where in the recording it was said.
    """
    times = times or {}
    lines = ["# Meeting notes", ""]
    lines.append(f"Date: {ws.meeting_date}" if ws.meeting_date else "Date: not given")
    lines.append("")
    for name in NOTES_SECTIONS:
        lines.extend([f"## {name}", ""])
        items = ws.sections[name]
        if not items:
            lines.extend(["_None noted._", ""])
            continue
        for item in items:
            if name == ACTION_SECTION:
                owner = item.owner or OWNER_TBD
                due = f" (due: {item.due})" if item.due else ""
                body = f"**{owner}**: {item.text}{due}"
            elif name == DATES_SECTION:
                body = f"**{item.date}** ({item.precision}): {item.text}"
            else:
                body = item.text
            lines.append(f"- {body} {_where(item, times)} <!-- {item.id} -->")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def notes_with_quotes(ws: NotesWorkspace) -> str:
    """Every item with the exact words it cites, for the advisor's cold read."""
    lines: list[str] = []
    for name in NOTES_SECTIONS:
        lines.append(f"## {name}")
        for item in ws.sections[name]:
            extra = ""
            if name == ACTION_SECTION:
                extra = f" [owner: {item.owner or OWNER_TBD}; due: {item.due or 'not said'}]"
            elif name == DATES_SECTION:
                extra = f" [date: {item.date}; precision: {item.precision}]"
            lines.append(f"- {item.id}: {item.text}{extra}")
            lines.extend(f"    cites turn {c.page}: {c.quote!r}" for c in item.citations)
        if not ws.sections[name]:
            lines.append("  (empty)")
    return "\n".join(lines)


@dataclass(frozen=True)
class RenderedNotes:
    markdown: str
    data: dict[str, Any]


def render_notes(ws: NotesWorkspace, times: Mapping[int, float] | None = None) -> RenderedNotes:
    """`notes.md` (with times) and `notes.json` (pages and quotes only). Deterministic."""
    return RenderedNotes(markdown=notes_text(ws, times), data=ws.to_json())


def write_notes(
    ws: NotesWorkspace, meeting_dir: Path, times: Mapping[int, float] | None = None
) -> tuple[Path, Path]:
    """Write `meeting/notes.md`, `meeting/notes.json`, and `meeting/notes.rendered.md` — the
    copy as written, which "apply my edits" diffs the person's edited `notes.md` against."""
    rendered = render_notes(ws, times)
    meeting_dir = Path(meeting_dir)
    meeting_dir.mkdir(parents=True, exist_ok=True)
    md = meeting_dir / "notes.md"
    js = meeting_dir / "notes.json"
    md.write_text(rendered.markdown, encoding="utf-8")
    (meeting_dir / "notes.rendered.md").write_text(rendered.markdown, encoding="utf-8")
    js.write_text(
        json.dumps(rendered.data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return md, js


__all__ = [
    "ACTION_SECTION",
    "DATES_SECTION",
    "NOTES_SECTIONS",
    "OWNER_TBD",
    "CiteDraft",
    "DatePrecision",
    "NoteItem",
    "NoteItemDraft",
    "NotesError",
    "NotesWorkspace",
    "RenderedNotes",
    "notes_text",
    "notes_with_quotes",
    "render_notes",
    "write_notes",
]
