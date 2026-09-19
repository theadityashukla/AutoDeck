"""The validation agent: independent re-retrieval, batched judgement, `verdicts.py`'s rule.

`autodeck/agents/planner.py` is the closest sibling in register; `autodeck/audit/verdicts.py`
is the closest sibling in *purpose*, and this module is its wrapper — plumbing that
assembles evidence and a model judgement and hands both to `assess_claim`, never deciding a
verdict itself. Read `verdicts.py`'s own module docstring first; nothing here restates the
rule, only what surrounds it.

## Independence is enforced by the type this module builds, not by convention

`autodeck.audit.verdicts.ValidatorEvidence` refuses at construction to hold any `Citation`
not marked `retrieved_by="validator"`. That is deliberate: it makes "the validator treated
the writer's citation as evidence" — the defining v1 failure — unreachable by accident. This
module works *with* that constraint rather than around it: every span this agent hands to
`ValidatorEvidence` comes from this agent's own `HybridIndex.search` calls, resolved through
`RetrievedSpan.to_citation(..., retrieved_by="validator")` — the same blessed helper
`agents/content.py` uses for the writer's side, reused rather than a second path invented
for this side. The writer's own citation reaches this module only as `Claim.citations`, a
visibly separate argument passed straight through to `assess_claim`, exactly as
`verdicts.py`'s docstring describes.

## Two searches, not one

`prompts/validation.md` names the failure mode plainly: a validator that only searches for
support cannot return `contradicted`, which is the one verdict v1 could never produce. So
every claim gets **two** independent, deterministic retrieval queries — one built to find
agreement, one built to find disagreement (`CONTRADICTION_QUERY_HINTS`) — and both sets of
citable hits become the evidence pool the model judges against. Search is code, not
judgement, so neither call counts against the `validation` role's daily quota; only the
structured-output call per batch does.

**Being honest about what the contradiction query is.** It is a lexical heuristic — the
claim's own text plus a fixed set of hedge-and-limitation vocabulary — not a model deciding
what would refute the claim. That is weaker than a validator that reasons about what
counter-evidence would look like and searches for it specifically, and it is the trade this
module makes for staying at one judgement call per batch rather than a planning call before
every retrieval. If eval numbers ever show this heuristic missing real contradictions the
corpus contains, the fix is a model call that proposes the contradiction query per claim
before this one that judges the evidence it finds — a second call per claim, still batched,
not a return to one call per claim per query.

## The batch size is a number you should be able to see, not infer

`BATCH_SIZE` claims go into one structured-output call. A ten-slide deck with, say, three
claim-bearing blocks per slide (faces and notes together) is on the order of thirty claims;
at the default batch size that is `ceil(30 / BATCH_SIZE)` calls to the `validation` role,
comfortably inside the dev tier's 20-requests-per-day-per-model allowance (B25) without the
deck needing one call per claim, let alone one call per claim per retry. `ValidationResult`
carries `provider_calls` so this number is measured on a real run rather than estimated.

## Failure is `unverified`, never a guess

If a batch call raises, every claim in it gets `judgement=None`, and `assess_claim` decides
what that means — `unverified` if this agent's own retrieval found something to judge,
`unsupported` if it found nothing at all, exactly the same distinction `EvidenceProbe.probe`
draws for a classifier that never ran. This module never invents a verdict to paper over a
provider outage.

## The seam `prompts/validation.md` cannot close on its own

The prompt (task 2b.7, not touched here — `prompts/` is a guardrail path) is written as
though the model returns **citation objects** — "verbatim, with its doc_id, page and bbox"
— and as though supporting evidence is a **list** of spans, plural, the way contradicting
evidence is. Neither is true of what a model can actually produce or what this module's
schema accepts: `verdicts.VerdictJudgement` — reused here unmodified, per the instruction not
to re-implement what already exists — asks for a single `supporting_quote` string and a list
of `contradicting_quotes` strings, nothing else. A model has no way to compute a bounding box
or a SHA-256 (`VerdictJudgement`'s own docstring says so), and this agent maps a verbatim
quote back onto whichever independently retrieved `Citation` contains it — the same move
`EvidenceClassification.strongest_quote` and `agents/content.py`'s citation resolution make.

The exact correction this report recommends for `prompts/validation.md`, so it can be made
in that file's own task rather than worked around here:

> Your answer is a `verdict`, a `verdict_notes` line, **the single strongest quote** that
> supports the claim, and **every quote** that contradicts it — each copied verbatim from
> the evidence you were shown. These are quotes, not citation objects: you have no way to
> compute a page, a bounding box or a hash, and the system resolves each quote you name back
> onto the real span it came from. A quote that does not match anything you were shown is
> dropped, which is why copying it exactly, spacing included, matters more than anything
> else in this document.

Owning phase: 2b (task 2b.8b). Sonnet tier — implementation against `prompts/validation.md`
(Opus) and `autodeck/audit/verdicts.py` (Opus, guardrail); this module is the plumbing
between them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from autodeck.audit.verdicts import (
    ClaimBlock,
    ValidatorEvidence,
    VerdictAssessment,
    VerdictJudgement,
    VerdictReport,
    assess_claim,
)
from autodeck.ingest.document_store import DocumentStore, IngestError
from autodeck.ir.models import Block, Citation, Claim, Deck, DiagramNode
from autodeck.retrieval.hybrid import HybridIndex, RetrievedSpan, search

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/validation.md")

#: How many claims one structured-output call judges at once. See the module docstring's
#: worked arithmetic for why this, not one call per claim, is what keeps a deck's validation
#: pass inside the dev tier's daily quota (B25).
BATCH_SIZE = 6

#: Citable spans retrieved per claim, per search. Two searches per claim (support and
#: contradiction), each capped here — generous enough to show the model a real spread of
#: what the corpus says, small enough that a batch of `BATCH_SIZE` claims stays a reasonable
#: single prompt (the same shape of concern `evidence_gap.py`'s `SPAN_CHARS` names, B24).
SUPPORT_LIMIT = 5
CONTRADICTION_LIMIT = 5

#: Appended to the claim's own text to build the contradiction-search query. Deliberately a
#: fixed lexical heuristic rather than a model call — see the module docstring's honesty
#: about what this buys and what it does not.
CONTRADICTION_QUERY_HINTS = (
    "limitation however does not fail contrary counterexample no evidence caveat "
    "in contrast negative result does not hold"
)


class ValidationAgentError(RuntimeError):
    """The validation agent cannot proceed at all — not a single claim's verdict.

    A batch call failing is not this: that is handled per claim, per the module docstring's
    "failure is unverified" posture. This is for the surrounding plumbing — nothing to
    validate, or a caller error.
    """


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


class ClaimJudgement(BaseModel):
    """One claim's judgement inside a batch response.

    `judgement` is `verdicts.VerdictJudgement` unmodified — reused, not re-specified, so the
    boundary between the four verdicts is defined in exactly one place. `claim_id` is this
    module's own bookkeeping, matching whichever id the claim was shown under in the prompt.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, description="Copied from the claim as it was shown.")
    judgement: VerdictJudgement


class ValidationDraft(BaseModel):
    """A batch's worth of judgements. Required and non-nullable (B26): a `list | None` field
    can arrive silently absent, and a batch that reads as "validated" while carrying no
    judgements at all is the exact failure this schema shape exists to make impossible."""

    model_config = ConfigDict(extra="forbid")

    judgements: list[ClaimJudgement] = Field(min_length=1)


class ValidationModel(Protocol):
    """What the agent needs from a provider, bound to the `validation` role in config."""

    def complete_structured(
        self,
        prompt: str,
        response_model: type[ValidationDraft],
        *,
        system: str | None = None,
    ) -> ValidationDraft: ...  # pragma: no cover — protocol shape only


# ---------------------------------------------------------------------------
# Claim sites — where a claim lives, and how to write a validated one back
# ---------------------------------------------------------------------------


@dataclass
class ClaimSite:
    """One claim in the deck, plus how to replace it once it has a verdict.

    Claims live in two places in the IR — `Block.claim` directly, and, nested inside a
    diagram block, `DiagramNode.claim` — and A3 does not care which; a diagram node whose
    label asserts a fact is a claim like any other (`autodeck/ir/models.py`'s own words).
    Rather than special-case the second everywhere a claim is visited, each site carries its
    own setter, so `validate_deck`'s main loop only ever sees "a claim, and a place to put
    the validated one back".
    """

    claim_id: str
    """`slide_id:block_id` or `slide_id:block_id:node_id` — unique across the deck, since
    slide ids are deck-unique and block/node ids are unique within their parent."""
    slide_id: str
    block_id: str
    claim: Claim
    _write: Callable[[Claim], None]

    def apply(self, assessment: VerdictAssessment) -> None:
        self._write(assessment.apply(self.claim))


def _claim_sites(deck: Deck) -> list[ClaimSite]:
    """Every claim in the deck, faces and speaker notes alike (`Slide.all_blocks`)."""
    sites: list[ClaimSite] = []
    for slide in deck.slides:
        for block in slide.all_blocks():
            if block.claim is not None:
                sites.append(_block_site(slide.id, block.id, block.claim, block))
            if block.diagram is not None:
                for node in block.diagram.nodes:
                    if node.claim is not None:
                        sites.append(_node_site(slide.id, block.id, node))
    return sites


def _block_site(slide_id: str, block_id: str, claim: Claim, block: Block) -> ClaimSite:
    def write(new_claim: Claim) -> None:
        block.claim = new_claim

    return ClaimSite(
        claim_id=f"{slide_id}:{block_id}",
        slide_id=slide_id,
        block_id=block_id,
        claim=claim,
        _write=write,
    )


def _node_site(slide_id: str, block_id: str, node: DiagramNode) -> ClaimSite:
    assert node.claim is not None

    def write(new_claim: Claim) -> None:
        node.claim = new_claim

    return ClaimSite(
        claim_id=f"{slide_id}:{block_id}:{node.id}",
        slide_id=slide_id,
        block_id=block_id,
        claim=node.claim,
        _write=write,
    )


def _chunks(items: Sequence[ClaimSite], size: int) -> Iterator[list[ClaimSite]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


# ---------------------------------------------------------------------------
# Independent re-retrieval — deterministic, two searches per claim
# ---------------------------------------------------------------------------


def _resolve_spans(spans: Sequence[RetrievedSpan], *, store: DocumentStore) -> list[Citation]:
    """Resolve retrieved spans into validator citations, dropping any that will not resolve.

    Reuses `RetrievedSpan.to_citation` exactly as `agents/content.py` does — the citability
    check and the element-scoped search both happen there, not re-implemented here. A span
    that fails (stale index, non-citable) is simply not evidence; it is not this function's
    job to report that, since a validator search turning up some uncitable noise among ten
    genuine hits is normal and not a finding.
    """
    resolved: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for span in spans:
        key = (span.doc_id, span.element_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            resolved.append(span.to_citation(store, retrieved_by="validator"))
        except IngestError:
            continue
    return resolved


def gather_validator_evidence(
    claim: Claim,
    *,
    index: HybridIndex,
    store: DocumentStore,
    support_limit: int = SUPPORT_LIMIT,
    contradiction_limit: int = CONTRADICTION_LIMIT,
) -> ValidatorEvidence:
    """Independently retrieve support and contradiction evidence for one claim.

    Two searches from the claim's own text — never from the writer's citation, and never
    from the writer's original retrieval query, neither of which this function is even
    handed. `ValidatorEvidence`'s constructor is the structural half of A3's independence
    requirement; this function is what keeps every span offered to it genuinely
    `retrieved_by="validator"`.
    """
    support_hits = search(index, claim.text, limit=support_limit, citable_only=True)
    contradiction_hits = search(
        index,
        f"{claim.text} {CONTRADICTION_QUERY_HINTS}",
        limit=contradiction_limit,
        citable_only=True,
    )
    spans = _resolve_spans((*support_hits, *contradiction_hits), store=store)
    return ValidatorEvidence(spans=tuple(spans))


# ---------------------------------------------------------------------------
# Prompt assembly and the batched judgement call
# ---------------------------------------------------------------------------


def _render_writer_citation(claim: Claim) -> str:
    lines = ["writer's citation(s) — check these, they are NOT evidence:"]
    for citation in claim.citations:
        lines.append(f"  [{citation.doc_id} p.{citation.page}] {citation.quote!r}")
    return "\n".join(lines)


def _render_evidence(evidence: ValidatorEvidence) -> str:
    if not evidence:
        return "  (independent search found nothing citable for this claim)"
    return "\n".join(
        f"  [{span.doc_id} p.{span.page}] {span.quote!r}" for span in evidence.spans
    )


def _render_batch_prompt(
    sites: Sequence[ClaimSite], evidence: dict[str, ValidatorEvidence]
) -> str:
    parts = []
    for site in sites:
        parts.append(
            f"## claim_id: {site.claim_id}\n\n"
            f"claim: {site.claim.text}\n\n"
            f"{_render_writer_citation(site.claim)}\n\n"
            f"independently retrieved evidence (support and contradiction searches, "
            f"combined):\n{_render_evidence(evidence[site.claim_id])}"
        )
    return (
        f"Judge each of the following {len(sites)} claim(s). Return one judgement per "
        "claim_id, copied exactly as shown.\n\n" + "\n\n---\n\n".join(parts)
    )


def _judge_batch(
    sites: Sequence[ClaimSite],
    evidence: dict[str, ValidatorEvidence],
    *,
    model: ValidationModel,
    system: str,
) -> dict[str, VerdictJudgement]:
    """One structured-output call for a whole batch. Never raises.

    A provider failure — network, rate limit, exhausted repair attempts — is exactly the
    posture `EvidenceProbe.probe` takes: log it, return nothing, and let the caller's
    `assess_claim` decide the honest verdict from the evidence alone. Claiming a judgement
    happened when it did not would be worse than admitting the check did not run.
    """
    try:
        draft = model.complete_structured(
            _render_batch_prompt(sites, evidence), ValidationDraft, system=system
        )
    except Exception as exc:  # any provider failure, deliberately broad
        logger.warning(
            "validation batch of %d claim(s) failed (%s): %s — treated as unjudged",
            len(sites),
            type(exc).__name__,
            exc,
        )
        return {}

    known = {site.claim_id for site in sites}
    judgements: dict[str, VerdictJudgement] = {}
    for item in draft.judgements:
        if item.claim_id not in known:
            logger.warning(
                "validation batch returned a judgement for unknown claim_id %r; ignored",
                item.claim_id,
            )
            continue
        judgements[item.claim_id] = item.judgement
    return judgements


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """What one validation pass over a deck produced.

    `deck` is the same object `validate_deck` was given, mutated in place — every validated
    `Claim.citations` is untouched and every `Claim.verdict`/`verdict_notes`/
    `contradicting_spans` is updated, exactly what `VerdictAssessment.apply` does. Callers
    call `deck.blocking_blocks()` themselves for the blocking set; this module does not
    duplicate that rule, only produces the deck it is computed from.
    """

    deck: Deck
    report: VerdictReport
    claims_table: list[ClaimBlock] = field(default_factory=list)
    provider_calls: int = 0
    """One per batch — the number this module's docstring asks you to be able to see."""


def validate_deck(
    deck: Deck,
    *,
    index: HybridIndex,
    store: DocumentStore,
    model: ValidationModel,
    prompt_path: Path = PROMPT_PATH,
    batch_size: int = BATCH_SIZE,
) -> ValidationResult:
    """Validate every claim in `deck` — faces, notes, and diagram-node claims alike.

    Mutates `deck` in place (see `ValidationResult`) and returns it alongside the claims
    table data and the blocking set's inputs. Retrieval is deterministic and free; only the
    `ceil(len(claims) / batch_size)` structured-output calls count against the `validation`
    role's quota.

    Raises:
        ValidationAgentError: the prompt file named by `prompt_path` is missing. Never
            raised for a claim's own verdict — see the module docstring's failure posture.
    """
    system = _read_prompt(prompt_path)
    sites = _claim_sites(deck)

    report = VerdictReport()
    claims_table: list[ClaimBlock] = []
    provider_calls = 0

    for batch in _chunks(sites, batch_size):
        evidence = {
            site.claim_id: gather_validator_evidence(site.claim, index=index, store=store)
            for site in batch
        }
        judgements = _judge_batch(batch, evidence, model=model, system=system)
        provider_calls += 1

        for site in batch:
            assessment = assess_claim(
                site.claim,
                evidence=evidence[site.claim_id],
                judgement=judgements.get(site.claim_id),
            )
            report.add(assessment)
            claims_table.append(
                ClaimBlock(
                    slide_id=site.slide_id,
                    block_id=site.block_id,
                    verdict=assessment.verdict,
                    notes=assessment.notes,
                )
            )
            site.apply(assessment)

    return ValidationResult(
        deck=deck, report=report, claims_table=claims_table, provider_calls=provider_calls
    )


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _read_prompt(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise ValidationAgentError(
            f"validation prompt not found at {path}. Prompts are versioned files (plan "
            "§0.5) and their hashes go into the build manifest — there is no inline "
            "fallback."
        )
    return path.read_text(encoding="utf-8")
