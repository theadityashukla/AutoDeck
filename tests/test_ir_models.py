"""Deck IR model tests.

The A1 tests here are the reason the IR is built first. If one of them ever needs changing
in order to pass, something has gone wrong upstream of it — plan §0.4 and D9: never weaken
an invariant to make a test pass.
"""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from autodeck.ir.models import (
    Block,
    BlockKind,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    Deck,
    Derivation,
    DerivationInput,
    DiagramEdge,
    DiagramNode,
    DiagramSpec,
    IconRef,
    Slide,
    quote_digest,
)

QUOTE = "Throughput rose from 412 to 671 sequences per second."


def make_citation(quote: str = QUOTE, **overrides: object) -> Citation:
    fields: dict[str, object] = {
        "doc_id": "doc-1",
        "page": 3,
        "bbox": (10.0, 20.0, 300.0, 44.0),
        "quote": quote,
        "retrieved_by": "writer",
    }
    fields.update(overrides)
    return Citation.for_quote(**fields)  # type: ignore[arg-type]


def make_claim(**overrides: object) -> Claim:
    fields: dict[str, object] = {"text": "Throughput improved.", "citations": [make_citation()]}
    fields.update(overrides)
    return Claim(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A1 — universal citation. These are the invariant tests.
# ---------------------------------------------------------------------------


def test_claim_without_citations_is_rejected() -> None:
    """A1, enforced structurally: a claim with no evidence cannot be constructed."""
    with pytest.raises(ValidationError) as excinfo:
        Claim(text="Throughput improved 62.9%.", citations=[])
    assert "citations" in str(excinfo.value)


def test_claim_block_without_a_claim_is_rejected() -> None:
    """A1's other half: the block kind and its payload must agree."""
    with pytest.raises(ValidationError, match="needs a claim"):
        Block(id="b1", kind="claim", slot="body", text="Throughput improved 62.9%.")


def test_a_claim_block_requires_the_claim_to_carry_citations() -> None:
    """The two halves compose: there is no route to a citation-free claim block."""
    with pytest.raises(ValidationError):
        Block(id="b1", kind="claim", slot="body", claim=Claim(text="x", citations=[]))


def test_speaker_notes_are_blocks_and_get_the_same_treatment() -> None:
    """A1 applies to notes, not just the slide face — the usual hiding place."""
    with pytest.raises(ValidationError, match="needs a claim"):
        Slide(
            id="s1",
            narrative_role="evidence",
            component="big_number",
            speaker_notes=[Block(id="n1", kind="claim", slot="notes", text="uncited aside")],
        )


# ---------------------------------------------------------------------------
# Citation hash self-verification
# ---------------------------------------------------------------------------


def test_citation_hash_must_match_its_quote() -> None:
    with pytest.raises(ValidationError, match="does not match quote"):
        Citation(
            doc_id="doc-1",
            page=1,
            bbox=(0.0, 0.0, 1.0, 1.0),
            quote=QUOTE,
            quote_sha256=quote_digest("a different quote"),
            retrieved_by="writer",
        )


def test_mutating_a_stored_quote_fails_the_hash_check() -> None:
    """Simulates drift between the IR and the document store."""
    payload = make_citation().model_dump(mode="json")
    payload["quote"] = payload["quote"].replace("671", "871")
    with pytest.raises(ValidationError, match="does not match quote"):
        Citation.model_validate(payload)


def test_for_quote_round_trips() -> None:
    citation = make_citation()
    assert citation.quote_sha256 == quote_digest(QUOTE)
    assert Citation.model_validate(citation.model_dump(mode="json")) == citation


# ---------------------------------------------------------------------------
# A2 — derivations
# ---------------------------------------------------------------------------


def test_derivation_inputs_must_appear_in_the_claim_citations() -> None:
    """Otherwise the audit report shows working that cites sources it never lists."""
    cited = make_citation()
    elsewhere = make_citation(quote="An unrelated span from another document.")
    with pytest.raises(ValidationError, match="not present in claim citations"):
        Claim(
            text="Throughput improved 62.9%.",
            citations=[cited],
            derivation=Derivation(
                formula="(new - old) / old * 100",
                inputs={"new": DerivationInput(value=671.0, citation=elsewhere)},
                result=62.9,
                unit="%",
            ),
        )


def test_derivation_carries_values_so_the_formula_can_be_re_executed() -> None:
    """A2 requires re-execution; a citation alone has no value to substitute (B13)."""
    citation = make_citation()
    claim = make_claim(
        citations=[citation],
        derivation=Derivation(
            formula="(new - old) / old * 100",
            inputs={
                "new": DerivationInput(value=671.0, citation=citation),
                "old": DerivationInput(value=412.0, citation=citation),
            },
            result=62.86407766990291,
            unit="%",
        ),
    )
    assert claim.derivation is not None
    values = {name: item.value for name, item in claim.derivation.inputs.items()}
    recomputed = (values["new"] - values["old"]) / values["old"] * 100
    assert recomputed == pytest.approx(claim.derivation.result)


# ---------------------------------------------------------------------------
# A3 — verdicts gate the render
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", ["unsupported", "contradicted"])
def test_failing_verdicts_block_render(verdict: str) -> None:
    deck = _deck_with_verdict(verdict)
    assert [b.id for b in deck.blocking_blocks()] == ["b1"]


@pytest.mark.parametrize("verdict", ["unverified", "supported", "partially_supported"])
def test_other_verdicts_do_not_block_render(verdict: str) -> None:
    assert _deck_with_verdict(verdict).blocking_blocks() == []


def _deck_with_verdict(verdict: str) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="a",
        version=1,
        theme_ref="t",
        component_lib_version="0.1.0",
        slides=[
            Slide(
                id="s1",
                narrative_role="evidence",
                component="big_number",
                blocks=[
                    Block(
                        id="b1",
                        kind="claim",
                        slot="body",
                        claim=make_claim(verdict=verdict),
                    )
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Block / slide / deck structure
# ---------------------------------------------------------------------------


def test_a_block_carries_exactly_one_payload() -> None:
    with pytest.raises(ValidationError, match="a block has exactly one payload"):
        Block(
            id="b1",
            kind="claim",
            slot="body",
            claim=make_claim(),
            icon=IconRef(concept="growth", glyph_id="trending-up", color_token="accent1"),
        )


@pytest.mark.parametrize("kind", ["framing", "section_header"])
def test_text_kinds_require_non_empty_text(kind: str) -> None:
    with pytest.raises(ValidationError, match="needs non-empty text"):
        Block(id="b1", kind=cast(BlockKind, kind), slot="body", text="   ")


def test_extra_fields_are_forbidden() -> None:
    """LLM structured output must not be able to smuggle a field past the schema."""
    with pytest.raises(ValidationError):
        Block.model_validate(
            {
                "id": "b1",
                "kind": "framing",
                "slot": "body",
                "text": "ok",
                "verdict": "supported",
            }
        )


def test_duplicate_block_ids_within_a_slide_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate block ids"):
        Slide(
            id="s1",
            narrative_role="evidence",
            component="bullets_supporting",
            blocks=[
                Block(id="dup", kind="framing", slot="a", text="one"),
                Block(id="dup", kind="framing", slot="b", text="two"),
            ],
        )


def test_duplicate_slide_ids_are_rejected() -> None:
    slide = Slide(id="s1", narrative_role="evidence", component="quote")
    with pytest.raises(ValidationError, match="duplicate slide ids"):
        Deck(
            run_id="r1",
            project="p",
            client="c",
            audience="a",
            version=1,
            theme_ref="t",
            component_lib_version="0.1.0",
            slides=[slide, slide],
        )


# ---------------------------------------------------------------------------
# Chart and diagram payloads
# ---------------------------------------------------------------------------


def test_chart_requires_data_provenance() -> None:
    """D10: a chart whose numbers cannot be traced is the screenshot D10 forbids."""
    with pytest.raises(ValidationError):
        ChartSpec(
            chart_type="column",
            categories=["a", "b"],
            series=[ChartSeries(name="s", values=[1.0, 2.0])],
            source_citations=[],
        )


def test_chart_series_must_align_with_categories() -> None:
    with pytest.raises(ValidationError, match="one value per category"):
        ChartSpec(
            chart_type="column",
            categories=["a", "b", "c"],
            series=[ChartSeries(name="s", values=[1.0, 2.0])],
            source_citations=[make_citation()],
        )


def test_diagram_edges_must_resolve_to_nodes() -> None:
    with pytest.raises(ValidationError, match="unknown node ids"):
        DiagramSpec(
            kind="process_flow",
            nodes=[DiagramNode(id="n1", label="Ingest")],
            edges=[DiagramEdge(source="n1", target="n2")],
        )


def test_diagram_node_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate diagram node ids"):
        DiagramSpec(
            kind="cycle",
            nodes=[DiagramNode(id="n1", label="A"), DiagramNode(id="n1", label="B")],
        )
