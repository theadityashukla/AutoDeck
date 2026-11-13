"""The conversation's contracts: threads, their log lines, proposals, turn events, renders
(v3 plan §4, §5; Phase 1 task list in docs/phases/V3-PHASE-1.md).

Four rules shape these models:

* **A thread's log is for display and for that thread only (P2, plan §5.1).** Every line a
  thread writes (`ThreadLine`) goes to its own `messages.jsonl`. The same thread rebuilds
  its model conversation from it; no other thread, and no context builder, ever reads it.
  What a later thread knows comes from the artifacts, their change logs, proposals and
  memory, all of which are state.
* **A turn is classified by what its tools did, never by what the model said.** A turn
  that recorded a change-log entry, undid or redid one, or created an artifact is a
  `change`; otherwise one that created a proposal is a `proposal`; otherwise it is `talk`
  (`classify_turn`). `TurnEndLine` and `TurnFinished` validate that their `turn_kind`
  agrees, so a mislabelled turn cannot be written.
* **Proposals are state, not chat.** A `ProposalRecord` is the smallest record that lets a
  later thread know what was offered and what the owner did with it: the summary, the
  options (text, and optionally candidate slides), and a status with who resolved it.
* **Events are what the interface streams (event granularity, not tokens).** The provider
  layer returns whole turns, so a turn streams as a sequence of `TurnEvent`s: started, the
  model's text, each tool call and its one-line result, changes, proposals, finished, and
  later the previews.

Everything is `extra="forbid"` (via `StudioModel`), for the reason `models.py` gives.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from autodeck.studio.models import (
    DIGEST_PATTERN,
    ENTRY_ID_PATTERN,
    OPTION_IDS,
    PROPOSAL_ID_PATTERN,
    RENDER_DIGEST_PATTERN,
    SCHEMA_VERSION,
    SEGMENT_PATTERN,
    THREAD_ID_PATTERN,
    TURN_ID_PATTERN,
    Layer,
    OptionId,
    Slide,
    StudioModel,
)

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

TurnKind = Literal["talk", "proposal", "change"]
"""Plan §5.2. `talk`: nothing changed. `proposal`: options offered, nothing changed.
`change`: an artifact was edited (the turn lists the entries)."""

StopReason = Literal["replied", "step_cap", "token_cap", "stalled", "error"]
"""Why a turn ended. `replied`: the model answered in text with no tool call (the normal
end of a turn, not a stall). `step_cap` / `token_cap`: a limit stopped it. `stalled`: the
model returned neither text nor a tool call twice in a row. `error`: an exception (a
provider failure, or a bug in a tool) ended it; `error` carries the message."""

UserOrigin = Literal["owner", "choice", "context", "recap"]
"""Where a user-role line came from. `owner`: typed by the owner. `choice`: generated when
the owner picked a proposal option with the button (`prompt.choice_text`). `context`: the
opening context built from state, written as the first line of a thread's first turn.
`recap`: the fixed request for a recap (`prompt.RECAP_REQUEST`) that opens a returning
thread. `context` and `recap` lines are hidden in the interface."""

NoteKind = Literal["proposal_dismissed", "owner_undo", "owner_redo"]
"""Something the owner did outside the conversation, between turns, that the model in this
thread should be told about at its next turn (as a bracketed note merged into the next
user message, see `loop.build_model_messages`)."""

ProposalStatus = Literal["open", "accepted", "dismissed"]

ResolvedBy = Literal["owner", "chat"]
"""`owner`: resolved with the interface's buttons (pick or dismiss). `chat`: the model
applied an option after the owner chose it in words (`apply_option` on an open proposal)."""

MAX_SUMMARY_CHARS = 200
"""A tool result summary, a note, a proposal summary: one line, at most this long."""

MAX_LABEL_CHARS = 80
"""A proposal option label: one line, at most this long."""


def _one_line(value: str, *, what: str, limit: int) -> None:
    if not value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{what} must be one non-blank line")
    if len(value) > limit:
        raise ValueError(f"{what} is {len(value)} characters; at most {limit}")


def classify_turn(
    *,
    change_ids: list[str],
    undone_ids: list[str],
    redone_ids: list[str],
    created_artifacts: list[str],
    proposal_ids: list[str],
) -> TurnKind:
    """The kind of a turn from what its tools did (plan §5.2).

    `change` when any change-log entry was recorded, undone or redone, or an artifact was
    created; else `proposal` when any proposal was created; else `talk`. A turn that both
    changed the deck and proposed something is a `change` (its `proposal_ids` still list
    the proposals). Pure.
    """
    if change_ids or undone_ids or redone_ids or created_artifacts:
        return "change"
    if proposal_ids:
        return "proposal"
    return "talk"


class _TurnTotals(StudioModel):
    """Fields shared by `TurnEndLine` and `TurnFinished`: the turn's outcome."""

    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    turn_kind: TurnKind
    stop_reason: StopReason
    model_id: str = Field(min_length=1)
    steps: int = Field(ge=0, description="Model calls made in this turn.")
    change_ids: list[str] = Field(
        default_factory=list, description="Entries recorded, in order (`c0001`...)."
    )
    undone_ids: list[str] = Field(default_factory=list, description="Entries undone.")
    redone_ids: list[str] = Field(default_factory=list, description="Entries redone.")
    created_artifacts: list[str] = Field(default_factory=list)
    proposal_ids: list[str] = Field(default_factory=list)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    error: str = Field(default="", description="Non-empty exactly when stop_reason is error.")

    @model_validator(mode="after")
    def _kind_matches_what_happened(self) -> _TurnTotals:
        expected = classify_turn(
            change_ids=self.change_ids,
            undone_ids=self.undone_ids,
            redone_ids=self.redone_ids,
            created_artifacts=self.created_artifacts,
            proposal_ids=self.proposal_ids,
        )
        if self.turn_kind != expected:
            raise ValueError(
                f"turn {self.turn_id}: kind {self.turn_kind!r}, but it was {expected!r}"
            )
        if (self.stop_reason == "error") != bool(self.error.strip()):
            raise ValueError(f"turn {self.turn_id}: error text is set exactly when it errored")
        for entry_id in [*self.change_ids, *self.undone_ids, *self.redone_ids]:
            if not _matches(ENTRY_ID_PATTERN, entry_id):
                raise ValueError(f"turn {self.turn_id}: {entry_id!r} is not an entry id")
        for proposal_id in self.proposal_ids:
            if not _matches(PROPOSAL_ID_PATTERN, proposal_id):
                raise ValueError(f"turn {self.turn_id}: {proposal_id!r} is not a proposal id")
        for artifact_id in self.created_artifacts:
            if not _matches(SEGMENT_PATTERN, artifact_id):
                raise ValueError(f"turn {self.turn_id}: {artifact_id!r} is not an artifact id")
        return self


def _matches(pattern: str, value: str) -> bool:
    return re.fullmatch(pattern, value) is not None


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


class ThreadRecord(StudioModel):
    """`<engagement>/threads/<thread-id>/thread.json` (plan §4 "Thread", P2).

    Written once, when the thread is created, and never rewritten. `opening` says whether
    the engagement had state to recap when the thread began (`context.is_returning`);
    `context_digest` is the SHA-256 of `context.md`, the exact opening context the thread
    was given, so a test or the owner can check what the model was told.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    id: str = Field(pattern=THREAD_ID_PATTERN)
    client: str = Field(pattern=SEGMENT_PATTERN)
    project: str = Field(pattern=SEGMENT_PATTERN)
    title: str = Field(default="", description="A human label; '' shows the thread id.")
    created_at: AwareDatetime
    opening: Literal["fresh", "returning"]
    context_digest: str = Field(pattern=DIGEST_PATTERN)
    model_id: str = Field(min_length=1, description="The lead binding when it was created.")


class ToolCallRecord(StudioModel):
    """One tool call as the model requested it (v2's `ToolCall`, as data)."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class _Line(StudioModel):
    """Fields every log line has. `seq` is the line's 1-based position in the file, assigned
    by `ThreadStore.append`; a file whose seqs are not 1..n is corrupt (`ThreadLogError`)."""

    seq: int = Field(ge=1)
    created_at: AwareDatetime


class UserLine(_Line):
    """A user-role message: what the owner typed, a pick, the opening context, or the recap
    request (`UserOrigin`). Starts a turn (several user lines may share one turn id: the
    first turn of a thread writes the context line and then the owner's or recap line)."""

    kind: Literal["user"] = "user"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    origin: UserOrigin
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _text_not_blank(self) -> UserLine:
        if not self.text.strip():
            raise ValueError("a user line has non-blank text")
        return self


class AssistantLine(_Line):
    """One model call's reply: its text (possibly empty) and the tool calls it requested."""

    kind: Literal["assistant"] = "assistant"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    step: int = Field(ge=1, description="1-based model call within the turn.")
    text: str = ""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    model_id: str = Field(min_length=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ToolLine(_Line):
    """The result of one tool call: the text the model saw, and a one-line summary that is
    shown in the interface and replaces the text when the result is compacted."""

    kind: Literal["tool"] = "tool"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    step: int = Field(ge=1)
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    text: str
    summary: str
    error: bool = False

    @model_validator(mode="after")
    def _summary_is_one_line(self) -> ToolLine:
        _one_line(self.summary, what="a tool summary", limit=MAX_SUMMARY_CHARS)
        return self


class NoteLine(_Line):
    """Something the owner did between turns (`NoteKind`). Not part of any turn. `ref` is
    the proposal id or change-entry id it concerns; `text` is the one line the model is
    told, e.g. "The owner dismissed proposal p0002: Two ways to open the deck."."""

    kind: Literal["note"] = "note"
    note: NoteKind
    ref: str = Field(min_length=1)
    artifact_id: str | None = Field(default=None, pattern=SEGMENT_PATTERN)
    text: str

    @model_validator(mode="after")
    def _ref_matches_note(self) -> NoteLine:
        _one_line(self.text, what="a note", limit=MAX_SUMMARY_CHARS)
        pattern = PROPOSAL_ID_PATTERN if self.note == "proposal_dismissed" else ENTRY_ID_PATTERN
        if not _matches(pattern, self.ref):
            raise ValueError(f"note {self.note}: ref {self.ref!r} is not the right kind of id")
        if self.note != "proposal_dismissed" and self.artifact_id is None:
            raise ValueError(f"note {self.note} names the artifact it changed")
        return self


class TurnEndLine(_Line, _TurnTotals):
    """The last line of every turn, including one that errored: its kind and totals."""

    kind: Literal["turn_end"] = "turn_end"


ThreadLine = Annotated[
    UserLine | AssistantLine | ToolLine | NoteLine | TurnEndLine, Field(discriminator="kind")
]
"""One line of `messages.jsonl`, discriminated by `kind`."""

THREAD_LINE: TypeAdapter[ThreadLine] = TypeAdapter(ThreadLine)
"""Validate one line: `THREAD_LINE.validate_json(text)` or `.validate_python(data)`."""


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------


class ProposalOption(StudioModel):
    """One option of a proposal: a label, a description, and optionally candidate slides.

    Candidate slides are complete base `Slide`s, rendered for preview and never committed
    until the option is applied (`apply_option`). Applying replaces the deck's slide with
    the same id, or inserts a slide whose id is new: all new slides go, in the option's
    order, before 1-based position `insert_at` (None: at the end).
    """

    id: OptionId
    label: str
    text: str = Field(min_length=1)
    slides: list[Slide] = Field(default_factory=list)
    insert_at: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _label_and_slides(self) -> ProposalOption:
        _one_line(self.label, what="an option label", limit=MAX_LABEL_CHARS)
        ids = [s.id for s in self.slides]
        if len(set(ids)) != len(ids):
            raise ValueError(f"option {self.id}: candidate slide ids repeat")
        if self.insert_at is not None and not self.slides:
            raise ValueError(f"option {self.id}: insert_at without candidate slides")
        return self


class ProposalRecord(StudioModel):
    """`<engagement>/proposals/<proposal-id>/proposal.json` (plan §5.2 "Propose", P6).

    The smallest record that lets a later thread know what was rejected: what was being
    decided (`summary`), what was offered (`options`), and what became of it (`status`,
    `chosen`, `resolved_by`, `resolved_at`). Rewritten atomically when resolved; never
    deleted.

    Invariants: option ids are `A`, `B`, ... in order; an `open` proposal has no
    resolution fields; an `accepted` one names a `chosen` option it has, and how and when;
    a `dismissed` one has no `chosen` and says how and when. A proposal with candidate
    slides names its `artifact_id`.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    id: str = Field(pattern=PROPOSAL_ID_PATTERN)
    thread_id: str = Field(pattern=THREAD_ID_PATTERN)
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    artifact_id: str | None = Field(default=None, pattern=SEGMENT_PATTERN)
    summary: str
    options: list[ProposalOption] = Field(min_length=1, max_length=len(OPTION_IDS))
    status: ProposalStatus = "open"
    chosen: OptionId | None = None
    resolved_by: ResolvedBy | None = None
    resolved_at: AwareDatetime | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> ProposalRecord:
        _one_line(self.summary, what="a proposal summary", limit=MAX_SUMMARY_CHARS)
        expected = list(OPTION_IDS[: len(self.options)])
        if [o.id for o in self.options] != expected:
            raise ValueError(f"proposal {self.id}: option ids must be {expected} in order")
        if any(o.slides for o in self.options) and self.artifact_id is None:
            raise ValueError(f"proposal {self.id}: candidate slides need an artifact_id")
        resolved = (self.resolved_by is not None, self.resolved_at is not None)
        if self.status == "open":
            if self.chosen is not None or any(resolved):
                raise ValueError(f"proposal {self.id}: an open proposal has no resolution")
        else:
            if not all(resolved):
                raise ValueError(f"proposal {self.id}: a resolved proposal says how and when")
            if self.status == "accepted" and self.chosen not in expected:
                raise ValueError(f"proposal {self.id}: accepted, but chose no option it has")
            if self.status == "dismissed" and self.chosen is not None:
                raise ValueError(f"proposal {self.id}: dismissed, so nothing was chosen")
        return self

    def option(self, option_id: str) -> ProposalOption:
        """The option with this id. Raises KeyError naming it when absent."""
        for option in self.options:
            if option.id == option_id:
                return option
        raise KeyError(f"proposal {self.id} has no option {option_id!r}")


# ---------------------------------------------------------------------------
# Renders
# ---------------------------------------------------------------------------


class RenderManifest(StudioModel):
    """`render.json` inside one render directory (`renders/<digest12>/` for a deck state,
    `proposals/<id>/renders/<option>/` for an option). Written last, so a directory with a
    manifest is complete. `images` are paths relative to the render directory, one per
    slide in `slide_ids` order, or `[]` when `rendered` is False (`note` says why)."""

    schema_version: Literal[1] = SCHEMA_VERSION
    digest: str = Field(pattern=RENDER_DIGEST_PATTERN)
    slide_ids: list[str] = Field(default_factory=list)
    rendered: bool
    note: str = ""
    placeholders: dict[str, str] = Field(default_factory=dict)
    images: list[str] = Field(default_factory=list)
    pptx: str | None = Field(default=None, description="Relative path of the PPTX, if built.")
    seconds_build: float = Field(default=0.0, ge=0)
    seconds_previews: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _images_match_slides(self) -> RenderManifest:
        if self.rendered and len(self.images) != len(self.slide_ids):
            raise ValueError("a rendered manifest has one image per slide")
        if not self.rendered and self.images:
            raise ValueError("an unrendered manifest has no images")
        return self


# ---------------------------------------------------------------------------
# Turn events (what the interface streams)
# ---------------------------------------------------------------------------


class _Event(StudioModel):
    thread_id: str = Field(pattern=THREAD_ID_PATTERN)


class TurnStarted(_Event):
    """First event of a turn. `text` is the user's text for `owner` and `choice` turns and
    `""` for `context`/`recap` turns (the opening context is not streamed)."""

    type: Literal["turn_started"] = "turn_started"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    origin: UserOrigin
    text: str = ""
    model_id: str = Field(min_length=1)


class AssistantText(_Event):
    """The model's text from one model call, when non-blank (an intermediate "I will look
    at the sources first" as well as the final reply)."""

    type: Literal["assistant_text"] = "assistant_text"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    step: int = Field(ge=1)
    text: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class ToolCalled(_Event):
    """A tool call is about to run."""

    type: Literal["tool_called"] = "tool_called"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    step: int = Field(ge=1)
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ToolFinished(_Event):
    """A tool call has run: its one-line summary and whether it was an error result."""

    type: Literal["tool_finished"] = "tool_finished"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    step: int = Field(ge=1)
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    summary: str
    error: bool = False


class ChangeRecorded(_Event):
    """A change-log entry was recorded by a tool. `lines` is `diff.describe(entry.diff)`,
    at most `MAX_DIFF_LINES` of them (`truncated` says whether more existed)."""

    type: Literal["change_recorded"] = "change_recorded"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    artifact_id: str = Field(pattern=SEGMENT_PATTERN)
    entry_id: str = Field(pattern=ENTRY_ID_PATTERN)
    instruction: str = Field(min_length=1)
    layer: Layer
    model_id: str = Field(min_length=1)
    lines: list[str] = Field(default_factory=list)
    truncated: bool = False


class ChangeReverted(_Event):
    """An entry was undone or redone, by the model (a tool, within a turn) or by the owner
    (the Changes tab, between turns; `turn_id` is None then)."""

    type: Literal["change_reverted"] = "change_reverted"
    turn_id: str | None = Field(default=None, pattern=TURN_ID_PATTERN)
    artifact_id: str = Field(pattern=SEGMENT_PATTERN)
    entry_id: str = Field(pattern=ENTRY_ID_PATTERN)
    action: Literal["undo", "redo"]
    by: Literal["model", "owner"]


class ArtifactCreated(_Event):
    """A deck artifact was created by `create_deck`."""

    type: Literal["artifact_created"] = "artifact_created"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    artifact_id: str = Field(pattern=SEGMENT_PATTERN)


class ProposalCreated(_Event):
    """A proposal was recorded by `propose`."""

    type: Literal["proposal_created"] = "proposal_created"
    turn_id: str = Field(pattern=TURN_ID_PATTERN)
    proposal_id: str = Field(pattern=PROPOSAL_ID_PATTERN)
    artifact_id: str | None = Field(default=None, pattern=SEGMENT_PATTERN)
    summary: str
    option_ids: list[OptionId]


class ProposalResolved(_Event):
    """A proposal was accepted or dismissed."""

    type: Literal["proposal_resolved"] = "proposal_resolved"
    proposal_id: str = Field(pattern=PROPOSAL_ID_PATTERN)
    status: Literal["accepted", "dismissed"]
    chosen: OptionId | None = None
    by: ResolvedBy


class TurnFinished(_Event, _TurnTotals):
    """Last event of every turn, including one that errored (`stop_reason="error"`). Its
    fields are exactly the `TurnEndLine`'s, minus `seq` and `created_at`."""

    type: Literal["turn_finished"] = "turn_finished"


class PreviewsReady(_Event):
    """A deck state finished rendering (or failed to: `rendered=False`, `note` says why).
    Sent after the turn's `turn_finished`, or after an owner undo/redo (`turn_id` None).
    Image n (1-based) is at `/api/.../artifacts/<artifact_id>/renders/<digest>/<n>.png`."""

    type: Literal["previews_ready"] = "previews_ready"
    turn_id: str | None = Field(default=None, pattern=TURN_ID_PATTERN)
    artifact_id: str = Field(pattern=SEGMENT_PATTERN)
    digest: str = Field(pattern=RENDER_DIGEST_PATTERN)
    slide_ids: list[str] = Field(default_factory=list)
    rendered: bool
    note: str = ""
    placeholders: dict[str, str] = Field(default_factory=dict)


class ProposalPreviewsReady(_Event):
    """The candidate slides of a proposal finished rendering. `options` maps each option
    that has candidate slides to its number of images (0 when not rendered)."""

    type: Literal["proposal_previews_ready"] = "proposal_previews_ready"
    proposal_id: str = Field(pattern=PROPOSAL_ID_PATTERN)
    options: dict[OptionId, int] = Field(default_factory=dict)
    rendered: bool
    note: str = ""


TurnEvent = Annotated[
    TurnStarted
    | AssistantText
    | ToolCalled
    | ToolFinished
    | ChangeRecorded
    | ChangeReverted
    | ArtifactCreated
    | ProposalCreated
    | ProposalResolved
    | TurnFinished
    | PreviewsReady
    | ProposalPreviewsReady,
    Field(discriminator="type"),
]
"""One streamed event; `type` is also the SSE `event:` name."""

TURN_EVENT: TypeAdapter[TurnEvent] = TypeAdapter(TurnEvent)

MAX_DIFF_LINES = 12
"""`ChangeRecorded.lines` carries at most this many `describe` lines."""
