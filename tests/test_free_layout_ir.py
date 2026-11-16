"""Creative mode's layout IR (B69): every face block placed once, as what it is; no text in a shape."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodeck.ir.models import (
    FREE_LAYOUT_COMPONENT,
    Block,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    Deck,
    FreeLayout,
    Placement,
    ShapeElement,
    Slide,
    TextElement,
    VisualElement,
)

CITE = Citation.for_quote(
    doc_id="d1", page=1, bbox=(0.0, 0.0, 1.0, 1.0), quote="BLEU 28.4 on English-German",
    retrieved_by="writer",
)


def _blocks() -> list[Block]:
    chart = ChartSpec(
        chart_type="bar", categories=["Base", "Big"],
        series=[ChartSeries(name="BLEU", values=[27.3, 28.4])], source_citations=[CITE],
    )
    return [
        Block(id="h1", kind="section_header", slot="headline", text="Even the small model beat everything before it"),
        Block(id="b1", kind="claim", slot="body", claim=Claim(text="28.4 BLEU on English-German", citations=[CITE])),
        Block(id="c1", kind="chart", slot="chart", chart=chart),
    ]


def _frame(x: float = 5, y: float = 5, w: float = 40, h: float = 20) -> Placement:
    return Placement(x=x, y=y, w=w, h=h)


def _layout(*extra: object, emphasis: list[str] | None = None) -> FreeLayout:
    return FreeLayout(elements=[
        ShapeElement(shape="rect", frame=Placement(x=0, y=0, w=100, h=100), fill="dk1"),
        TextElement(block_id="h1", frame=_frame(), role="title", color="lt1"),
        TextElement(block_id="b1", frame=_frame(y=30)),
        VisualElement(type="chart", block_id="c1", frame=_frame(x=50, y=30), emphasis=emphasis or []),
        *extra,  # type: ignore[list-item]
    ])


def _slide(layout: FreeLayout | None, component: str = FREE_LAYOUT_COMPONENT, blocks: list[Block] | None = None) -> Slide:
    return Slide(id="s1", narrative_role="evidence", component=component,
                 blocks=blocks if blocks is not None else _blocks(), layout=layout)


def test_a_complete_layout_is_valid_and_round_trips() -> None:
    slide = _slide(_layout(emphasis=["Big"]))
    deck = Deck(run_id="r", project="p", client="c", audience="a", version=1, slides=[slide],
                theme_ref="dev", component_lib_version="1", design_mode="creative")
    again = Deck.model_validate_json(deck.model_dump_json())
    assert again == deck
    assert again.slides[0].layout.placed_block_ids() == ["h1", "b1", "c1"]  # type: ignore[union-attr]


def test_an_unplaced_face_block_is_a_dropped_fact() -> None:
    layout = FreeLayout(elements=[TextElement(block_id="h1", frame=_frame()),
                                  VisualElement(type="chart", block_id="c1", frame=_frame(y=40))])
    with pytest.raises(ValidationError, match="'b1' is not placed"):
        _slide(layout)


def test_a_block_placed_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="placed more than once"):
        _slide(_layout(TextElement(block_id="b1", frame=_frame(y=60))))


def test_a_block_is_placed_as_what_it_is() -> None:
    wrong = FreeLayout(elements=[
        TextElement(block_id="h1", frame=_frame()),
        TextElement(block_id="b1", frame=_frame(y=30)),
        TextElement(block_id="c1", frame=_frame(y=60)),
    ])
    with pytest.raises(ValidationError, match="'c1' is a chart, not text"):
        _slide(wrong)


def test_emphasis_must_name_real_chart_categories() -> None:
    with pytest.raises(ValidationError, match="not in the chart"):
        _slide(_layout(emphasis=["Huge"]))


def test_a_speaker_note_cannot_be_placed_on_the_face() -> None:
    slide_blocks = _blocks()
    note = Block(id="n1", kind="framing", slot="notes", text="Say this aloud")
    with pytest.raises(ValidationError, match="not on speaker notes"):
        Slide(id="s1", narrative_role="evidence", component=FREE_LAYOUT_COMPONENT,
              blocks=slide_blocks, speaker_notes=[note],
              layout=_layout(TextElement(block_id="n1", frame=_frame(y=70))))


def test_layout_and_component_must_agree() -> None:
    with pytest.raises(ValidationError, match="component must be"):
        _slide(_layout(), component="bullets_supporting")
    with pytest.raises(ValidationError, match="with no layout"):
        _slide(None)


def test_a_shape_carries_no_text_and_must_be_visible() -> None:
    with pytest.raises(ValidationError):
        ShapeElement.model_validate({"shape": "rect", "frame": _frame().model_dump(), "fill": "dk1", "text": "Hi"})
    with pytest.raises(ValidationError, match="needs a fill, a line"):
        ShapeElement(shape="rect", frame=_frame())


def test_a_placement_cannot_run_off_the_slide_and_colours_are_tokens() -> None:
    with pytest.raises(ValidationError, match="runs off the slide"):
        Placement(x=80, y=0, w=30, h=10)
    with pytest.raises(ValidationError):
        TextElement.model_validate({"block_id": "h1", "frame": _frame().model_dump(), "color": "#FF0000"})
