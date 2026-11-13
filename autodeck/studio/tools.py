"""The lead's tools: read state, read sources, edit, propose, undo (plan §12 Phase 1).

Built on v2's `Tool` / `ToolBox` / `ToolResult` (`agents/tools/registry.py`): every tool
has a pydantic argument model (`tool_args`), the toolbox validates the model's call, and a
bad call comes back to the model as an `ERROR:` result, never as an exception. v2's
`ToolBox.dispatch` turns only its own `ToolError` (and two v2 error types) into error
results, so every tool here runs inside `guarded`, which converts the studio's expected
failures into `ToolError`:

* `StudioError` subclasses that describe a refusal (`EditError`, `NoChangeError`,
  `NothingToUndoError`, `NothingToRedoError`, `ArtifactExistsError`,
  `ArtifactNotFoundError`, `ProposalNotFoundError`, `ProposalStateError`,
  `SourceNotFoundError`, `InvalidSegmentError`);
* `pydantic.ValidationError` (an edit that would make an invalid deck): the message is the
  first errors, one per `; `, as v2's `_validation_text` formats them;
* v2's `ClientIsolationError`: the message is exactly `ISOLATION_REFUSAL`, so nothing about
  the other client's path reaches the model; `NoChangeError`: exactly `NO_CHANGE_REFUSAL`;
* v2's `SkillError`.

Anything else (including `ChangeLogIntegrityError`) is a bug or a corrupt store and
propagates: the session ends the turn with `stop_reason="error"`.

**Every edit goes through `ArtifactStore.apply`**, with the turn's instruction (the
owner's message as one line), the thread id, the tool's layer (`TOOL_LAYERS`) and the
bound model's id, and is recorded in the turn's `TurnLedger`. One model writes every
layer in Phase 1; the layer is recorded anyway so Phase 2's routing and Phase 7's
benchmark have the data (V5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from autodeck.agents.tools.registry import ToolBox, ToolResult
from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.conversation import ProposalRecord
from autodeck.studio.engagement import Engagement
from autodeck.studio.models import ChangeEntry, DeckArtifact, Layer, Slide
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.sources import SourceLibrary
from autodeck.studio.store import ArtifactStore

TOOL_NAMES: tuple[str, ...] = (
    "view_deck",
    "view_slide",
    "list_sources",
    "read_source",
    "search_sources",
    "create_deck",
    "set_brief",
    "set_storyline",
    "set_design_concept",
    "write_slide",
    "set_block_text",
    "remove_slide",
    "move_slide",
    "set_marker",
    "propose",
    "apply_option",
    "undo",
    "redo",
    "load_skill",
)
"""Every tool, in the order `build_toolbox` registers them (the order the model sees)."""

TOOL_LAYERS: dict[str, Layer] = {
    "set_brief": "direction",
    "set_storyline": "direction",
    "set_design_concept": "direction",
    "set_marker": "direction",
    "remove_slide": "direction",
    "move_slide": "direction",
    "write_slide": "composition",
    "set_block_text": "composition",
    "apply_option": "composition",
}
"""The layer each editing tool's change-log entries record (plan §6.1)."""

ISOLATION_REFUSAL = "refused: that is outside this engagement."
"""The whole error text the model sees for a `ClientIsolationError`."""

NO_CHANGE_REFUSAL = "that leaves the deck unchanged"
"""The whole error text the model sees for a `NoChangeError`."""

INSTRUCTION_LIMIT = 200
"""`instruction_line` clips the owner's message to this many characters."""

QA_PASSED = "layout passed"
QA_NO_LAYOUT = "no layout yet"


@dataclass
class TurnLedger:
    """What the tools of one turn did, in order. The loop reads it after each tool call to
    stream events (`since`), and the session reads it at the end to classify the turn and
    to know which artifacts need new previews. Plain data: no I/O."""

    changes: list[tuple[str, ChangeEntry]] = field(default_factory=list)
    """`(artifact_id, entry)` for each entry recorded."""
    undone: list[tuple[str, ChangeEntry]] = field(default_factory=list)
    redone: list[tuple[str, ChangeEntry]] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    """Artifact ids created."""
    proposals: list[ProposalRecord] = field(default_factory=list)
    events: list[tuple[str, str, object]] = field(default_factory=list)
    """Every item above, in the order it happened, as `(kind, artifact_id or "", item)`
    with kind one of `change`, `undo`, `redo`, `created`, `proposal`. Appended by the
    `record_*` methods; read through `since`."""

    def record_change(self, artifact_id: str, entry: ChangeEntry) -> None:
        self.changes.append((artifact_id, entry))
        self.events.append(("change", artifact_id, entry))

    def record_undo(self, artifact_id: str, entry: ChangeEntry) -> None:
        self.undone.append((artifact_id, entry))
        self.events.append(("undo", artifact_id, entry))

    def record_redo(self, artifact_id: str, entry: ChangeEntry) -> None:
        self.redone.append((artifact_id, entry))
        self.events.append(("redo", artifact_id, entry))

    def record_created(self, artifact_id: str) -> None:
        self.created.append(artifact_id)
        self.events.append(("created", artifact_id, artifact_id))

    def record_proposal(self, proposal: ProposalRecord) -> None:
        self.proposals.append(proposal)
        self.events.append(("proposal", proposal.artifact_id or "", proposal))

    def mark(self) -> int:
        """A position to pass to `since` later."""
        return len(self.events)

    def since(self, mark: int) -> list[tuple[str, str, object]]:
        """The events recorded after `mark`, in order."""
        return list(self.events[mark:])

    @property
    def version(self) -> int:
        """Changes whenever anything is recorded: the toolbox's repeat-guard state key."""
        return len(self.events)

    def touched_artifacts(self) -> list[str]:
        """Artifact ids with a change, undo, redo or creation this turn, in first-touch
        order, without repeats. These get new previews after the turn."""
        seen: list[str] = []
        for kind, artifact_id, _ in self.events:
            if kind != "proposal" and artifact_id and artifact_id not in seen:
                seen.append(artifact_id)
        return seen


@dataclass
class ToolContext:
    """Everything the tools of one turn need. Built by the session per turn."""

    engagement: Engagement
    thread_id: str
    turn_id: str
    instruction: str
    """The turn's instruction as one line (`instruction_line`); recorded on every entry."""
    model_id: str
    tokens: DesignTokens
    sources: SourceLibrary
    proposals: ProposalStore
    ledger: TurnLedger
    clock: Callable[[], datetime]


def instruction_line(text: str, *, limit: int = INSTRUCTION_LIMIT) -> str:
    """The owner's message as a change-log instruction: `views.clip(views.flat(text),
    limit)`; `"(no instruction)"` when that is empty. Always one non-blank line."""
    raise NotImplementedError


def guarded(name: str, run: Callable[[object], ToolResult]) -> Callable[[object], ToolResult]:
    """`run` wrapped so the expected failures listed in the module docstring raise
    `ToolError(message)` instead (v2's `ToolBox.dispatch` turns that into an error result
    with summary `<name>: refused`). Other exceptions propagate unchanged."""
    raise NotImplementedError


def resolve_artifact(ctx: ToolContext, artifact_id: str | None) -> ArtifactStore:
    """The store a deck tool acts on.

    Given an id: `ctx.engagement.artifact_store(artifact_id)`, which must exist (else
    `ArtifactNotFoundError` "no deck <id>; decks here: <ids or none>"). Omitted: the
    engagement's only artifact; with none, `ArtifactNotFoundError` "there is no deck yet;
    create one with create_deck"; with several, `ArtifactNotFoundError` naming them and
    asking for `artifact_id`.
    """
    raise NotImplementedError


def apply_edit(
    ctx: ToolContext, store: ArtifactStore, new_deck: DeckArtifact, tool_name: str
) -> ChangeEntry:
    """`store.apply(new_deck, instruction=ctx.instruction, thread_id=ctx.thread_id,
    layer=TOOL_LAYERS[tool_name], model_id=ctx.model_id, now=ctx.clock())`, then
    `ctx.ledger.record_change(store.artifact_id, entry)`; returns the entry. A
    `NoChangeError` propagates; `guarded` reports it as exactly `NO_CHANGE_REFUSAL`."""
    raise NotImplementedError


def qa_text(slide: Slide, tokens: DesignTokens) -> tuple[str, str]:
    """The layout check of one slide for the model: `(status, text)`.

    * no layout: `(QA_NO_LAYOUT, "No layout yet: the owner sees a placeholder until the
      slide has one.")`;
    * `render_adapter.check_slide` finds nothing: `(QA_PASSED, "Layout check passed.")`;
    * findings: `(f"{k} layout findings", "Layout check found:\\n" + one line per finding
      "- <block_id or 'slide'>: [<check>] <message>")` (`1 layout finding` when k == 1);
    * v2's `FontNotFoundError` while checking: `("layout not checked", "Layout check
      unavailable: <message>")`.
    """
    raise NotImplementedError


def change_text(store: ArtifactStore, entry: ChangeEntry) -> str:
    """`Recorded change <id> on <artifact id>:` followed by every `diff.describe` line of
    the entry, one per line."""
    raise NotImplementedError


def build_toolbox(ctx: ToolContext) -> ToolBox:
    """A `ToolBox` with one `Tool` per name in `TOOL_NAMES`, in that order, each run
    through `guarded`, `state_key=lambda: ctx.ledger.version`, v2's default repeat limit.

    Each tool's behaviour, result text (the model reads it) and summary (one line, the
    interface shows it) are:

    * `view_deck` (`ViewDeckArgs`): text `views.deck_outline(deck)`; summary
      `viewed deck <id> (<n> slides)`.
    * `view_slide`: text `views.slide_detail(...)`, a blank line, then `qa_text`'s text;
      summary `viewed slide <slide id>`. Unknown slide: error "deck <id> has no slide <s>".
    * `list_sources`: text one line per source `<id> | <title> | <detail>`, or
      `No sources.`; summary `<n> sources`.
    * `read_source`: `ctx.sources.read(...)`'s text and summary.
    * `search_sources`: text one paragraph per hit, `[<source id>]` or
      `[<source id> p.<page>]` then a space and the hit text, paragraphs separated by a
      blank line, or `No passages match.`; summary `search "<clip(query, 60)>": <n>
      passages`.
    * `create_deck` (`CreateDeckArgs`): refused when the engagement already has any
      artifact ("this engagement already has a deck: <ids>; Phase 1 works on one deck");
      else `ctx.engagement.create_artifact(DeckArtifact(id=..., client=..., project=...,
      title=...))` and `ledger.record_created(id)`. No change-log entry (creation is the
      initial state). Text `Created deck <id>. It is empty.`; summary `created deck <id>`.
    * `set_brief`: `edits.set_brief`; summary `set the brief`.
    * `set_storyline`: `edits.set_storyline` with `[(p.id, p.text) ...]`; text adds, when
      links were dropped, a line `Dropped links: <slide>-><point>, ...`; summary
      `set the storyline (<k> points)`.
    * `set_design_concept`: summary `set the design concept`.
    * `write_slide`: `edits.upsert_slide`; text `change_text`, a blank line, `qa_text`'s
      text; summary `wrote slide <id> (<new|replaced>, position <i>): <qa status>`.
    * `set_block_text`: `edits.set_block_text`; text as write_slide; summary
      `set text of <slide id>/<block id>: <qa status>`.
    * `remove_slide`: summary `removed slide <id>`.
    * `move_slide`: `edits.move_slide(to_index=position - 1)`; summary
      `moved slide <id> to position <p>`.
    * `set_marker`: `edits.set_part_marker`; summary `marked <target> <marker>`.
      For the edit tools above the text is `change_text(...)` unless stated otherwise.
    * `propose` (`ProposeArgs`): options get ids `A`, `B`, ... in order. When any option
      has slides, the deck (`resolve_artifact`) must exist and every candidate must:
      have a layout ("candidate slide <id> has no layout; candidates are shown rendered"),
      make a valid deck with `edits.apply_candidate_slides` (a `ValidationError` is
      refused), and pass `render_adapter.check_slide` (findings are refused, listed as in
      `qa_text`). Then `ctx.proposals.create(thread_id, turn_id, artifact_id (None when
      no option has slides and no artifact_id was given and the engagement has no deck;
      otherwise the resolved deck's id), summary, options, now)` and
      `ledger.record_proposal`. Nothing in the deck changes. Text `Recorded proposal
      <id> with options <A, B, ...>. Nothing has changed; the owner will pick one or
      dismiss them.`; summary `proposed <id>: <k> options`.
    * `apply_option` (`ApplyOptionArgs`): load the proposal. Dismissed: refused ("the
      owner dismissed <id>"). Accepted with another option: refused ("the owner chose
      <X> of <id>"). Option without slides: refused ("option <X> of <id> has no candidate
      slides; make the change with the editing tools"). Open: resolve it accepted with
      `by="chat"` first. Then `edits.apply_candidate_slides(deck, option.slides,
      insert_at=option.insert_at)` on the proposal's artifact and `apply_edit`. Summary
      `applied option <X> of <id>`.
    * `undo` / `redo`: `store.undo()` / `store.redo()`, `ledger.record_undo/redo`. Text
      `Undid <id> (<instruction>). The deck is back to the state before it.` / `Redid
      <id> (<instruction>).`; summary `undid <id>: <clip(instruction, 60)>` /
      `redid <id>: ...`. Nothing to undo/redo: refused with the store's message.
    * `load_skill`: only names in `prompt.ALLOWED_SKILLS` (else refused "skill <name>
      is not available here; available: <names>"); `agents.skills.load_skill(name,
      skills_dir=prompt.SKILLS_DIR)`; text `## Skill: <name>` + blank line + body;
      summary `loaded skill <name>`.
    """
    raise NotImplementedError
