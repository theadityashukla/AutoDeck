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

## Batching is by prompt size, and independence is who judges, not how many calls (B44)

Claims are packed into structured-output calls by an approximate **token budget** for the
batch prompt (`batch_budget_tokens`, default 48,000; a token is estimated as
`len(text) // 4` characters, which is crude and deliberately so — it only has to keep a
prompt from growing without bound, not predict a bill). The budget counts what actually
makes a prompt large: each claim, the writer's citations, and the evidence that claim's own
independent retrieval found. A five-slide deck's ~15 claims is therefore ONE call. A hard
cap, `MAX_BATCH_CLAIMS`, stops a single response growing past a sane size however short the
evidence is. (`BATCH_SIZE` is kept as an alias of that cap for older importers; it used to
be a fixed 6, which turned a 15-claim deck into three calls for no reason.)

Why this is safe: A3's independence is a property of *who judges and from what evidence* —
a different model, evidence this module retrieved itself, `retrieved_by="validator"` — and
none of that depends on how many claims share a call. Retrieval and the contradiction
query run per claim exactly as before. `ValidationResult.provider_calls` still reports the
number, so it is measured on a real run rather than estimated. The dev tier's
20-requests-per-day-per-model allowance (B25) is why fewer calls matter at all.

## Unchanged claims keep their verdict

A revision redoes only what it touches (B44). When `validate_deck` is given the `previous`
deck, a claim whose identity — its site (`slide:block[:node]`), its text, and the
`(doc_id, page, quote_sha256)` of each of its citations — matches a claim in `previous`
that already carries a judged verdict is not sent to the model again: its verdict, notes and
contradicting spans are copied across verbatim, and `ValidationResult.reused` counts them.
A claim still `unverified` in `previous` (never judged, or its batch failed) is judged
afresh, never "reused". The key is deliberately strict: change the text or swap one cited
quote and the claim is re-judged, because a verdict is a statement about that exact claim
against that exact evidence. If nothing changed there are zero calls.

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
from collections.abc import Iterator, Sequence
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
from autodeck.ir.models import (
    CONVERSATION_DOC_PREFIX,
    Citation,
    Claim,
    ClaimSite,
    Deck,
    HeadlineCheck,
    HeadlineVerdict,
    Slide,
    StorylineCheck,
    StorylineFinding,
    StorylineIssue,
)
from autodeck.retrieval.hybrid import HybridIndex, RetrievedSpan, search

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/validation.md")

#: Default approximate token budget for one batch prompt (claims + writer citations + the
#: evidence each claim's independent retrieval found). Tokens are estimated as
#: `len(text) // 4`. See the module docstring (B44).
BATCH_BUDGET_TOKENS = 48_000

#: Hard cap on claims in one call, so a single response stays a sane size however small the
#: prompt is.
MAX_BATCH_CLAIMS = 40

#: Older name for the claim cap; it used to be a fixed batch size of 6.
BATCH_SIZE = MAX_BATCH_CLAIMS

#: Citable spans retrieved per claim, per search. Two searches per claim (support and
#: contradiction), each capped here — generous enough to show the model a real spread of
#: what the corpus says, small enough that a batch stays a reasonable single
#: prompt (the same shape of concern `evidence_gap.py`'s `SPAN_CHARS` names, B24).
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


class HeadlineJudgement(BaseModel):
    """One talking header's judgement against its own slide's claims (B62)."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1, description="Copied from the slide as it was shown.")
    verdict: HeadlineVerdict
    notes: str = Field(
        description=(
            "For 'overstates': exactly what the header says that the claims do not — the "
            "stronger word, the wider population, the comparator that tied. '' if carried."
        )
    )


class HeadlineDraft(BaseModel):
    """Every judged header in one response. Required and non-nullable (B26)."""

    model_config = ConfigDict(extra="forbid")

    judgements: list[HeadlineJudgement] = Field(min_length=1)


class StorylineFindingDraft(BaseModel):
    """One header's problem in the storyline, as the validator returns it (B70)."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1, description="Copied from the header as it was shown.")
    issue: StorylineIssue
    notes: str = Field(
        description=(
            "What is wrong, fixable in one edit: for 'unspeakable', the fragment and how a "
            "presenter would say it; for 'breaks_chain', the missing step; for 'repeats', "
            "which earlier slide already made the point."
        )
    )


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
#
# This module used to own the walk: `Block.claim` directly, plus `DiagramNode.claim`
# nested inside a diagram block. It was correct, and it was the *only* correct one — the
# blocking checks had their own, narrower walk, so a `contradicted` diagram node validated
# here was cleared to render there. The walk now lives on the IR (`Deck.claim_sites`), and
# this module reads it like everyone else.


def _claim_sites(deck: Deck) -> list[ClaimSite]:
    """Every claim in the deck, faces, notes and diagram nodes alike."""
    return deck.claim_sites()


def _estimate_tokens(text: str) -> int:
    """Approximate token count: four characters to a token. Crude on purpose (B44)."""
    return len(text) // 4


def _pack_batches(
    sites: Sequence[ClaimSite],
    evidence: dict[str, ValidatorEvidence],
    *,
    budget_tokens: int,
    max_claims: int,
) -> Iterator[list[ClaimSite]]:
    """Greedily pack sites, in deck order, into batches under the token and claim caps.

    A single claim whose own prompt exceeds the budget still gets a batch of one — it is
    judged, never dropped.
    """
    batch: list[ClaimSite] = []
    used = 0
    for site in sites:
        cost = _estimate_tokens(_render_claim_section(site, evidence[site.claim_id]))
        if batch and (len(batch) >= max_claims or used + cost > budget_tokens):
            yield batch
            batch, used = [], 0
        batch.append(site)
        used += cost
    if batch:
        yield batch


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
    extra_spans: Sequence[RetrievedSpan] = (),
) -> ValidatorEvidence:
    """Independently retrieve support and contradiction evidence for one claim.

    Two searches from the claim's own text — never from the writer's citation, and never
    from the writer's original retrieval query, neither of which this function is even
    handed. `ValidatorEvidence`'s constructor is the structural half of A3's independence
    requirement; this function is what keeps every span offered to it genuinely
    `retrieved_by="validator"`.

    `extra_spans` are spans the index does not hold but the validator must be able to see —
    in `normal` mode, the person's own conversation (B55), offered whole. They are resolved
    through the same `_resolve_spans`, so they too arrive as `retrieved_by="validator"`.
    """
    support_hits = search(index, claim.text, limit=support_limit, citable_only=True)
    contradiction_hits = search(
        index,
        f"{claim.text} {CONTRADICTION_QUERY_HINTS}",
        limit=contradiction_limit,
        citable_only=True,
    )
    spans = _resolve_spans((*support_hits, *contradiction_hits, *extra_spans), store=store)
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


def _render_claim_section(site: ClaimSite, evidence: ValidatorEvidence) -> str:
    return (
        f"## claim_id: {site.claim_id}\n\n"
        f"claim: {site.claim.text}\n\n"
        f"{_render_writer_citation(site.claim)}\n\n"
        f"independently retrieved evidence (support and contradiction searches, "
        f"combined):\n{_render_evidence(evidence)}"
    )


def _render_terms(terms: Sequence[str]) -> str:
    """Engagement memory's Terms as context (B79): never evidence, never a citation."""
    if not terms:
        return ""
    lines = "\n".join(f"- {term}" for term in terms)
    return (
        "Engagement terms (context, not evidence) — how this engagement spells names and "
        "acronyms, and what a transcript has misheard them as:\n"
        f"{lines}\n\n---\n\n"
    )


def _render_batch_prompt(
    sites: Sequence[ClaimSite],
    evidence: dict[str, ValidatorEvidence],
    terms: Sequence[str] = (),
) -> str:
    parts = [_render_claim_section(site, evidence[site.claim_id]) for site in sites]
    return (
        _render_terms(terms)
        + f"Judge each of the following {len(sites)} claim(s). Return one judgement per "
        "claim_id, copied exactly as shown.\n\n" + "\n\n---\n\n".join(parts)
    )


def _judge_batch(
    sites: Sequence[ClaimSite],
    evidence: dict[str, ValidatorEvidence],
    *,
    model: ValidationModel,
    system: str,
    terms: Sequence[str] = (),
) -> dict[str, VerdictJudgement]:
    """One structured-output call for a whole batch. Never raises.

    A provider failure — network, rate limit, exhausted repair attempts — is exactly the
    posture `EvidenceProbe.probe` takes: log it, return nothing, and let the caller's
    `assess_claim` decide the honest verdict from the evidence alone. Claiming a judgement
    happened when it did not would be worse than admitting the check did not run.
    """
    try:
        draft = model.complete_structured(
            _render_batch_prompt(sites, evidence, terms), ValidationDraft, system=system
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
# Talking headers (B62)
# ---------------------------------------------------------------------------
#
# A header has no citation of its own (B54), so the claim pass above never judged one. Code
# already checks that its numbers and names appear on the slide (draft checks); only a model
# can tell that "beat empagliflozin" is stronger than "similar to empagliflozin". The header
# is judged against the slide's own claims and their verdicts — not re-retrieved: whether a
# claim is true is the claim pass's question, whether the header says more than the claims
# is this one's.


def _headline_of(slide: Slide) -> str | None:
    for block in slide.blocks:
        if block.slot == "headline" and block.kind == "section_header" and block.text:
            return block.text
    return None


def _face_claims(deck: Deck, slide_id: str) -> list[Claim]:
    return [
        site.claim
        for site in deck.claim_sites()
        if site.slide_id == slide_id and not site.in_speaker_notes
    ]


def _headline_key(headline: str, claims: Sequence[Claim]) -> tuple[str, tuple[str, ...]]:
    return headline, tuple(c.text for c in claims)


def _render_headline_prompt(items: Sequence[tuple[Slide, str, list[Claim]]]) -> str:
    parts = []
    for slide, headline, claims in items:
        lines = [f"## slide_id: {slide.id}", "", f"headline: {headline}", "", "claims on this slide:"]
        lines.extend(f"  - [{c.verdict}] {c.text}" for c in claims)
        if not claims:
            lines.append("  (none — this slide carries no cited claim)")
        parts.append("\n".join(lines))
    return (
        f"Judge each of the following {len(items)} slide headline(s) against the claims on "
        "the same slide, as the **Talking headers** section of your instructions describes. "
        "A headline is `carried` when every part of it is stated or directly summarised by "
        "the claims shown, at no greater strength. It `overstates` when it says anything "
        "stronger, wider or different: a comparator that tied described as beaten, a group "
        "of comparators where the claims cover only some, a population the claims do not "
        "name, a causal or general statement from a measured result, or a fact no claim "
        "states. A claim marked unsupported or contradicted cannot carry the headline. A slide "
        "with no claims carries a headline only if it asserts nothing about the world: an "
        "ask, a decision, a question or the route through the deck is carried; a statement "
        "of benefit, effect or comparison overstates. "
        "Return one judgement per slide_id, copied exactly as shown.\n\n"
        + "\n\n---\n\n".join(parts)
    )


def check_headlines(
    deck: Deck,
    *,
    model: ValidationModel,
    system: str,
    previous: Deck | None = None,
) -> int:
    """Judge every content slide's talking header against its own claims. Mutates `deck`.

    Slides with no headline are skipped (`headline_check` stays None). A slide with no
    face claims is still judged: its header may ask or decide, but not assert (a closing
    slide's "significant benefits" sat over no claim at all in run XLP). A
    header whose text and claims match the `previous` deck's same slide keeps that verdict.
    One call for all the rest. A failed call leaves them unjudged, never `carried`.

    Returns:
        The number of provider calls made (0 or 1).
    """
    earlier: dict[str, tuple[tuple[str, tuple[str, ...]], HeadlineCheck]] = {}
    if previous is not None:
        for slide in previous.slides:
            headline = _headline_of(slide)
            if headline is not None and slide.headline_check is not None:
                key = _headline_key(headline, _face_claims(previous, slide.id))
                earlier[slide.id] = (key, slide.headline_check)

    pending: list[tuple[Slide, str, list[Claim]]] = []
    for slide in deck.slides:
        headline = _headline_of(slide)
        claims = _face_claims(deck, slide.id)
        if headline is None:
            continue
        reuse = earlier.get(slide.id)
        if reuse is not None and reuse[0] == _headline_key(headline, claims):
            slide.headline_check = reuse[1]
            continue
        pending.append((slide, headline, claims))
    if not pending:
        return 0

    try:
        draft = model.complete_structured(
            _render_headline_prompt(pending), HeadlineDraft, system=system  # type: ignore[arg-type]
        )
    except Exception as exc:  # any provider failure, deliberately broad
        logger.warning(
            "headline check of %d slide(s) failed (%s): %s — left unjudged",
            len(pending),
            type(exc).__name__,
            exc,
        )
        return 1
    by_id = {item.slide_id: item for item in draft.judgements}
    for slide, headline, _claims in pending:
        item = by_id.get(slide.id)
        if item is None:
            continue
        slide.headline_check = HeadlineCheck(
            verdict=item.verdict,
            notes=item.notes.strip() if item.verdict == "overstates" else "",
            headline=headline,
        )
    return 1


# ---------------------------------------------------------------------------
# The storyline: the headers read in order (B70)
# ---------------------------------------------------------------------------
#
# `check_headlines` asks whether each header is true of its own slide. This asks whether
# the headers, read aloud in order, are one argument a presenter could actually say. A
# deck can pass the first and fail the second completely: every header carried, and the
# whole a list of facts.

STORY_SLOTS = ("headline", "title", "takeaway")
"""The slot that carries a slide's line in the storyline, in order of preference: a
content slide's talking header, the title slide's title, a callout's takeaway."""


def story_line_of(slide: Slide) -> str | None:
    """The sentence this slide contributes to the storyline, or None."""
    by_slot = {b.slot: b.text for b in slide.blocks if b.text}
    for slot in STORY_SLOTS:
        if by_slot.get(slot):
            return by_slot[slot]
    return None


class StorylineDraft(BaseModel):
    """The validator's reading of the whole storyline. Required fields (B26)."""

    model_config = ConfigDict(extra="forbid")

    tells_story: bool
    summary: str = Field(description="One or two sentences on the storyline as a whole.")
    findings: list[StorylineFindingDraft] = Field(
        description="One entry per header with a problem; [] when there is none."
    )


def _render_storyline_prompt(deck: Deck, lines: Sequence[tuple[Slide, str]]) -> str:
    rows = "\n".join(
        f"{n}. [slide_id: {slide.id} · role: {slide.narrative_role}] {line}"
        for n, (slide, line) in enumerate(lines, start=1)
    )
    return (
        "Read these headers aloud, in order, as the **Storyline** section of your "
        "instructions describes. They are the only words most of the audience will "
        f"remember.\n\nAudience: {deck.audience}\n\n{rows}\n\n"
        "Say whether they tell one connected story, and list every header that is "
        "`unspeakable`, `breaks_chain` or `repeats`, with slide_id copied exactly."
    )


def check_storyline(
    deck: Deck,
    *,
    model: ValidationModel,
    system: str,
    previous: Deck | None = None,
) -> int:
    """Judge the deck's headers in order as one argument. Mutates `deck`. Advisory.

    Skipped (and left None) for a deck with fewer than two lines. If the lines are
    exactly those `previous` judged, its check is reused. A failed call leaves the
    check None, never a pass.

    Returns:
        The number of provider calls made (0 or 1).
    """
    lines = [(s, line) for s in deck.slides if (line := story_line_of(s)) is not None]
    if len(lines) < 2:
        deck.storyline_check = None
        return 0
    texts = [line for _s, line in lines]
    if (
        previous is not None
        and previous.storyline_check is not None
        and previous.storyline_check.headlines == texts
    ):
        deck.storyline_check = previous.storyline_check
        return 0
    try:
        draft = model.complete_structured(
            _render_storyline_prompt(deck, lines), StorylineDraft, system=system  # type: ignore[arg-type]
        )
    except Exception as exc:  # any provider failure, deliberately broad
        logger.warning(
            "storyline check failed (%s): %s — left unjudged", type(exc).__name__, exc
        )
        return 1
    known = {s.id for s, _line in lines}
    deck.storyline_check = StorylineCheck(
        tells_story=draft.tells_story,
        summary=draft.summary.strip(),
        findings=[
            StorylineFinding(slide_id=f.slide_id, issue=f.issue, notes=f.notes.strip())
            for f in draft.findings
            if f.slide_id in known and f.notes.strip()
        ],
        headlines=texts,
    )
    return 1


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
    reused: int = 0
    """Claims whose verdict was copied from `previous` rather than judged again."""


def _identity(site: ClaimSite) -> tuple[object, ...]:
    """What makes a claim "the same claim" for verdict reuse: where it is, what it says, and
    exactly which quotes it cites."""
    return (
        site.claim_id,
        site.claim.text,
        tuple((c.doc_id, c.page, c.quote_sha256) for c in site.claim.citations),
    )


def _reusable(previous: Deck | None) -> dict[tuple[object, ...], Claim]:
    if previous is None:
        return {}
    return {
        _identity(site): site.claim
        for site in _claim_sites(previous)
        if site.claim.verdict != "unverified"
    }


def _assessment_from_claim(claim: Claim) -> VerdictAssessment:
    """A report row for a reused verdict.

    The model's chosen supporting span is not stored on the claim, so a reused `supported`
    verdict is reported against the claim's own first citation purely to satisfy
    `VerdictAssessment`'s shape check; the report prints verdict and notes, not that span.
    """
    return VerdictAssessment(
        claim_text=claim.text,
        verdict=claim.verdict,
        notes=claim.verdict_notes or "",
        supporting_span=claim.citations[0] if claim.verdict == "supported" else None,
        contradicting_spans=tuple(claim.contradicting_spans),
    )


def conversation_spans_for(deck: Deck, *, store: DocumentStore) -> tuple[RetrievedSpan, ...]:
    """Every span of the conversation document(s) the deck cites, in `normal` mode (B55).

    Empty for a `strict` deck, or one with no `conversation--` citation, or when the store
    cannot supply the document (the claim then simply gets no conversation evidence).
    """
    if deck.provenance != "normal":
        return ()
    from autodeck.agents.evidence_pack import document_spans

    doc_ids = sorted(
        {
            c.doc_id
            for site in deck.claim_sites()
            for c in site.claim.citations
            if c.doc_id.startswith(CONVERSATION_DOC_PREFIX)
        }
    )
    spans: list[RetrievedSpan] = []
    for doc_id in doc_ids:
        try:
            spans.extend(document_spans(store.get(doc_id)))
        except IngestError:
            continue
    return tuple(spans)


def validate_deck(
    deck: Deck,
    *,
    index: HybridIndex,
    store: DocumentStore,
    model: ValidationModel,
    prompt_path: Path = PROMPT_PATH,
    batch_budget_tokens: int = BATCH_BUDGET_TOKENS,
    max_batch_claims: int = MAX_BATCH_CLAIMS,
    previous: Deck | None = None,
    terms: Sequence[str] = (),
) -> ValidationResult:
    """Validate every claim in `deck` — faces, notes, and diagram-node claims alike.

    Mutates `deck` in place (see `ValidationResult`) and returns it alongside the claims
    table data and the blocking set's inputs. Retrieval is deterministic and free; only the
    structured-output calls count against the `validation` role's quota. Claims are packed
    into calls by `batch_budget_tokens` (about `len(text) // 4` tokens of prompt per batch)
    and at most `max_batch_claims` per call. When `previous` is given, claims identical to a
    judged claim there reuse its verdict instead of being judged again (see the module
    docstring); `ValidationResult.reused` counts them. `terms` (B79) is engagement memory's
    Terms section, shown to every claim batch as context so a transcript's "APID" is not
    read as contradicting the engagement's "APLD"; it is never evidence.

    Raises:
        ValidationAgentError: the prompt file named by `prompt_path` is missing. Never
            raised for a claim's own verdict — see the module docstring's failure posture.
    """
    system = _read_prompt(prompt_path)
    sites = _claim_sites(deck)

    known = _reusable(previous)
    reused_claims: dict[str, Claim] = {}
    to_judge: list[ClaimSite] = []
    for site in sites:
        earlier = known.get(_identity(site))
        if earlier is None:
            to_judge.append(site)
        else:
            reused_claims[site.claim_id] = earlier

    conversation = conversation_spans_for(deck, store=store)
    evidence = {
        site.claim_id: gather_validator_evidence(
            site.claim, index=index, store=store, extra_spans=conversation
        )
        for site in to_judge
    }
    assessments: dict[str, VerdictAssessment] = {}
    provider_calls = 0

    for batch in _pack_batches(
        to_judge, evidence, budget_tokens=batch_budget_tokens, max_claims=max_batch_claims
    ):
        judgements = _judge_batch(batch, evidence, model=model, system=system, terms=terms)
        provider_calls += 1
        for site in batch:
            assessment = assess_claim(
                site.claim,
                evidence=evidence[site.claim_id],
                judgement=judgements.get(site.claim_id),
            )
            assessments[site.claim_id] = assessment
            site.replace(assessment.apply(site.claim))

    report = VerdictReport()
    claims_table: list[ClaimBlock] = []
    for site in sites:  # deck order, whether judged or reused
        earlier = reused_claims.get(site.claim_id)
        if earlier is not None:
            assessment = _assessment_from_claim(earlier)
            site.replace(
                site.claim.model_copy(
                    update={
                        "verdict": earlier.verdict,
                        "verdict_notes": earlier.verdict_notes,
                        "contradicting_spans": list(earlier.contradicting_spans),
                    }
                )
            )
        else:
            assessment = assessments[site.claim_id]
        report.add(assessment)
        claims_table.append(
            ClaimBlock(
                slide_id=site.slide_id,
                block_id=site.block_id,
                verdict=assessment.verdict,
                notes=assessment.notes,
                node_id=site.node_id,
            )
        )

    provider_calls += check_headlines(deck, model=model, system=system, previous=previous)
    provider_calls += check_storyline(deck, model=model, system=system, previous=previous)

    return ValidationResult(
        deck=deck,
        report=report,
        claims_table=claims_table,
        provider_calls=provider_calls,
        reused=len(reused_claims),
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
