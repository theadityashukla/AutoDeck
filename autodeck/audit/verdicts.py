"""The A3 verdict core: what makes a claim `contradicted` rather than `supported`.

A3 is the invariant that says a deck cannot ship an assertion the corpus does not back,
and its defining behaviour is the one v1 never had: **a claim whose own citation is
perfectly valid is still `contradicted` when a different span elsewhere in the corpus says
the opposite.** `legacy/v1/LEGACY.md` records that v1's validator checked the writer's
retrieval and stopped there, which can only ever confirm the writer.

## Why the rule lives here and not in the agent

`agents/validation.py` is the plumbing — prompt assembly, re-retrieval, the claims table.
This module is the *rule*, and it sits inside the `autodeck/audit/` guardrail path because
it is the thing that must not quietly loosen (decision B28). It takes evidence and a model
judgement as **inputs** and returns a verdict: no provider call, no prompt text, no I/O.
Everything here is reproducible from its arguments, which is what lets the load-bearing
behaviours be asserted by a unit test rather than measured by an eval.

## The ceiling, applied after the model rather than asked for in the prompt

`agents/evidence_gap.py` is this module's nearest sibling and the shape is deliberately the
same: **a model's answer is bounded by what retrieval actually found, and the bound is
applied to the answer afterwards.** `prompts/validation.md` asks for all of this too, and
asking is worth doing — but a prompt is a request and a ceiling is a property. A model that
ignores its instructions, or a weaker model swapped in under B8, still cannot produce a
verdict its evidence does not carry. Each bound below names the wrong outcome it prevents.

Caps are surfaced (`VerdictAssessment.capped`), never silent, for the reason
`ProbeResult.capped` gives: a model that regularly needs capping is one to stop trusting,
and that signal disappears the moment the cap stops announcing itself.

## Independence is carried by the type, not by a convention

`Citation.retrieved_by` already distinguishes `writer` from `validator`. `ValidatorEvidence`
refuses to hold anything but `validator` spans, so the writer's own citation — the object
v1's validator mistook for evidence — **cannot be put into the evidence set at all**. The
writer's citations reach this module only as `Claim.citations`, a separate argument a reader
can see is separate. A validator that independently retrieves the same sentence is a
different matter and is allowed: that is confirmation, and `ValidatorEvidence.echoes_of`
names it so the audit report can say which spans were found twice.

## What it does not do

It does not soften. There is no "close enough to supported", and every cap in here moves a
verdict down or sideways, never up — except the contradiction rule, which moves it to
`contradicted` from anywhere, because that is the one direction the evidence can force.

It does not decide whether the build proceeds. `require_safe_to_render` in
`pipeline/orchestrator.py` does that; this module reports.

Owning phase: 2b (task 2b.8a). Opus tier — `autodeck/audit/` is a path guardrail.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from autodeck.ingest.provenance import find_span
from autodeck.ir.models import Block, Citation, Claim, Deck, Verdict

JudgedVerdict = Literal["supported", "partially_supported", "unsupported", "contradicted"]
"""The four verdicts A3 names — the IR's `Verdict` minus `unverified`.

`unverified` means *nobody looked*, which is a fact about the pipeline rather than about the
evidence, so it is not an answer a model is allowed to return. Keeping it out of the
structured schema is the same move `EvidenceClassification` makes with `unprobed`: a model
cannot report that it did not run.
"""


class VerdictIndependenceError(ValueError):
    """Something that is not independently retrieved evidence was offered as evidence.

    Raised rather than logged, and raised at construction rather than checked later. A3's
    whole content is that the validator does its own retrieval; a validator handed the
    writer's citation and asked "does this support the claim?" is v1, and v1 is what this
    phase exists to replace.
    """


class VerdictShapeError(ValueError):
    """A verdict was assembled without the span that is the only reason to believe it.

    `prompts/validation.md`: *"If you found a contradicting span, it goes in the list —
    verbatim, with its doc_id, page and bbox — or it did not happen."* The claims table at
    GATE 2 prints spans, not reasoning, so a `contradicted` verdict carrying no span is an
    audit report that asserts a contradiction and shows nothing.
    """


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


class VerdictJudgement(BaseModel):
    """One model's judgement about one claim, before any ceiling is applied.

    Field names follow `prompts/validation.md`, which is authoritative on the boundary
    between the four verdicts; the descriptions restate its rules so the schema and the
    prompt cannot drift apart unnoticed.

    The quotes are **verbatim strings, not citations**. The prompt speaks of citation
    objects because that is what ends up in the IR, but a model cannot compute a bounding
    box or a SHA-256, so it names the span and `assess_claim` maps the name back onto the
    evidence it was shown — exactly as `EvidenceClassification.strongest_quote` does. A
    quote that does not map is dropped, because a fabricated span reads identically to a
    real one and sends a writer hunting for a sentence that does not exist.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: JudgedVerdict = Field(
        description=(
            "supported, partially_supported, unsupported, or contradicted. Between two "
            "verdicts, take the lower one."
        )
    )
    verdict_notes: str = Field(
        min_length=1,
        description=(
            "The specific support or the specific mismatch — which quantity, which "
            "configuration, which paper — and what you searched for. Not a restatement of "
            "the claim."
        ),
    )
    supporting_quote: str = Field(
        default="",
        description=(
            "The single strongest span backing the claim, copied VERBATIM from the "
            "evidence shown. Empty when nothing backs it."
        ),
    )
    contradicting_quotes: list[str] = Field(
        default_factory=list,
        description=(
            "Every span incompatible with the claim, copied VERBATIM from the evidence "
            "shown. A list left empty is a list nobody can read later. Where two sources "
            "disagree with each other, record both rather than choosing."
        ),
    )


# ---------------------------------------------------------------------------
# Independence, as a type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidatorEvidence:
    """The spans the validator retrieved for itself — the only evidence a verdict may rest on.

    **Construction rejects any citation not marked `retrieved_by="validator"`.** That is the
    structural half of A3's independence requirement: "the validator treated the writer's
    citation as evidence" is not a mistake this type can express, so no call site has to
    remember not to make it. The writer's citations arrive at `assess_claim` as
    `Claim.citations`, a visibly separate argument.

    It is not *quite* unrepresentable, and the docstring should say where the seam is: a
    caller could re-resolve the writer's quote through the document store with
    `retrieved_by="validator"` and hand it over. That is a caller lying about who searched,
    not a caller forgetting the rule, and no type can stop it — so `echoes_of` exists to
    make the overlap visible instead of hiding it. A span the validator genuinely found for
    itself that happens to be the writer's span is confirmation and counts as support.

    Spans are `Citation` objects because every one of them has already resolved through
    `DocumentStore.resolve_quote`. Citability is therefore settled before this module sees
    them: a figure description or a page footer cannot reach a verdict (§6.3), and "a
    citable supporting span" needs no runtime check here.
    """

    spans: Sequence[Citation] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "spans", tuple(self.spans))
        borrowed = [c for c in self.spans if c.retrieved_by != "validator"]
        if borrowed:
            where = ", ".join(f"{c.doc_id} p.{c.page}" for c in borrowed)
            raise VerdictIndependenceError(
                f"{len(borrowed)} span(s) offered as validator evidence were retrieved by "
                f"the writer ({where}). A3 requires the validator to re-retrieve "
                "independently; checking the writer's own citation can only confirm the "
                "writer, which is precisely what v1 did (legacy/v1/LEGACY.md)."
            )

    def __len__(self) -> int:
        return len(self.spans)

    def __bool__(self) -> bool:
        return bool(self.spans)

    def find(self, quote: str) -> Citation | None:
        """The evidence span containing `quote`, or None if the model invented it.

        Matching uses `provenance.find_span`, the same tolerant-but-not-approximate matcher
        the citation resolver uses, so a ligature or a curly quote does not cause a false
        rejection while a paraphrase still does.

        The span returned is the whole retrieved element, not a slice of it. The claim is
        that this evidence carries the quoted sentence, and the element's own citation is
        the one that already resolved and hashed — narrowing it here would mean minting a
        citation outside the document store, which is the one thing A1 forbids.
        """
        if not quote.strip():
            return None
        return next(
            (span for span in self.spans if find_span(span.quote, quote) is not None), None
        )

    def echoes_of(self, writer_citations: Sequence[Citation]) -> tuple[Citation, ...]:
        """Evidence spans identical to one of the writer's citations.

        Not an error — an independent search that lands on the same sentence has confirmed
        it. Reported so the audit report can distinguish "found it again" from "found
        something new", and so a test can prove the evidence was not simply the writer's
        list handed back.
        """
        writer = {c.identity() for c in writer_citations}
        return tuple(span for span in self.spans if span.identity() in writer)


# ---------------------------------------------------------------------------
# The assessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictAssessment:
    """The verdict A3 assigns to one claim, with the spans that justify it.

    Immutable, and validated on construction: a verdict that has lost its evidence between
    here and the audit report is the failure `VerdictShapeError` describes.
    """

    claim_text: str
    verdict: Verdict
    notes: str
    supporting_span: Citation | None = None
    contradicting_spans: tuple[Citation, ...] = ()
    capped: bool = False
    """True when a bound lowered or redirected the model's own answer.

    Surfaced rather than swallowed, exactly as `ProbeResult.capped` is: a model that
    regularly needs capping is one to stop trusting on A3, and B8 says that judgement has
    to be made on real numbers from `sit` rather than on an impression.
    """
    cap_reasons: tuple[str, ...] = ()
    dropped_quotes: tuple[str, ...] = ()
    """Quotes the model named that were not in the evidence it was shown."""

    def __post_init__(self) -> None:
        if self.verdict == "contradicted" and not self.contradicting_spans:
            raise VerdictShapeError(
                "a `contradicted` verdict was assembled with no contradicting span. The "
                "claims table prints spans, not reasoning: a contradiction nobody can read "
                "is a contradiction that did not happen (prompts/validation.md)."
            )
        if self.verdict == "supported" and self.supporting_span is None:
            raise VerdictShapeError(
                "a `supported` verdict was assembled with no supporting span. Support is a "
                "span or it is an opinion, and A1 cannot record an opinion."
            )

    def blocks_render(self) -> bool:
        """Whether A3 forbids the claim carrying this verdict from reaching final render."""
        return verdict_blocks_render(self.verdict)

    def apply(self, claim: Claim) -> Claim:
        """Return `claim` carrying this verdict, its notes, and its contradicting spans.

        The contradicting spans land on the claim rather than in a side-car because A3 asks
        the audit report to *show* the contradiction, and `Claim.contradicting_spans` exists
        for exactly this. The writer's citations are untouched: the writer's citation being
        valid is not in dispute and deleting it would erase what the contradiction is
        contradicting.
        """
        return claim.model_copy(
            update={
                "verdict": self.verdict,
                "verdict_notes": self.notes or None,
                "contradicting_spans": list(self.contradicting_spans),
            }
        )


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def assess_claim(
    claim: Claim,
    *,
    evidence: ValidatorEvidence,
    judgement: VerdictJudgement | None = None,
) -> VerdictAssessment:
    """Assign a verdict to one claim: the model's judgement, bounded by its evidence.

    Args:
        claim: the claim as the writer left it. Its `citations` are the writer's, and they
            are an **input to be checked** — they never count as evidence and they can
            never raise a verdict.
        evidence: what the validator retrieved for itself, independently.
        judgement: what the model concluded. None means nobody judged this claim, which
            comes back `unverified` rather than being guessed at.

    The bounds, in the order they fire:

    1. **No independently retrieved span → `unsupported`.** Zero evidence means there is
       nothing to be right about. *Prevents:* a model confirming the writer's citation and
       calling it support, which is A3's entire failure mode; and a `contradicted` verdict
       resting on the model's own knowledge of the literature rather than on the corpus.
    2. **A real contradicting span outranks everything, including a valid citation.**
       *Prevents:* the defining v1 failure — a claim with a perfect citation that the
       corpus elsewhere refutes, averaged away into `supported` because the citation
       checked out.
    3. **A contradiction the model cannot quote is not a contradiction → `unsupported`.**
       *Prevents:* a fabricated contradiction, which `prompts/validation.md` rates worse
       than a missed one: it sends a writer hunting for a sentence that does not exist and
       it discredits every other verdict in the table.
    4. **Support must name a span that is really in the evidence → `unsupported`.**
       *Prevents:* `supported` resting on a hallucinated quote, and `supported` resting on
       nothing at all because the model left the field empty while arguing its case in
       prose.

    Nothing here rewrites the claim, softens a verdict, or decides whether the build
    proceeds.
    """
    if not evidence:
        capped = judgement is not None and judgement.verdict != "unsupported"
        return VerdictAssessment(
            claim_text=claim.text,
            verdict="unsupported",
            notes=(
                "Independent re-retrieval found no citable span for this claim, so there "
                "is nothing to judge it against. The writer's citation is not evidence "
                "here (A3): a validator that reads it has only confirmed the writer."
            ),
            capped=capped,
            cap_reasons=(
                (
                    f"model returned {judgement.verdict!r} with zero independently "
                    "retrieved spans",
                )
                if capped and judgement is not None
                else ()
            ),
        )

    if judgement is None:
        return VerdictAssessment(
            claim_text=claim.text,
            verdict="unverified",
            notes=(
                f"{len(evidence)} independently retrieved span(s) are available but nothing "
                "has judged them against the claim. Nobody looked — which is not the same "
                "finding as `unsupported`, where somebody looked and found nothing."
            ),
        )

    contradicting, dropped_contradictions = _real_spans(
        judgement.contradicting_quotes, evidence
    )
    supporting = evidence.find(judgement.supporting_quote)
    dropped = tuple(dropped_contradictions)
    if judgement.supporting_quote.strip() and supporting is None:
        dropped = (*dropped, judgement.supporting_quote)

    notes = judgement.verdict_notes.strip()
    caps: list[str] = []

    if contradicting:
        # Bound 2. Ordered first on purpose: `contradicted` has to *win* rather than be
        # weighed against a valid citation, and anything that reaches a comparison
        # eventually loses one.
        if judgement.verdict != "contradicted":
            caps.append(
                f"model returned {judgement.verdict!r} while naming "
                f"{len(contradicting)} contradicting span(s); a valid citation does not "
                "outrank a contradiction (A3)"
            )
        verdict: Verdict = "contradicted"
    elif judgement.verdict == "contradicted":
        # Bound 3.
        caps.append(
            "model returned 'contradicted' but no contradicting span it named appears in "
            "the evidence it was shown; belief is not a span (A1)"
        )
        verdict = "unsupported"
    elif judgement.verdict in ("supported", "partially_supported") and supporting is None:
        # Bound 4.
        caps.append(
            f"model returned {judgement.verdict!r} without a supporting span present in "
            "the evidence it was shown"
        )
        verdict = "unsupported"
    else:
        verdict = judgement.verdict

    if dropped:
        notes = (
            f"{notes} [A3: {len(dropped)} quote(s) the model named were not in the "
            "evidence it was shown and have been dropped.]"
        )

    return VerdictAssessment(
        claim_text=claim.text,
        verdict=verdict,
        notes=notes,
        # A contradicted claim keeps its supporting span when one was found: two spans that
        # disagree is a conflict for the audit report (A8), not something to tidy away by
        # dropping the half that agreed.
        supporting_span=supporting if verdict != "unsupported" else None,
        contradicting_spans=contradicting,
        capped=bool(caps),
        cap_reasons=tuple(caps),
        dropped_quotes=dropped,
    )


def _real_spans(
    quotes: Sequence[str], evidence: ValidatorEvidence
) -> tuple[tuple[Citation, ...], tuple[str, ...]]:
    """Split quotes into the spans that are really in the evidence and the ones that are not.

    Deduplicated by span identity: a model naming the same sentence twice has found one
    contradiction, and a claims table listing it twice reads as two.
    """
    found: list[Citation] = []
    seen: set[tuple[str, int, str]] = set()
    missing: list[str] = []
    for quote in quotes:
        span = evidence.find(quote)
        if span is None:
            if quote.strip():
                missing.append(quote)
            continue
        if span.identity() in seen:
            continue
        seen.add(span.identity())
        found.append(span)
    return tuple(found), tuple(missing)


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

#: A throwaway citation, so the question "does this verdict block?" can be put to the IR
#: itself. `Claim.citations` has `min_length=1` (A1), so asking needs an object to ask with.
_PROBE_CITATION = Citation.for_quote(
    doc_id="a3-probe",
    page=1,
    bbox=(0.0, 0.0, 1.0, 1.0),
    quote="probe",
    retrieved_by="validator",
)

#: Answered once, at import, by `Claim.blocks_render` — the IR's rule, not a copy of it.
#: A restatement here would be one `or` away from disagreeing with the model that the
#: renderer, the audit report and this guard all read, and the disagreement would look
#: exactly like a passing build.
_BLOCKS_RENDER: dict[str, bool] = {
    verdict: Claim(
        text="verdict probe", citations=[_PROBE_CITATION], verdict=verdict
    ).blocks_render()
    for verdict in get_args(Verdict)
}


def verdict_blocks_render(verdict: Verdict) -> bool:
    """Whether A3 forbids a claim carrying `verdict` from reaching final render.

    The answer is `Claim.blocks_render`'s, looked up rather than recomputed. Callers that
    hold a verdict but not yet a claim — the validation agent mid-assessment, the render
    guard reading a `Demotion` — ask here and get the same answer the IR would give.
    """
    return _BLOCKS_RENDER[verdict]


BLOCKING_VERDICTS: frozenset[str] = frozenset(
    verdict for verdict, blocks in _BLOCKS_RENDER.items() if blocks
)
"""The verdicts that bar a final render, derived from the IR rather than declared."""


@dataclass(frozen=True)
class ClaimBlock:
    """A claim-bearing block, located. What a report or a guard needs to name it.

    `Deck.blocking_blocks()` returns `Block` objects, which carry no slide id — and "block
    b3 is contradicted" sends a reviewer through the whole deck looking for b3.
    """

    slide_id: str
    block_id: str
    verdict: Verdict
    notes: str = ""

    def __str__(self) -> str:
        detail = f" — {self.notes}" if self.notes else ""
        return f"slide {self.slide_id} block {self.block_id}: {self.verdict}{detail}"


def blocking_blocks(deck: Deck) -> list[ClaimBlock]:
    """Every block whose verdict forbids final render, with the slide it sits on.

    Delegates the rule to `Block.blocks_render()`. This function is about *locating* them;
    what counts as blocking is the IR's to say and is said in exactly one place.
    """
    return [
        _locate(slide.id, block)
        for slide in deck.slides
        for block in slide.all_blocks()
        if block.blocks_render()
    ]


def unverified_claims(deck: Deck) -> list[ClaimBlock]:
    """Every claim block the validator never reached.

    A3's first clause is *"every claim gets a verdict"*, and `unverified` is not one of the
    four. It does not block under `Claim.blocks_render` — correctly, since that method
    answers A3's second clause — so a deck whose validation pass failed outright has a
    clean `blocking_blocks()` and no verdicts at all. That is the same shape of trap as a
    framing demotion, which is why the render guard consults this too.
    """
    return [
        _locate(slide.id, block)
        for slide in deck.slides
        for block in slide.all_blocks()
        if block.claim is not None and block.claim.verdict == "unverified"
    ]


def _locate(slide_id: str, block: Block) -> ClaimBlock:
    claim = block.claim
    return ClaimBlock(
        slide_id=slide_id,
        block_id=block.id,
        verdict=claim.verdict if claim is not None else "unverified",
        notes=(claim.verdict_notes or "") if claim is not None else "",
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@dataclass
class VerdictReport:
    """What A3 concluded across a set of claims, in the shape the other linters report in.

    Mirrors `NumericReport` and `FramingReport` so the orchestrator reads three reports the
    same way and the audit report renders them the same way.
    """

    assessments: list[VerdictAssessment] = field(default_factory=list)
    claims_checked: int = 0

    @property
    def blocking(self) -> list[VerdictAssessment]:
        return [a for a in self.assessments if a.blocks_render()]

    @property
    def capped(self) -> list[VerdictAssessment]:
        return [a for a in self.assessments if a.capped]

    @property
    def passes(self) -> bool:
        """Whether A3 holds over these assessments. Still not a decision to render."""
        return not self.blocking

    def add(self, assessment: VerdictAssessment) -> None:
        self.assessments.append(assessment)
        self.claims_checked += 1

    def render(self) -> str:
        lines = [
            "A3 — claim verdicts",
            f"{self.claims_checked} claim(s) · {len(self.blocking)} blocking · "
            f"{len(self.capped)} capped",
            "",
        ]
        if not self.assessments:
            lines.append("Nothing was validated.")
            return "\n".join(lines)
        for assessment in self.assessments:
            lines.append(f"{assessment.verdict}: {assessment.claim_text}")
            if assessment.notes:
                lines.append(f"    {assessment.notes}")
            for span in assessment.contradicting_spans:
                lines.append(f"    contradicted by {span.doc_id} p.{span.page}: {span.quote!r}")
            for reason in assessment.cap_reasons:
                lines.append(f"    capped: {reason}")
        return "\n".join(lines)
