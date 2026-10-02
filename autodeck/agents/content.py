"""The content agent: one slide's blocks, with every citation resolved rather than composed.

`autodeck/agents/planner.py` is the closest sibling in register, and the parallel is
deliberate: a model may *propose* content, but the property the deck depends on is decided
in code, applied to the model's answer, never trusted from its prose. Here that property is
A1's whole content: **a citation is a real span in the document store, or it does not exist.**

## Citations are resolved, never composed

The model selects a verbatim quote and names the `doc_id` it came from. It does not, and
cannot, produce a page number, a bounding box or a SHA-256 — nothing in a language model's
weights knows where text sits on a PDF page. So the model's `doc_id`/`quote` pair is only
ever a **lookup key** into the evidence this module already assembled and showed it: the
curated claims from `claims.md` and the spans `HybridIndex` retrieved for this slide. A hit
resolves through `CachedClaim.to_citation` or `RetrievedSpan.to_citation` — the two
functions that already do this correctly elsewhere in the codebase — and *that* call is what
produces the real page, bbox and hash. A page number or hash the model types into its own
response is never read; there is no field for one to go in.

This module deliberately does not add a third way to build a `Citation`. `DocumentStore` is
the only place `resolve_quote` is called from directly (its own docstring says so), and both
blessed helpers already route through it — reusing them is what keeps that true rather than
merely stated.

## A quote that does not resolve is a failure, not a warning

If any citation a claim names — including a `Derivation` input's citation — fails to
resolve, the **whole block is dropped**, not just the bad citation. `prompts/content.md` is
explicit that a claim with an uncitable number is not a lesser claim, it is not a claim, and
falling back to writing the sentence without its citation would manufacture the exact
uncited assertion A1 exists to forbid. Every rejection is recorded in
`ContentResult.rejections` with the reason, because a build that silently drops a slide's
best evidence and says nothing is worse than one that fails loudly.

`§6.3` forbids citing a figure's VLM description or any other non-citable span. Nothing
special has to be written here to enforce that: `RetrievedSpan.to_citation` already checks
`citable` before anything else and raises `UncitableSourceError` with that reason named, and
this module's job is only to not swallow it — the error becomes a rejection with the
resolver's own message, not a generic "not found".

## Speaker notes are blocks, not a cheaper cousin

`ContentDraft.speaker_notes` is a list of the same `ProposedBlock` shape as the slide face,
run through the exact same resolution function. There is no separate, looser path for notes
— `prompts/content.md`'s point that notes are "where this goes wrong" would be undefended by
a content.py that trusted them more than the slide face.

## Budgets are checked before blocks are returned

`autodeck.design.components.catalog.check_overflow` is the deterministic, pre-render gate
§6.7 requires. This module calls it, once, over every face block's text grouped by slot,
after citations have resolved — an overflowing block is dropped and reported exactly like an
unresolved citation, never rendered small to make it fit. Where the catalog does not yet
cover a component (Phase 3a's registry is still growing — see `catalog.py`'s own docstring),
budgets are skipped and that gap is reported rather than silently assumed clean.

`check_overflow` reports two different kinds of finding in one list (its own docstring says
so): content the writer wrote that does not fit, and a required slot the writer wrote
nothing for. The first is what A1/§6.7 exist to catch and belongs in `rejections` next to a
dropped citation — both are the writer having produced something wrong. The second is not
that: nothing was dropped, because nothing was ever written, and a caller counting
`rejections` to mean "the writer's output was rejected" would be wrong to include it. This
module splits them with `is_missing_slot_finding` and keeps the second kind in its own
`ContentResult.incomplete_slots`, so a citation-resolution failure — the reason this file's
seven citation tests exist — is never diluted by an unrelated slot the fixture never meant to
fill (task 3a's component fan-out, `6f2c3ae`, found this the hard way: registering
`closing_cta` et al. made `check_overflow` start running for slides that only ever filled one
slot, and every one of those slides' "no rejections" assertions broke on missing-slot noise
until the split below existed).

## What this module does not do

It does not decide whether a claim is *true* — that is A3, and `autodeck/audit/verdicts.py`
is where the independent verdict is applied, never here. It does not lint numerals or
framing — `autodeck/audit/numeric_linter.py` and `framing_linter.py` are the guardrail
modules that own A2 and A5, and this module structurally *enables* both (every number is
either verbatim in a resolved citation or declared as a `Derivation`; framing blocks carry
no citation at all) without re-implementing either check. Duplicating a linter here would
be a second copy of an invariant to keep in sync, which is exactly the failure mode
`autodeck/audit/` exists to prevent.

Owning phase: 2b (task 2b.4). Sonnet tier — implementation against `prompts/content.md`,
which Opus wrote; this module is the plumbing that keeps the prompt's promises honest.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, get_type_hints

from pydantic import BaseModel, ConfigDict, Field

from autodeck.design.components.catalog import (
    BlockValue,
    UnknownComponentError,
    check_overflow,
    is_missing_slot_finding,
    missing_slot_finding,
    registration,
    render_budgets,
)
from autodeck.design.headers.prompt import render_for_prompt, resolve_profile
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.document_store import DocumentStore, IngestError
from autodeck.ir.models import (
    GEOMETRIES,
    Block,
    ChartKind,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    DeckBrief,
    Derivation,
    DerivationInput,
    DiagramSpec,
    KeyMessage,
    LabelFraming,
    LabelReason,
    OpenRisk,
    ProcessFlowSpec,
    ProcessStep,
    Slide,
)
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import HybridIndex, RetrievedSpan, search, tokenize

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/content.md")

#: Curated claims and retrieved spans shown to the writer per slide. One retrieval call per
#: slide (deterministic, not a provider call) regardless of how many messages it serves —
#: the query is built once from the slide's intent and served messages together.
CLAIM_LIMIT = 8
SPAN_LIMIT = 10

#: Words carrying no topical signal, for the crude curated-claim overlap match below. Kept
#: as prose for the same reason `evidence_gap.py`'s own copy is: a list this short is easier
#: to read and extend than a literal.
_STOPWORD_TEXT = (
    "a an the is are was were be been being of to in on for by with and or but that "
    "this it its as at from we our their has have had can could will would should "
    "more most than then so if not no"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


class ContentError(RuntimeError):
    """The content agent cannot proceed at all — a missing prompt file, an unusable slide."""


class CitationResolutionError(IngestError):
    """A proposed citation could not be resolved to a real span the writer was shown.

    Raised internally and always caught: it is how `_resolve_citation` reports the specific
    reason (uncitable source, quote not found, doc not among the evidence shown) up to the
    caller that decides to drop a block, never allowed to propagate out of this module.
    """


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


class ProposedCitation(BaseModel):
    """A citation as a model can actually produce one: a lookup key, not a resolved span.

    `doc_id` and `quote` are the only fields, because they are the only two things a model
    can know — which document, and which sentence in it. Page, bbox and hash are computed by
    `_resolve_citation` from the document store and never taken from the model.
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    quote: str = Field(
        min_length=1,
        description=(
            "Copied VERBATIM, character for character, from a span shown in the evidence "
            "below. Never paraphrased, never tidied — an edited quote stops resolving, "
            "which is correct behaviour, not a bug to route around."
        ),
    )


class ProposedDerivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    citation: ProposedCitation


class ProposedDerivation(BaseModel):
    """A2: a computed number, shown working. See `prompts/content.md`'s A2 section."""

    model_config = ConfigDict(extra="forbid")

    formula: str = Field(min_length=1, description="e.g. '(a - b) / b * 100'.")
    inputs: dict[str, ProposedDerivationInput] = Field(min_length=1)
    result: float
    unit: str = Field(default="", description="Unit of `result`; '' for a bare ratio.")


class ProposedClaim(BaseModel):
    """A factual assertion, with the evidence it rests on. A1's shape, pre-resolution."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    citations: list[ProposedCitation] = Field(min_length=1)
    derivation: ProposedDerivation | None = None


class ProposedChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    values: list[float] = Field(min_length=1)


class ProposedChart(BaseModel):
    """D10: a chart is a dense set of factual assertions, so it carries its own citations."""

    model_config = ConfigDict(extra="forbid")

    chart_type: ChartKind
    title: str = ""
    categories: list[str] = Field(min_length=1)
    series: list[ProposedChartSeries] = Field(min_length=1)
    x_axis_label: str = ""
    y_axis_label: str = ""
    source_citations: list[ProposedCitation] = Field(min_length=1)


BlockKindDraft = Literal["claim", "framing", "chart", "section_header", "diagram"]
"""The block kinds the writer authors. `diagram` was added by B37: the outline could
already assign `framework_diagram` and `timeline`, and nothing could fill them, so no
pipeline-built deck could carry the native diagram GATE 3 requires. `figure` and `icon`
remain out of scope here — icons are art direction's (`AssignIcons`, B36)."""


class ProposedStep(BaseModel):
    """One step of a proposed process flow (B37). Flat and fully required, per B26.

    `status` says which of the two A1 cases this label is, before anything else: a label
    that asserts a fact carries `claim`; a label that names a stage, party, artefact,
    category or question carries `framing_reason`. Exactly one is meaningful for the status
    given — the other must be empty (`claim: null`, `framing_reason: ""`).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    label: str = Field(min_length=1, description="At most four words. What the box says.")
    transition: str = Field(
        default="", description="Label on the arrow leaving this step, or ''. Never decor."
    )
    status: Literal["claim", "framing"]
    claim: ProposedClaim | None = Field(default=None, description="For status='claim'.")
    framing_reason: LabelReason | Literal[""] = Field(
        default="", description="For status='framing'. '' otherwise."
    )


class ProposedDiagram(BaseModel):
    """A proposed diagram (B37). **process_flow only in this round** — the geometry the
    `timeline` component requires and the plan's own example ("how the algorithm works"
    becomes a slide). `two_by_two` and `layered_stack` follow once this one is proven live;
    each adds schema the B26 flat-schema rule makes costly to get wrong.

    `relationship` precedes the payload for the reason `DiagramSpec` gives: the model states
    what the points have to do with each other before it is offered a shape.
    """

    model_config = ConfigDict(extra="forbid")

    relationship: Literal["sequence"]
    title: str = Field(default="", description="Uncited framing; '' for none.")
    steps: list[ProposedStep] = Field(min_length=2, max_length=6)


class ProposedBlock(BaseModel):
    """One block, still carrying the model's citations rather than the resolved ones.

    **Every field that matters is required and non-nullable** (B26): a `list[X] | None`
    field arrives silently absent from Gemini on some fraction of calls, with no error, and
    the slide reads perfectly in the model's `reply`-shaped fields while the structure that
    actually becomes the deck is empty. `text`, `claim` and `chart` are mutually exclusive by
    `kind`, mirroring `autodeck.ir.models.Block`'s own validator — the same shape, checked
    twice, is cheaper than a proposed block that reaches the IR looking valid and is not.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: BlockKindDraft
    slot: str = Field(min_length=1)
    text: str = Field(
        default="", description="For kind='framing' or 'section_header'. '' otherwise."
    )
    claim: ProposedClaim | None = Field(default=None, description="For kind='claim'.")
    chart: ProposedChart | None = Field(default=None, description="For kind='chart'.")
    diagram: ProposedDiagram | None = Field(default=None, description="For kind='diagram'.")


class ContentDraft(BaseModel):
    """One slide's worth of writing, before any citation has been checked.

    `blocks` and `speaker_notes` are both required, non-nullable lists (B26) — the exact
    field shape that went missing from live planner responses before `PlannerAction` made
    the same fix. `speaker_notes` may legitimately be empty (not every slide needs a spoken
    caveat beyond its face), so there is no `min_length` on it; `blocks` may not, because a
    slide with no face content is not a slide.
    """

    model_config = ConfigDict(extra="forbid")

    blocks: list[ProposedBlock] = Field(min_length=1)
    speaker_notes: list[ProposedBlock] = Field(default_factory=list)


class ContentModel(Protocol):
    """What the agent needs from a provider, bound to the `content` role in config."""

    def complete_structured(
        self,
        prompt: str,
        response_model: type[ContentDraft],
        *,
        system: str | None = None,
    ) -> ContentDraft: ...  # pragma: no cover — protocol shape only


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class ContentResult:
    """What one slide-writing call produced, and everything that was rejected on the way.

    `rejections` is not an afterthought: a build that drops the writer's best evidence for a
    slide and says nothing about it teaches nobody anything. Every drop — an unresolved
    quote, an overflowing block, an unknown slot — is named here with its reason. It is
    deliberately *not* where a missing required slot goes (see `incomplete_slots`): nothing
    was dropped there, so filing it as a rejection would tell a caller counting rejections
    that the writer produced something bad when it produced nothing at all.
    """

    blocks: list[Block] = field(default_factory=list)
    speaker_notes: list[Block] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    incomplete_slots: list[str] = field(default_factory=list)
    """A required slot of `component` that no block filled, one entry per slot
    (`catalog.check_overflow`'s missing-slot findings — see `is_missing_slot_finding`). Kept
    apart from `rejections` because it names an absence, not a failure of something the
    writer wrote: a slide can legitimately be mid-fixture, mid-test or mid-draft with a slot
    still blank, and that is a different situation from a citation that failed to resolve or
    a block that had to be dropped for overflowing its budget. Still worth naming, because a
    real build render cannot proceed with a required slot empty — just not worth conflating
    with the rejections that mean the writer's own output was wrong."""
    budgets_checked: bool = True
    """False when the catalog has no entry yet for this slide's component (Phase 3a is
    still growing the registry — see `catalog.py`). Overflow cannot be caught for a
    component with no declared slots, and that gap is named rather than assumed clean."""


# ---------------------------------------------------------------------------
# Evidence gathering — deterministic, one retrieval call per slide
# ---------------------------------------------------------------------------


def _gather_claims(query: str, claims: Sequence[CachedClaim]) -> list[CachedClaim]:
    """Curated claims sharing meaningful vocabulary with the slide's own text.

    Deliberately crude, matching `evidence_gap.py`'s own private matcher: `claims.md` is a
    curated library of tens of entries, not a corpus, so recall matters far more than
    precision here.
    """
    wanted = set(tokenize(query)) - _STOPWORDS
    if not wanted:
        return []
    scored = [
        (len(wanted & (set(tokenize(c.claim)) | set(tokenize(c.quote)))), c) for c in claims
    ]
    return [c for overlap, c in sorted(scored, key=lambda p: -p[0]) if overlap >= 2][
        :CLAIM_LIMIT
    ]


def _gather_spans(query: str, index: HybridIndex) -> list[RetrievedSpan]:
    """Retrieved spans for the slide, citable and non-citable alike.

    Non-citable hits (figure descriptions, page furniture) are kept rather than filtered:
    `prompts/content.md` says descriptions are retrievable for finding the right page even
    though they can never be cited, and a writer that never sees one cannot be shown the
    resolver refusing to cite it. `_render_evidence` marks each one plainly.
    """
    return search(index, query, limit=SPAN_LIMIT, citable_only=False)


def _slide_query(slide: Slide, messages: Sequence[KeyMessage]) -> str:
    parts = [slide.intent or "", *(m.text for m in messages)]
    return " ".join(part for part in parts if part)


def _render_evidence(claims: Sequence[CachedClaim], spans: Sequence[RetrievedSpan]) -> str:
    lines: list[str] = []
    for claim in claims:
        lines.append(f"[claims.md · {claim.doc_id} p.{claim.page}] {claim.claim}")
        lines.append(f"    quote: {claim.quote!r}")
        if claim.note:
            lines.append(f"    note: {claim.note}")
    for span in spans:
        tag = "citable" if span.citable else "NOT CITABLE — metadata only, see §6.3"
        text = " ".join(span.text.split())
        lines.append(f"[corpus · {span.doc_id} p.{span.page} · {tag}] {text}")
    return "\n".join(lines) if lines else "(nothing retrieved for this slide)"


# ---------------------------------------------------------------------------
# Citation resolution — the one path, reused rather than rewritten
# ---------------------------------------------------------------------------


def _resolve_citation(
    proposed: ProposedCitation,
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
    retrieved_by: Literal["writer"] = "writer",
) -> Citation:
    """Turn a model-named (doc_id, quote) into the real `Citation` it points at, or fail.

    Looks the pair up among exactly the evidence this slide was shown — a curated claim by
    its own (doc_id, quote), otherwise a retrieved span by `doc_id` — and calls that
    object's own `to_citation`. Nothing here calls `DocumentStore.resolve_quote` directly:
    that would be the third citation path the task explicitly asks not to write, and it
    would lose `RetrievedSpan.to_citation`'s citability check and its element-scoped search.

    Raises:
        CitationResolutionError: the pair matches nothing shown, or matches something that
            will not resolve (an uncited figure description, an edited quote).
    """
    for claim in claims:
        if claim.doc_id == proposed.doc_id and claim.quote == proposed.quote:
            try:
                return claim.to_citation(store=store, retrieved_by=retrieved_by)
            except IngestError as exc:
                raise CitationResolutionError(
                    f"cached claim for {proposed.doc_id!r} no longer resolves: {exc}"
                ) from exc

    candidates = [span for span in spans if span.doc_id == proposed.doc_id]
    if not candidates:
        raise CitationResolutionError(
            f"{proposed.doc_id!r} was not among the evidence shown for this slide (neither "
            "a curated claim nor a retrieved span). A citation names evidence actually "
            "presented, never a document the writer merely recalls."
        )

    last_error: IngestError | None = None
    for span in candidates:
        try:
            return span.to_citation(store, quote=proposed.quote, retrieved_by=retrieved_by)
        except IngestError as exc:
            last_error = exc
            continue

    assert last_error is not None
    raise CitationResolutionError(
        f"quote for {proposed.doc_id!r} did not resolve against any evidence span shown "
        f"for this slide: {last_error}"
    ) from last_error


def _resolve_claim(
    proposed: ProposedClaim,
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
) -> Claim:
    """Resolve a claim's citations and derivation, or raise so the caller drops the block.

    All citations are resolved through the same lookup (`_resolve_citation`) before the
    `Claim` is ever constructed, and the pydantic model is the last check rather than the
    first — a defensive backstop, not the mechanism A1 relies on.

    A derivation input's citation is resolved the same way and folded into the claim's own
    `citations` if it named a (doc_id, quote) the claim had not already listed — a citation
    that has already resolved through this exact function is not a citation being composed,
    it is bookkeeping the model should not have to get right by hand.
    """
    resolved: dict[tuple[str, str], Citation] = {}
    for item in proposed.citations:
        citation = _resolve_citation(item, store=store, claims=claims, spans=spans)
        resolved.setdefault((item.doc_id, item.quote), citation)

    derivation: Derivation | None = None
    if proposed.derivation is not None:
        inputs: dict[str, DerivationInput] = {}
        for name, item in proposed.derivation.inputs.items():
            key = (item.citation.doc_id, item.citation.quote)
            if key not in resolved:
                resolved[key] = _resolve_citation(
                    item.citation, store=store, claims=claims, spans=spans
                )
            inputs[name] = DerivationInput(value=item.value, citation=resolved[key])
        derivation = Derivation(
            formula=proposed.derivation.formula,
            inputs=inputs,
            result=proposed.derivation.result,
            unit=proposed.derivation.unit,
        )

    return Claim(
        text=proposed.text,
        citations=list(resolved.values()),
        derivation=derivation,
    )


def _resolve_chart(
    proposed: ProposedChart,
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
) -> ChartSpec:
    citations = [
        _resolve_citation(item, store=store, claims=claims, spans=spans)
        for item in proposed.source_citations
    ]
    return ChartSpec(
        chart_type=proposed.chart_type,
        title=proposed.title or None,
        categories=proposed.categories,
        series=[ChartSeries(name=s.name, values=s.values) for s in proposed.series],
        x_axis_label=proposed.x_axis_label or None,
        y_axis_label=proposed.y_axis_label or None,
        source_citations=citations,
    )


def _resolve_diagram(
    proposed: ProposedDiagram,
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
) -> DiagramSpec:
    """Resolve a proposed process flow into a `DiagramSpec`, or raise so the block drops.

    Each step is exactly one of the two A1 cases, and `status` says which before the
    payload is read:
      - `status="claim"`: `claim` must be set and `framing_reason` empty. The claim resolves
        through `_resolve_claim` — the same path as a claim block, no second resolver — and
        becomes the node's `claim`.
      - `status="framing"`: `framing_reason` must be a `LabelReason` and `claim` must be
        None; it becomes `LabelFraming(reason=...)`.

    **Any step failing drops the whole diagram**, never just the step: a flow missing a step
    is a different sequence, which is a changed fact, not a smaller one. The error names the
    step so the rejection says where. The IR's own validators (contiguous orders, label
    budget, claim/framing exclusivity) are the last check; their errors drop the block like
    any other (`_resolve_block` catches them).

    The label word budget is the geometry's (`GEOMETRIES["process_flow"].max_label_words`),
    enforced by `DiagramSpec` at construction — the one place it is checked.
    """
    steps: list[ProcessStep] = []
    for step in proposed.steps:
        try:
            steps.append(_resolve_step(step, store=store, claims=claims, spans=spans))
        except (CitationResolutionError, IngestError) as exc:
            raise CitationResolutionError(
                f"diagram step {step.id!r} (order {step.order}) dropped the whole diagram: "
                f"{exc}"
            ) from exc
    return DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        title=proposed.title or None,
        process_flow=ProcessFlowSpec(steps=steps),
    )


def _resolve_step(
    step: ProposedStep,
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
) -> ProcessStep:
    """One proposed step into a `ProcessStep`, with `status` and payload checked to agree."""
    resolved_claim: Claim | None = None
    framing: LabelFraming | None = None
    if step.status == "claim":
        if step.claim is None:
            raise CitationResolutionError("status='claim' with no claim payload")
        if step.framing_reason != "":
            raise CitationResolutionError(
                f"status='claim' but framing_reason={step.framing_reason!r}; a label is a "
                "claim or framing, never both"
            )
        resolved_claim = _resolve_claim(step.claim, store=store, claims=claims, spans=spans)
    else:
        if step.framing_reason == "":
            raise CitationResolutionError("status='framing' with no framing_reason")
        if step.claim is not None:
            raise CitationResolutionError(
                "status='framing' but a claim was supplied; a label is a claim or framing, "
                "never both"
            )
        framing = LabelFraming(reason=step.framing_reason)
    return ProcessStep(
        id=step.id,
        order=step.order,
        label=step.label,
        transition=step.transition or None,
        claim=resolved_claim,
        framing=framing,
    )


def _resolve_block(
    proposed: ProposedBlock,
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
    location: str,
    rejections: list[str],
) -> Block | None:
    """Resolve one proposed block, or record why it was dropped and return None.

    A quote that does not resolve is a failure, not a warning (task 2b.4): the whole block
    is dropped rather than falling back to an uncited version of it, and the *reason* is
    kept rather than the block silently disappearing.
    """
    try:
        if proposed.kind == "claim":
            if proposed.claim is None:
                raise CitationResolutionError("kind='claim' with no claim payload")
            claim = _resolve_claim(proposed.claim, store=store, claims=claims, spans=spans)
            return Block(id=proposed.id, kind="claim", slot=proposed.slot, claim=claim)
        if proposed.kind == "chart":
            if proposed.chart is None:
                raise CitationResolutionError("kind='chart' with no chart payload")
            chart = _resolve_chart(proposed.chart, store=store, claims=claims, spans=spans)
            return Block(id=proposed.id, kind="chart", slot=proposed.slot, chart=chart)
        if proposed.kind == "diagram":
            if proposed.diagram is None:
                raise CitationResolutionError("kind='diagram' with no diagram payload")
            diagram = _resolve_diagram(
                proposed.diagram, store=store, claims=claims, spans=spans
            )
            return Block(id=proposed.id, kind="diagram", slot=proposed.slot, diagram=diagram)
        # framing / section_header: plain text, no citation to resolve (A5's exemption).
        if not proposed.text.strip():
            raise CitationResolutionError(f"kind={proposed.kind!r} with no text")
        return Block(id=proposed.id, kind=proposed.kind, slot=proposed.slot, text=proposed.text)
    except (CitationResolutionError, IngestError) as exc:
        rejections.append(f"{location} block {proposed.id!r} ({proposed.slot}): {exc}")
        return None
    except Exception as exc:  # pydantic's own validators, as a defensive backstop
        rejections.append(
            f"{location} block {proposed.id!r} ({proposed.slot}): "
            f"failed IR validation after resolution: {exc}"
        )
        return None


# ---------------------------------------------------------------------------
# Budgets — checked before blocks are returned
# ---------------------------------------------------------------------------


def _excerpt(text: str, width: int = 60) -> str:
    """The first `width` characters of a sentence, for naming a dropped block."""
    collapsed = " ".join(text.split())
    return f"“{collapsed[:width]}{'…' if len(collapsed) > width else ''}”"


def _block_text(block: Block) -> str:
    if block.claim is not None:
        return block.claim.text
    return block.text or ""


def _diagram_slots(component: str) -> list[str]:
    """The slots of `component`'s content type that take a `DiagramSpec` (B37).

    The catalog's text table declares no diagram slot — a diagram's boxes depend on node
    count — so what the component needs is read off its content dataclass, the same
    classification the render stage's `adapt_slide` fills from. Empty for a component the
    catalog does not know.
    """
    try:
        content_type = registration(component).content_type
    except UnknownComponentError:
        return []
    hints = get_type_hints(content_type)
    return [f.name for f in dataclasses.fields(content_type) if hints[f.name] is DiagramSpec]


def _chart_slots(component: str) -> list[str]:
    """The slots of `component`'s content type that take a `ChartSpec`.

    Like `_diagram_slots`, a chart's size depends on data dimensions and cannot be predicted
    from a text budget, so the catalog declares no chart slot. This function reads the
    component's content dataclass to find which slots require a chart.
    Empty for a component the catalog does not know.
    """
    try:
        content_type = registration(component).content_type
    except UnknownComponentError:
        return []
    hints = get_type_hints(content_type)
    return [f.name for f in dataclasses.fields(content_type) if hints[f.name] is ChartSpec]


def _check_budgets(
    blocks: list[Block], *, component: str, tokens: DesignTokens
) -> tuple[list[Block], list[str], list[str], bool]:
    """Drop any face block whose slot overflows its budget. Chart and diagram blocks are
    exempt — the catalog declares text slots, not chart or diagram geometry. A diagram's
    labels are budgeted by its geometry (`GEOMETRIES[kind].max_label_words`), which
    `DiagramSpec` enforces when the block is built, so an over-long label has already
    dropped its block (as an IR-validation rejection) by the time this runs.

    A component that takes a diagram (`_diagram_slots`) or a chart (`_chart_slots`) but
    received none is reported in `incomplete_slots`, in the catalog's own missing-slot form:
    the catalog's text table cannot see an absent diagram or chart, and the render stage
    would otherwise be the first to notice.

    `check_overflow` reports overflow and missing-required-slot findings in one list; they
    are split here (`is_missing_slot_finding`) because they mean different things to a
    caller — see `ContentResult.rejections` and `.incomplete_slots`. Only an overflow finding
    ever drops a block: a missing-slot finding has no block to drop, since none was written.

    Returns `(kept, rejections, incomplete_slots, budgets_checked)`.
    """
    by_slot: dict[str, list[Block]] = {}
    for block in blocks:
        if block.chart is not None or block.diagram is not None:
            continue
        by_slot.setdefault(block.slot, []).append(block)

    try:
        content: dict[str, BlockValue] = {
            slot: [_block_text(b) for b in items] if len(items) > 1 else _block_text(items[0])
            for slot, items in by_slot.items()
        }
        findings = check_overflow(content, component, tokens)
    except UnknownComponentError:
        return blocks, [], [], False

    overflow_findings = [f for f in findings if not is_missing_slot_finding(f)]
    incomplete_slots = [f for f in findings if is_missing_slot_finding(f)]
    filled_diagrams = {b.slot for b in blocks if b.diagram is not None}
    incomplete_slots.extend(
        missing_slot_finding(component, slot)
        for slot in _diagram_slots(component)
        if slot not in filled_diagrams
    )
    filled_charts = {b.slot for b in blocks if b.chart is not None}
    incomplete_slots.extend(
        missing_slot_finding(component, slot)
        for slot in _chart_slots(component)
        if slot not in filled_charts
    )
    if not overflow_findings:
        return blocks, [], incomplete_slots, True

    findings_by_slot: dict[str, list[str]] = {}
    for finding in overflow_findings:
        slot = finding.split(":", 1)[0].rsplit(".", 1)[-1].split("[")[0]
        findings_by_slot.setdefault(slot, []).append(finding)

    # One rejection per block that is actually dropped. A finding is per *slot*, and a slot
    # can hold several blocks, all of which go — counting findings would report one drop
    # where two sentences vanished, and the writer would have no way to know which.
    rejections: list[str] = []
    kept: list[Block] = []
    for block in blocks:
        if (
            block.chart is not None
            or block.diagram is not None
            or block.slot not in findings_by_slot
        ):
            kept.append(block)
            continue
        rejections.append(
            f"dropped block {block.id!r} (slot {block.slot!r}): "
            f"{_excerpt(_block_text(block))} — overflow: "
            f"{'; '.join(findings_by_slot[block.slot])}"
        )
    return kept, rejections, incomplete_slots, True


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _a8_context(slide: Slide, brief: DeckBrief) -> str:
    """A8's ceiling: the writer cannot hedge a gap it was never told about.

    Every served message's evidence status is shown, and any `open_risk` recorded against
    one goes in verbatim — the risk was accepted by a named person for a reason, and this is
    where that reason reaches the slide it applies to.
    """
    messages = [brief.message(mid) for mid in slide.message_ids]
    messages = [m for m in messages if m is not None]
    if not messages:
        return "(this slide serves no brief key message)"

    lines: list[str] = []
    for message in messages:
        lines.append(f"- {message.id}: {message.text} [{message.evidence_status}]")
        if message.evidence_status in ("thin", "unsupported"):
            lines.append(
                "    weak evidence — do not write past this. Name the gap or hedge to it "
                "explicitly; do not use 'proves'/'shows'/'demonstrates' for it."
            )
        if message.probe_notes:
            lines.append(f"    probe notes: {message.probe_notes}")
    risks: list[OpenRisk] = [r for r in brief.open_risks if r.message_id in slide.message_ids]
    if risks:
        lines.append("open risks accepted against these messages — hedge to them by name:")
        for risk in risks:
            lines.append(
                f"  - {risk.message_id}: {risk.description} (accepted by {risk.accepted_by})"
            )
            if risk.mitigation:
                lines.append(f"      mitigation: {risk.mitigation}")
    return "\n".join(lines)


def _content_prompt(
    slide: Slide,
    brief: DeckBrief,
    context: AssembledContext,
    *,
    budgets: str,
    evidence: str,
) -> str:
    header_profile = resolve_profile(context.header_profile, brief.header_style)
    parts = [
        "# Curated knowledge for this build\n\n" + context.to_prompt_context(),
        "# This slide\n\n"
        f"component: {slide.component}\n"
        f"narrative_role: {slide.narrative_role}\n"
        f"intent: {slide.intent or '(none recorded)'}",
        "# Header style profile for this deck (D12 — phrasing only, never a citation "
        "exemption)\n\n" + render_for_prompt(header_profile),
        "# Key messages this slide serves, and what the brief already knows about them "
        "(A8)\n\n" + _a8_context(slide, brief),
        "# Text budgets for this component's slots (§6.7 — hard constraints)\n\n" + budgets,
        "# Evidence available for this slide — curated claims and retrieval\n\n" + evidence,
    ]
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def write_slide(
    slide: Slide,
    brief: DeckBrief,
    context: AssembledContext,
    *,
    store: DocumentStore,
    index: HybridIndex,
    claims: Sequence[CachedClaim],
    tokens: DesignTokens,
    model: ContentModel,
    prompt_path: Path = PROMPT_PATH,
) -> ContentResult:
    """Write one slide's blocks and speaker notes, every citation resolved through the store.

    One provider call. Retrieval (`_gather_claims`/`_gather_spans`) is deterministic and
    does not count against the `content` role's daily quota (B25) — only the structured
    generation call below does.

    Raises:
        ContentError: the prompt file is missing, or the slide has an empty `intent`/
            `component` that makes it unbuildable — never for a rejected block, which is
            reported in the result instead of raised.
    """
    system = _read_prompt(prompt_path)

    served = [m for m in (brief.message(mid) for mid in slide.message_ids) if m is not None]
    query = _slide_query(slide, served)
    matched_claims = _gather_claims(query, claims)
    matched_spans = _gather_spans(query, index)
    evidence_text = _render_evidence(matched_claims, matched_spans)
    budgets_text = _slide_budgets(slide.component, tokens)

    prompt = _content_prompt(
        slide, brief, context, budgets=budgets_text, evidence=evidence_text
    )

    try:
        draft = model.complete_structured(prompt, ContentDraft, system=system)
    except Exception as exc:
        raise ContentError(
            f"content generation failed for slide {slide.id!r}: {type(exc).__name__}: {exc}"
        ) from exc

    rejections: list[str] = []
    blocks = _resolve_blocks(
        draft.blocks,
        store=store,
        claims=matched_claims,
        spans=matched_spans,
        location=f"slide {slide.id} face",
        rejections=rejections,
    )
    speaker_notes = _resolve_blocks(
        draft.speaker_notes,
        store=store,
        claims=matched_claims,
        spans=matched_spans,
        location=f"slide {slide.id} notes",
        rejections=rejections,
    )

    kept, overflow_rejections, incomplete_slots, budgets_checked = _check_budgets(
        blocks, component=slide.component, tokens=tokens
    )
    rejections.extend(overflow_rejections)

    return ContentResult(
        blocks=kept,
        speaker_notes=speaker_notes,
        rejections=rejections,
        incomplete_slots=incomplete_slots,
        budgets_checked=budgets_checked,
    )


def _resolve_blocks(
    proposed: Sequence[ProposedBlock],
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
    location: str,
    rejections: list[str],
) -> list[Block]:
    resolved: list[Block] = []
    for item in proposed:
        block = _resolve_block(
            item,
            store=store,
            claims=claims,
            spans=spans,
            location=location,
            rejections=rejections,
        )
        if block is not None:
            resolved.append(block)
    return resolved


def _slide_budgets(component: str, tokens: DesignTokens) -> str:
    try:
        text = render_budgets(component, tokens)
    except UnknownComponentError as exc:
        return (
            f"(no declared budgets for {component!r} yet — {exc}. Write concisely; "
            "overflow cannot be checked automatically for this component.)"
        )
    lines = [text]
    flow = GEOMETRIES["process_flow"]
    for slot in _diagram_slots(component):
        lines.append(
            f"- {slot}: ONE block of kind 'diagram' (a process flow of 2 to 6 steps). Every "
            f"step label and every transition is at most {flow.max_label_words} words; a "
            "longer one drops the whole diagram. The diagram's own title is not drawn."
        )
    for slot in _chart_slots(component):
        lines.append(
            f"- {slot}: ONE block of kind 'chart'. The chart's categories, series names, and "
            "axis labels are measured at render and are not pre-budgeted here."
        )
    return "\n".join(lines)


def _read_prompt(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise ContentError(
            f"content prompt not found at {path}. Prompts are versioned files (plan §0.5) "
            "and their hashes go into the build manifest — there is no inline fallback."
        )
    return path.read_text(encoding="utf-8")
