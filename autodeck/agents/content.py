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
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, get_type_hints

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.rejections import Rejection, RejectionKind
from autodeck.agents.skills import SEPARATOR as SKILL_SEPARATOR
from autodeck.agents.skills import skills_text
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
from autodeck.ingest.document_store import DocumentStore, IngestError, UncitableSourceError
from autodeck.ingest.provenance import (
    NORMAL_SNAP_MIN_COVERAGE,
    SNAP_MIN_COVERAGE,
    diagnose_quote,
    snap_span,
)
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

    `kind` is the structured reason (a `RejectionKind`) and `detail` its figures, so the
    caller can record a `Rejection` rather than only a sentence.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: RejectionKind = "quote_not_found",
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind: RejectionKind = kind
        self.detail: dict[str, Any] = detail or {}


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


BlockKindDraft = Literal["claim", "framing", "chart", "section_header", "diagram", "unsourced"]
"""The block kinds the writer authors. `unsourced` (B55) is a normal deck's qualitative general
knowledge: plain `text`, no citation, resolved to a `claim` with `basis="unsourced"` — and
rejected as `mode_blocked` in a strict deck or a redesign. `diagram` was added by B37: the
outline could already assign `framework_diagram` and `timeline`, and nothing could fill them,
so no pipeline-built deck could carry the native diagram GATE 3 requires. `figure` and `icon`
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
        default="",
        description="For kind='framing', 'section_header' or 'unsourced'. '' otherwise.",
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
    resolver refusing to cite it. `render_evidence` marks each one plainly.
    """
    return search(index, query, limit=SPAN_LIMIT, citable_only=False)


def _slide_query(slide: Slide, messages: Sequence[KeyMessage]) -> str:
    parts = [slide.intent or "", *(m.text for m in messages)]
    return " ".join(part for part in parts if part)


def render_evidence(claims: Sequence[CachedClaim], spans: Sequence[RetrievedSpan]) -> str:
    """Render curated claims then retrieved spans as the text a model is shown.

    Public for the same reason as `resolve_blocks`: the evidence pack renders with the very
    function slides use, so what the model saw is what the resolver will accept.
    """
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
                    f"cached claim for {proposed.doc_id!r} no longer resolves: {exc}",
                    kind="quote_not_found",
                    detail={"doc_id": proposed.doc_id, "quote": proposed.quote},
                ) from exc

    candidates = [span for span in spans if span.doc_id == proposed.doc_id]
    if not candidates:
        raise CitationResolutionError(
            f"{proposed.doc_id!r} was not among the evidence shown for this slide (neither "
            "a curated claim nor a retrieved span). A citation names evidence actually "
            "presented, never a document the writer merely recalls.",
            kind="doc_not_shown",
            detail={"doc_id": proposed.doc_id},
        )

    last_error: IngestError | None = None
    errors: list[IngestError] = []
    for span in candidates:
        try:
            return span.to_citation(store, quote=proposed.quote, retrieved_by=retrieved_by)
        except IngestError as exc:
            last_error = exc
            errors.append(exc)
            continue

    snapped = _snap_citation(proposed, store=store, spans=candidates, retrieved_by=retrieved_by)
    if snapped is not None:
        return snapped

    assert last_error is not None
    detail: dict[str, Any] = {"doc_id": proposed.doc_id, "quote": proposed.quote}
    if all(isinstance(e, UncitableSourceError) for e in errors):
        raise CitationResolutionError(
            f"quote for {proposed.doc_id!r} did not resolve against any evidence span shown "
            f"for this slide: {last_error}",
            kind="uncitable",
            detail=detail,
        ) from last_error

    passages = _passages(store, candidates)
    diagnosis = diagnose_quote(proposed.quote, passages)
    detail["best_coverage"] = round(float(diagnosis["best_coverage"]), 3)
    kind: RejectionKind = "quote_not_found"
    if diagnosis["splice"]:
        kind = "quote_splice"
        detail["parts"] = diagnosis["parts"]
    raise CitationResolutionError(
        f"quote for {proposed.doc_id!r} did not resolve against any evidence span shown "
        f"for this slide: {last_error}"
        + (" (it joins two separate passages)" if kind == "quote_splice" else ""),
        kind=kind,
        detail=detail,
    ) from last_error


def _passages(store: DocumentStore, spans: Sequence[RetrievedSpan]) -> list[str]:
    """The verbatim text of each citable span's element, for diagnosing a failed quote."""
    texts: list[str] = []
    for span in spans:
        if not span.citable:
            continue
        element = store.get(span.doc_id).element(span.element_id)
        if element is not None:
            texts.append(element.text)
    return texts


#: Where `_snap_citation` reports, set by `resolve_blocks` for the duration of one call:
#: `(location, notes)`. A context variable rather than a parameter because the resolver
#: sits four calls deep (block -> claim/chart/diagram -> step -> citation).
_SNAP_NOTES: ContextVar[tuple[str, list[str]] | None] = ContextVar("_SNAP_NOTES", default=None)

#: How much of a quote must match one shown passage for `_snap_citation` to resolve it to
#: that passage's words (B52, B86): strict and redesign keep `SNAP_MIN_COVERAGE`; a `normal`
#: deck and meeting notes use `NORMAL_SNAP_MIN_COVERAGE`. Set by `resolve_blocks` and by
#: `loose_snapping()`; a context variable for the same reason as `_SNAP_NOTES`.
_SNAP_COVERAGE: ContextVar[float] = ContextVar("_SNAP_COVERAGE", default=SNAP_MIN_COVERAGE)


@contextmanager
def loose_snapping() -> Iterator[None]:
    """Resolve near quotes at the `normal`-mode bar for the duration (B86)."""
    token = _SNAP_COVERAGE.set(NORMAL_SNAP_MIN_COVERAGE)
    try:
        yield
    finally:
        _SNAP_COVERAGE.reset(token)


def _snap_citation(
    proposed: ProposedCitation,
    *,
    store: DocumentStore,
    spans: Sequence[RetrievedSpan],
    retrieved_by: Literal["writer"],
) -> Citation | None:
    """The citation a near-verbatim quote was pointing at, in the document's words (B52).

    Only the spans this slide was shown are searched, so a snap can never reach evidence
    the writer did not see. The citation is resolved through `to_citation` with the
    passage's verbatim text, the same A1 path as an exact quote; the model's version of the
    words is discarded. Whether the passage supports the sentence is the validator's call.
    """
    best: tuple[float, RetrievedSpan, str] | None = None
    for span in spans:
        if not span.citable:
            continue
        element = store.get(span.doc_id).element(span.element_id)
        if element is None:
            continue
        found = snap_span(element.text, proposed.quote, min_coverage=_SNAP_COVERAGE.get())
        if found is None:
            continue
        (start, end), coverage = found
        if best is None or coverage > best[0]:
            best = (coverage, span, element.text[start:end])
    if best is None:
        return None

    coverage, span, verbatim = best
    try:
        citation = span.to_citation(store, quote=verbatim, retrieved_by=retrieved_by)
    except IngestError:
        return None
    sink = _SNAP_NOTES.get()
    if sink is not None:
        location, notes = sink
        notes.append(
            f"{location}: quote for {proposed.doc_id!r} was not verbatim; cited the "
            f"source's own words instead ({coverage:.0%} match). Model: "
            f"{proposed.quote[:80]!r} -> source: {verbatim[:80]!r}"
        )
    return citation


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
                f"{exc}",
                kind=getattr(exc, "kind", "quote_not_found"),
                detail=getattr(exc, "detail", None),
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
            raise CitationResolutionError(
                "status='claim' with no claim payload", kind="no_payload"
            )
        if step.framing_reason != "":
            raise CitationResolutionError(
                f"status='claim' but framing_reason={step.framing_reason!r}; a label is a "
                "claim or framing, never both",
                kind="ir_invalid",
            )
        resolved_claim = _resolve_claim(step.claim, store=store, claims=claims, spans=spans)
    else:
        if step.framing_reason == "":
            raise CitationResolutionError(
                "status='framing' with no framing_reason", kind="no_payload"
            )
        if step.claim is not None:
            raise CitationResolutionError(
                "status='framing' but a claim was supplied; a label is a claim or framing, "
                "never both",
                kind="ir_invalid",
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
    records: list[Rejection] | None = None,
    slide_id: str = "",
    where: Literal["face", "notes", "message"] = "face",
    allow_unsourced: bool = False,
) -> Block | None:
    """Resolve one proposed block, or record why it was dropped and return None.

    A quote that does not resolve is a failure, not a warning (task 2b.4): the whole block
    is dropped rather than falling back to an uncited version of it, and the *reason* is
    kept rather than the block silently disappearing — as a sentence in `rejections` and,
    when `records` is given, as a structured `Rejection` beside it.
    """

    def record(kind: RejectionKind, message: str, detail: dict[str, Any] | None = None) -> None:
        rejections.append(message)
        if records is not None:
            records.append(
                Rejection(
                    kind=kind,
                    where=where,
                    slide_id=slide_id,
                    block_id=proposed.id,
                    slot=proposed.slot,
                    message=message,
                    detail=detail or {},
                    proposed=proposed,
                )
            )

    try:
        if proposed.kind == "claim":
            if proposed.claim is None:
                raise CitationResolutionError(
                    "kind='claim' with no claim payload", kind="no_payload"
                )
            claim = _resolve_claim(proposed.claim, store=store, claims=claims, spans=spans)
            return Block(id=proposed.id, kind="claim", slot=proposed.slot, claim=claim)
        if proposed.kind == "chart":
            if proposed.chart is None:
                raise CitationResolutionError(
                    "kind='chart' with no chart payload", kind="no_payload"
                )
            chart = _resolve_chart(proposed.chart, store=store, claims=claims, spans=spans)
            return Block(id=proposed.id, kind="chart", slot=proposed.slot, chart=chart)
        if proposed.kind == "diagram":
            if proposed.diagram is None:
                raise CitationResolutionError(
                    "kind='diagram' with no diagram payload", kind="no_payload"
                )
            diagram = _resolve_diagram(
                proposed.diagram, store=store, claims=claims, spans=spans
            )
            return Block(id=proposed.id, kind="diagram", slot=proposed.slot, diagram=diagram)
        if proposed.kind == "unsourced":
            if not allow_unsourced:
                raise CitationResolutionError(
                    "an unsourced statement is not allowed in this deck (strict provenance, "
                    "or a redesign): cite a document or leave it out (B55)",
                    kind="mode_blocked",
                )
            if not proposed.text.strip():
                raise CitationResolutionError(
                    "kind='unsourced' with no text", kind="no_payload"
                )
            return Block(
                id=proposed.id,
                kind="claim",
                slot=proposed.slot,
                claim=Claim(text=proposed.text, basis="unsourced"),
            )
        # framing / section_header: plain text, no citation to resolve (A5's exemption).
        if not proposed.text.strip():
            raise CitationResolutionError(
                f"kind={proposed.kind!r} with no text", kind="no_payload"
            )
        return Block(id=proposed.id, kind=proposed.kind, slot=proposed.slot, text=proposed.text)
    except CitationResolutionError as exc:
        record(
            exc.kind,
            f"{location} block {proposed.id!r} ({proposed.slot}): {exc}",
            exc.detail,
        )
        return None
    except IngestError as exc:
        kind: RejectionKind = (
            "uncitable" if isinstance(exc, UncitableSourceError) else "quote_not_found"
        )
        record(kind, f"{location} block {proposed.id!r} ({proposed.slot}): {exc}")
        return None
    except Exception as exc:  # pydantic's own validators, as a defensive backstop
        record(
            "ir_invalid",
            f"{location} block {proposed.id!r} ({proposed.slot}): "
            f"failed IR validation after resolution: {exc}",
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


def _payload_slots(component: str, payload_type: type) -> list[str]:
    """The slots of `component`'s content type that take a given payload type.

    Diagrams and charts cannot be predicted from a text budget (diagrams' boxes depend on
    node count, charts' size depends on data dimensions), so the catalog declares no slot
    for either. This function reads the component's content dataclass to find which slots
    require a particular payload type (DiagramSpec, ChartSpec, etc.). The catalog's text
    table will never know about these slots, so gaps must be detected here rather than at
    render. Empty for a component the catalog does not know.
    """
    try:
        content_type = registration(component).content_type
    except UnknownComponentError:
        return []
    hints = get_type_hints(content_type)
    return [f.name for f in dataclasses.fields(content_type) if hints[f.name] is payload_type]


def _diagram_slots(component: str) -> list[str]:
    """The slots of `component` that take a `DiagramSpec` (B37). See `_payload_slots`."""
    return _payload_slots(component, DiagramSpec)


def _chart_slots(component: str) -> list[str]:
    """The slots of `component` that take a `ChartSpec`. See `_payload_slots`."""
    return _payload_slots(component, ChartSpec)


_ITEM_FINDING = re.compile(r"^[^:]*?\.(?P<slot>[A-Za-z0-9_]+)\[(?P<index>\d+)\]:")
_STACK_FINDING = re.compile(r"item\(s\) need [\d.]+pt stacked but only [\d.]+pt")
_CHARS = re.compile(r"(?P<chars>\d+) characters does not fit")
_BUDGET = re.compile(
    r"at most (?P<lines>\d+) line\(s\), roughly (?P<max>\d+) characters, "
    r"at (?P<size>[\d.]+)pt (?P<family>.+?)(?: bold| italic)*\)"
)


def _finding_detail(finding: str) -> dict[str, Any]:
    """The figures in an overflow finding, for a repair prompt: chars, max_chars, ..."""
    detail: dict[str, Any] = {}
    if m := _CHARS.search(finding):
        detail["chars"] = int(m["chars"])
    if m := _BUDGET.search(finding):
        detail.update(
            max_lines=int(m["lines"]),
            max_chars=int(m["max"]),
            size_pt=float(m["size"]),
            family=m["family"],
        )
    return detail


def _finding_slot(finding: str) -> str:
    return finding.split(":", 1)[0].rsplit(".", 1)[-1].split("[")[0]


def _slot_content(blocks: Sequence[Block]) -> dict[str, BlockValue]:
    by_slot: dict[str, list[Block]] = {}
    for block in blocks:
        by_slot.setdefault(block.slot, []).append(block)
    return {
        slot: [_block_text(b) for b in items] if len(items) > 1 else _block_text(items[0])
        for slot, items in by_slot.items()
    }


def _computed_slots() -> frozenset[str]:
    from autodeck.render.renderer import _COMPUTED_FIELDS  # lazy: render imports the pipeline

    return frozenset(_COMPUTED_FIELDS)


def _trial_overflow(blocks: Sequence[Block], component: str, tokens: DesignTokens) -> str | None:
    """Lay `blocks` out with the component's real renderer on a throwaway slide.

    Returns the layout error's message when the slide does not fit as a whole, else None.
    A slide that cannot be adapted at all (a required slot empty, cards unpaired) returns
    None: the missing-slot checks report that, and there is nothing to lay out.
    """
    from autodeck.design.charts import ChartConstructionError
    from autodeck.design.layout_kit import Canvas, LayoutOverflowError
    from autodeck.design.theme.master_builder import new_presentation
    from autodeck.ir.models import Slide
    from autodeck.render.renderer import _BLANK_LAYOUT, RenderStageError, adapt_slide

    try:
        entry = registration(component)
        trial = Slide(id="trial", narrative_role="trial", component=component, blocks=list(blocks))
        content, _warnings = adapt_slide(trial, entry.content_type)
    except (RenderStageError, ValueError, UnknownComponentError):
        return None
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    try:
        entry.renderer(slide, Canvas(tokens), content)
    except (LayoutOverflowError, ChartConstructionError) as exc:
        return str(exc)
    return None


def _fit_victim(blocks: Sequence[Block], component: str, tokens: DesignTokens) -> Block | None:
    """The block to drop when a slide does not fit as a whole.

    Optional slots go first, then items of list slots, longest first. Required slots and the
    headline are never dropped (None is returned once only they are left).
    """
    from autodeck.design.components.catalog import spec_for

    try:
        spec = spec_for(component, tokens)
        required = {s.name for s in spec.slots if s.required and not s.repeatable}
        repeatable = {s.name for s in spec.slots if s.repeatable}
    except Exception:
        required, repeatable = set(), set()
    texts = [b for b in blocks if b.chart is None and b.diagram is None and _block_text(b)]
    if not texts:
        return None

    required_lists = {s.name for s in spec.slots if s.required and s.repeatable} if required else set()

    def droppable(block: Block) -> bool:
        if block.slot in ("headline", "title") or block.slot in required:
            return False
        if block.slot in required_lists:
            return sum(1 for b in texts if b.slot == block.slot) > 1
        return True

    def rank(block: Block) -> tuple[int, int]:
        return (1 if block.slot in repeatable else 0), -len(_block_text(block))

    # Never a headline, a required slot, or a required list's last item: dropping one only
    # turns "too long" into "missing", and the slide would still be drawn as a placeholder,
    # with a less accurate reason. Such a slide is left for the repair call to shorten.
    candidates = [b for b in texts if droppable(b)]
    return min(candidates, key=rank) if candidates else None


def _single_slots(component: str, tokens: DesignTokens) -> frozenset[str]:
    """The component's slots that take exactly one block (not a LIST), in any variant."""
    from autodeck.design.components.catalog import spec_for

    names: set[str] = set()
    repeatable: set[str] = set()
    try:
        entry = registration(component)
        for variant in entry.variants:
            for slot in spec_for(component, tokens, variant=variant.name).slots:
                (repeatable if slot.repeatable else names).add(slot.name)
    except Exception:  # an unknown component or variant: nothing to enforce here
        return frozenset()
    return frozenset(names - repeatable)


def _slot_rejection(block: Block, component: str) -> tuple[RejectionKind, str] | None:
    """Why `block`'s slot is not one of `component`'s, or None when it is placeable."""
    from autodeck.render.renderer import (  # lazy: render imports the pipeline
        UnknownComponentError as RenderUnknownComponentError,
    )
    from autodeck.render.renderer import (
        placeable_slots,
    )

    try:
        allowed = placeable_slots(component)
    except RenderUnknownComponentError:
        return None
    if block.slot in allowed:
        return None
    if block.slot in _computed_slots():
        return (
            "computed_slot",
            f"slot {block.slot!r} is filled by the renderer from the deck's own citations "
            f"and is never written; {component!r} takes: {', '.join(sorted(allowed))}",
        )
    return (
        "unknown_slot",
        f"{block.slot!r} is not a slot of {component!r}; it takes: "
        f"{', '.join(sorted(allowed))}",
    )


def check_budgets(
    blocks: list[Block],
    *,
    component: str,
    tokens: DesignTokens,
    records: list[Rejection] | None = None,
    slide_id: str = "",
    where: Literal["face", "notes", "message"] = "face",
) -> tuple[list[Block], list[str], list[str], bool]:
    """Drop any face block whose slot overflows its budget. Chart and diagram blocks are
    exempt from the text budgets — the catalog declares text slots, not chart or diagram
    geometry. A diagram's labels are budgeted by its geometry (`GEOMETRIES[kind].
    max_label_words`), which `DiagramSpec` enforces when the block is built, so an over-long
    label has already dropped its block (as an IR-validation rejection) by the time this
    runs.

    **Only the block that overflows is dropped.** A finding names `slot[index]`; the index is
    the position in the slot's list as `check_overflow` saw it, which maps back to exactly
    one block (`overflow_item`). If the slot's stacked height still does not fit once the
    over-long items are gone, blocks are dropped from the END of the slot until it does
    (`overflow_stack`). A single-text slot that overflows drops its one block
    (`overflow_text`). Earlier versions dropped every block in the slot, so one 132-character
    bullet cost its 92- and 101-character neighbours too.

    A block whose slot is not one the component places is rejected first: `computed_slot`
    for a field the renderer fills itself (`source`), `unknown_slot` for anything else —
    either would otherwise survive to render and fail there as an unplaced block.

    A component that takes a diagram (`_diagram_slots`) or a chart (`_chart_slots`) but
    received none is reported in `incomplete_slots`, in the catalog's own missing-slot form:
    the catalog's text table cannot see an absent diagram or chart, and the render stage
    would otherwise be the first to notice.

    `check_overflow` reports overflow and missing-required-slot findings in one list; they
    are split here (`is_missing_slot_finding`) because they mean different things to a
    caller — see `ContentResult.rejections` and `.incomplete_slots`. Only an overflow finding
    ever drops a block: a missing-slot finding has no block to drop, since none was written.

    `records`, when given, receives a structured `Rejection` for every drop, alongside the
    returned sentences.

    Returns `(kept, rejections, incomplete_slots, budgets_checked)`.
    """
    try:
        registration(component)
    except UnknownComponentError:
        return blocks, [], [], False

    rejections: list[str] = []

    def drop(
        block: Block,
        kind: RejectionKind,
        message: str,
        *,
        item_index: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        rejections.append(message)
        if records is not None:
            records.append(
                Rejection(
                    kind=kind,
                    where=where,
                    slide_id=slide_id,
                    block_id=block.id,
                    slot=block.slot,
                    message=message,
                    item_index=item_index,
                    detail=detail or {},
                )
            )

    current: list[Block] = []
    for block in blocks:
        bad = _slot_rejection(block, component)
        if bad is None:
            current.append(block)
            continue
        kind, why = bad
        drop(
            block,
            kind,
            f"dropped block {block.id!r} (slot {block.slot!r}): {_excerpt(_block_text(block))}"
            f" — {why}",
            detail={"slot": block.slot},
        )

    # A slot that is not a LIST holds exactly one block. A second one used to survive to the
    # preview, which then drew the whole slide as a placeholder (run XLP3: two `takeaway`
    # blocks on a callout). The first block written stays; each extra is rejected so the
    # repair call can merge or move it.
    single = _single_slots(component, tokens)
    filled: set[str] = set()
    for block in list(current):
        if block.slot not in single:
            continue
        if block.slot in filled:
            current.remove(block)
            drop(
                block,
                "overflow_text",
                f"dropped block {block.id!r} (slot {block.slot!r}): "
                f"{_excerpt(_block_text(block))} — {block.slot!r} holds one block and "
                "already has one; merge the two or move this one to a list slot",
                detail={"slot": block.slot, "reason": "second_block_in_single_slot"},
            )
        else:
            filled.add(block.slot)

    def text_blocks() -> list[Block]:
        return [b for b in current if b.chart is None and b.diagram is None]

    findings: list[str] = []
    try:
        while True:
            texts = text_blocks()
            findings = check_overflow(_slot_content(texts), component, tokens)
            overflow = [f for f in findings if not is_missing_slot_finding(f)]
            if not overflow:
                break

            # Position of each block within its slot's item list, as check_overflow built it
            # (empty items are skipped there, so they are skipped here).
            members: dict[str, list[Block]] = {}
            for block in texts:
                if _block_text(block):
                    members.setdefault(block.slot, []).append(block)

            doomed: dict[str, tuple[Block, RejectionKind, str, int | None, dict[str, Any]]] = {}
            stacked: list[str] = []
            for finding in overflow:
                slot = _finding_slot(finding)
                item = _ITEM_FINDING.match(finding)
                if item is not None:
                    index = int(item["index"])
                    block = members[slot][index]
                    doomed[block.id] = (
                        block,
                        "overflow_item",
                        f"dropped block {block.id!r} (slot {slot!r}): "
                        f"{_excerpt(_block_text(block))} — overflow: "
                        f"{finding}",
                        index,
                        _finding_detail(finding),
                    )
                elif _STACK_FINDING.search(finding):
                    stacked.append(slot)
                else:
                    block = members[slot][-1]
                    doomed[block.id] = (
                        block,
                        "overflow_text",
                        f"dropped block {block.id!r} (slot {slot!r}): "
                        f"{_excerpt(_block_text(block))} — overflow: "
                        f"{finding}",
                        None,
                        _finding_detail(finding),
                    )
            if not doomed:
                # Only stacked-height findings are left: shed from the end of each slot.
                for slot in dict.fromkeys(stacked):
                    block = members[slot][-1]
                    finding = next(
                        f
                        for f in overflow
                        if _finding_slot(f) == slot and _STACK_FINDING.search(f)
                    )
                    doomed[block.id] = (
                        block,
                        "overflow_stack",
                        f"dropped block {block.id!r} (slot {slot!r}): "
                        f"{_excerpt(_block_text(block))} — overflow: "
                        f"{finding}",
                        len(members[slot]) - 1,
                        {"items": len(members[slot])},
                    )
            if not doomed:  # pragma: no cover — every overflow finding is one of the three
                break
            for block, kind, message, index, detail in doomed.values():
                drop(block, kind, message, item_index=index, detail=detail)
            current = [b for b in current if b.id not in doomed]
    except UnknownComponentError:
        return blocks, [], [], False

    # Slots that each fit their own budget can still overflow the region they share: a
    # seven-line headline the headline budget allows leaves no room for the points; a
    # big_number's label and support each fit, but not together (design gallery,
    # 2026-10-13). So the slide is laid out for real (python-pptx only, no LibreOffice) and
    # blocks are dropped until it fits: optional parts first, then the longest item, the
    # headline last. Each drop is reported so the repair call can shorten instead.
    if where == "face":
        for _ in range(12):
            problem = _trial_overflow(current, component, tokens)
            if problem is None:
                break
            victim = _fit_victim(current, component, tokens)
            if victim is None:
                # Only required text is left and it still does not fit: nothing is dropped,
                # the preview draws a placeholder saying so, and this says why.
                rejections.append(
                    f"slide {slide_id or '?'} does not fit as a whole even with its optional "
                    f"parts removed: {problem.split('. Shorten')[0]}. Its headline or required "
                    "text must be shorter, or it needs a component with more room"
                )
                break
            current = [b for b in current if b.id != victim.id]
            drop(
                victim,
                "overflow_stack",
                f"dropped block {victim.id!r} (slot {victim.slot!r}): "
                f"{_excerpt(_block_text(victim))} — the slide does not fit as a whole: "
                f"{problem.split('. Shorten')[0]}. Shorten the headline or the body, or drop "
                "an optional part",
                detail={"slot": victim.slot, "reason": "slide_does_not_fit_as_a_whole"},
            )

    # A required slot the renderer fills itself (a divider's number, a source line) is never
    # "missing": no block could ever fill it.
    computed = _computed_slots()
    incomplete_slots = [
        f for f in findings if is_missing_slot_finding(f) and _finding_slot(f) not in computed
    ]
    filled_diagrams = {b.slot for b in current if b.diagram is not None}
    incomplete_slots.extend(
        missing_slot_finding(component, slot)
        for slot in _diagram_slots(component)
        if slot not in filled_diagrams
    )
    filled_charts = {b.slot for b in current if b.chart is not None}
    incomplete_slots.extend(
        missing_slot_finding(component, slot)
        for slot in _chart_slots(component)
        if slot not in filled_charts
    )
    if records is not None:
        for finding in incomplete_slots:
            records.append(
                Rejection(
                    kind="missing_slot",
                    where=where,
                    slide_id=slide_id,
                    block_id="",
                    slot=_finding_slot(finding),
                    message=finding,
                )
            )
    return current, rejections, incomplete_slots, True


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
    # The index carries the project (A4), so its own gold exemplar is withheld (B65).
    system = SKILL_SEPARATOR.join(
        [_read_prompt(prompt_path), skills_text("content", project=index.project)]
    )

    served = [m for m in (brief.message(mid) for mid in slide.message_ids) if m is not None]
    query = _slide_query(slide, served)
    matched_claims = _gather_claims(query, claims)
    matched_spans = _gather_spans(query, index)
    evidence_text = render_evidence(matched_claims, matched_spans)
    budgets_text = slide_budgets(slide.component, tokens)

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
    blocks = resolve_blocks(
        draft.blocks,
        store=store,
        claims=matched_claims,
        spans=matched_spans,
        location=f"slide {slide.id} face",
        rejections=rejections,
    )
    speaker_notes = resolve_blocks(
        draft.speaker_notes,
        store=store,
        claims=matched_claims,
        spans=matched_spans,
        location=f"slide {slide.id} notes",
        rejections=rejections,
    )

    kept, overflow_rejections, incomplete_slots, budgets_checked = check_budgets(
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


def resolve_blocks(
    proposed: Sequence[ProposedBlock],
    *,
    store: DocumentStore,
    claims: Sequence[CachedClaim],
    spans: Sequence[RetrievedSpan],
    location: str,
    rejections: list[str],
    snapped: list[str] | None = None,
    records: list[Rejection] | None = None,
    slide_id: str = "",
    where: Literal["face", "notes", "message"] = "face",
    allow_unsourced: bool = False,
) -> list[Block]:
    """Resolve every proposed block's citations through the store; drop what fails.

    Public so that compose (whole-deck drafting) resolves citations with exactly the code
    a single slide uses — one resolver, no third path. Each refusal is appended to
    `rejections` as a plain sentence naming `location`; a block that resolves to nothing is
    omitted, never half-built. A quote that was not verbatim but clearly points at one
    passage is cited in the source's own words (B52), and noted in `snapped` if given. When
    `records` is given each drop is also appended there as a structured `Rejection`.
    """
    resolved: list[Block] = []
    token = _SNAP_NOTES.set((location, snapped) if snapped is not None else None)
    # B86: `allow_unsourced` is exactly a normal-mode deck that is not a redesign.
    coverage = _SNAP_COVERAGE.set(
        NORMAL_SNAP_MIN_COVERAGE if allow_unsourced else _SNAP_COVERAGE.get()
    )
    try:
        for item in proposed:
            block = _resolve_block(
                item,
                store=store,
                claims=claims,
                spans=spans,
                location=location,
                rejections=rejections,
                records=records,
                slide_id=slide_id,
                where=where,
                allow_unsourced=allow_unsourced,
            )
            if block is not None:
                resolved.append(block)
    finally:
        _SNAP_COVERAGE.reset(coverage)
        _SNAP_NOTES.reset(token)
    return resolved


def slide_budgets(component: str, tokens: DesignTokens) -> str:
    """Render the declared per-slot budgets for `component` as prompt text.

    Public so compose states budgets in the same words as a single-slide write. A component
    with no catalog entry yet gets a plain note instead of an error.
    """
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


# Private names kept as aliases: the public resolver API above is the contract; these keep
# older call sites and tests working unchanged.
_resolve_blocks = resolve_blocks
_check_budgets = check_budgets
_render_evidence = render_evidence
_slide_budgets = slide_budgets
