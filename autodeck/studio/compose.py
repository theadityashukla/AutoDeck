"""Composition orchestration: what the lead's design and composition tools do (Phase 2-3).

The tool handlers in `tools.py` call these functions. They tie the designer
(`designer.py`), the system layer (`system_layer.py`), the design-system store
(`design.DesignSystemStore`) and the artifact store together, and own three rules:

* **Results land through the artifact store, one entry per slide.** Each slide the designer
  finishes is applied with `ArtifactStore.apply` on its own, in deck order after the whole
  parallel batch has returned, with the layer `composition` and the **designer's** model id
  (not the lead's), and the turn's instruction and thread. So the change log shows who
  composed each slide, and one slide's recomposition can be undone alone.
* **A failure is recorded, not hidden.** A slide that does not come out clean gets a
  `CompositionFailure` (its previous designed form, if any, is kept), recorded as its own
  entry, so the lead, the owner and the next thread's context can see it.
* **Nothing rebuilds by itself.** Choosing what to compose is explicit (`select_slides`);
  adopting a design only changes the deck's reference, and designed slides become stale by
  fingerprint.

The design system of a deck is `DesignSystemStore.for_deck(deck)`; its tokens are
`design.design_tokens(system.palette, ctx.base_tokens)`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from autodeck.studio.conversation import ProposalRecord
from autodeck.studio.design import DesignDraft, DesignSystem
from autodeck.studio.designer import DesignJob, DesignResult
from autodeck.studio.models import ChangeEntry, DeckArtifact, SlideBrief
from autodeck.studio.store import ArtifactStore
from autodeck.studio.tool_args import ApplyDesignArgs, ProposeBriefsArgs, ProposeDesignArgs

if TYPE_CHECKING:
    from autodeck.studio.tools import ComposedSlide, ToolContext

NOTHING_TO_COMPOSE = (
    "Nothing to compose: every slide with a brief is designed in the current design system."
)
MAX_SAMPLES = 3
MAX_FINDINGS_IN_TEXT = 3
FINDING_CLIP = 160
DRAFT_SYSTEM_ID = "draft"
"""The id of the in-memory `DesignSystem` a sample is composed in before a design is
adopted (`draft_system`); never stored."""


def select_slides(deck: DeckArtifact, slide_ids: Sequence[str] | None) -> list[str]:
    """The slides to compose, in deck order, without repeats.

    `None`: every slide whose `models.composition_status` (against
    `models.effective_system(deck)`) is `undesigned` or `stale` (failed slides are not
    retried unless named). Named: each must exist (`EditError` "deck <id> has no slide
    <s>") and have a brief (`CompositionError` "slide <s> has no brief; write one with
    set_slide_brief"); returned in deck order whatever their state (a fresh slide named
    explicitly is redesigned).
    """
    raise NotImplementedError


def draft_system(draft: DesignDraft) -> DesignSystem:
    """An unstored `DesignSystem` for composing samples in a draft: `id=DRAFT_SYSTEM_ID`,
    `version=1`, `marker="provisional"`, every other field from the draft, `created_at`
    None."""
    raise NotImplementedError


def jobs_for(
    deck: DeckArtifact, slide_ids: Sequence[str], system: DesignSystem, ctx: ToolContext
) -> list[DesignJob]:
    """One `DesignJob(slide_id, slide.brief, system, design.design_tokens(system.palette,
    ctx.base_tokens))` per id, in the given order. Every slide named has a brief."""
    raise NotImplementedError


def compose_slides(
    ctx: ToolContext, store: ArtifactStore, slide_ids: Sequence[str] | None
) -> list[ComposedSlide]:
    """Design the selected slides in parallel and apply each result. In order:

    1. `ctx.bindings` is None → `CompositionError("no designer is bound")`.
    2. `deck = store.load()`; `system = DesignSystemStore(ctx.engagement,
       base=ctx.base_tokens).for_deck(deck)`; `ids = select_slides(deck, slide_ids)`; no ids
       → return `[]` (no model call).
    3. `results = designer.design_slides(ctx.bindings.designer, jobs_for(...),
       attempts=ctx.designer_attempts, max_parallel=ctx.designer_parallel)`.
    4. For each result, in deck order: reload the deck; a clean result →
       `edits.apply_composition(deck, id, result.slide, ComposedFrom(result.brief_digest,
       system.id, system.version, result.model_id))`; a failed one →
       `edits.record_compose_failure(deck, id, CompositionFailure(..., attempts=max(1,
       result.attempt_count), findings=<result.findings clipped to FINDING_CLIP each, at
       most models.MAX_FAILURE_FINDINGS>))`. Apply with `store.apply(new,
       instruction=ctx.instruction, thread_id=ctx.thread_id, layer="composition",
       model_id=result.model_id, now=ctx.clock())` and `ctx.ledger.record_change`. A
       `NoChangeError` (the same failure again) records no entry (`entry_id` None). Then
       `ctx.ledger.record_composed(store.artifact_id, ComposedSlide(...))`.
    5. Return the `ComposedSlide`s in deck order.
    """
    raise NotImplementedError


def compose_text(results: Sequence[ComposedSlide]) -> str:
    """The tool result for `compose_slides`, lines joined by `\\n`:

    * `Composed <clean> of <n> slides.`
    * per slide, in order: `- <id>: clean in <a> attempt|attempts` or
      `- <id>: failed after <a> attempt|attempts: <first MAX_FINDINGS_IN_TEXT findings
      joined by "; ">` (singular only for 1);
    * when any failed: `The previous design is kept for slides that failed; shorten their
      briefs or ask again.`
    `NOTHING_TO_COMPOSE` for no results.
    """
    raise NotImplementedError


def sample_slides(deck: DeckArtifact, named: Sequence[str] | None) -> list[str]:
    """The slides a design proposal is rendered on. Named: each must exist and have a brief
    (`CompositionError` naming it); at most `MAX_SAMPLES`. Not named: the first
    `MAX_SAMPLES` slides with a brief, in deck order. None found → `CompositionError(
    "write slide briefs first: design directions are rendered on the deck's own slides")`.
    """
    raise NotImplementedError


def propose_design(
    ctx: ToolContext, store: ArtifactStore, args: ProposeDesignArgs
) -> tuple[ProposalRecord, list[str]]:
    """Offer design directions, each made concrete and rendered on real slides. In order:

    1. No bindings → `CompositionError("no designer is bound")`. `deck = store.load()`;
       `samples = sample_slides(deck, args.sample_slide_ids)`; `briefs` = the briefs of the
       deck's slides in deck order.
    2. `system_layer.make_designs(ctx.bindings.system, args.directions, briefs=briefs,
       attempts=ctx.system_attempts)` (in parallel).
    3. For every direction that produced a draft: one `DesignJob` per sample in
       `draft_system(draft)` with that draft's tokens; all jobs of all directions in **one**
       `designer.design_slides` call (in parallel), in direction order then sample order.
    4. Options, in direction order, for each direction with at least one clean sample:
       `ProposalOption(id=<next of A, B, C>, label=direction.name, text=direction.concept,
       design=draft, candidates=[CandidateSlide(slide=<the clean sample slide, with the
       deck slide's serves and marker>, replaces=<its slide id>) per clean sample])`.
    5. No option → `CompositionError` whose message lists, per direction, why it was
       dropped (`palette refused: <findings>` or `no sample came out clean: <findings>`).
    6. `record = ctx.proposals.create(thread_id, turn_id, artifact_id=store.artifact_id,
       summary=args.summary, options=..., now=ctx.clock())`; `ctx.ledger.record_proposal`.

    Returns the record and one line per direction: `- <option id>. <name>: rendered on
    <k> slide|slides` or `- <name>: dropped (<reason, clipped to FINDING_CLIP>)`. Nothing in
    the deck changes; nothing is stored in the design-system store.
    """
    raise NotImplementedError


def apply_design(
    ctx: ToolContext, store: ArtifactStore | None, args: ApplyDesignArgs
) -> tuple[DesignSystem, ChangeEntry, list[str]]:
    """Adopt a design as the deck's decided design system. In order:

    1. The draft. Option form: `record = ctx.proposals.load(args.proposal_id)`; dismissed →
       `ProposalStateError("the owner dismissed <id>")`; accepted with another option →
       `ProposalStateError("the owner chose <X> of <id>")`; unknown option →
       `ProposalStateError`; an option without `design` → `ProposalStateError("option <X>
       of <id> is not a design; use apply_option")`; the store is the proposal's artifact
       (`tools.resolve_artifact(ctx, record.artifact_id)`). Direction form:
       `system_layer.make_design(ctx.bindings.system, args.direction, briefs=<deck
       briefs>, attempts=ctx.system_attempts)`; no draft → `CompositionError("the palette
       for <name> could not be made to pass: <findings>")`; the store is `store`.
    2. `system = DesignSystemStore(ctx.engagement, base=ctx.base_tokens).add(draft,
       marker="decided", now=ctx.clock())`.
    3. Option form, proposal still open: `ctx.proposals.resolve(id, status="accepted",
       chosen=option, by="chat", now=ctx.clock())`.
    4. `entry = tools.apply_edit(ctx, store, edits.set_design_system(deck,
       system.ref(marker="decided")), "apply_design")`.
    5. `stale` = ids of slides whose status is `stale` after the change, in deck order.

    Returns `(system, entry, stale)`.
    """
    raise NotImplementedError


def propose_briefs(
    ctx: ToolContext, store: ArtifactStore | None, args: ProposeBriefsArgs
) -> ProposalRecord:
    """`propose` with candidate briefs. In order:

    1. Options get ids `A`, `B`, ... When any option has candidates: `store` must not be
       None (else `ArtifactNotFoundError` "there is no deck yet; create one with
       create_deck") and bindings must be set (`CompositionError`).
    2. Applicability first, before any model call: for each option with candidates, build
       placeholder `CandidateSlide`s (`Slide(id, intent=brief.intent, brief=brief)` with
       the input's `replaces` / `insert_at`) and run `edits.apply_candidate_slides(deck,
       ...)`; its `EditError` / `ValidationError` propagate (the tool reports them).
    3. Compose every candidate in the deck's current system, all options in one
       `designer.design_slides` call. Any candidate not clean → `CompositionError(
       "candidate slide <id> did not come out clean: <findings joined by '; '>")`.
    4. Each candidate slide is the clean designed slide with `composed` set (brief digest,
       the deck's system, the designer's model id), so it is fresh once applied.
    5. `ctx.proposals.create(...)` (artifact id: the store's, or None as Phase 1 decided
       it) and `ctx.ledger.record_proposal`. Returns the record.
    """
    raise NotImplementedError


def deck_briefs(deck: DeckArtifact) -> list[SlideBrief]:
    """The briefs of the deck's slides that have one, in deck order."""
    raise NotImplementedError


def result_line(result: DesignResult) -> str:
    """One finding-free line for logs: `<slide id>: clean|failed, <a> attempts,
    <seconds:.1f>s, <in>/<out> tokens`."""
    raise NotImplementedError
