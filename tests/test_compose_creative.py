"""Creative mode in compose and revise (B69): the writer places each slide; code reconciles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodeck.agents.compose import (
    CreativeComposeDraft,
    CreativeComposedSlide,
    CreativeReviseDraft,
    compose_deck,
    revise_deck,
)
from autodeck.agents.repair import _retarget
from autodeck.ir.models import (
    FREE_LAYOUT_COMPONENT,
    FreeLayout,
    Placement,
    ShapeElement,
    TextElement,
)
from tests.test_compose import (
    OTHER,
    QUOTE,
    TOKENS,
    Scripted,
    claim_block,
    env,
    message,
)
from tests.test_content import context


def _frame(y: float) -> Placement:
    return Placement(x=6, y=y, w=60, h=14)


def _creative_slide(sid: str, *blocks: Any, placed: list[str] | None = None) -> CreativeComposedSlide:
    ids = placed if placed is not None else [b.id for b in blocks]
    return CreativeComposedSlide(
        id=sid,
        narrative_role="evidence",
        component="free_layout",
        intent=f"Make the point of {sid}.",
        message_ids=["km1"],
        blocks=list(blocks),
        speaker_notes=[],
        layout=FreeLayout(
            elements=[
                ShapeElement(shape="rect", frame=Placement(x=0, y=0, w=100, h=6), fill="accent1"),
                *(TextElement(block_id=i, frame=_frame(12 + 18 * n)) for n, i in enumerate(ids)),
            ],
            rationale="The claim leads; a thin band marks the section.",
        ),
    )


def _draft(*slides: CreativeComposedSlide) -> CreativeComposeDraft:
    return CreativeComposeDraft(
        objective="Decide whether to serve better.",
        audience="CTO",
        length_target=2,
        key_messages=[message("km1", "Quantisation halves memory.", "prompt", QUOTE)],
        must_include=[],
        must_avoid=[],
        slides=list(slides),
        coverage=[],
        notes="",
    )


def _compose(tmp_path: Path, draft: CreativeComposeDraft):  # type: ignore[no-untyped-def]
    store, pack = env(tmp_path)
    model = Scripted(draft)
    result = compose_deck(
        "Make a deck.", answers=[], pack=pack, context=context(), store=store, tokens=TOKENS,
        model=model, run_id="r1", client="c", project="p", theme_ref="dev",
        component_lib_version="1", repair=False, design_mode="creative",
    )
    return result, model, store, pack


def test_a_creative_draft_becomes_free_layout_slides(tmp_path: Path) -> None:
    good = _creative_slide("s1", claim_block("b1", "Quantisation halves memory.", QUOTE, slot="body"))
    result, model, _store, _pack = _compose(tmp_path, _draft(good))

    deck = result.deck
    assert deck.design_mode == "creative"
    slide = deck.slides[0]
    assert slide.component == FREE_LAYOUT_COMPONENT
    assert slide.layout is not None and slide.layout.placed_block_ids() == ["b1"]
    assert slide.layout.rationale.startswith("The claim leads")

    prompt, schema, system = model.calls[0]
    assert schema is CreativeComposeDraft
    assert "# The master you design inside" in prompt and "Safe area for text" in prompt
    assert "Components and their slot budgets" not in prompt
    assert "Creative mode: you design each slide" in (system or "")
    assert "## Skill: `slide-design`" in (system or "")


def test_a_dropped_block_takes_its_element_and_an_unplaced_one_is_reported(tmp_path: Path) -> None:
    s1 = _creative_slide(
        "s1",
        claim_block("b1", "Quantisation halves memory.", QUOTE, slot="body"),
        claim_block("b2", "Invented sentence.", "This quote is not in any paper at all.", slot="body2"),
        claim_block("b3", "Batching raises throughput.", OTHER, slot="body3"),
        placed=["b1", "b2"],
    )
    result, _model, _store, _pack = _compose(tmp_path, _draft(s1))
    slide = result.deck.slides[0]
    assert [b.id for b in slide.blocks] == ["b1"]
    assert slide.layout is not None and slide.layout.placed_block_ids() == ["b1"]
    assert any("'b2' removed" in c for c in result.corrections)
    assert any("'b3' (body3) was not placed" in c for c in result.corrections)


def test_a_structured_compose_is_unchanged(tmp_path: Path) -> None:
    from tests.test_compose import compose_draft, run_compose

    result, model, _store, _pack = run_compose(tmp_path, compose_draft())
    assert result.deck.design_mode == "structured"
    assert all(s.layout is None for s in result.deck.slides)
    assert "Components and their slot budgets" in model.calls[0][0]


def test_a_revision_of_a_creative_deck_asks_for_creative_slides(tmp_path: Path) -> None:
    first = _creative_slide("s1", claim_block("b1", "Quantisation halves memory.", QUOTE, slot="body"))
    result, _model, store, pack = _compose(tmp_path, _draft(first))

    rewrite = _creative_slide("s1", claim_block("b1", "Quantisation cuts memory in half.", QUOTE, slot="body"))
    answer = CreativeReviseDraft(
        objective="Decide whether to serve better.", audience="CTO", length_target=2,
        key_messages=[message("km1", "Quantisation halves memory.", "prompt", QUOTE)],
        must_include=[], must_avoid=[], changed_slides=[rewrite], removed_slide_ids=[],
        order=["s1"], coverage=[], reply="Reworded the claim.",
    )
    model = Scripted(answer)
    revised = revise_deck(
        "Say it more plainly", deck=result.deck, draft_brief=result.draft_brief, pack=pack,
        context=context(), store=store, tokens=TOKENS, model=model,
    )
    prompt, schema, system = model.calls[0]
    assert schema is CreativeReviseDraft
    assert "layout: " in prompt
    assert "## Skill: `slide-design`" in (system or "")
    assert revised.deck.slides[0].layout is not None
    assert revised.deck.design_mode == "creative"


def test_a_repair_that_splits_a_block_stacks_the_parts_in_its_frame() -> None:
    layout = FreeLayout(elements=[TextElement(block_id="b1", frame=Placement(x=10, y=20, w=50, h=30))])
    split = _retarget(layout, "b1", ["b1", "b1-r2"])
    frames = [(e.block_id, e.frame.y, e.frame.h) for e in split.elements]  # type: ignore[union-attr]
    assert frames == [("b1", 20, 15), ("b1-r2", 35, 15)]


def test_layout_problems_are_measured_and_only_text_fit_is_repairable(tmp_path: Path) -> None:
    from autodeck.agents.repair import repairable

    long_text = "Quantisation halves memory. " * 12
    s1 = CreativeComposedSlide(
        id="s1", narrative_role="evidence", component="free_layout", intent="x",
        message_ids=["km1"],
        blocks=[
            claim_block("b1", long_text.strip(), QUOTE, slot="body"),
            claim_block("b2", "Batching raises throughput.", OTHER, slot="aside"),
        ],
        speaker_notes=[],
        layout=FreeLayout(elements=[
            TextElement(block_id="b1", frame=Placement(x=8, y=12, w=20, h=6)),
            TextElement(block_id="b2", frame=Placement(x=10, y=14, w=40, h=10)),
        ]),
    )
    result, _model, _store, _pack = _compose(tmp_path, _draft(s1))
    kinds = {(f.kind, f.block_id) for f in result.failures}
    assert ("overflow_frame", "b1") in kinds
    assert any(kind == "layout_fit" for kind, _b in kinds)
    assert {b.id for b in result.deck.slides[0].blocks} == {"b1", "b2"}  # flagged, not dropped
    assert all(f.kind != "layout_fit" for f in repairable(result.failures))
