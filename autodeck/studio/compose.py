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

from autodeck.studio import design, designer, edits, system_layer, views
from autodeck.studio.conversation import (
    OPTION_IDS,
    CandidateSlide,
    ProposalOption,
    ProposalRecord,
    SampleOutcome,
)
from autodeck.studio.design import DesignDraft, DesignSystem, DesignSystemStore
from autodeck.studio.designer import DesignJob, DesignResult
from autodeck.studio.errors import (
    ArtifactNotFoundError,
    CompositionError,
    EditError,
    NoChangeError,
    ProposalStateError,
)
from autodeck.studio.models import (
    MAX_FAILURE_FINDINGS,
    ChangeEntry,
    ComposedFrom,
    CompositionFailure,
    DeckArtifact,
    Slide,
    SlideBrief,
    composition_status,
    effective_system,
)
from autodeck.studio.store import ArtifactStore
from autodeck.studio.tool_args import ApplyDesignArgs, ProposeBriefsArgs, ProposeDesignArgs

if TYPE_CHECKING:
    from autodeck.studio.tools import ComposedSlide, ToolContext

NOTHING_TO_COMPOSE = (
    "Nothing to compose: every slide with a brief is designed in the current design system."
)
DEFAULT_SAMPLES = 2
"""How many slides each direction is rendered on when the lead names none: the opening and
the slide that best shows a figure or chart (`sample_slides`). Cost: every sample is one
designer run per direction."""
MAX_SAMPLES = 3
"""The most the lead may ask for, when the owner wants a fuller look."""
MAX_FINDINGS_IN_TEXT = 3
FINDING_CLIP = 160
DRAFT_SYSTEM_ID = "draft"
"""The id of the in-memory `DesignSystem` a sample is composed in before a design is
adopted (`draft_system`); never stored."""


def _clip(finding: str) -> str:
    return views.clip(views.flat(finding), FINDING_CLIP)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def select_slides(deck: DeckArtifact, slide_ids: Sequence[str] | None) -> list[str]:
    """The slides to compose, in deck order, without repeats.

    `None`: every slide whose `models.composition_status` (against
    `models.effective_system(deck)`) is `undesigned` or `stale` (failed slides are not
    retried unless named). Named: each must exist (`EditError` "deck <id> has no slide
    <s>") and have a brief (`CompositionError` "slide <s> has no brief; write one with
    set_slide_brief"); returned in deck order whatever their state (a fresh slide named
    explicitly is redesigned).
    """
    if slide_ids is None:
        system = effective_system(deck)
        return [
            s.id
            for s in deck.slides
            if composition_status(s, system).state in ("undesigned", "stale")
        ]
    known = set(deck.slide_ids())
    for sid in slide_ids:
        if sid not in known:
            raise EditError(f"deck {deck.id} has no slide {sid}")
        if deck.slide(sid).brief is None:
            raise CompositionError(f"slide {sid} has no brief; write one with set_slide_brief")
    wanted = set(slide_ids)
    return [s.id for s in deck.slides if s.id in wanted]


def draft_system(draft: DesignDraft) -> DesignSystem:
    """An unstored `DesignSystem` for composing samples in a draft: `id=DRAFT_SYSTEM_ID`,
    `version=1`, `marker="provisional"`, every other field from the draft, `created_at`
    None."""
    return DesignSystem(
        id=DRAFT_SYSTEM_ID,
        version=1,
        marker="provisional",
        name=draft.name,
        concept=draft.concept,
        rules=list(draft.rules),
        palette=draft.palette,
        roles=dict(draft.roles),
        background=draft.background,
        text_pairs=list(draft.text_pairs),
        made_by=draft.made_by,
        created_at=None,
    )


def jobs_for(
    deck: DeckArtifact, slide_ids: Sequence[str], system: DesignSystem, ctx: ToolContext
) -> list[DesignJob]:
    """One `DesignJob(slide_id, slide.brief, system, design.design_tokens(system.palette,
    ctx.base_tokens))` per id, in the given order. Every slide named has a brief."""
    tokens = design.design_tokens(system.palette, ctx.base_tokens)
    jobs: list[DesignJob] = []
    for sid in slide_ids:
        brief = deck.slide(sid).brief
        if brief is None:
            raise CompositionError(f"slide {sid} has no brief; write one with set_slide_brief")
        jobs.append(DesignJob(sid, brief, system, tokens))
    return jobs


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
    from autodeck.studio.tools import ComposedSlide

    if ctx.bindings is None:
        raise CompositionError("no designer is bound")
    deck = store.load()
    system = DesignSystemStore(ctx.engagement, base=ctx.base_tokens).for_deck(deck)
    ids = select_slides(deck, slide_ids)
    if not ids:
        return []
    results = designer.design_slides(
        ctx.bindings.designer,
        jobs_for(deck, ids, system, ctx),
        attempts=ctx.designer_attempts,
        max_parallel=ctx.designer_parallel,
    )
    composed: list[ComposedSlide] = []
    for sid, result in zip(ids, results, strict=True):
        current = store.load()
        findings: tuple[str, ...] = ()
        if result.clean and result.slide is not None:
            new = edits.apply_composition(
                current,
                sid,
                result.slide,
                ComposedFrom(
                    brief_digest=result.brief_digest,
                    system_id=system.id,
                    system_version=system.version,
                    model_id=result.model_id,
                ),
            )
            attempts = result.attempt_count
        else:
            findings = tuple(_clip(f) for f in result.findings[:MAX_FAILURE_FINDINGS])
            attempts = max(1, result.attempt_count)
            new = edits.record_compose_failure(
                current,
                sid,
                CompositionFailure(
                    brief_digest=result.brief_digest,
                    system_id=system.id,
                    system_version=system.version,
                    model_id=result.model_id,
                    attempts=attempts,
                    findings=list(findings),
                ),
            )
        entry_id: str | None = None
        try:
            entry = store.apply(
                new,
                instruction=ctx.instruction,
                thread_id=ctx.thread_id,
                layer="composition",
                model_id=result.model_id,
                now=ctx.clock(),
            )
        except NoChangeError:
            pass
        else:
            ctx.ledger.record_change(store.artifact_id, entry)
            entry_id = entry.id
        outcome = ComposedSlide(
            slide_id=sid,
            clean=result.clean and result.slide is not None,
            attempts=attempts,
            findings=findings,
            model_id=result.model_id,
            seconds=result.seconds,
            entry_id=entry_id,
            failed_earlier=sum(
                1
                for aid, earlier in ctx.ledger.composed
                if aid == store.artifact_id and earlier.slide_id == sid and not earlier.clean
            ),
        )
        ctx.ledger.record_composed(store.artifact_id, outcome)
        composed.append(outcome)
    return composed


def compose_text(results: Sequence[ComposedSlide]) -> str:
    """The tool result for `compose_slides`, lines joined by `\\n`:

    * `Composed <clean> of <n> slides.`
    * per slide, in order: `- <id>: clean in <a> attempt|attempts` (plus ` (it FAILED to
      compose <n> time|times earlier this turn: report that to the owner)` when the slide
      failed earlier in the same turn, `ComposedSlide.failed_earlier`) or
      `- <id>: failed after <a> attempt|attempts: <first MAX_FINDINGS_IN_TEXT findings
      joined by "; ">` (singular only for 1);
    * when any failed: `The previous design is kept for slides that failed; shorten their
      briefs or ask again.`
    `NOTHING_TO_COMPOSE` for no results.
    """
    if not results:
        return NOTHING_TO_COMPOSE
    clean = sum(1 for r in results if r.clean)
    lines = [f"Composed {clean} of {len(results)} slides."]
    for r in results:
        attempts = _plural(r.attempts, "attempt")
        if r.clean:
            line = f"- {r.slide_id}: clean in {attempts}"
            if r.failed_earlier:
                line += (
                    f" (it FAILED to compose {_plural(r.failed_earlier, 'time')} earlier "
                    "this turn: report that to the owner)"
                )
            lines.append(line)
        else:
            found = "; ".join(r.findings[:MAX_FINDINGS_IN_TEXT])
            lines.append(f"- {r.slide_id}: failed after {attempts}: {found}")
    if any(not r.clean for r in results):
        lines.append(
            "The previous design is kept for slides that failed; shorten their briefs or "
            "ask again."
        )
    return "\n".join(lines)


def _showing_power(brief: SlideBrief) -> tuple[int, int]:
    """How well a slide shows a design: a chart first, then the number of figures."""
    return (1 if brief.content.chart is not None else 0, len(brief.content.figures))


def sample_slides(deck: DeckArtifact, named: Sequence[str] | None) -> list[str]:
    """The slides a design proposal is rendered on. Named: each must exist and have a brief
    (`CompositionError` naming it); at most `MAX_SAMPLES`. Not named: `DEFAULT_SAMPLES`
    slides with a brief, chosen deterministically: the opening (the first slide with a
    brief) and, of the others, the one with the most showing power (a chart, then the most
    figures; the earliest wins a tie, so with no figures anywhere it is the next slide),
    returned in deck order. With one slide with a brief, just that one. None found →
    `CompositionError("write slide briefs first: design directions are rendered on the
    deck's own slides")`.
    """
    if named is not None:
        chosen: list[str] = []
        known = set(deck.slide_ids())
        for sid in named:
            if sid not in known:
                raise CompositionError(f"deck {deck.id} has no slide {sid} to render on")
            if deck.slide(sid).brief is None:
                raise CompositionError(
                    f"slide {sid} has no brief; write one with set_slide_brief"
                )
            if sid not in chosen:
                chosen.append(sid)
        return chosen[:MAX_SAMPLES]
    briefed = [s for s in deck.slides if s.brief is not None]
    if not briefed:
        raise CompositionError(
            "write slide briefs first: design directions are rendered on the deck's own slides"
        )
    picked = [briefed[0]]
    rest = briefed[1:]
    if rest and DEFAULT_SAMPLES > 1:
        best = rest[0]
        for slide in rest[1:]:
            assert slide.brief is not None and best.brief is not None
            if _showing_power(slide.brief) > _showing_power(best.brief):
                best = slide
        picked.append(best)
    return [s.id for s in picked][:DEFAULT_SAMPLES]


def palette_note(draft: DesignDraft) -> str:
    """One line when a palette needed more than one attempt, else "": `Palette for "<name>"
    needed <n> attempts; refused: <the findings of the refused attempts, clipped>`."""
    attempts = draft.palette_attempts
    if len(attempts) <= 1:
        return ""
    refused = "; ".join(
        f"attempt {a.attempt}: {'; '.join(a.findings)}" for a in attempts if not a.accepted
    )
    return _clip(
        f'Palette for "{draft.name}" needed {len(attempts)} attempts; refused {refused}'
    )


def _sample_outcomes(
    rendered: Sequence[DesignResult], samples: Sequence[str]
) -> list[SampleOutcome]:
    """One `SampleOutcome` per sample asked of a direction (a missing result counts as a
    failure with no attempts)."""
    by_slide = {r.slide_id: r for r in rendered}
    out: list[SampleOutcome] = []
    for sid in samples:
        r = by_slide.get(sid)
        if r is None:
            out.append(SampleOutcome(slide_id=sid, clean=False, attempts=0))
        elif r.clean and r.slide is not None:
            out.append(SampleOutcome(slide_id=sid, clean=True, attempts=r.attempt_count))
        else:
            out.append(
                SampleOutcome(
                    slide_id=sid,
                    clean=False,
                    attempts=r.attempt_count,
                    findings=[_clip(f) for f in r.findings[:MAX_FINDINGS_IN_TEXT]],
                )
            )
    return out


def direction_line(option_id: str, option: ProposalOption) -> str:
    """The tool-result line of a design option, in words the lead can repeat:
    `- <id>. <name>: <k> of <n> samples rendered` plus, per failed sample, `slide <s> could
    not be designed after <a> attempt|attempts: <findings>`, plus ` INCOMPLETE: tell the
    owner` when any failed, plus the palette note."""
    n = len(option.samples)
    k = sum(1 for o in option.samples if o.clean)
    text = f"- {option_id}. {option.label}: {k} of {_plural(n, 'sample')} rendered"
    failed = [o for o in option.samples if not o.clean]
    if failed:
        parts = []
        for o in failed:
            why = "; ".join(o.findings) or "no findings recorded"
            parts.append(
                f"slide {o.slide_id} could not be designed after "
                f"{_plural(o.attempts, 'attempt')}: {why}"
            )
        text += "; " + "; ".join(parts) + ". INCOMPLETE: say so when you present it"
    if option.design is not None:
        note = palette_note(option.design)
        if note:
            text += f". {note}"
    return text


def propose_design(
    ctx: ToolContext, store: ArtifactStore, args: ProposeDesignArgs
) -> tuple[ProposalRecord, list[str]]:
    """Offer design directions, each made concrete and rendered on real slides. In order:

    1. No bindings → `CompositionError("no designer is bound")`. `deck = store.load()`;
       `samples = sample_slides(deck, args.sample_slide_ids)` (two by default);
       `briefs` = the briefs of the
       deck's slides in deck order.
    2. `system_layer.make_designs(ctx.bindings.system, args.directions, briefs=briefs,
       attempts=ctx.system_attempts)` (in parallel).
    3. For every direction that produced a draft: one `DesignJob` per sample in
       `draft_system(draft)` with that draft's tokens; all jobs of all directions in **one**
       `designer.design_slides` call (in parallel), in direction order then sample order.
    4. Options, in direction order, for each direction with at least one clean sample:
       `ProposalOption(id=<next of A, B, C>, label=direction.name, text=direction.concept,
       design=draft, candidates=[CandidateSlide(slide=<the clean sample slide, with the
       deck slide's serves and marker>, replaces=<its slide id>) per clean sample],
       samples=<one `SampleOutcome` per sample asked: slide, clean, attempts, first
       findings of a failure>)`. The draft carries the system layer's `palette_attempts`.
    5. No option → `CompositionError` whose message lists, per direction, why it was
       dropped (`palette refused: <findings>` or `no sample came out clean: <findings>`).
    6. `record = ctx.proposals.create(thread_id, turn_id, artifact_id=store.artifact_id,
       summary=args.summary, options=..., now=ctx.clock())`; `ctx.ledger.record_proposal`.

    Returns the record and one line per direction: `direction_line` for an offered one (how
    many samples rendered, which failed and why, the palette note) or `- <name>: dropped
    (<reason, clipped to FINDING_CLIP>)`. Nothing in the deck changes; nothing is stored in
    the design-system store.

    A direction with no clean sample at all is **not offered**: the owner picks by looking,
    and an option with nothing to look at is a coin toss on a palette. It is dropped loudly:
    its line names why, so the lead tells the owner; if every direction is dropped the call
    fails with every reason. A direction with some clean samples is offered, with each
    failed sample recorded on the option (`ProposalOption.samples`).
    """
    if ctx.bindings is None:
        raise CompositionError("no designer is bound")
    deck = store.load()
    samples = sample_slides(deck, args.sample_slide_ids)
    drafts = system_layer.make_designs(
        ctx.bindings.system,
        args.directions,
        briefs=deck_briefs(deck),
        attempts=ctx.system_attempts,
    )
    jobs: list[DesignJob] = []
    owners: list[int] = []
    for i, made in enumerate(drafts):
        if made.draft is None:
            continue
        system = draft_system(made.draft)
        tokens = design.design_tokens(system.palette, ctx.base_tokens)
        for sid in samples:
            brief = deck.slide(sid).brief
            assert brief is not None
            jobs.append(DesignJob(sid, brief, system, tokens))
            owners.append(i)
    results = designer.design_slides(
        ctx.bindings.designer,
        jobs,
        attempts=ctx.designer_attempts,
        max_parallel=ctx.designer_parallel,
    )
    by_direction: dict[int, list[DesignResult]] = {}
    for i, result in zip(owners, results, strict=True):
        by_direction.setdefault(i, []).append(result)

    options: list[ProposalOption] = []
    lines: list[str] = []
    dropped: list[str] = []
    for i, made in enumerate(drafts):
        name = made.direction.name
        if made.draft is None:
            reason = f"palette refused: {'; '.join(made.findings)}"
            note = _attempt_count_note(made.attempts)
            if note:
                reason += f" ({note})"
        else:
            rendered = by_direction.get(i, [])
            clean = [r for r in rendered if r.clean and r.slide is not None]
            outcomes = _sample_outcomes(rendered, samples)
            if clean:
                option_id = OPTION_IDS[len(options)]
                candidates = []
                for r in clean:
                    assert r.slide is not None
                    original = deck.slide(r.slide_id)
                    sample = r.slide.model_copy(
                        update={"serves": list(original.serves), "marker": original.marker}
                    )
                    candidates.append(CandidateSlide(slide=sample, replaces=r.slide_id))
                options.append(
                    ProposalOption(
                        id=option_id,
                        label=name,
                        text=made.direction.concept,
                        design=made.draft,
                        candidates=candidates,
                        samples=outcomes,
                    )
                )
                lines.append(direction_line(option_id, options[-1]))
                continue
            found = "; ".join(
                f"slide {o.slide_id}: {'; '.join(o.findings) or 'no findings recorded'}"
                for o in outcomes
            )
            reason = f"no sample came out clean: {found}"
        dropped.append(f"{name}: {reason}")
        lines.append(f"- {name}: dropped ({_clip(reason)})")
    if not options:
        raise CompositionError("no design direction could be rendered. " + " | ".join(dropped))
    record = ctx.proposals.create(
        thread_id=ctx.thread_id,
        turn_id=ctx.turn_id,
        artifact_id=store.artifact_id,
        summary=args.summary,
        options=options,
        now=ctx.clock(),
    )
    ctx.ledger.record_proposal(record)
    return record, lines


def _attempt_count_note(attempts: int) -> str:
    return f"{attempts} palette attempts" if attempts > 1 else ""


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
    from autodeck.studio import tools

    open_proposal: ProposalRecord | None = None
    option_id = args.option_id
    if args.proposal_id is not None and option_id is not None:
        record = ctx.proposals.load(args.proposal_id)
        if record.status == "dismissed":
            raise ProposalStateError(f"the owner dismissed {record.id}")
        if record.status == "accepted" and record.chosen != option_id:
            raise ProposalStateError(f"the owner chose {record.chosen} of {record.id}")
        option = next((o for o in record.options if o.id == option_id), None)
        if option is None:
            raise ProposalStateError(f"proposal {record.id} has no option {option_id}")
        if option.design is None:
            raise ProposalStateError(
                f"option {option_id} of {record.id} is not a design; use apply_option"
            )
        draft = option.design
        target = tools.resolve_artifact(ctx, record.artifact_id)
        if record.status == "open":
            open_proposal = record
    else:
        if args.direction is None:
            raise CompositionError("give a proposal option or a direction")
        if ctx.bindings is None:
            raise CompositionError("no designer is bound")
        if store is None:
            raise ArtifactNotFoundError("there is no deck yet; create one with create_deck")
        target = store
        made = system_layer.make_design(
            ctx.bindings.system,
            args.direction,
            briefs=deck_briefs(target.load()),
            attempts=ctx.system_attempts,
        )
        if made.draft is None:
            raise CompositionError(
                f"the palette for {args.direction.name} could not be made to pass: "
                f"{'; '.join(made.findings)}"
            )
        draft = made.draft
    system = DesignSystemStore(ctx.engagement, base=ctx.base_tokens).add(
        draft, marker="decided", now=ctx.clock()
    )
    if open_proposal is not None and option_id is not None:
        ctx.proposals.resolve(
            open_proposal.id, status="accepted", chosen=option_id, by="chat", now=ctx.clock()
        )
    deck = target.load()
    entry = tools.apply_edit(
        ctx,
        target,
        edits.set_design_system(deck, system.ref(marker="decided")),
        "apply_design",
    )
    after = target.load()
    current = effective_system(after)
    stale = [s.id for s in after.slides if composition_status(s, current).state == "stale"]
    return system, entry, stale


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
    has_candidates = any(o.slides for o in args.options)
    deck: DeckArtifact | None = None
    system: DesignSystem | None = None
    results: list[DesignResult] = []
    if has_candidates:
        if store is None:
            raise ArtifactNotFoundError("there is no deck yet; create one with create_deck")
        if ctx.bindings is None:
            raise CompositionError("no designer is bound")
        deck = store.load()
        for option in args.options:
            if not option.slides:
                continue
            placeholders = [
                CandidateSlide(
                    slide=Slide(id=c.slide_id, intent=c.brief.intent, brief=c.brief),
                    replaces=c.replaces,
                    insert_at=c.insert_at,
                )
                for c in option.slides
            ]
            edits.apply_candidate_slides(deck, placeholders)
        system = DesignSystemStore(ctx.engagement, base=ctx.base_tokens).for_deck(deck)
        tokens = design.design_tokens(system.palette, ctx.base_tokens)
        jobs = [
            DesignJob(c.slide_id, c.brief, system, tokens)
            for option in args.options
            for c in option.slides
        ]
        results = designer.design_slides(
            ctx.bindings.designer,
            jobs,
            attempts=ctx.designer_attempts,
            max_parallel=ctx.designer_parallel,
        )
        for result in results:
            if not result.clean or result.slide is None:
                raise CompositionError(
                    f"candidate slide {result.slide_id} did not come out clean: "
                    f"{'; '.join(result.findings)}"
                )
    options: list[ProposalOption] = []
    position = 0
    for index, option in enumerate(args.options):
        candidates: list[CandidateSlide] = []
        for c in option.slides:
            result = results[position]
            position += 1
            assert result.slide is not None and system is not None
            slide = result.slide.model_copy(
                update={
                    "composed": ComposedFrom(
                        brief_digest=result.brief_digest,
                        system_id=system.id,
                        system_version=system.version,
                        model_id=result.model_id,
                    )
                }
            )
            candidates.append(
                CandidateSlide(slide=slide, replaces=c.replaces, insert_at=c.insert_at)
            )
        options.append(
            ProposalOption(
                id=OPTION_IDS[index],
                label=option.label,
                text=option.text,
                candidates=candidates,
            )
        )
    record = ctx.proposals.create(
        thread_id=ctx.thread_id,
        turn_id=ctx.turn_id,
        artifact_id=store.artifact_id if store is not None else None,
        summary=args.summary,
        options=options,
        now=ctx.clock(),
    )
    ctx.ledger.record_proposal(record)
    return record


def deck_briefs(deck: DeckArtifact) -> list[SlideBrief]:
    """The briefs of the deck's slides that have one, in deck order."""
    return [s.brief for s in deck.slides if s.brief is not None]


def result_line(result: DesignResult) -> str:
    """One finding-free line for logs: `<slide id>: clean|failed, <a> attempts,
    <seconds:.1f>s, <in>/<out> tokens`."""
    state = "clean" if result.clean else "failed"
    return (
        f"{result.slide_id}: {state}, {result.attempt_count} attempts, "
        f"{result.seconds:.1f}s, {result.input_tokens}/{result.output_tokens} tokens"
    )
