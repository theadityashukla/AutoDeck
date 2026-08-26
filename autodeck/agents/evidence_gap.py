"""The evidence-gap check: does the corpus actually support this key message? (task 2a.4)

Plan §6.13 gives this phase its reason for existing:

> so evidence gaps surface before a single slide is written, not at validation.

A gap caught here costs one conversational turn. Caught at GATE 2 it costs a rewrite of
every slide built on the message. Caught by the client in the room it costs the engagement.

## The shape of the problem

Classifying "is this message supported?" is a judgement, and judgement means a model — but
a model asked *"is this supported?"* while holding a page of retrieved text will say yes
far more often than it should. It is agreeable, the text is topically adjacent, and nothing
in the question pushes back.

So the work is split, and the split is the whole design:

- **Retrieval is deterministic.** `gather_evidence` searches the curated claim library and
  the corpus and returns what it found, citable spans only. Code, no model, no opinion.
- **Classification is a model judgement**, but it is *bounded* by what retrieval found.
  `EvidenceProbe.classify` will not let a verdict exceed its evidence: zero citable spans
  is `unsupported` no matter what the model returns, and the model is never asked at all in
  that case.

That ceiling is the A1-shaped part of this module. It is not a check the model is asked to
respect — it is applied to the model's answer afterwards, so a model that ignores the
instruction still cannot produce an unsupported claim marked `supported`.

## Why `thin` exists

`unsupported` is the easy case; everyone agrees it needs handling. `thin` is the message
that reads as solid in a deck and collapses when the client asks *"measured on what
hardware?"* — a memory result quoted to support a cost claim, a number that holds only
under a configuration the client does not run, a paper reporting someone else's finding.

It is also the case a hurried planner rounds up to `supported`. So `thin` is a first-class
status with its own consequences: like `unsupported`, it forces a recorded `OpenRisk`
(`KeyMessage.needs_a_risk`), which means rounding up is the only way to make it disappear
and rounding up is what the ceiling and the prompt are both built to resist.

Owning phase: 2a (task 2a.4). Opus tier — accuracy-critical per the phase brief.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from autodeck.ingest.document_store import DocumentStore, IngestError
from autodeck.ir.models import EvidenceStatus, KeyMessage, OpenRisk
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import HybridIndex, search

logger = logging.getLogger(__name__)

#: How many corpus spans to put in front of the classifier. Enough to show a real range of
#: what exists; small enough that a weak signal is not buried under topical noise.
EVIDENCE_LIMIT = 6

CLASSIFY_SYSTEM_PROMPT = """\
You judge whether retrieved evidence supports a proposed key message for a consulting deck.

You are the step that stops an unsupported assertion reaching a client. Being agreeable
here is the failure mode: the retrieved text will always be topically related, because that
is how it was retrieved. Topical relatedness is not support.

Answer with one status:

- supported: a quoted span backs the message ON THE TERMS THE MESSAGE STATES.
- thin: something related exists, but at least one of these is true —
    * it measures an adjacent quantity (memory quoted for latency, throughput for cost);
    * it holds only under a stated configuration (model size, hardware, batch size) that
      the message does not carry;
    * the source is reporting someone else's result rather than measuring it;
    * a single source says it, and the message states it as settled.
- unsupported: nothing here backs the message.

If you are between supported and thin, choose thin. A message wrongly marked thin costs one
question in a planning conversation. A message wrongly marked supported reaches a client
slide with nothing behind it.

In `reasoning`, name the specific mismatch — which quantity, which configuration, which
source — rather than restating the message. In `strongest_quote`, copy the single most
relevant span VERBATIM from the evidence provided; never paraphrase it and never write a
quote that is not in the evidence.
"""


class EvidenceClassification(BaseModel):
    """The model's judgement about one key message.

    `strongest_quote` is a lead for the writer, not a citation. It is verified to actually
    appear in the evidence that was shown (`_quote_is_real`), because a hallucinated quote
    here would travel into the brief looking exactly like a real one.
    """

    model_config = ConfigDict(extra="forbid")

    status: EvidenceStatus = Field(
        description="supported, thin, or unsupported. Never unprobed — you have looked."
    )
    reasoning: str = Field(
        min_length=1,
        description="The specific mismatch or the specific support. Not a restatement.",
    )
    strongest_quote: str = Field(
        default="", description="Verbatim span from the evidence shown. Empty if none apply."
    )


@dataclass(frozen=True)
class EvidenceSpan:
    """One candidate piece of support, with where it came from."""

    doc_id: str
    page: int
    text: str
    source: str
    """`claims.md` or `corpus` — a curated claim is a stronger starting point than a raw
    retrieval hit, and the classifier is told which it is looking at."""

    def render(self) -> str:
        return f"[{self.source} · {self.doc_id} p.{self.page}] {self.text.strip()}"


@dataclass
class ProbeResult:
    """What the check found and concluded for one key message."""

    message_id: str
    status: EvidenceStatus
    evidence: list[EvidenceSpan] = field(default_factory=list)
    reasoning: str = ""
    strongest_quote: str = ""
    capped: bool = False
    """True when the model's answer was lowered to fit the evidence actually retrieved.

    Worth surfacing rather than swallowing: a classifier that regularly needs capping is
    one to stop trusting, and that signal is invisible if the cap is silent.
    """

    def needs_a_risk(self) -> bool:
        return self.status in ("unsupported", "thin")

    def apply(self, message: KeyMessage) -> KeyMessage:
        """Return `message` updated with this probe's findings."""
        return message.model_copy(
            update={
                "evidence_status": self.status,
                "probe_notes": self.reasoning or None,
                "supporting_claims": [
                    f"{span.doc_id} p.{span.page}" for span in self.evidence[:3]
                ],
            }
        )

    def suggested_risk(self, message: KeyMessage, *, accepted_by: str) -> OpenRisk:
        """Draft the `OpenRisk` this gap would need, for the human to accept or edit.

        `accepted_by` is required rather than defaulted — the planner must have somebody's
        name before this is a recorded acceptance rather than an unaccounted gap (A7).
        """
        return OpenRisk(
            message_id=message.id,
            description=(
                self.reasoning or f"No citable support found in the corpus for: {message.text}"
            ),
            accepted_by=accepted_by,
        )


class Classifier(Protocol):
    """What the probe needs from a provider — `complete_structured` only."""

    def complete_structured(
        self,
        prompt: str,
        response_model: type[EvidenceClassification],
        *,
        system: str | None = None,
    ) -> EvidenceClassification: ...  # pragma: no cover — protocol shape only


# ---------------------------------------------------------------------------
# Gathering — deterministic
# ---------------------------------------------------------------------------


def gather_evidence(
    message_text: str,
    *,
    index: HybridIndex,
    store: DocumentStore,
    claims: list[CachedClaim] | None = None,
    limit: int = EVIDENCE_LIMIT,
) -> list[EvidenceSpan]:
    """Find candidate support for a message. No model, no judgement.

    The curated claim library is searched first and its hits lead the list — D8 makes
    `claims.md` the main road and retrieval the long tail, and a curated claim has already
    been read by a human.

    Only **citable** spans are returned. A figure description can be retrieved and is
    genuinely useful for finding the right page, but it can never back a claim (§6.3), so
    including it here would let the classifier treat generated text as evidence.
    """
    spans: list[EvidenceSpan] = []
    seen: set[tuple[str, str]] = set()

    for claim in _matching_claims(message_text, claims or []):
        try:
            citation = claim.to_citation(store=store)
        except IngestError as exc:
            # A stale cached claim is a real finding, but it is not this function's to
            # report — it must not be silently promoted into evidence either.
            logger.warning("cached claim for %r no longer resolves: %s", claim.doc_id, exc)
            continue
        key = (citation.doc_id, citation.quote)
        if key in seen:
            continue
        seen.add(key)
        spans.append(
            EvidenceSpan(
                doc_id=citation.doc_id,
                page=citation.page,
                text=citation.quote,
                source="claims.md",
            )
        )

    for hit in search(index, message_text, limit=limit, citable_only=True):
        key = (hit.doc_id, hit.text)
        if key in seen:
            continue
        seen.add(key)
        spans.append(
            EvidenceSpan(doc_id=hit.doc_id, page=hit.page, text=hit.text, source="corpus")
        )

    return spans[:limit]


def _matching_claims(message_text: str, claims: list[CachedClaim]) -> list[CachedClaim]:
    """Cached claims sharing meaningful vocabulary with the message.

    Deliberately crude — a token overlap, not a ranking. `claims.md` is a curated library
    of tens of entries, not a corpus, so recall matters far more than precision and a
    missed curated claim is the expensive error.
    """
    from autodeck.retrieval.hybrid import tokenize

    wanted = set(tokenize(message_text)) - _STOPWORDS
    if not wanted:
        return []
    scored = [
        (len(wanted & (set(tokenize(claim.claim)) | set(tokenize(claim.quote)))), claim)
        for claim in claims
    ]
    return [claim for overlap, claim in sorted(scored, key=lambda p: -p[0]) if overlap >= 2]


#: Words carrying no topical signal, held as prose because that is how it stays readable
#: and editable — a 45-element list literal is harder to scan and harder to add to.
_STOPWORD_TEXT = (
    "a an the is are was were be been being of to in on for by with and or but that "
    "this it its as at from we our their has have had can could will would should "
    "more most than then so if not no"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


# ---------------------------------------------------------------------------
# Probing — model judgement, bounded
# ---------------------------------------------------------------------------


@dataclass
class EvidenceProbe:
    """Probes key messages against the corpus.

    Holds the index, store and curated claims for one project so the planner session can
    probe repeatedly through a conversation without reassembling them.
    """

    index: HybridIndex
    store: DocumentStore
    claims: list[CachedClaim] = field(default_factory=list)
    classifier: Classifier | None = None
    """Omit to run gathering only. Every message then comes back `unsupported` when nothing
    citable was found and `unprobed` when something was — never `supported`, because
    nothing judged it."""

    def probe(self, message: KeyMessage) -> ProbeResult:
        """Classify one key message against the evidence.

        Raises nothing on a model failure — a probe that cannot reach a verdict returns
        `unprobed` with the reason, which the planner surfaces. Failing the whole session
        because one classification errored would be worse than saying "nobody looked".
        """
        evidence = gather_evidence(
            message.text, index=self.index, store=self.store, claims=self.claims
        )

        # The ceiling, applied before the model is consulted rather than after. With no
        # citable span there is nothing to be right about, so there is no question to ask.
        if not evidence:
            return ProbeResult(
                message_id=message.id,
                status="unsupported",
                reasoning=(
                    "No citable span in the curated claims or the corpus matches this "
                    "message. Retrieval found nothing to judge."
                ),
            )

        if self.classifier is None:
            return ProbeResult(
                message_id=message.id,
                status="unprobed",
                evidence=evidence,
                reasoning=(
                    f"{len(evidence)} candidate span(s) found but no classifier was "
                    "supplied, so nothing has judged whether they support the message."
                ),
            )

        try:
            judgement = self.classifier.complete_structured(
                _classification_prompt(message.text, evidence),
                EvidenceClassification,
                system=CLASSIFY_SYSTEM_PROMPT,
            )
        except Exception as exc:  # any provider failure, deliberately broad
            logger.warning("evidence classification failed for %s: %s", message.id, exc)
            return ProbeResult(
                message_id=message.id,
                status="unprobed",
                evidence=evidence,
                reasoning=f"Classification failed ({type(exc).__name__}); nobody judged this.",
            )

        status, capped = _cap(judgement.status, evidence)
        quote = judgement.strongest_quote.strip()
        return ProbeResult(
            message_id=message.id,
            status=status,
            evidence=evidence,
            reasoning=judgement.reasoning.strip(),
            strongest_quote=quote if _quote_is_real(quote, evidence) else "",
            capped=capped,
        )

    def probe_all(self, messages: list[KeyMessage]) -> list[ProbeResult]:
        return [self.probe(message) for message in messages]


def _cap(status: EvidenceStatus, evidence: list[EvidenceSpan]) -> tuple[EvidenceStatus, bool]:
    """Lower a verdict that outruns its evidence. Returns `(status, was_capped)`.

    A single corpus hit cannot make a message `supported`. That is precisely the shape the
    prompt calls thin — one source, stated as settled — and encoding it here means a model
    that ignores the instruction still cannot produce the wrong answer.

    A single **curated** claim is different and is left alone: a human already read it,
    checked the quote, and wrote down what it does and does not say.
    """
    if status != "supported":
        return status, False
    if len(evidence) == 1 and evidence[0].source != "claims.md":
        return "thin", True
    return status, False


def _quote_is_real(quote: str, evidence: list[EvidenceSpan]) -> bool:
    """Whether `quote` actually appears in what the model was shown.

    A fabricated quote travelling into the brief would look identical to a real one, and
    the writer would go looking for a sentence that does not exist. Matching is done with
    the same normalisation the citation resolver uses, so a ligature or curly quote does
    not cause a false rejection.
    """
    if not quote:
        return False
    from autodeck.ingest.provenance import find_span

    return any(find_span(span.text, quote) is not None for span in evidence)


def _classification_prompt(message_text: str, evidence: list[EvidenceSpan]) -> str:
    rendered = "\n\n".join(f"{i}. {span.render()}" for i, span in enumerate(evidence, start=1))
    return (
        f"PROPOSED KEY MESSAGE:\n{message_text}\n\n"
        f"RETRIEVED EVIDENCE ({len(evidence)} span(s)):\n\n{rendered}\n\n"
        "Does this evidence support the message on the terms the message states?"
    )
