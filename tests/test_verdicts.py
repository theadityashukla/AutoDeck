"""A3 — the four verdicts, and the ceiling that stops a model overclaiming.

The load-bearing test is `test_a_valid_citation_does_not_outrank_a_contradiction`: a claim
whose own citation resolves perfectly, refuted by a different span elsewhere in the corpus,
must come back `contradicted`. That is the phase brief's done-when and the behaviour v1's
validator could not have — it read the writer's citation and stopped there.

`test_removing_the_contradiction_rule_makes_the_claim_supported` is the same test with the
defence switched off, so that a green run proves the rule is doing the work rather than the
fixture happening to be agreeable.

Every fake model here returns `supported` by default. That agreeableness is the failure
being guarded against — the retrieved text is always topically related, because that is how
it was retrieved — and these tests assert the right verdict comes out anyway.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from autodeck.audit import verdicts
from autodeck.audit.verdicts import (
    BLOCKING_VERDICTS,
    ValidatorEvidence,
    VerdictAssessment,
    VerdictIndependenceError,
    VerdictJudgement,
    VerdictReport,
    VerdictShapeError,
    assess_claim,
    blocking_blocks,
    unverified_claims,
    verdict_blocks_render,
)
from autodeck.ir.models import Block, Citation, Claim, Deck, RetrievedBy, Slide, Verdict

#: `prompts/validation.md`'s own worked example, because the prompt is authoritative on the
#: boundary between the verdicts and the tests should be arguing about the same sentences.
CLAIM_TEXT = "Quantisation speeds up inference."
MEMORY = (
    "LLM.int8() can cut the memory needed for inference by half while retaining full "
    "precision performance on models up to 175B parameters."
)
GPTQ = (
    "our method currently does not provide speedups for the actual multiplications, due "
    "to the lack of hardware support for mixed-precision operands"
)
THROUGHPUT = (
    "vLLM improves the LLM serving throughput by 2-4x compared to the state-of-the-art "
    "systems, without affecting model accuracy."
)


def citation(
    quote: str,
    *,
    doc_id: str = "llm-int8",
    page: int = 4,
    retrieved_by: RetrievedBy = "validator",
) -> Citation:
    return Citation.for_quote(
        doc_id=doc_id,
        page=page,
        bbox=(72.0, 100.0, 523.0, 200.0),
        quote=quote,
        retrieved_by=retrieved_by,
    )


def writer_citation(quote: str = MEMORY) -> Citation:
    """A perfectly valid citation, resolved and hashed, exactly as the writer left it."""
    return citation(quote, retrieved_by="writer")


def claim(text: str = CLAIM_TEXT, *, cited: str = MEMORY) -> Claim:
    return Claim(text=text, citations=[writer_citation(cited)])


def evidence(*quotes: str) -> ValidatorEvidence:
    """Spans the validator retrieved for itself."""
    return ValidatorEvidence(
        [citation(quote, doc_id="gptq" if quote == GPTQ else "llm-int8") for quote in quotes]
    )


class AlwaysSupported:
    """The failure mode as a test double: a judgement that agrees with the writer.

    It can still *report* what it found — a contradicting span it noticed and then talked
    itself out of is the exact case A3 exists for, and the case a v1-shaped validator
    resolves in the writer's favour.
    """

    def __init__(
        self, *, supporting_quote: str = MEMORY, contradicting_quotes: list[str] | None = None
    ) -> None:
        self.supporting_quote = supporting_quote
        self.contradicting_quotes = contradicting_quotes or []

    def judge(self) -> VerdictJudgement:
        return VerdictJudgement(
            verdict="supported",
            verdict_notes="The citation resolves and says what the claim says.",
            supporting_quote=self.supporting_quote,
            contradicting_quotes=list(self.contradicting_quotes),
        )


def judgement(
    verdict: str = "supported",
    *,
    supporting_quote: str = "",
    contradicting_quotes: list[str] | None = None,
    notes: str = "Searched for the quantity, the configuration and the opposite.",
) -> VerdictJudgement:
    return VerdictJudgement(
        verdict=verdict,  # type: ignore[arg-type]
        verdict_notes=notes,
        supporting_quote=supporting_quote,
        contradicting_quotes=contradicting_quotes or [],
    )


def deck_with(*blocks: Block, notes: tuple[Block, ...] = ()) -> Deck:
    return Deck(
        run_id="r1",
        project="llm-inference-efficiency",
        client="northwind-retail",
        audience="CTO",
        version=1,
        theme_ref="t",
        component_lib_version="1",
        slides=[
            Slide(
                id="s1",
                narrative_role="evidence",
                component="text_block",
                blocks=list(blocks),
                speaker_notes=list(notes),
            )
        ],
    )


def claim_block(block_id: str, verdict: Verdict) -> Block:
    return Block(
        id=block_id,
        kind="claim",
        slot="body",
        claim=claim().model_copy(update={"verdict": verdict}),
    )


# ---------------------------------------------------------------------------
# The contradiction rule — the defining behaviour
# ---------------------------------------------------------------------------


class TestTheContradictionRule:
    def test_a_valid_citation_does_not_outrank_a_contradiction(self) -> None:
        """The brief's done-when, and the thing v1 could never do.

        The writer's citation resolves, hashes and says what it is quoted as saying. A
        different span elsewhere in the corpus refutes the claim anyway, and the model —
        agreeable, holding a citation that checks out — still answers `supported`. A
        validator that weighs the two loses this; A3 requires that the contradiction wins.
        """
        model = AlwaysSupported(contradicting_quotes=[GPTQ])

        assessment = assess_claim(
            claim(), evidence=evidence(MEMORY, GPTQ), judgement=model.judge()
        )

        assert assessment.verdict == "contradicted"
        assert [span.quote for span in assessment.contradicting_spans] == [GPTQ]
        assert assessment.blocks_render()

    def test_the_contradicting_span_reaches_the_claim(self) -> None:
        """A contradiction the audit report cannot print is a contradiction that did not
        happen — and the writer's own citation must survive for it to contradict."""
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY, GPTQ),
            judgement=AlwaysSupported(contradicting_quotes=[GPTQ]).judge(),
        )

        judged = assessment.apply(claim())

        assert judged.verdict == "contradicted"
        assert judged.blocks_render()
        assert GPTQ in judged.contradicting_spans[0].quote
        assert judged.contradicting_spans[0].retrieved_by == "validator"
        assert judged.citations == claim().citations, "the writer's citation is still there"

    def test_removing_the_contradiction_rule_makes_the_claim_supported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defence disabled, and the test goes red — so the verdict above comes from the
        rule rather than from a fixture that was going to say `contradicted` anyway."""
        monkeypatch.setattr(verdicts, "_real_spans", lambda quotes, ev: ((), ()))

        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY, GPTQ),
            judgement=AlwaysSupported(contradicting_quotes=[GPTQ]).judge(),
        )

        assert assessment.verdict == "supported"
        assert not assessment.blocks_render()

    def test_capping_the_model_is_visible(self) -> None:
        """A model that regularly needs capping is one to stop trusting on A3 (B8), and
        that signal disappears if the cap is silent."""
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY, GPTQ),
            judgement=AlwaysSupported(contradicting_quotes=[GPTQ]).judge(),
        )

        assert assessment.capped
        assert "does not outrank a contradiction" in " ".join(assessment.cap_reasons)

    def test_a_contradiction_found_under_an_unsupported_verdict_still_counts(self) -> None:
        """The rule is about the span, not about the word the model chose: a real
        contradicting span makes the verdict `contradicted` from wherever it started."""
        assessment = assess_claim(
            claim(),
            evidence=evidence(GPTQ),
            judgement=judgement("unsupported", contradicting_quotes=[GPTQ]),
        )

        assert assessment.verdict == "contradicted"

    def test_a_model_that_agrees_with_itself_is_not_capped(self) -> None:
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY, GPTQ),
            judgement=judgement("contradicted", contradicting_quotes=[GPTQ]),
        )

        assert assessment.verdict == "contradicted"
        assert not assessment.capped

    def test_a_contradiction_the_model_cannot_quote_is_not_a_contradiction(self) -> None:
        """A fabricated contradiction is worse than a missed one: it sends the writer
        hunting for a sentence that does not exist and discredits the whole table."""
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY),
            judgement=judgement(
                "contradicted",
                contradicting_quotes=["quantisation has never once made anything faster"],
            ),
        )

        assert assessment.verdict == "unsupported"
        assert assessment.contradicting_spans == ()
        assert assessment.capped
        assert assessment.dropped_quotes

    def test_two_spans_disagreeing_are_both_recorded(self) -> None:
        """A8: where sources genuinely conflict, both spans travel to the report rather
        than one being picked as the better source."""
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY, GPTQ, THROUGHPUT),
            judgement=judgement(
                "contradicted",
                supporting_quote=MEMORY,
                contradicting_quotes=[GPTQ, THROUGHPUT],
            ),
        )

        assert len(assessment.contradicting_spans) == 2
        assert assessment.supporting_span is not None, "the agreeing half is not tidied away"

    def test_the_same_span_named_twice_is_one_contradiction(self) -> None:
        assessment = assess_claim(
            claim(),
            evidence=evidence(GPTQ),
            judgement=judgement(
                "contradicted",
                contradicting_quotes=[GPTQ, "does not provide speedups"],
            ),
        )

        assert len(assessment.contradicting_spans) == 1


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------


class TestTheCeiling:
    def test_zero_retrieved_evidence_cannot_be_supported(self) -> None:
        """Zero evidence means there is nothing to be right about, whatever the model says."""
        assessment = assess_claim(
            claim(), evidence=ValidatorEvidence(), judgement=AlwaysSupported().judge()
        )

        assert assessment.verdict == "unsupported"
        assert assessment.capped

    def test_a_valid_writer_citation_does_not_stand_in_for_retrieval(self) -> None:
        """A3's failure mode in one test: the writer's citation resolves perfectly, the
        validator's own search found nothing, and that is `unsupported` — because a
        validator reading the writer's citation has only confirmed the writer."""
        perfect = claim(cited=MEMORY)
        assert perfect.citations[0].quote == MEMORY

        assessment = assess_claim(
            perfect, evidence=ValidatorEvidence(), judgement=AlwaysSupported().judge()
        )

        assert assessment.verdict == "unsupported"
        assert "not evidence" in assessment.notes

    def test_a_contradiction_cannot_rest_on_an_empty_corpus_either(self) -> None:
        """`prompts/validation.md`: believing a claim is wrong with nothing in the corpus
        saying so is `unsupported` with a note, never `contradicted`."""
        assessment = assess_claim(
            claim(),
            evidence=ValidatorEvidence(),
            judgement=judgement("contradicted", contradicting_quotes=[GPTQ]),
        )

        assert assessment.verdict == "unsupported"

    def test_a_fabricated_supporting_quote_lowers_the_verdict(self) -> None:
        """Dropping the support span drops the verdict with it: `supported` rests on a
        span, and a span that is not in the evidence was not found."""
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY, THROUGHPUT),
            judgement=judgement(
                "supported", supporting_quote="quantisation triples inference speed"
            ),
        )

        assert assessment.verdict == "unsupported"
        assert assessment.supporting_span is None
        assert assessment.dropped_quotes == ("quantisation triples inference speed",)
        assert "dropped" in assessment.notes

    def test_support_argued_in_prose_with_no_span_is_not_support(self) -> None:
        """The empty-list failure `prompts/validation.md` names: a verdict argued
        convincingly with nothing in the field the claims table actually prints."""
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY),
            judgement=judgement("supported", notes="Clearly right, see the citation."),
        )

        assert assessment.verdict == "unsupported"
        assert assessment.capped

    def test_partially_supported_also_needs_a_real_span(self) -> None:
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY),
            judgement=judgement("partially_supported", supporting_quote="halves latency"),
        )

        assert assessment.verdict == "unsupported"

    def test_a_real_supporting_quote_survives(self) -> None:
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY, THROUGHPUT),
            judgement=judgement(
                "supported", supporting_quote="cut the memory needed for inference by half"
            ),
        )

        assert assessment.verdict == "supported"
        assert assessment.supporting_span is not None
        assert assessment.supporting_span.quote == MEMORY, "the whole resolved span"
        assert not assessment.capped

    def test_no_judgement_means_unverified_rather_than_supported(self) -> None:
        """Nobody looked is a different finding from somebody looked and found nothing."""
        assessment = assess_claim(claim(), evidence=evidence(MEMORY))

        assert assessment.verdict == "unverified"
        assert "Nobody looked" in assessment.notes

    def test_no_cap_fires_when_the_model_is_within_its_evidence(self) -> None:
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY),
            judgement=judgement(
                "partially_supported",
                supporting_quote="cut the memory needed for inference by half",
            ),
        )

        assert assessment.verdict == "partially_supported"
        assert not assessment.capped
        assert assessment.cap_reasons == ()


# ---------------------------------------------------------------------------
# Independence
# ---------------------------------------------------------------------------


class TestIndependence:
    def test_the_writers_citation_cannot_be_offered_as_evidence(self) -> None:
        """v1's validator, made unconstructible: the object it mistook for evidence is one
        this type refuses to hold."""
        with pytest.raises(VerdictIndependenceError, match="retrieved by"):
            ValidatorEvidence([writer_citation()])

    def test_a_mixed_list_is_refused_whole(self) -> None:
        with pytest.raises(VerdictIndependenceError):
            ValidatorEvidence([citation(GPTQ), writer_citation()])

    def test_an_independent_hit_on_the_writers_span_is_confirmation(self) -> None:
        """Re-retrieving the same sentence is a real finding, not an error — but it is
        reported, so the table can distinguish 'found it again' from 'found something new'."""
        found_again = evidence(MEMORY, GPTQ)

        echoes = found_again.echoes_of([writer_citation(MEMORY)])

        assert [span.quote for span in echoes] == [MEMORY]
        assert all(span.retrieved_by == "validator" for span in echoes)

    def test_evidence_that_shares_nothing_with_the_writer_echoes_nothing(self) -> None:
        assert evidence(GPTQ).echoes_of([writer_citation(MEMORY)]) == ()

    def test_a_quote_is_matched_against_the_evidence_not_the_claim(self) -> None:
        """The writer's citation is not searchable material here: quoting it back does not
        make it support unless the validator's own retrieval also found it."""
        assessment = assess_claim(
            claim(cited=THROUGHPUT),
            evidence=evidence(MEMORY),
            judgement=judgement("supported", supporting_quote="2-4x"),
        )

        assert assessment.verdict == "unsupported"


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------


class TestBlocking:
    @pytest.mark.parametrize("verdict", list(get_args(Verdict)))
    def test_the_blocking_rule_is_the_irs_own(self, verdict: Verdict) -> None:
        """One rule, one place: a second copy would be one `or` away from disagreeing with
        the IR, and the disagreement would look exactly like a passing build."""
        probe = claim().model_copy(update={"verdict": verdict})
        assert verdict_blocks_render(verdict) == probe.blocks_render()

    def test_unsupported_and_contradicted_are_the_blocking_verdicts(self) -> None:
        assert set(BLOCKING_VERDICTS) == {"unsupported", "contradicted"}

    def test_partially_supported_blocks_nothing(self) -> None:
        """A8 wants hedged claims carried honestly, not removed; blocking them would push
        the whole pipeline toward rounding verdicts up."""
        assert not verdict_blocks_render("partially_supported")
        assert not verdict_blocks_render("supported")

    def test_a_partially_supported_verdict_round_trips(self) -> None:
        assessment = assess_claim(
            claim(),
            evidence=evidence(MEMORY),
            judgement=judgement(
                "partially_supported",
                supporting_quote="cut the memory needed for inference by half",
                notes="Memory is not speed; the claim names a quantity the span does not.",
            ),
        )

        judged = assessment.apply(claim())

        assert judged.verdict == "partially_supported"
        assert judged.verdict_notes is not None
        assert "Memory is not speed" in judged.verdict_notes
        assert not judged.blocks_render()

    def test_blocking_blocks_names_the_slide(self) -> None:
        """'Block b3 is contradicted' sends a reviewer through the whole deck looking for b3."""
        deck = deck_with(
            claim_block("b1", "supported"),
            claim_block("b2", "contradicted"),
            notes=(claim_block("n1", "unsupported"),),
        )

        found = blocking_blocks(deck)

        assert {(b.block_id, b.verdict) for b in found} == {
            ("b2", "contradicted"),
            ("n1", "unsupported"),
        }
        assert all(b.slide_id == "s1" for b in found)
        assert "slide s1 block b2" in str(found[0])

    def test_speaker_notes_block_a_render_too(self) -> None:
        """A1 and A3 apply to notes; a validator iterating `slide.blocks` would be blind to
        the place an unsupported number is most likely to hide."""
        deck = deck_with(
            claim_block("b1", "supported"), notes=(claim_block("n1", "contradicted"),)
        )

        assert [b.block_id for b in blocking_blocks(deck)] == ["n1"]

    def test_an_unverified_claim_does_not_show_up_as_blocking(self) -> None:
        """The trap the render guard exists for: a deck nobody validated has an empty
        `blocking_blocks()`, because no verdict is not the same as a bad verdict."""
        deck = deck_with(claim_block("b1", "unverified"))

        assert blocking_blocks(deck) == []
        assert [b.block_id for b in unverified_claims(deck)] == ["b1"]

    def test_a_validated_deck_has_nothing_unverified(self) -> None:
        deck = deck_with(
            claim_block("b1", "supported"), claim_block("b2", "partially_supported")
        )

        assert unverified_claims(deck) == []
        assert blocking_blocks(deck) == []


# ---------------------------------------------------------------------------
# Shapes that must not be constructible
# ---------------------------------------------------------------------------


class TestShape:
    def test_a_contradicted_verdict_needs_its_span(self) -> None:
        with pytest.raises(VerdictShapeError, match="no contradicting span"):
            VerdictAssessment(claim_text=CLAIM_TEXT, verdict="contradicted", notes="trust me")

    def test_a_supported_verdict_needs_its_span(self) -> None:
        with pytest.raises(VerdictShapeError, match="no supporting span"):
            VerdictAssessment(claim_text=CLAIM_TEXT, verdict="supported", notes="looks fine")

    def test_unverified_is_not_an_answer_a_model_can_give(self) -> None:
        """`unverified` is a fact about the pipeline, not about the evidence: a model
        cannot report that it did not run."""
        with pytest.raises(ValidationError):
            VerdictJudgement(verdict="unverified", verdict_notes="n/a")  # type: ignore[arg-type]

    def test_a_judgement_must_say_why(self) -> None:
        with pytest.raises(ValidationError):
            VerdictJudgement(verdict="supported", verdict_notes="")

    def test_an_invented_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            VerdictJudgement(
                verdict="supported",
                verdict_notes="ok",
                confidence=0.9,  # type: ignore[call-arg]
            )

    @pytest.mark.parametrize("verdict", list(get_args(verdicts.JudgedVerdict)))
    def test_every_judged_verdict_is_an_ir_verdict(self, verdict: str) -> None:
        assert verdict in get_args(Verdict)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class TestReport:
    def test_a_report_counts_blocking_and_capped_separately(self) -> None:
        report = VerdictReport()
        report.add(
            assess_claim(
                claim(),
                evidence=evidence(MEMORY, GPTQ),
                judgement=AlwaysSupported(contradicting_quotes=[GPTQ]).judge(),
            )
        )
        report.add(
            assess_claim(
                claim(),
                evidence=evidence(MEMORY),
                judgement=judgement(
                    "partially_supported", supporting_quote="cut the memory needed"
                ),
            )
        )

        assert report.claims_checked == 2
        assert len(report.blocking) == 1
        assert len(report.capped) == 1
        assert not report.passes

    def test_the_report_prints_the_contradicting_span(self) -> None:
        """The claims table prints spans, not reasoning."""
        report = VerdictReport()
        report.add(
            assess_claim(
                claim(),
                evidence=evidence(MEMORY, GPTQ),
                judgement=AlwaysSupported(contradicting_quotes=[GPTQ]).judge(),
            )
        )

        rendered = report.render()

        assert "contradicted by gptq p.4" in rendered
        assert "capped:" in rendered

    def test_an_empty_report_says_nothing_was_validated(self) -> None:
        assert "Nothing was validated." in VerdictReport().render()
