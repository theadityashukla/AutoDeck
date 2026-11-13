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
from autodeck.studio import diff as diffmod
from autodeck.studio import edits, prompt, render_adapter, tool_args, views
from autodeck.studio.conversation import ProposalOption, ProposalRecord
from autodeck.studio.engagement import Engagement
from autodeck.studio.errors import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    EditError,
    InvalidSegmentError,
    NoChangeError,
    NothingToRedoError,
    NothingToUndoError,
    ProposalNotFoundError,
    ProposalStateError,
    SourceNotFoundError,
)
from autodeck.studio.models import OPTION_IDS, ChangeEntry, DeckArtifact, Layer, Slide
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
    flat = views.flat(text)
    return views.clip(flat, limit) if flat else "(no instruction)"


_REFUSALS = (
    EditError,
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
    layer=TOOL_LAYERS[tool_name], model_id=ctx.model_id, now=ctx.clock())`, then
    `ctx.ledger.record_change(store.artifact_id, entry)`; returns the entry. A
    `NoChangeError` propagates; `guarded` reports it as exactly `NO_CHANGE_REFUSAL`."""
    entry = store.apply(
        new_deck,
        instruction=ctx.instruction,
        thread_id=ctx.thread_id,
        layer=TOOL_LAYERS[tool_name],
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

    def edit_result(
        store: ArtifactStore, new_deck: DeckArtifact, tool: str, summary: str
    ) -> ToolResult:
        entry = apply_edit(ctx, store, new_deck, tool)
        return ToolResult(change_text(store, entry), summary)

    def slide_edit_result(
        store: ArtifactStore, new_deck: DeckArtifact, tool: str, slide_id: str, summary: str
    ) -> ToolResult:
        entry = apply_edit(ctx, store, new_deck, tool)
        status, text = qa_text(new_deck.slide(slide_id), ctx.tokens)
        return ToolResult(f"{change_text(store, entry)}\n\n{text}", summary.format(qa=status))

    def view_deck(a: tool_args.ViewDeckArgs) -> ToolResult:
        deck = resolve_artifact(ctx, a.artifact_id).load()
        return ToolResult(
            views.deck_outline(deck), f"viewed deck {deck.id} ({len(deck.slides)} slides)"
        )

    def view_slide(a: tool_args.ViewSlideArgs) -> ToolResult:
        deck = resolve_artifact(ctx, a.artifact_id).load()
        if a.slide_id not in deck.slide_ids():
            raise EditError(f"deck {deck.id} has no slide {a.slide_id}")
        _, qa = qa_text(deck.slide(a.slide_id), ctx.tokens)
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

    def set_design_concept(a: tool_args.SetDesignConceptArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new = edits.set_design_concept(store.load(), text=a.text, marker=a.marker)
        return edit_result(store, new, "set_design_concept", "set the design concept")

    def write_slide(a: tool_args.WriteSlideArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new, is_new, index = edits.upsert_slide(store.load(), a.slide, position=a.position)
        kind = "new" if is_new else "replaced"
        return slide_edit_result(
            store,
            new,
            "write_slide",
            a.slide.id,
            f"wrote slide {a.slide.id} ({kind}, position {index}): {{qa}}",
        )

    def set_block_text(a: tool_args.SetBlockTextArgs) -> ToolResult:
        store = resolve_artifact(ctx, a.artifact_id)
        new = edits.set_block_text(
            store.load(), slide_id=a.slide_id, block_id=a.block_id, text=a.text
        )
        return slide_edit_result(
            store,
            new,
            "set_block_text",
            a.slide_id,
            f"set text of {a.slide_id}/{a.block_id}: {{qa}}",
        )

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

    def propose(a: tool_args.ProposeArgs) -> ToolResult:
        has_slides = any(o.slides for o in a.options)
        deck: DeckArtifact | None = None
        artifact_id: str | None = None
        if has_slides or a.artifact_id is not None or ctx.engagement.artifact_ids():
            store = resolve_artifact(ctx, a.artifact_id)
            artifact_id = store.artifact_id
            deck = store.load()
        options: list[ProposalOption] = []
        for index, option in enumerate(a.options):
            options.append(
                ProposalOption(
                    id=OPTION_IDS[index],
                    label=option.label,
                    text=option.text,
                    slides=option.slides,
                    insert_at=option.insert_at,
                )
            )
        for option in options:
            if not option.slides:
                continue
            assert deck is not None
            for candidate in option.slides:
                if candidate.layout is None:
                    raise EditError(
                        f"candidate slide {candidate.id} has no layout; "
                        "candidates are shown rendered"
                    )
            edits.apply_candidate_slides(deck, option.slides, insert_at=option.insert_at)
            for candidate in option.slides:
                findings = render_adapter.check_slide(candidate, ctx.tokens)
                if findings:
                    raise EditError(
                        f"candidate slide {candidate.id} fails the layout check:\n"
                        + _finding_lines(findings)
                    )
        record = ctx.proposals.create(
            thread_id=ctx.thread_id,
            turn_id=ctx.turn_id,
            artifact_id=artifact_id,
            summary=a.summary,
            options=options,
            now=ctx.clock(),
        )
        ctx.ledger.record_proposal(record)
        ids = ", ".join(o.id for o in options)
        return ToolResult(
            f"Recorded proposal {record.id} with options {ids}. Nothing has changed; "
            "the owner will pick one or dismiss them.",
            f"proposed {record.id}: {len(options)} options",
        )

    def apply_option(a: tool_args.ApplyOptionArgs) -> ToolResult:
        record = ctx.proposals.load(a.proposal_id)
        if record.status == "dismissed":
            raise ProposalStateError(f"the owner dismissed {record.id}")
        if record.status == "accepted" and record.chosen != a.option_id:
            raise ProposalStateError(f"the owner chose {record.chosen} of {record.id}")
        option = next((o for o in record.options if o.id == a.option_id), None)
        if option is None:
            raise ProposalStateError(f"proposal {record.id} has no option {a.option_id}")
        if not option.slides:
            raise ProposalStateError(
                f"option {a.option_id} of {record.id} has no candidate slides; "
                "make the change with the editing tools"
            )
        store = resolve_artifact(ctx, record.artifact_id)
        new = edits.apply_candidate_slides(
            store.load(), option.slides, insert_at=option.insert_at
        )
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
        return ToolResult(
            change_text(store, entry), f"applied option {a.option_id} of {record.id}"
        )

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

    specs: list[tuple[str, type[Any], Callable[[Any], ToolResult], str]] = [
        (
            "view_deck",
            tool_args.ViewDeckArgs,
            view_deck,
            "View the deck: brief, storyline, design concept and slide list.",
        ),
        (
            "view_slide",
            tool_args.ViewSlideArgs,
            view_slide,
            "View one slide in full with its layout check.",
        ),
        (
            "list_sources",
            tool_args.ListSourcesArgs,
            list_sources,
            "List the sources this engagement can read.",
        ),
        (
            "read_source",
            tool_args.ReadSourceArgs,
            read_source,
            "Read a knowledge file or a document page.",
        ),
        (
            "search_sources",
            tool_args.SearchSourcesArgs,
            search_sources,
            "Search the sources for passages.",
        ),
        (
            "create_deck",
            tool_args.CreateDeckArgs,
            create_deck,
            "Create the engagement's deck (only when it has none).",
        ),
        ("set_brief", tool_args.SetBriefArgs, set_brief, "Set the deck's title and brief."),
        (
            "set_storyline",
            tool_args.SetStorylineArgs,
            set_storyline,
            "Replace the storyline with an ordered list of points.",
        ),
        (
            "set_design_concept",
            tool_args.SetDesignConceptArgs,
            set_design_concept,
            "Set the deck's design concept.",
        ),
        (
            "write_slide",
            tool_args.WriteSlideArgs,
            write_slide,
            "Write one whole slide (blocks and layout); returns the layout check.",
        ),
        (
            "set_block_text",
            tool_args.SetBlockTextArgs,
            set_block_text,
            "Replace the text of one text block.",
        ),
        (
            "remove_slide",
            tool_args.RemoveSlideArgs,
            remove_slide,
            "Remove a slide from the deck.",
        ),
        (
            "move_slide",
            tool_args.MoveSlideArgs,
            move_slide,
            "Move a slide to a new 1-based position.",
        ),
        (
            "set_marker",
            tool_args.SetMarkerArgs,
            set_marker,
            "Mark a part decided or provisional.",
        ),
        (
            "propose",
            tool_args.ProposeArgs,
            propose,
            "Offer the owner options without changing the deck.",
        ),
        (
            "apply_option",
            tool_args.ApplyOptionArgs,
            apply_option,
            "Apply the option the owner chose.",
        ),
        ("undo", tool_args.UndoArgs, undo, "Undo the most recent live change."),
        ("redo", tool_args.RedoArgs, redo, "Redo the most recently undone change."),
        ("load_skill", tool_args.LoadSkillArgs, load_skill, "Read one deck-craft skill."),
    ]
    assert tuple(name for name, *_ in specs) == TOOL_NAMES
    tools = [
        Tool(name=name, description=description, args_model=model, run=guarded(name, run))
        for name, model, run, description in specs
    ]
    return ToolBox(tools, state_key=lambda: ctx.ledger.version)
