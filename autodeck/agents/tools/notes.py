"""The notes agent's tools: read the transcript, write the notes, have them read cold (B80).

Showing is the gate here as in the deck's corpus tools (B75): a turn becomes citable only when
`read_transcript` or `search_transcript` puts it in front of the agent (or the opening message
preloaded it). The notes themselves are edited through the workspace, which resolves every
quote and refuses what does not resolve; these tools only carry the call and show the result.

**Summaries carry no transcript text.** A tool result's one-line summary reaches the UI
timeline and the logs, and a meeting is client-confidential (B78): a summary names item ids,
turn numbers and counts, never words someone said.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.advisor import AdvisorModel, ask
from autodeck.agents.notes_workspace import (
    NOTES_SECTIONS,
    NoteItemDraft,
    NotesWorkspace,
    notes_text,
    notes_with_quotes,
)
from autodeck.agents.tools.registry import Tool, ToolError, ToolResult
from autodeck.audit.report import meeting_stamp
from autodeck.retrieval.hybrid import HybridIndex, build_index, search

MAX_TURNS_PER_READ = 40
MAX_ATTACHED_PAGES = 6
WHOLE_TRANSCRIPT_TOKENS = 20_000
"""A transcript estimated (`len // 4`) below this goes to the advisor whole."""


def turn_line(page: int, text: str, times: Mapping[int, float]) -> str:
    """`turn 3 [00:31]: text`, or `turn 3: text` when the sidecar has no time for it."""
    stamp = f" [{meeting_stamp(times[page])}]" if page in times else ""
    return f"turn {page}{stamp}: {text}"


def transcript_lines(
    ws: NotesWorkspace, times: Mapping[int, float], pages: list[int] | None = None
) -> str:
    wanted = pages if pages is not None else range(1, ws.page_count + 1)
    return "\n".join(turn_line(p, ws.page_text(p), times) for p in wanted)


def transcript_index(ws: NotesWorkspace, *, project: str) -> HybridIndex:
    """An index over the transcript alone: the notes agent never searches the papers."""
    return build_index([ws.transcript], project=project)


# -- arguments ------------------------------------------------------------------------


class ReadTranscriptArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_page: int = Field(ge=1, description="The first turn to read.")
    to_page: int = Field(ge=1, description=f"The last turn, at most {MAX_TURNS_PER_READ} on.")


class SearchTranscriptArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="What to look for, in the speakers' words.")
    limit: int = Field(default=8, ge=1, le=12, description="Turns to return, 1 to 12.")


class SetSectionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(description=f"One of: {', '.join(NOTES_SECTIONS)}.")
    items: list[NoteItemDraft] = Field(
        description="The section's whole contents. Replaces what is there; all or nothing."
    )


class AddItemArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(description=f"One of: {', '.join(NOTES_SECTIONS)}.")
    item: NoteItemDraft


class EditItemArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(description="The note to rewrite, e.g. 'n3'. It keeps its id.")
    item: NoteItemDraft = Field(description="The whole note as it should now read.")


class RemoveItemArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(description="The note to remove, e.g. 'n3'.")


class ShowNotesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinishNotesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_to_person: str = Field(
        description=(
            "What the person should check first: a spelling you could not confirm, an "
            "action with no owner, a date you could not pin down. Or '' for nothing."
        )
    )


class AskAdvisorArgs(BaseModel):
    """What the advisor sees: the question and only what is attached. Nothing else."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=1,
        description=(
            "One specific question, e.g. 'Read these notes against the transcript: which "
            "decision was only discussed, which owner never agreed, what is missing?'"
        ),
    )
    whole_notes: bool = Field(
        description=(
            "Attach the whole notes with the words each item cites, and the transcript. "
            "Needed once before finish_notes."
        )
    )
    pages: list[int] = Field(
        description=f"Transcript turns to attach, at most {MAX_ATTACHED_PAGES}; [] for none."
    )


# -- the tools ------------------------------------------------------------------------


def _section_text(ws: NotesWorkspace, section: str, times: Mapping[int, float]) -> str:
    """One section as `notes_text` renders it."""
    lines = notes_text(ws, times).splitlines()
    start = lines.index(f"## {section}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), None)
    return "\n".join(lines[start:end]).rstrip()


def _canonical(section: str) -> str:
    for name in NOTES_SECTIONS:
        if name.casefold() == section.strip().casefold():
            return name
    return section


def notes_tools(
    ws: NotesWorkspace,
    *,
    times: Mapping[int, float],
    index: HybridIndex,
    require_cold_read: bool,
) -> list[Tool]:
    def read_transcript(args: ReadTranscriptArgs) -> ToolResult:
        if args.to_page < args.from_page:
            raise ToolError("to_page is before from_page.")
        count = args.to_page - args.from_page + 1
        if count > MAX_TURNS_PER_READ:
            raise ToolError(
                f"read at most {MAX_TURNS_PER_READ} turns at a time; you asked for {count}. "
                f"Try turns {args.from_page} to {args.from_page + MAX_TURNS_PER_READ - 1}."
            )
        pages = list(range(args.from_page, args.to_page + 1))
        ws.show_pages(pages)
        return ToolResult(
            transcript_lines(ws, times, pages),
            f"read_transcript: turns {args.from_page}-{args.to_page}",
        )

    def search_transcript(args: SearchTranscriptArgs) -> ToolResult:
        hits = search(index, args.query, limit=args.limit, citable_only=True)
        pages: list[int] = []
        for span in hits:
            if span.doc_id == ws.doc_id and span.page not in pages:
                pages.append(span.page)
        if not pages:
            return ToolResult("No turn matches.", "search_transcript: 0 turns")
        ws.show_pages(pages)
        return ToolResult(
            transcript_lines(ws, times, pages), f"search_transcript: {len(pages)} turns"
        )

    def set_section(args: SetSectionArgs) -> ToolResult:
        ids = ws.set_section(args.section, args.items)
        name = _canonical(args.section)
        return ToolResult(
            f"{name} now has {len(ids)} note(s): {', '.join(ids) or 'none'}.\n\n"
            + _section_text(ws, name, times),
            f"notes_set_section {name}: {len(ids)} notes",
        )

    def add_item(args: AddItemArgs) -> ToolResult:
        item_id = ws.add_item(args.section, args.item)
        name = ws.find(item_id).section
        return ToolResult(
            f"Added {item_id} to {name}.\n\n" + _section_text(ws, name, times),
            f"notes_add_item {name}: {item_id}",
        )

    def edit_item(args: EditItemArgs) -> ToolResult:
        ws.edit_item(args.item_id, args.item)
        name = ws.find(args.item_id).section
        return ToolResult(
            f"Rewrote {args.item_id} in {name}.\n\n" + _section_text(ws, name, times),
            f"notes_edit_item {args.item_id}",
        )

    def remove_item(args: RemoveItemArgs) -> ToolResult:
        name = ws.find(args.item_id).section
        ws.remove_item(args.item_id)
        return ToolResult(
            f"Removed {args.item_id} from {name}.\n\n" + _section_text(ws, name, times),
            f"notes_remove_item {args.item_id}",
        )

    def show_notes(_: ShowNotesArgs) -> ToolResult:
        return ToolResult(notes_with_quotes(ws), "show_notes")

    def finish_notes(args: FinishNotesArgs) -> ToolResult:
        problems = ws.finish_problems(require_cold_read=require_cold_read)
        if problems:
            raise ToolError("the notes cannot be finished yet: " + "; ".join(problems) + ".")
        ws.note_to_person = args.note_to_person.strip()
        return ToolResult("Notes finished.", "finish_notes", finished=True)

    return [
        Tool(
            "read_transcript",
            f"Read turns of the transcript, in order, at most {MAX_TURNS_PER_READ} at a time. "
            "Turns you read are citable.",
            ReadTranscriptArgs,
            read_transcript,
        ),
        Tool(
            "search_transcript",
            "Search the transcript (only the transcript) for the turns about something. "
            "Turns found are citable.",
            SearchTranscriptArgs,
            search_transcript,
        ),
        Tool(
            "notes_set_section",
            "Replace a whole section of the notes. Every item cites verbatim quotes from "
            "turns you have read; if one item is refused nothing is written.",
            SetSectionArgs,
            set_section,
        ),
        Tool(
            "notes_add_item",
            "Add one note to a section.",
            AddItemArgs,
            add_item,
        ),
        Tool(
            "notes_edit_item",
            "Rewrite one note in place (same id, same place).",
            EditItemArgs,
            edit_item,
        ),
        Tool("notes_remove_item", "Remove one note.", RemoveItemArgs, remove_item),
        Tool(
            "show_notes",
            "The notes as they stand, each item with the words it cites.",
            ShowNotesArgs,
            show_notes,
        ),
        Tool(
            "finish_notes",
            "Finish. Refused while the notes have problems (empty Summary, nothing else "
            "noted, no cold read by the advisor).",
            FinishNotesArgs,
            finish_notes,
        ),
    ]


def notes_advisor_tools(
    ws: NotesWorkspace,
    *,
    model: AdvisorModel,
    times: Mapping[int, float],
    project: str | None = None,
) -> list[Tool]:
    def run(args: AskAdvisorArgs) -> ToolResult:
        if len(args.pages) > MAX_ATTACHED_PAGES:
            raise ToolError(f"attach at most {MAX_ATTACHED_PAGES} turns")
        bad = [p for p in args.pages if not 1 <= p <= ws.page_count]
        if bad:
            raise ToolError(
                f"the transcript has turns 1 to {ws.page_count}; there is no turn "
                + ", ".join(str(p) for p in bad)
                + "."
            )
        attachments: list[tuple[str, str]] = []
        if args.whole_notes:
            attachments.append(
                ("The notes, with the words each item cites", notes_with_quotes(ws))
            )
            everything = transcript_lines(ws, times)
            if len(everything) // 4 < WHOLE_TRANSCRIPT_TOKENS:
                attachments.append(("The transcript, every turn", everything))
            else:
                cited = {p for items in ws.sections.values() for i in items for p in i.pages}
                chosen = sorted(cited | set(args.pages))
                attachments.append(
                    (
                        "The transcript, only the turns the notes cite and the ones asked for",
                        transcript_lines(ws, times, chosen),
                    )
                )
        elif args.pages:
            attachments.append(
                ("Transcript turns", transcript_lines(ws, times, sorted(set(args.pages))))
            )
        advice = ask(model, args.question, attachments)
        if args.whole_notes:
            ws.record_cold_read()
        what = ", ".join(t for t, _ in attachments) or "no attachments"
        label = "whole notes" if args.whole_notes else f"{len(args.pages)} turns"
        return ToolResult(
            text=f"Advisor (who saw only: {what}):\n\n{advice}",
            summary=f"ask_advisor: {label}",
        )

    return [
        Tool(
            name="ask_advisor",
            description=(
                "Ask a second reader one question. It sees ONLY what you attach, reads it "
                "cold, and answers in plain text. Use it with whole_notes=true to have the "
                "notes read against the transcript (required before finish_notes), or to "
                "check what a few turns really say. It cannot edit and its words are not "
                "evidence."
            ),
            args_model=AskAdvisorArgs,
            run=run,
        )
    ]
