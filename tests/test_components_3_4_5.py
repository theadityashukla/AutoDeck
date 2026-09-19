"""`quote`, `bullets_supporting`, `callout_takeaway` — task 3a.4's first tranche.

Per component: it renders; `check_overflow` rejects text past its budget; the registry
answers for it; and the overflow path raises rather than shrinking. The fourth of those is
tested here at the renderer level (LibreOffice never enters it — `LayoutOverflowError` is
raised by `layout_kit` before python-pptx is asked to draw anything), which is a stronger
and faster guarantee than anything the golden-preview render could show.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.components.catalog import (
    UnknownComponentError,
    budget_for,
    check_overflow,
    registration,
    renderer_for,
    spec_for,
)
from autodeck.design.components.renderers import bullets_supporting, callout_takeaway, quote
from autodeck.design.fonts import is_available
from autodeck.design.layout_kit import Canvas, Frame, LayoutOverflowError
from autodeck.design.theme.master_builder import new_presentation
from autodeck.design.theme.tokens import DesignTokens
from tests.test_catalog import tokens_for

TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"

requires_test_font = pytest.mark.skipif(
    not is_available("Liberation Sans"), reason="Liberation Sans not installed"
)


def _frame(tokens: DesignTokens) -> Frame:
    """A real slide to draw on. python-pptx only — no LibreOffice, so this runs in CI."""
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    return Canvas(tokens).on(slide)


# ---------------------------------------------------------------------------
# quote
# ---------------------------------------------------------------------------


@requires_test_font
def test_quote_renders_headline_mark_quote_and_attribution() -> None:
    frame = _frame(tokens_for())
    quote.render(
        frame.slide,
        frame.canvas,
        quote.QuoteContent(
            headline="Clients notice the difference",
            quote="This is the first deck I have not had to fact-check myself.",
            attribution="VP of Strategy",
            source="Source: debrief call.",
        ),
    )
    # headline + rule, mark + quote + attribution, caption: at least six shapes.
    assert len(frame.slide.shapes) >= 6


@requires_test_font
def test_quote_with_no_source_draws_no_caption_shape() -> None:
    tokens = tokens_for()
    frame = _frame(tokens)
    quote.render(
        frame.slide,
        frame.canvas,
        quote.QuoteContent(headline="H", quote="Q", attribution="A"),
    )
    with_source_count = len(frame.slide.shapes)

    frame2 = _frame(tokens)
    quote.render(
        frame2.slide,
        frame2.canvas,
        quote.QuoteContent(headline="H", quote="Q", attribution="A", source="Cited."),
    )
    assert len(frame2.slide.shapes) == with_source_count + 1


@requires_test_font
def test_quote_too_long_raises_rather_than_shrinking() -> None:
    tokens = tokens_for()
    frame = _frame(tokens)
    with pytest.raises(LayoutOverflowError):
        quote.render(
            frame.slide,
            frame.canvas,
            quote.QuoteContent(
                headline="A headline",
                quote="A single sentence that will not stop, " * 40,
                attribution="Someone",
            ),
        )


def test_quote_source_box_is_exactly_the_caption_strip() -> None:
    tokens = tokens_for()
    canvas = Canvas(tokens)
    _, source_area = canvas.body_and_caption()
    source = spec_for("quote", tokens).slot("source")
    assert (source.box.x, source.box.y, source.box.width, source.box.height) == (
        source_area.x,
        source_area.y,
        source_area.width,
        source_area.height,
    )


def test_quote_slot_uses_the_quote_scale() -> None:
    tokens = tokens_for()
    budget = budget_for("quote", "quote", tokens)
    assert budget.size_pt == pytest.approx(tokens.typography.title * quote._QUOTE_SCALE)


@requires_test_font
def test_quote_check_overflow_rejects_an_overlong_quote() -> None:
    tokens = tokens_for()
    blocks = {
        "headline": "A headline",
        "quote": "word " * 400,
        "attribution": "Someone",
    }
    findings = check_overflow(blocks, "quote", tokens)
    assert any(f.startswith("quote.quote:") for f in findings)


@requires_test_font
def test_quote_check_overflow_flags_missing_required_slots_but_not_source() -> None:
    tokens = tokens_for()
    findings = check_overflow({}, "quote", tokens)
    assert any("headline" in f and "missing" in f for f in findings)
    assert any("attribution" in f and "missing" in f for f in findings)
    assert not any("source" in f for f in findings)


def test_quote_is_registered_with_its_renderer_and_content_type() -> None:
    assert renderer_for("quote") is quote.render
    assert registration("quote").content_type is quote.QuoteContent


# ---------------------------------------------------------------------------
# bullets_supporting
# ---------------------------------------------------------------------------


@requires_test_font
def test_bullets_supporting_renders_a_marker_and_text_shape_per_point() -> None:
    frame = _frame(tokens_for())
    bullets_supporting.render(
        frame.slide,
        frame.canvas,
        bullets_supporting.BulletsSupportingContent(
            headline="Three changes explain the improvement",
            points=["First point.", "Second point.", "Third point."],
        ),
    )
    # headline + rule, then a marker + text shape per point: at least 2 + 2*3.
    assert len(frame.slide.shapes) >= 8


@requires_test_font
def test_bullets_supporting_too_many_points_raises_rather_than_shrinking() -> None:
    tokens = tokens_for()
    frame = _frame(tokens)
    with pytest.raises(LayoutOverflowError):
        bullets_supporting.render(
            frame.slide,
            frame.canvas,
            bullets_supporting.BulletsSupportingContent(
                headline="H",
                points=[f"Point number {i} that says something." for i in range(40)],
            ),
        )


def test_bullets_supporting_points_slot_is_repeatable_and_full_width() -> None:
    tokens = tokens_for()
    canvas = Canvas(tokens)
    region = canvas.content
    spec = spec_for("bullets_supporting", tokens)
    points = spec.slot("points")
    assert points.repeatable
    assert points.item_box is not None
    assert points.box.width == pytest.approx(region.width)
    assert points.row_gap > 0


@requires_test_font
def test_bullets_supporting_check_overflow_catches_a_too_long_point() -> None:
    tokens = tokens_for()
    blocks = {"headline": "H", "points": ["Short.", "word " * 300]}
    findings = check_overflow(blocks, "bullets_supporting", tokens)
    assert any("points[1]" in f for f in findings)
    assert not any("points[0]" in f for f in findings)


@requires_test_font
def test_bullets_supporting_requires_points() -> None:
    tokens = tokens_for()
    findings = check_overflow({"headline": "H"}, "bullets_supporting", tokens)
    assert any("points" in f and "missing" in f for f in findings)


def test_bullets_supporting_is_registered_with_its_renderer_and_content_type() -> None:
    assert renderer_for("bullets_supporting") is bullets_supporting.render
    assert (
        registration("bullets_supporting").content_type
        is bullets_supporting.BulletsSupportingContent
    )


# ---------------------------------------------------------------------------
# callout_takeaway
# ---------------------------------------------------------------------------


@requires_test_font
def test_callout_takeaway_renders_label_takeaway_and_panel() -> None:
    frame = _frame(tokens_for())
    callout_takeaway.render(
        frame.slide,
        frame.canvas,
        callout_takeaway.CalloutTakeawayContent(
            takeaway="The rewrite pays for itself in six weeks.",
            support="Every week after that is margin.",
        ),
    )
    # panel rect + label + takeaway + support: at least 4 shapes.
    assert len(frame.slide.shapes) >= 4


@requires_test_font
def test_callout_takeaway_without_support_draws_fewer_shapes() -> None:
    tokens = tokens_for()
    frame = _frame(tokens)
    callout_takeaway.render(
        frame.slide,
        frame.canvas,
        callout_takeaway.CalloutTakeawayContent(takeaway="One sentence.", support="A line."),
    )
    with_support = len(frame.slide.shapes)

    frame2 = _frame(tokens)
    callout_takeaway.render(
        frame2.slide, frame2.canvas, callout_takeaway.CalloutTakeawayContent(takeaway="One.")
    )
    assert len(frame2.slide.shapes) == with_support - 1


@requires_test_font
def test_callout_takeaway_too_long_raises_rather_than_shrinking() -> None:
    tokens = tokens_for()
    frame = _frame(tokens)
    with pytest.raises(LayoutOverflowError):
        callout_takeaway.render(
            frame.slide,
            frame.canvas,
            callout_takeaway.CalloutTakeawayContent(
                takeaway="A very long sentence that keeps going. " * 30
            ),
        )


def test_callout_takeaway_label_is_capped_to_one_line() -> None:
    tokens = tokens_for()
    budget = budget_for("callout_takeaway", "label", tokens)
    assert budget.max_lines == 1


@requires_test_font
def test_callout_takeaway_check_overflow_flags_missing_takeaway_but_not_support() -> None:
    tokens = tokens_for()
    findings = check_overflow({}, "callout_takeaway", tokens)
    assert any("takeaway" in f and "missing" in f for f in findings)
    assert not any("support" in f for f in findings)
    # `label` has a default in the content dataclass, but `check_overflow` only sees what a
    # caller actually puts in `blocks` — a caller that also omits `label` is missing a
    # required slot, same as any other.
    assert any("label" in f and "missing" in f for f in findings)


def test_callout_takeaway_is_registered_with_its_renderer_and_content_type() -> None:
    assert renderer_for("callout_takeaway") is callout_takeaway.render
    assert (
        registration("callout_takeaway").content_type is callout_takeaway.CalloutTakeawayContent
    )


def test_an_unknown_slot_on_a_new_component_names_the_known_ones() -> None:
    with pytest.raises(UnknownComponentError, match="takeaway"):
        budget_for("callout_takeaway", "not_a_real_slot", tokens_for())
