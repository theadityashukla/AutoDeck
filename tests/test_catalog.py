"""The component catalog: real slot geometry, not invented numbers.

The property worth protecting is `spec_for`'s central claim — that every slot's box comes
from reading `big_number`/`two_column_compare`'s own arithmetic, never a fresh guess at it.
`test_two_column_titles_sit_at_the_renderers_own_column_x` and
`test_big_number_source_box_is_exactly_the_renderers_caption_strip` pin that directly
against the renderers' own constants and split calls; the rest exercise the budget and
overflow plumbing built on top of the geometry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.components.catalog import (
    UnknownComponentError,
    budget_for,
    check_overflow,
    known_components,
    render_budgets,
    spec_for,
)
from autodeck.design.components.renderers import two_column_compare
from autodeck.design.fonts import is_available
from autodeck.design.layout_kit import Canvas
from autodeck.design.theme.tokens import DesignTokens

TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"

#: Any real installed font does for these tests — they check the plumbing between a slot's
#: box and its `SlotBudget`, never a font-specific value. `Liberation Sans` is used rather
#: than `test_design.py`'s `Inter` because it is what is actually installed in this
#: environment; either works, and `is_available` decides which is meant per B11.
TEST_FAMILY = "Liberation Sans"

requires_test_font = pytest.mark.skipif(
    not is_available(TEST_FAMILY), reason=f"{TEST_FAMILY} not installed"
)


def tokens_for(family: str = TEST_FAMILY) -> DesignTokens:
    base = DesignTokens.load(TOKENS_DIR / "dev.json")
    return base.model_copy(
        update={
            "typography": base.typography.model_copy(update={"major": family, "minor": family})
        }
    )


# ---------------------------------------------------------------------------
# Geometry is read off the renderers, not invented
# ---------------------------------------------------------------------------


@requires_test_font
def test_two_column_titles_sit_at_the_renderers_own_column_x() -> None:
    tokens = tokens_for()
    canvas = Canvas(tokens)
    region, _ = canvas.content.split_bottom(canvas.size("caption") * 1.6, gutter=canvas.gutter)
    left, right = region.split_columns(2, canvas.gutter * 1.5)

    spec = spec_for("two_column_compare", tokens)
    left_title, right_title = spec.slot("left_title"), spec.slot("right_title")

    assert left_title.box.x == pytest.approx(left.x + two_column_compare._PANEL_PADDING)
    assert right_title.box.x == pytest.approx(right.x + two_column_compare._PANEL_PADDING)
    assert left_title.box.width == pytest.approx(right_title.box.width)
    assert left_title.box.width == pytest.approx(
        left.width - two_column_compare._PANEL_PADDING * 2
    )


@requires_test_font
def test_two_column_point_width_matches_the_renderers_text_width() -> None:
    """`_text_width` in the renderer subtracts padding on both sides and the marker inset
    on one; the `point` slot's box has to agree exactly, or its budget is measuring the
    wrong column."""
    tokens = tokens_for()
    canvas = Canvas(tokens)
    region, _ = canvas.content.split_bottom(canvas.size("caption") * 1.6, gutter=canvas.gutter)
    left, _ = region.split_columns(2, canvas.gutter * 1.5)
    expected_width = (
        left.width - two_column_compare._PANEL_PADDING * 2 - two_column_compare._MARKER_INSET
    )

    point = spec_for("two_column_compare", tokens).slot("left_point")
    assert point.box.width == pytest.approx(expected_width)


@requires_test_font
def test_big_number_source_box_is_exactly_the_renderers_caption_strip() -> None:
    """`source` is the one slot with no content-dependent sizing at all in the renderer, so
    its box must match `split_bottom`'s own output exactly, not approximately."""
    tokens = tokens_for()
    canvas = Canvas(tokens)
    _, source_area = canvas.content.split_bottom(
        canvas.size("caption") * 1.6, gutter=canvas.gutter
    )

    source = spec_for("big_number", tokens).slot("source")
    assert (source.box.x, source.box.y, source.box.width, source.box.height) == (
        source_area.x,
        source_area.y,
        source_area.width,
        source_area.height,
    )


@requires_test_font
def test_two_column_point_is_capped_to_one_line_by_design() -> None:
    """The one deliberate exception to "reserve headroom, don't guess": row parity across
    the two columns depends on it (see `_two_column_compare_slots`'s docstring)."""
    tokens = tokens_for()
    budget = budget_for("two_column_compare", "left_point", tokens)
    assert budget.max_lines == 1


# ---------------------------------------------------------------------------
# Budgets built on that geometry
# ---------------------------------------------------------------------------


@requires_test_font
def test_budget_for_measures_the_slots_own_box() -> None:
    tokens = tokens_for()
    slot = spec_for("big_number", tokens).slot("figure_label")
    budget = budget_for("big_number", "figure_label", tokens)
    assert budget.width_pt == pytest.approx(slot.box.width)
    assert budget.height_pt == pytest.approx(slot.box.height)
    assert budget.max_lines >= 1


@requires_test_font
def test_an_unknown_slot_names_the_known_ones() -> None:
    tokens = tokens_for()
    with pytest.raises(UnknownComponentError, match="headline"):
        budget_for("big_number", "not_a_real_slot", tokens)


def test_an_unknown_component_names_the_known_ones() -> None:
    """No font is touched on this path — an unknown name is rejected before any geometry
    or measurement runs, so this test needs nothing installed to be meaningful."""
    with pytest.raises(UnknownComponentError, match="big_number"):
        spec_for("not_a_real_component", tokens_for())


def test_known_components_lists_both_catalog_entries() -> None:
    assert known_components() == ["big_number", "two_column_compare"]


# ---------------------------------------------------------------------------
# Overflow — the deterministic pre-render gate
# ---------------------------------------------------------------------------


@requires_test_font
def test_check_overflow_reports_only_the_slot_that_overflows() -> None:
    tokens = tokens_for()
    blocks = {
        "headline": "Growth accelerated across every region",
        "figure": "42%",
        "figure_label": "word " * 300,
    }
    findings = check_overflow(blocks, "big_number", tokens)
    assert len(findings) == 1
    assert "figure_label" in findings[0]


@requires_test_font
def test_check_overflow_is_clean_when_every_slot_fits() -> None:
    tokens = tokens_for()
    blocks = {
        "headline": "Growth accelerated across every region",
        "figure": "42%",
        "figure_label": "YoY revenue growth",
    }
    assert check_overflow(blocks, "big_number", tokens) == []


@requires_test_font
def test_check_overflow_flags_a_missing_required_slot_but_not_an_optional_one() -> None:
    tokens = tokens_for()
    findings = check_overflow({}, "big_number", tokens)
    assert any("headline" in finding and "missing" in finding for finding in findings)
    assert not any("support" in finding for finding in findings)
    assert not any("source" in finding for finding in findings)


# ---------------------------------------------------------------------------
# render_budgets — what the content prompt actually sees
# ---------------------------------------------------------------------------


@requires_test_font
def test_render_budgets_names_every_slot_and_its_limit() -> None:
    tokens = tokens_for()
    block = render_budgets("two_column_compare", tokens)
    for slot in spec_for("two_column_compare", tokens).slots:
        assert slot.name in block
    assert "line(s)" in block
    assert "characters" in block


@requires_test_font
def test_render_budgets_marks_optional_slots() -> None:
    tokens = tokens_for()
    block = render_budgets("big_number", tokens)
    assert "support" in block
    support_line = next(line for line in block.splitlines() if line.startswith("- support"))
    assert "optional" in support_line
    headline_line = next(line for line in block.splitlines() if line.startswith("- headline"))
    assert "optional" not in headline_line
