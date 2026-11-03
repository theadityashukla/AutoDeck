"""B55 source classes in `assess_claim`."""

from __future__ import annotations

from autodeck.audit.verdicts import ValidatorEvidence, VerdictJudgement, assess_claim
from autodeck.ir.models import Citation, Claim

PAPER = "Oral semaglutide reduced HbA1c more than sitagliptin at week 26."
SAID = "Our architecture routes every request through a retrieval layer first."


def _span(doc_id: str, quote: str, by: str = "validator") -> Citation:
    return Citation.for_quote(
        doc_id=doc_id, page=1, bbox=(0, 0, 1, 1), quote=quote, retrieved_by=by
    )  # type: ignore[arg-type]


def _judge(verdict: str, support: str = "", contra: tuple[str, ...] = ()) -> VerdictJudgement:
    return VerdictJudgement(
        verdict=verdict,  # type: ignore[arg-type]
        verdict_notes="checked",
        supporting_quote=support,
        contradicting_quotes=list(contra),
    )


def test_corpus_claim_is_not_supported_by_the_persons_words() -> None:
    claim = Claim(
        text="Requests go through retrieval first.", citations=[_span("paper", PAPER, "writer")]
    )
    evidence = ValidatorEvidence([_span("conversation--r1", SAID)])
    out = assess_claim(claim, evidence=evidence, judgement=_judge("supported", SAID))
    assert out.verdict == "unsupported"


def test_from_you_claim_is_supported_by_what_was_said() -> None:
    claim = Claim(
        text="Requests go through retrieval first.",
        citations=[_span("conversation--r1", SAID, "writer")],
    )
    evidence = ValidatorEvidence([_span("conversation--r1", SAID), _span("paper", PAPER)])
    out = assess_claim(claim, evidence=evidence, judgement=_judge("supported", SAID))
    assert out.verdict == "supported"


def test_from_you_claim_is_not_supported_by_a_paper() -> None:
    claim = Claim(
        text="Semaglutide beat sitagliptin.",
        citations=[_span("conversation--r1", SAID, "writer")],
    )
    evidence = ValidatorEvidence([_span("paper", PAPER)])
    out = assess_claim(claim, evidence=evidence, judgement=_judge("supported", PAPER))
    assert out.verdict == "unsupported"


def test_unsourced_claim_with_nothing_found_is_uncorroborated() -> None:
    claim = Claim(text="Tablets are easier to start than injections.", basis="unsourced")
    out = assess_claim(claim, evidence=ValidatorEvidence(), judgement=_judge("unsupported"))
    assert out.verdict == "uncorroborated"
    assert not out.blocks_render()


def test_unsourced_claim_can_be_contradicted_by_the_corpus() -> None:
    claim = Claim(
        text="Sitagliptin lowers HbA1c more than oral semaglutide.", basis="unsourced"
    )
    evidence = ValidatorEvidence([_span("paper", PAPER)])
    out = assess_claim(
        claim, evidence=evidence, judgement=_judge("contradicted", contra=(PAPER,))
    )
    assert out.verdict == "contradicted"


def test_unsourced_claim_supported_by_the_corpus() -> None:
    claim = Claim(
        text="Oral semaglutide lowers HbA1c more than sitagliptin.", basis="unsourced"
    )
    evidence = ValidatorEvidence([_span("paper", PAPER)])
    out = assess_claim(claim, evidence=evidence, judgement=_judge("supported", PAPER))
    assert out.verdict == "supported"
