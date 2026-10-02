"""The validation agent: independent re-retrieval, and `verdicts.py`'s rule applied to it.

The load-bearing test is `test_a_valid_writer_citation_does_not_save_a_contradicted_claim`
— the one property v1 never had (`legacy/v1/LEGACY.md`, `verdicts.py`'s own docstring): a
claim whose own citation is perfectly valid still comes back `contradicted` when the
validator's independent search turns up a span elsewhere that disagrees with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.agents.validation import (
    BATCH_SIZE,
    ClaimJudgement,
    ValidationAgentError,
    ValidationDraft,
    gather_validator_evidence,
    validate_deck,
)
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.ir.models import (
    Block,
    Citation,
    Claim,
    Deck,
    DiagramSpec,
    LabelFraming,
    ProcessFlowSpec,
    ProcessStep,
    Slide,
)
from autodeck.retrieval.hybrid import build_index

PROMPT = Path("prompts/validation.md")


class Scripted:
    """A fake `validation` model returning one fixed batch response for every call."""

    def __init__(self, by_claim_id: dict[str, VerdictJudgement]) -> None:
        self.by_claim_id = by_claim_id
        self.prompts: list[str] = []
        self.calls = 0

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.prompts.append(prompt)
        judgements = [
            ClaimJudgement(claim_id=claim_id, judgement=judgement)
            for claim_id, judgement in self.by_claim_id.items()
            if claim_id in prompt
        ]
        return ValidationDraft(judgements=judgements)


class Broken:
    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider down")


def element(
    element_id: str, text: str, *, doc_id: str = "paper-1", page: int = 1, kind: str = "text"
) -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id=doc_id,
        kind=kind,  # type: ignore[arg-type]
        page=page,
        bbox=(72.0, 100.0, 523.0, 200.0),
        reading_order=0,
        text=text,
    )


def store_and_index(tmp_path: Path, *elements: DocumentElement):  # type: ignore[no-untyped-def]
    document = Document(
        doc_id="paper-1", source_path="paper-1.pdf", page_count=6, elements=list(elements)
    )
    store = DocumentStore(tmp_path)
    store.add(document)
    index = build_index([document], project="llm-inference-efficiency")
    return store, index


def writer_citation(store: DocumentStore, quote: str) -> Citation:
    return store.resolve_quote("paper-1", quote, retrieved_by="writer")


def claim_block(block_id: str, claim: Claim) -> Block:
    return Block(id=block_id, kind="claim", slot="figure", claim=claim)


def deck_with(*slides: Slide) -> Deck:
    return Deck(
        run_id="northwind-2026-08",
        project="llm-inference-efficiency",
        client="northwind",
        audience="CTO",
        version=1,
        slides=list(slides),
        theme_ref="northwind-theme",
        component_lib_version="0.1.0",
    )


SUPPORT_QUOTE = "quantisation cuts the memory needed for inference by half"
CONTRADICTION_QUOTE = (
    "our method currently does not provide speedups for the inference multiplications "
    "due to the lack of hardware support for mixed-precision operands"
)


# ---------------------------------------------------------------------------
# Independence: only validator-retrieved spans ever become evidence
# ---------------------------------------------------------------------------


def test_gathered_evidence_is_always_retrieved_by_validator(tmp_path: Path) -> None:
    store, index = store_and_index(
        tmp_path, element("e1", SUPPORT_QUOTE), element("e2", CONTRADICTION_QUOTE, page=2)
    )
    claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )

    evidence = gather_validator_evidence(claim, index=index, store=store)

    assert evidence
    assert all(span.retrieved_by == "validator" for span in evidence.spans)


def test_the_writers_own_citation_object_never_appears_as_evidence(tmp_path: Path) -> None:
    """Independent re-retrieval may land on the SAME sentence the writer cited — that is
    confirmation, not contamination — but the object handed to `assess_claim` as evidence is
    always the validator's own re-resolution, never the writer's `Citation` instance."""
    store, index = store_and_index(tmp_path, element("e1", SUPPORT_QUOTE))
    writer_cite = writer_citation(store, SUPPORT_QUOTE)
    claim = Claim(text="Quantisation speeds up inference.", citations=[writer_cite])

    evidence = gather_validator_evidence(claim, index=index, store=store)

    assert writer_cite not in evidence.spans
    assert any(span.quote == writer_cite.quote for span in evidence.spans)
    echoes = evidence.echoes_of(claim.citations)
    assert len(echoes) == 1


# ---------------------------------------------------------------------------
# Contradiction search is a real search
# ---------------------------------------------------------------------------


def test_a_valid_writer_citation_does_not_save_a_contradicted_claim(tmp_path: Path) -> None:
    """The property v1 never had: a claim with a perfectly valid citation is still
    `contradicted` when independent search finds a disagreeing span elsewhere."""
    store, index = store_and_index(
        tmp_path, element("e1", SUPPORT_QUOTE), element("e2", CONTRADICTION_QUOTE, page=2)
    )
    claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[claim_block("b1", claim)],
    )
    model = Scripted(
        {
            "s1:b1": VerdictJudgement(
                verdict="contradicted",
                verdict_notes="GPTQ says the opposite.",
                contradicting_quotes=[CONTRADICTION_QUOTE],
            )
        }
    )

    result = validate_deck(deck_with(slide), index=index, store=store, model=model)

    [assessment] = result.report.assessments
    assert assessment.verdict == "contradicted"
    assert assessment.contradicting_spans
    assert assessment.contradicting_spans[0].quote == CONTRADICTION_QUOTE

    updated_claim = result.deck.slides[0].blocks[0].claim
    assert updated_claim is not None
    assert updated_claim.verdict == "contradicted"
    assert updated_claim.contradicting_spans
    # The writer's own (valid) citation is untouched — the contradiction is recorded
    # alongside it, not in place of it.
    assert updated_claim.citations[0].quote == SUPPORT_QUOTE
    assert result.deck.blocking_blocks()


def test_a_fabricated_contradiction_the_model_cannot_quote_is_dropped(tmp_path: Path) -> None:
    store, index = store_and_index(tmp_path, element("e1", SUPPORT_QUOTE))
    claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[claim_block("b1", claim)],
    )
    model = Scripted(
        {
            "s1:b1": VerdictJudgement(
                verdict="contradicted",
                verdict_notes="I recall a paper that disagrees.",
                contradicting_quotes=["a sentence that appears nowhere in the evidence shown"],
            )
        }
    )

    result = validate_deck(deck_with(slide), index=index, store=store, model=model)

    [assessment] = result.report.assessments
    assert assessment.verdict == "unsupported"
    assert assessment.capped


# ---------------------------------------------------------------------------
# Failure is unverified, never a guess
# ---------------------------------------------------------------------------


def test_a_broken_provider_yields_unverified_when_evidence_exists(tmp_path: Path) -> None:
    store, index = store_and_index(tmp_path, element("e1", SUPPORT_QUOTE))
    claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[claim_block("b1", claim)],
    )

    result = validate_deck(deck_with(slide), index=index, store=store, model=Broken())

    [assessment] = result.report.assessments
    assert assessment.verdict == "unverified"


def test_a_broken_provider_yields_unsupported_when_nothing_was_retrieved(
    tmp_path: Path,
) -> None:
    # A corpus sharing no vocabulary at all with the claim OR the contradiction-search
    # hints, so BM25 has nothing to score and both independent searches come back empty.
    unrelated = "Zebra migration patterns across arid regions each summer."
    store, index = store_and_index(tmp_path, element("e1", unrelated))
    claim = Claim(
        text="Quantisation speeds up inference on GPUs.",
        citations=[writer_citation(store, unrelated)],
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[claim_block("b1", claim)],
    )

    result = validate_deck(deck_with(slide), index=index, store=store, model=Broken())

    [assessment] = result.report.assessments
    assert assessment.verdict == "unsupported"


# ---------------------------------------------------------------------------
# Deck-level: every block including notes and diagram-node claims
# ---------------------------------------------------------------------------


def test_speaker_note_claims_and_diagram_node_claims_are_both_validated(tmp_path: Path) -> None:
    store, index = store_and_index(tmp_path, element("e1", SUPPORT_QUOTE))
    face_claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    note_claim = Claim(
        text="This is discussed further in the appendix.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    diagram_claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    diagram_block = Block(
        id="b2",
        kind="diagram",
        slot="diagram",
        diagram=DiagramSpec(
            relationship="sequence",
            kind="process_flow",
            process_flow=ProcessFlowSpec(
                steps=[
                    ProcessStep(id="n1", label="Quantise", order=1, claim=diagram_claim),
                    ProcessStep(
                        id="n2",
                        label="Serve",
                        order=2,
                        framing=LabelFraming(reason="stage_name"),
                    ),
                ]
            ),
        ),
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[claim_block("b1", face_claim), diagram_block],
        speaker_notes=[claim_block("note1", note_claim)],
    )
    model = Scripted(
        {
            claim_id: VerdictJudgement(
                verdict="supported",
                verdict_notes="matches",
                supporting_quote=SUPPORT_QUOTE,
            )
            for claim_id in ("s1:b1", "s1:note1", "s1:b2:n1")
        }
    )

    result = validate_deck(deck_with(slide), index=index, store=store, model=model)

    ids = {c.block_id for c in result.claims_table}
    assert {"b1", "note1", "b2"} <= ids
    assert result.deck.slides[0].blocks[0].claim.verdict == "supported"  # type: ignore[union-attr]
    assert result.deck.slides[0].speaker_notes[0].claim.verdict == "supported"  # type: ignore[union-attr]
    assert (
        result.deck.slides[0].blocks[1].diagram.nodes[0].claim.verdict == "supported"  # type: ignore[union-attr]
    )


# ---------------------------------------------------------------------------
# Batching is visible, not buried
# ---------------------------------------------------------------------------


def test_provider_calls_matches_the_number_of_batches(tmp_path: Path) -> None:
    store, index = store_and_index(tmp_path, element("e1", SUPPORT_QUOTE))
    claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    blocks = [claim_block(f"b{i}", claim) for i in range(BATCH_SIZE + 3)]
    slide = Slide(id="s1", narrative_role="evidence", component="big_number", blocks=blocks)
    model = Scripted(
        {
            f"s1:b{i}": VerdictJudgement(
                verdict="supported", verdict_notes="ok", supporting_quote=SUPPORT_QUOTE
            )
            for i in range(BATCH_SIZE + 3)
        }
    )

    result = validate_deck(deck_with(slide), index=index, store=store, model=model)

    assert result.provider_calls == 2  # ceil((BATCH_SIZE + 3) / BATCH_SIZE)
    assert model.calls == 2
    assert len(result.claims_table) == BATCH_SIZE + 3


def test_default_batch_size_keeps_a_ten_slide_deck_well_under_daily_quota() -> None:
    """~30 claims (3 per slide, 10 slides) at the default batch size stays far under the
    dev tier's 20 requests/day/model (B25) — the arithmetic this module's docstring names."""
    import math

    assert math.ceil(30 / BATCH_SIZE) < 20


# ---------------------------------------------------------------------------
# Plumbing failures
# ---------------------------------------------------------------------------


def test_missing_prompt_file_raises(tmp_path: Path) -> None:
    store, index = store_and_index(tmp_path, element("e1", SUPPORT_QUOTE))
    claim = Claim(
        text="Quantisation speeds up inference.",
        citations=[writer_citation(store, SUPPORT_QUOTE)],
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[claim_block("b1", claim)],
    )

    with pytest.raises(ValidationAgentError):
        validate_deck(
            deck_with(slide),
            index=index,
            store=store,
            model=Scripted({}),
            prompt_path=tmp_path / "no-such-prompt.md",
        )
