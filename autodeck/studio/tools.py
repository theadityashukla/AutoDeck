"""The lead's and the mechanic's tools (plan §12 Phases 1, 2 and 3).

**Phase 2-3.** The lead no longer writes layouts: `write_slide` and `set_design_concept` are
gone from its vocabulary (`TOOL_NAMES`); it writes briefs (`set_slide_brief`), asks the
designer to compose them (`compose_slides`), proposes and adopts design directions
(`propose_design`, `apply_design`), and makes small direct text changes (`retitle_slide`,
`set_block_text`, which keep the brief in step and refuse text that no longer fits).
`propose` takes candidate slides as briefs, composed by the designer before the proposal is
recorded. The mechanic gets a handful of these tools (`MECHANIC_TOOL_NAMES`) plus
`hand_to_lead`. The orchestration of the designer and the system layer is in `compose.py`;
the tool handlers here call it. Entries made by the mechanic record the layer `mechanics`;
composition entries record `composition` and the designer's model id.

Phase 1's description follows.

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
from typing import Any

from pydantic import ValidationError

from autodeck.agents.skills import SkillError
from autodeck.agents.skills import load_skill as load_skill_file
from autodeck.agents.tools.registry import (
    Tool,
    ToolBox,
    ToolError,
    ToolResult,
    _validation_text,
)
from autodeck.design.fonts import FontNotFoundError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio import design, edits, prompt, render_adapter, tool_args, views
from autodeck.studio import diff as diffmod
from autodeck.studio.bindings import StudioBindings
from autodeck.studio.conversation import ProposalRecord
from autodeck.studio.engagement import Engagement
from autodeck.studio.errors import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    CompositionError,
    DesignSystemNotFoundError,
    EditError,
    InvalidSegmentError,
    NoChangeError,
    NothingToRedoError,
    NothingToUndoError,
    PaletteRefusedError,
    ProposalNotFoundError,
    ProposalStateError,
    SourceNotFoundError,
)
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
    "set_slide_brief",
    "remove_slide",
    "move_slide",
    "set_marker",
    "compose_slides",
    "propose_design",
    "apply_design",
    "retitle_slide",
    "set_block_text",
    "propose",
    "apply_option",
    "undo",
    "redo",
    "load_skill",
)
"""The lead's tools (Phase 2-3), in the order `build_toolbox` registers them. No tool here
takes a layout or a colour from the lead."""

MECHANIC_TOOL_NAMES: tuple[str, ...] = (
    "view_deck",
    "view_slide",
    "retitle_slide",
    "set_block_text",
    "swap_slides",
    "move_slide",
    "set_marker",
    "hand_to_lead",
)
"""The mechanic's tools (Phase 2-3): small local edits only, and a way to hand the turn to
the lead."""

RETIRED_TOOL_NAMES: tuple[str, ...] = ("write_slide", "set_design_concept")
"""Phase 1 tools no toolbox offers any more (the lead must not write layouts; the design
concept now lives in the design system)."""

TOOL_LAYERS: dict[str, Layer] = {
    "set_brief": "direction",
    "set_storyline": "direction",
    "set_slide_brief": "direction",
    "set_marker": "direction",
    "remove_slide": "direction",
    "move_slide": "direction",
    "swap_slides": "direction",
    "apply_design": "direction",
    "compose_slides": "composition",
    "retitle_slide": "composition",
    "set_block_text": "composition",
    "apply_option": "composition",
}
"""The layer each editing tool's change-log entries record when the lead runs it (plan
§6.1). Every entry the mechanic makes records `mechanics` instead (`apply_edit`).
`compose_slides` entries are recorded by `compose.py` with the designer's model id."""

ISOLATION_REFUSAL = "refused: that is outside this engagement."
"""The whole error text the model sees for a `ClientIsolationError`."""

NO_CHANGE_REFUSAL = "that leaves the deck unchanged"
"""The whole error text the model sees for a `NoChangeError`."""

INSTRUCTION_LIMIT = 200
"""`instruction_line` clips the owner's message to this many characters."""

QA_PASSED = "layout passed"
QA_NO_LAYOUT = "no layout yet"


@dataclass(frozen=True)
class ComposedSlide:
    """Phase 2-3: what the designer did with one slide of a `compose_slides` call, for the
    tool result and the `SlideComposed` event. `entry_id` is the change-log entry that
    applied the result (None when nothing changed, e.g. the same failure recorded twice)."""

    slide_id: str
    clean: bool
    attempts: int
    findings: tuple[str, ...]
    model_id: str
    seconds: float
    entry_id: str | None


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
    composed: list[tuple[str, ComposedSlide]] = field(default_factory=list)
    """Phase 2-3: `(artifact_id, result)` per slide the designer finished."""
    handoff: str | None = None
    """Phase 2-3: the mechanic's reason when it called `hand_to_lead`; the loop stops the
    mechanic's steps when this is set (`loop.run_steps(stop_when=...)`)."""
    events: list[tuple[str, str, object]] = field(default_factory=list)
    """Every item above, in the order it happened, as `(kind, artifact_id or "", item)`
    with kind one of `change`, `undo`, `redo`, `created`, `proposal`, `composed`. Appended
    by the `record_*` methods; read through `since`."""

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

    def record_composed(self, artifact_id: str, result: ComposedSlide) -> None:
        """Phase 2-3: one slide finished by the designer (recorded after its change)."""
        self.composed.append((artifact_id, result))
        self.events.append(("composed", artifact_id, result))

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
    role: str = "lead"
    """Phase 2-3: `lead` or `mechanic`: which toolbox `build_toolbox` builds by default and
    which layer edits record."""
    bindings: StudioBindings | None = None
    """Phase 2-3: the (metered) bindings the composition tools call: `designer` and
    `system`. None in tests of tools that never compose; a composition tool then refuses
    with `CompositionError("no designer is bound")`."""
    designer_attempts: int = 4
    designer_parallel: int = 4
    system_attempts: int = 3

    @property
    def base_tokens(self) -> DesignTokens:
        """The base tokens (`tokens`): fonts, sizes, spacing and the default palette. A
        deck's own tokens are `design.deck_tokens(deck, ctx.base_tokens)`."""
        return self.tokens


def instruction_line(text: str, *, limit: int = INSTRUCTION_LIMIT) -> str:
    """The owner's message as a change-log instruction: `views.clip(views.flat(text),
    limit)`; `"(no instruction)"` when that is empty. Always one non-blank line."""
    flat = views.flat(text)
    return views.clip(flat, limit) if flat else "(no instruction)"


_REFUSALS = (
    EditError,
    CompositionError,
    DesignSystemNotFoundError,
    PaletteRefusedError,
    ArtifactExistsError,
    ArtifactNotFoundError,
    ProposalNotFoundError,
    ProposalStateError,
    SourceNotFoundError,
    InvalidSegmentError,
    NothingToUndoError,
    NothingToRedoError,
)


def guarded(name: str, run: Callable[[object], ToolResult]) -> Callable[[object], ToolResult]:
    """`run` wrapped so the expected failures listed in the module docstring raise
    `ToolError(message)` instead (v2's `ToolBox.dispatch` turns that into an error result
    with summary `<name>: refused`). Other exceptions propagate unchanged."""

    def wrapper(args: object) -> ToolResult:
        try:
            return run(args)
        except ClientIsolationError as exc:
            raise ToolError(ISOLATION_REFUSAL) from exc
        except NoChangeError as exc:
            raise ToolError(NO_CHANGE_REFUSAL) from exc
        except ValidationError as exc:
            raise ToolError(_validation_text(exc)) from exc
        except (*_REFUSALS, SkillError) as exc:
            raise ToolError(str(exc)) from exc

    wrapper.__name__ = f"guarded_{name}"
    return wrapper


def resolve_artifact(ctx: ToolContext, artifact_id: str | None) -> ArtifactStore:
    """The store a deck tool acts on.

    Given an id: `ctx.engagement.artifact_store(artifact_id)`, which must exist (else
    `ArtifactNotFoundError` "no deck <id>; decks here: <ids or none>"). Omitted: the
    engagement's only artifact; with none, `ArtifactNotFoundError` "there is no deck yet;
    create one with create_deck"; with several, `ArtifactNotFoundError` naming them and
    asking for `artifact_id`.
    """
    ids = ctx.engagement.artifact_ids()
    if artifact_id is not None:
        store = ctx.engagement.artifact_store(artifact_id)
        if not store.exists():
            raise ArtifactNotFoundError(
                f"no deck {artifact_id}; decks here: {', '.join(ids) or 'none'}"
            )
        return store
    if not ids:
        raise ArtifactNotFoundError("there is no deck yet; create one with create_deck")
    if len(ids) > 1:
        raise ArtifactNotFoundError(
            f"there are several decks ({', '.join(ids)}); give artifact_id"
        )
    return ctx.engagement.artifact_store(ids[0])


def apply_edit(
    ctx: ToolContext, store: ArtifactStore, new_deck: DeckArtifact, tool_name: str
) -> ChangeEntry:
    """`store.apply(new_deck, instruction=ctx.instruction, thread_id=ctx.thread_id,
    layer=TOOL_LAYERS[tool_name] (`mechanics` when `ctx.role == "mechanic"`),
    model_id=ctx.model_id, now=ctx.clock())`, then
    `ctx.ledger.record_change(store.artifact_id, entry)`; returns the entry. A
    `NoChangeError` propagates; `guarded` reports it as exactly `NO_CHANGE_REFUSAL`."""
    layer: Layer = "mechanics" if ctx.role == "mechanic" else TOOL_LAYERS[tool_name]
    entry = store.apply(
        new_deck,
        instruction=ctx.instruction,
        thread_id=ctx.thread_id,
        layer=layer,
        model_id=ctx.model_id,
        now=ctx.clock(),
    )
    ctx.ledger.record_change(store.artifact_id, entry)
    return entry


def _finding_lines(findings: list[Any]) -> str:
    return "\n".join(f"- {f.block_id or 'slide'}: [{f.check}] {f.message}" for f in findings)


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
    if slide.layout is None:
        return (
            QA_NO_LAYOUT,
            "No layout yet: the owner sees a placeholder until the slide has one.",
        )
    try:
        findings = render_adapter.check_slide(slide, tokens)
    except FontNotFoundError as exc:
        return "layout not checked", f"Layout check unavailable: {exc}"
    if not findings:
        return QA_PASSED, "Layout check passed."
    k = len(findings)
    status = "1 layout finding" if k == 1 else f"{k} layout findings"
    return status, "Layout check found:\n" + _finding_lines(findings)


def change_text(store: ArtifactStore, entry: ChangeEntry) -> str:
    """`Recorded change <id> on <artifact id>:` followed by every `diff.describe` line of
    the entry, one per line."""
    lines = [
        f"Recorded change {entry.id} on {store.artifact_id}:",
        *diffmod.describe(entry.diff),
    ]
    return "\n".join(lines)


def qa_gate(deck: DeckArtifact, slide_id: str, tokens: DesignTokens) -> None:
    """Phase 2-3: refuse a small text change that breaks a designed slide's layout.

    When slide `slide_id` of `deck` (the deck *after* the edit) has a layout and
    `render_adapter.check_slide(slide, tokens)` finds anything, raise `EditError` with
    `"the new text does not fit slide <id>:\\n"` + the findings as `qa_text` lists them +
    `"\\nShorten it, or change the brief and compose the slide again."`. A slide without a
    layout passes. Nothing is recorded either way."""
    raise NotImplementedError


def run_set_slide_brief(ctx: ToolContext, a: tool_args.SetSlideBriefArgs) -> ToolResult:
    """`set_slide_brief`: `edits.set_slide_brief(deck, a.slide_id, a.brief,
    position=a.position, serves=a.serves)` on `resolve_artifact(ctx, a.artifact_id)`, then
    `apply_edit(..., "set_slide_brief")`.

    Text: `change_text(...)`, a blank line, then one line by the slide's composition state
    after the edit (`models.composition_status` against `models.effective_system`):
    undesigned → `Slide <id> is not designed yet; call compose_slides to design it.`;
    stale → `Slide <id> is now stale (<reasons joined by "; ">); call compose_slides to
    redesign it.`; any other state → `Slide <id> is <state>.`.
    Summary: `set brief of <id> (<new|updated>, position <i>)`.
    """
    raise NotImplementedError


def run_compose_slides(ctx: ToolContext, a: tool_args.ComposeSlidesArgs) -> ToolResult:
    """`compose_slides`: `compose.compose_slides(ctx, store, a.slide_ids)` on the resolved
    deck. Text `compose.compose_text(results)`; summary `composed <clean>/<n> slides`, or
    `nothing to compose` when no slide was selected (text then
    `compose.NOTHING_TO_COMPOSE`)."""
    raise NotImplementedError


def run_propose_design(ctx: ToolContext, a: tool_args.ProposeDesignArgs) -> ToolResult:
    """`propose_design`: `compose.propose_design(ctx, store, a)` → `(record, lines)`.
    Text: `Recorded proposal <id> with <k> design directions, each rendered on <sample slide
    ids joined by ", ">. Nothing has changed; the owner will pick one or dismiss them.`
    then the lines (one per direction, from `compose`). Summary
    `proposed <id>: <k> design directions`."""
    raise NotImplementedError


def run_apply_design(ctx: ToolContext, a: tool_args.ApplyDesignArgs) -> ToolResult:
    """`apply_design` (and `apply_option` on a design option):
    `compose.apply_design(ctx, store, a)` → `(system, entry, stale_ids)`, where the store is
    the proposal's artifact for the option form, else `resolve_artifact(ctx,
    a.artifact_id)`. Text: `Adopted the design "<name>" (<id> v<version>) as the deck's
    decided design system.`, then `change_text(store, entry)`, then `Now stale: <ids joined
    by ", ">. Call compose_slides to redesign them.` or `No slide was designed yet.`.
    Summary `adopted design <id> v<version>; <k> slides stale`."""
    raise NotImplementedError


def run_retitle_slide(ctx: ToolContext, a: tool_args.RetitleSlideArgs) -> ToolResult:
    """`retitle_slide`: `edits.retitle_slide(deck, a.slide_id, a.header)`, then
    `qa_gate(new, a.slide_id, design.deck_tokens(new, ctx.base_tokens))`, then
    `apply_edit(..., "retitle_slide")`. Text: `change_text`, a blank line, `qa_text` of the
    slide (deck tokens). Summary `retitled <id>: <qa status>`."""
    raise NotImplementedError


def run_set_block_text(ctx: ToolContext, a: tool_args.SetBlockTextArgs) -> ToolResult:
    """`set_block_text` (Phase 2-3): `edits.set_designed_text(...)`, `qa_gate` (deck
    tokens), `apply_edit(..., "set_block_text")`. Text and summary as Phase 1:
    `change_text`, a blank line, `qa_text` (deck tokens); summary `set text of
    <slide>/<block>: <qa status>`."""
    raise NotImplementedError


def run_swap_slides(ctx: ToolContext, a: tool_args.SwapSlidesArgs) -> ToolResult:
    """`swap_slides`: `edits.swap_slides`, `apply_edit(..., "swap_slides")`. Text
    `change_text` then `Slide order now: <views.slide_order(new)>`; summary
    `swapped slides <first> and <second>`."""
    raise NotImplementedError


def run_hand_to_lead(ctx: ToolContext, a: tool_args.HandToLeadArgs) -> ToolResult:
    """`hand_to_lead` (mechanic only): `ctx.ledger.handoff = a.reason`. Text
    `Handed to the lead: <reason>`; summary `handed to the lead: <clip(reason, 80)>`.
    Changes nothing."""
    raise NotImplementedError


def run_propose(ctx: ToolContext, a: tool_args.ProposeBriefsArgs) -> ToolResult:
    """`propose` (Phase 2-3): `compose.propose_briefs(ctx, store, a)` → the record
    (candidate briefs composed by the designer; refused with `CompositionError` naming the
    findings when any candidate does not come out clean). Text and summary exactly as Phase
    1: `Recorded proposal <id> with options <A, B, ...>. Nothing has changed; the owner
    will pick one or dismiss them.` / `proposed <id>: <k> options`. The deck is resolved as
    Phase 1 did (only when some option has candidates, an `artifact_id` was given, or the
    engagement has a deck; `store` is None otherwise)."""
    raise NotImplementedError


def build_toolbox(ctx: ToolContext, *, names: tuple[str, ...] | None = None) -> ToolBox:
    """A `ToolBox` with one `Tool` per name in `names` (default: `MECHANIC_TOOL_NAMES` when
    `ctx.role == "mechanic"`, else `TOOL_NAMES`), in that order, each run through
    `guarded`, `state_key=lambda: ctx.ledger.version`, v2's default repeat limit. Asking for
    a name that is not a tool raises `KeyError`.

    Unchanged from Phase 1 (see `docs/phases/V3-PHASE-1.md`): `view_deck`, `list_sources`,
    `read_source`, `search_sources`, `create_deck`, `set_brief`, `set_storyline`,
    `remove_slide`, `move_slide`, `set_marker`, `undo`, `redo`, `load_skill`. `view_slide`
    is Phase 1's with the layout check run in the deck's tokens. `apply_option` is Phase
    1's, except that a design option is applied as `apply_design`. Every other tool is a
    `run_*` function above.
    """

    def edit_result(
        store: ArtifactStore, new_deck: DeckArtifact, tool: str, summary: str
    ) -> ToolResult:
        entry = apply_edit(ctx, store, new_deck, tool)
        return ToolResult(change_text(store, entry), summary)

    def view_deck(a: tool_args.ViewDeckArgs) -> ToolResult:
        deck = resolve_artifact(ctx, a.artifact_id).load()
        return ToolResult(
            views.deck_outline(deck), f"viewed deck {deck.id} ({len(deck.slides)} slides)"
        )

    def view_slide(a: tool_args.ViewSlideArgs) -> ToolResult:
        deck = resolve_artifact(ctx, a.artifact_id).load()
        if a.slide_id not in deck.slide_ids():
            raise EditError(f"deck {deck.id} has no slide {a.slide_id}")
        tokens = design.deck_tokens(deck, ctx.base_tokens)
        _, qa = qa_text(deck.slide(a.slide_id), tokens)
        return ToolResult(
            f"{views.slide_detail(deck, a.slide_id)}\n\n{qa}", f"viewed slide {a.slide_id}"
        )

    def list_sources(a: tool_args.ListSourcesArgs) -> ToolResult:
        infos = ctx.sources.list()
        text = "\n".join(f"{i.id} | {i.title} | {i.detail}" for i in infos) or "No sources."
        return ToolResult(text, f"{len(infos)} sources")

    def read_source(a: tool_args.ReadSourceArgs) -> ToolResult:
        read = ctx.sources.read(a.source_id, page=a.page, offset=a.offset)
        return ToolResult(read.text, read.summary)

    def search_sources(a: tool_args.SearchSourcesArgs) -> ToolResult:
        hits = ctx.sources.search(a.query, limit=a.limit)
        paragraphs = []
        for h in hits:
            tag = h.source_id if h.page is None else f"{h.source_id} p.{h.page}"
            paragraphs.append(f"[{tag}] {h.text}")
        text = "\n\n".join(paragraphs) or "No passages match."
        return ToolResult(text, f'search "{views.clip(a.query, 60)}": {len(hits)} passages')

    def create_deck(a: tool_args.CreateDeckArgs) -> ToolResult:
        existing = ctx.engagement.artifact_ids()
        if existing:
            raise ArtifactExistsError(
                f"this engagement already has a deck: {', '.join(existing)}; "
                "Phase 1 works on one deck"
            )
        ctx.engagement.create_artifact(
            DeckArtifact(
                id=a.artifact_id,
                client=ctx.engagement.client,
                project=ctx.engagement.project,
                title=a.title,
            )
        )
        ctx.ledger.record_created(a.artifact_id)
        return ToolResult(
            f"Created deck {a.artifact_id}. It is empty.", f"created deck {a.artifact_id}"
        )

    def set_brief(a: tool_args.SetBriefArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new = edits.set_brief(
            store.load(),
            title=a.title,
            audience=a.audience,
            goal=a.goal,
            notes=a.notes,
            marker=a.marker,
        )
        return edit_result(store, new, "set_brief", "set the brief")

    def set_storyline(a: tool_args.SetStorylineArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new, dropped = edits.set_storyline(
            store.load(), [(p.id, p.text) for p in a.points], marker=a.marker
        )
        entry = apply_edit(ctx, store, new, "set_storyline")
        text = change_text(store, entry)
        if dropped:
            text += "\nDropped links: " + ", ".join(f"{s}->{p}" for s, p in dropped)
        return ToolResult(text, f"set the storyline ({len(a.points)} points)")

    def remove_slide(a: tool_args.RemoveSlideArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new = edits.remove_slide(store.load(), slide_id=a.slide_id)
        return edit_result(store, new, "remove_slide", f"removed slide {a.slide_id}")

    def move_slide(a: tool_args.MoveSlideArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new = edits.move_slide(store.load(), slide_id=a.slide_id, to_index=a.position - 1)
        return edit_result(
            store, new, "move_slide", f"moved slide {a.slide_id} to position {a.position}"
        )

    def set_marker(a: tool_args.SetMarkerArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new = edits.set_part_marker(store.load(), target=a.target, marker=a.marker)
        return edit_result(store, new, "set_marker", f"marked {a.target} {a.marker}")

    def apply_option(a: tool_args.ApplyOptionArgs) -> ToolResult:
        record = ctx.proposals.load(a.proposal_id)
        if record.status == "dismissed":
            raise ProposalStateError(f"the owner dismissed {record.id}")
        if record.status == "accepted" and record.chosen != a.option_id:
            raise ProposalStateError(f"the owner chose {record.chosen} of {record.id}")
        option = next((o for o in record.options if o.id == a.option_id), None)
        if option is None:
            raise ProposalStateError(f"proposal {record.id} has no option {a.option_id}")
        if option.design is not None:
            return run_apply_design(
                ctx,
                tool_args.ApplyDesignArgs(proposal_id=record.id, option_id=a.option_id),
            )
        if not option.slides:
            raise ProposalStateError(
                f"option {a.option_id} of {record.id} has no candidate slides; "
                "make the change with the editing tools"
            )
        if option.legacy:
            raise ProposalStateError(
                f"option {a.option_id} of {record.id} was recorded before proposals said "
                "whether a candidate replaces a slide or is inserted, so it cannot be applied; "
                "make the change with the editing tools, or propose again"
            )
        store = resolve_artifact(ctx, record.artifact_id)
        new, done = edits.apply_candidate_slides(store.load(), option.candidates)
        # Validated first, so a refused application leaves the proposal open.
        if record.status == "open":
            ctx.proposals.resolve(
                record.id,
                status="accepted",
                chosen=a.option_id,
                by="chat",
                now=ctx.clock(),
            )
        entry = apply_edit(ctx, store, new, "apply_option")
        text = "\n".join(
            [change_text(store, entry), *done, f"Slide order now: {views.slide_order(new)}"]
        )
        return ToolResult(text, f"applied option {a.option_id} of {record.id}")

    def undo(a: tool_args.UndoArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        entry = store.undo()
        ctx.ledger.record_undo(store.artifact_id, entry)
        return ToolResult(
            f"Undid {entry.id} ({entry.instruction}). The deck is back to the state before it.",
            f"undid {entry.id}: {views.clip(entry.instruction, 60)}",
        )

    def redo(a: tool_args.RedoArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        entry = store.redo()
        ctx.ledger.record_redo(store.artifact_id, entry)
        return ToolResult(
            f"Redid {entry.id} ({entry.instruction}).",
            f"redid {entry.id}: {views.clip(entry.instruction, 60)}",
        )

    def load_skill(a: tool_args.LoadSkillArgs) -> ToolResult:
        if a.name not in prompt.ALLOWED_SKILLS:
            raise SkillError(
                f"skill {a.name} is not available here; "
                f"available: {', '.join(prompt.ALLOWED_SKILLS)}"
            )
        skill = load_skill_file(a.name, skills_dir=prompt.SKILLS_DIR)
        return ToolResult(
            f"## Skill: {skill.name}\n\n{skill.body}", f"loaded skill {skill.name}"
        )

    def bind(run: Callable[[ToolContext, Any], ToolResult]) -> Callable[[Any], ToolResult]:
        return lambda a: run(ctx, a)

    specs: dict[str, tuple[type[Any], Callable[[Any], ToolResult], str]] = {
        "view_deck": (
            tool_args.ViewDeckArgs,
            view_deck,
            "View the deck: brief, storyline, design system, and each slide with its brief "
            "and whether it is designed, stale or failed.",
        ),
        "view_slide": (
            tool_args.ViewSlideArgs,
            view_slide,
            "View one slide in full (its brief, blocks and their ids) with its layout check.",
        ),
        "list_sources": (
            tool_args.ListSourcesArgs,
            list_sources,
            "List the sources this engagement can read.",
        ),
        "read_source": (
            tool_args.ReadSourceArgs,
            read_source,
            "Read a knowledge file or a document page.",
        ),
        "search_sources": (
            tool_args.SearchSourcesArgs,
            search_sources,
            "Search the sources for passages.",
        ),
        "create_deck": (
            tool_args.CreateDeckArgs,
            create_deck,
            "Create the engagement's deck (only when it has none).",
        ),
        "set_brief": (tool_args.SetBriefArgs, set_brief, "Set the deck's title and brief."),
        "set_storyline": (
            tool_args.SetStorylineArgs,
            set_storyline,
            "Replace the storyline with an ordered list of points.",
        ),
        "set_slide_brief": (
            tool_args.SetSlideBriefArgs,
            bind(run_set_slide_brief),
            "Create a slide from a brief, or update a slide's brief: header, intent, content "
            "(points, figures, optional chart data) and notes. Words only; the designer "
            "designs it when you call compose_slides.",
        ),
        "remove_slide": (
            tool_args.RemoveSlideArgs,
            remove_slide,
            "Remove a slide from the deck.",
        ),
        "move_slide": (
            tool_args.MoveSlideArgs,
            move_slide,
            "Move a slide to a new 1-based position.",
        ),
        "set_marker": (
            tool_args.SetMarkerArgs,
            set_marker,
            "Mark a part decided or provisional.",
        ),
        "compose_slides": (
            tool_args.ComposeSlidesArgs,
            bind(run_compose_slides),
            "Ask the designer to design or redesign slides from their briefs in the deck's "
            "design system, in parallel. Omit slide_ids for every stale or undesigned slide. "
            "Reports per slide: clean or not, attempts, findings.",
        ),
        "propose_design": (
            tool_args.ProposeDesignArgs,
            bind(run_propose_design),
            "Offer two or three design directions (name, concept, rules), each turned into a "
            "checked palette and rendered on up to three of this deck's slides. Changes "
            "nothing until the owner picks.",
        ),
        "apply_design": (
            tool_args.ApplyDesignArgs,
            bind(run_apply_design),
            "Adopt a design as the deck's decided design system: a proposal option the owner "
            "chose, or a direction in words. Designed slides become stale.",
        ),
        "retitle_slide": (
            tool_args.RetitleSlideArgs,
            bind(run_retitle_slide),
            "Give a slide a new header, keeping its design. Refused if it no longer fits.",
        ),
        "set_block_text": (
            tool_args.SetBlockTextArgs,
            bind(run_set_block_text),
            "Replace the text of one text block, keeping the design and the brief in step. "
            "Refused if it no longer fits.",
        ),
        "swap_slides": (
            tool_args.SwapSlidesArgs,
            bind(run_swap_slides),
            "Exchange the positions of two slides.",
        ),
        "hand_to_lead": (
            tool_args.HandToLeadArgs,
            bind(run_hand_to_lead),
            "Give this turn to the lead: the request is more than a small edit.",
        ),
        "propose": (
            tool_args.ProposeBriefsArgs,
            bind(run_propose),
            "Offer the owner options without changing the deck. Candidate slides are briefs "
            "the designer renders; each says whether it replaces an existing slide "
            "(replaces: its id) or is inserted at a position (insert_at).",
        ),
        "apply_option": (
            tool_args.ApplyOptionArgs,
            apply_option,
            "Apply the option the owner chose: each candidate replaces the slide it named or "
            "is inserted where it said (on a design option: adopts the design). The result "
            "states what was replaced or inserted and the resulting slide order; report "
            "that, not what you expected.",
        ),
        "undo": (tool_args.UndoArgs, undo, "Undo the most recent live change."),
        "redo": (tool_args.RedoArgs, redo, "Redo the most recently undone change."),
        "load_skill": (tool_args.LoadSkillArgs, load_skill, "Read one deck-craft skill."),
    }
    if names is not None:
        chosen = names
    else:
        chosen = MECHANIC_TOOL_NAMES if ctx.role == "mechanic" else TOOL_NAMES
    tools = []
    for name in chosen:
        model, run, description = specs[name]
        tools.append(
            Tool(name=name, description=description, args_model=model, run=guarded(name, run))
        )
    return ToolBox(tools, state_key=lambda: ctx.ledger.version)
