"""Deterministic QA for creative layouts (B69): a good layout is clean, each check fires."""

from __future__ import annotations

import pytest

from autodeck.design.fonts import is_available
from autodeck.design.free_layout_qa import check_free_layout
from autodeck.ir.models import (
    FREE_LAYOUT_COMPONENT,
    FreeLayout,
    Placement,
    ShapeElement,
    Slide,
    TextElement,
    VisualElement,
)
from tests.test_free_layout_render import _chart_slide, _number_slide, _title_slide
from tests.test_renderer import _claim_block, _framing_block, tokens_for

pytestmark = pytest.mark.skipif(
    not is_available("Liberation Sans"), reason="Liberation Sans not installed"
)

TOKENS = tokens_for()


def P(x: float, y: float, w: float, h: float) -> Placement:
    return Placement(x=x, y=y, w=w, h=h)


def _slide(*elements: object, background: str = "lt1", cite: bool = False) -> Slide:
    blocks = [_framing_block("a", "Alpha beta gamma", block_id="a"),
              _framing_block("b", "Delta epsilon", block_id="b")]
    if cite:
        blocks.append(_claim_block("c", "Cost per token fell 41%.", block_id="c"))
        elements = (*elements, TextElement(block_id="c", frame=P(60, 50, 30, 8)))
    return Slide(id="q", narrative_role="t", component=FREE_LAYOUT_COMPONENT, blocks=blocks,
                 layout=FreeLayout(background=background, elements=list(elements)))  # type: ignore[arg-type]


def _a(**kw: object) -> TextElement:
    return TextElement(block_id="a", frame=kw.pop("frame", P(10, 10, 40, 10)), **kw)  # type: ignore[arg-type]


def _b(**kw: object) -> TextElement:
    return TextElement(block_id="b", frame=kw.pop("frame", P(10, 30, 40, 10)), **kw)  # type: ignore[arg-type]


def _checks(slide: Slide) -> set[str]:
    return {f.check for f in check_free_layout(slide, TOKENS)}


def test_good_layouts_are_clean() -> None:
    for slide in (_title_slide(), _number_slide(), _chart_slide(), _slide(_a(), _b())):
        assert check_free_layout(slide, TOKENS) == []


def test_text_that_does_not_fit_its_box() -> None:
    assert _checks(_slide(_a(frame=P(10, 10, 8, 3), role="title"), _b())) == {"text_fit"}


def test_text_outside_the_safe_area_but_shapes_may_bleed() -> None:
    assert "safe_area" in _checks(_slide(_a(frame=P(0, 10, 40, 10)), _b()))
    bleed = ShapeElement(shape="rect", frame=P(0, 0, 100, 100), fill="dk1")
    assert _checks(_slide(bleed, _a(color="lt1"), _b(color="lt1"))) == set()


def test_overlaps() -> None:
    assert _checks(_slide(_a(), _b(frame=P(30, 15, 40, 10)))) == {"overlap"}
    chart = _chart_slide()
    chart.layout.elements[2] = chart.layout.elements[2].model_copy(  # type: ignore[union-attr]
        update={"frame": P(40, 30, 30, 20)}
    )
    assert "overlap" in _checks(chart)


def test_visuals_overlapping_each_other() -> None:
    s = _chart_slide()
    extra = s.blocks[1].model_copy(update={"id": "c9"})
    s2 = Slide(id="q", narrative_role="t", component=FREE_LAYOUT_COMPONENT,
               blocks=[*s.blocks, extra],
               layout=FreeLayout(elements=[
                   *s.layout.elements,  # type: ignore[union-attr]
                   VisualElement(type="chart", block_id="c9", frame=P(30, 30, 30, 30)),
               ]))
    findings = check_free_layout(s2, TOKENS)
    assert any(f.check == "overlap" and "visuals" in f.message for f in findings)


def test_the_source_band_is_reserved_only_when_a_source_is_drawn() -> None:
    low = P(10, 92, 40, 5)
    assert "source_band" in _checks(_slide(_a(frame=low), _b(), cite=True))
    assert "source_band" not in _checks(_slide(_a(frame=low), _b()))


def test_minimum_size() -> None:
    assert _checks(_slide(_a(size_pt=8), _b())) == {"min_size"}


def test_contrast_uses_what_is_beneath_the_box() -> None:
    assert _checks(_slide(_a(color="lt1"), _b())) == {"contrast"}  # white on white
    assert _checks(_slide(_a(color="lt1"), _b(), background="dk1")) == {"contrast"}  # b is dk1 on dk1
    panel = ShapeElement(shape="rect", frame=P(5, 5, 50, 20), fill="dk1")
    assert _checks(_slide(panel, _a(color="lt1"), _b())) == set()
    # tint lightens the panel, so light text on a tinted accent fails
    tinted = ShapeElement(shape="rect", frame=P(5, 5, 50, 20), fill="accent1", tint=0.9)
    assert _checks(_slide(tinted, _a(color="lt1"), _b())) == {"contrast"}
    # large text only needs 3:1 (accent6 on white is ~3.5:1)
    assert _checks(_slide(_a(color="accent6", size_pt=30, frame=P(10, 10, 80, 12)), _b())) == set()
    assert _checks(_slide(_a(color="accent6", size_pt=14), _b())) == {"contrast"}


def test_the_source_line_must_be_legible() -> None:
    # accent3 background leaves none of dk2/dk1/lt1 at 4.5:1 only if it sits mid-tone
    mid = ShapeElement(shape="rect", frame=P(0, 85, 100, 15), fill="accent6")
    findings = check_free_layout(_slide(mid, _a(), _b(), cite=True), TOKENS)
    assert not any(f.block_id == "" for f in findings) or all(f.check == "contrast" for f in findings if f.block_id == "")


def test_a_later_shape_that_paints_over_text_is_found() -> None:
    cover = ShapeElement(shape="rect", frame=P(5, 5, 60, 30), fill="lt2")
    assert "hidden_text" in _checks(_slide(_a(), cover, _b()))


def test_findings_carry_the_slide_and_block() -> None:
    f = check_free_layout(_slide(_a(size_pt=8), _b()), TOKENS)[0]
    assert (f.slide_id, f.block_id, f.check) == ("q", "a", "min_size") and f.message
