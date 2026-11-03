"""B55 in the IR: `Claim.basis`, `Deck.provenance`, and strict mode enforced structurally."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.ir.actions import facts_digest
from autodeck.ir.models import (
    CONVERSATION_DOC_PREFIX,
    Block,
    Citation,
    Claim,
    Deck,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def _citation(doc_id: str = "paper-1") -> Citation:
    return Citation.for_quote(
        doc_id=doc_id, page=1, bbox=(0, 0, 1, 1), quote="a real sentence", retrieved_by="writer"
    )


def _deck_with(claim: Claim, provenance: str) -> Deck:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["provenance"] = provenance
    deck = Deck.model_validate(raw)
    slide = deck.slides[0]
    block = Block(id="bx", kind="claim", slot="points", claim=claim)
    data = deck.model_dump(mode="json")
    data["slides"][0]["blocks"].append(block.model_dump(mode="json"))
    data["slides"][0]["id"] = slide.id
    return Deck.model_validate(data)


def test_default_basis_still_requires_a_citation() -> None:
    with pytest.raises(ValidationError, match="cited claim needs at least one citation"):
        Claim(text="x")


def test_unsourced_claim_carries_no_evidence() -> None:
    assert Claim(text="general knowledge", basis="unsourced").citations == []
    with pytest.raises(ValidationError, match="unsourced claim carries no citations"):
        Claim(text="x", basis="unsourced", citations=[_citation()])


def test_uncorroborated_is_only_for_unsourced_claims() -> None:
    Claim(text="x", basis="unsourced", verdict="uncorroborated")
    with pytest.raises(ValidationError, match="only for unsourced claims"):
        Claim(text="x", citations=[_citation()], verdict="uncorroborated")


def test_uncorroborated_does_not_block_render() -> None:
    assert not Claim(text="x", basis="unsourced", verdict="uncorroborated").blocks_render()


def test_source_class_reads_the_doc_id() -> None:
    assert _citation().source_class == "corpus"
    assert _citation("client-deck--q3").source_class == "client_deck"
    assert _citation(f"{CONVERSATION_DOC_PREFIX}run1").source_class == "conversation"


def test_a_deck_with_no_provenance_field_is_strict() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw.pop("provenance", None)
    assert Deck.model_validate(raw).provenance == "strict"


@pytest.mark.parametrize(
    "claim",
    [
        Claim(text="general knowledge", basis="unsourced"),
        Claim(text="you said so", citations=[_citation(f"{CONVERSATION_DOC_PREFIX}run1")]),
    ],
    ids=["unsourced", "conversation"],
)
def test_strict_deck_refuses_non_document_sources(claim: Claim) -> None:
    with pytest.raises(ValidationError, match="strict deck cites documents only"):
        _deck_with(claim, "strict")
    assert _deck_with(claim, "normal").provenance == "normal"


def test_changing_mode_changes_the_facts_digest() -> None:
    claim = Claim(text="cited", citations=[_citation()])
    assert facts_digest(_deck_with(claim, "strict")) != facts_digest(
        _deck_with(claim, "normal")
    )
