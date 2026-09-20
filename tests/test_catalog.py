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
    ComponentVariant,
    RegistrationError,
    UnknownComponentError,
    budget_for,
    check_overflow,
    components_missing_previews,
    known_components,
    register,
    registration,
    render_budgets,
    renderer_for,
    spec_for,
    variant_for,
)
from autodeck.design.components.renderers import big_number, two_column_compare
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
    """`point` stays a single line for legibility (a scannable phrase), not for row parity
    — see `_two_column_compare_slots`'s corrected docstring."""
    tokens = tokens_for()
    budget = budget_for("two_column_compare", "left_point", tokens)
    assert budget.max_lines == 1


# ---------------------------------------------------------------------------
# Carried finding (2b.2 review): repeatable slots — real content is a LIST
# ---------------------------------------------------------------------------


@requires_test_font
def test_two_column_points_slots_share_point_widths() -> None:
    """`left_points`/`right_points` are the real, multi-item content model; their per-item
    geometry must be exactly `left_point`/`right_point`'s box, not a fresh guess."""
    tokens = tokens_for()
    spec = spec_for("two_column_compare", tokens)
    assert spec.slot("left_points").item_box == spec.slot("left_point").box
    assert spec.slot("right_points").item_box == spec.slot("right_point").box
    assert spec.slot("left_points").repeatable
    assert spec.slot("left_points").row_gap > 0


@requires_test_font
def test_check_overflow_catches_a_too_long_point_in_a_list() -> None:
    tokens = tokens_for()
    blocks = {
        "headline": "Two paths forward",
        "left_title": "Add hardware",
        "right_title": "Rewrite the kernel",
        "left_points": ["Cost scales linearly with load.", "word " * 300],
    }
    findings = check_overflow(blocks, "two_column_compare", tokens)
    assert any("left_points[1]" in finding for finding in findings)
    assert not any("left_points[0]" in finding for finding in findings)


@requires_test_font
def test_check_overflow_catches_too_many_points_even_if_each_fits_alone() -> None:
    tokens = tokens_for()
    spec = spec_for("two_column_compare", tokens)
    max_items = _max_items_for_test(spec.slot("left_points"))
    blocks = {
        "headline": "Two paths forward",
        "left_title": "Add hardware",
        "right_title": "Rewrite the kernel",
        "left_points": [f"Point number {i}." for i in range(max_items + 5)],
    }
    findings = check_overflow(blocks, "two_column_compare", tokens)
    assert any("left_points" in finding and "item(s) need" in finding for finding in findings)


def _max_items_for_test(slot: object) -> int:
    """A local, obviously-correct re-derivation, kept independent of the catalog's own
    `_max_items` so a bug in that private helper cannot hide behind reusing it here."""
    item_box = slot.item_box  # type: ignore[attr-defined]
    row_gap = slot.row_gap  # type: ignore[attr-defined]
    box = slot.box  # type: ignore[attr-defined]
    row = item_box.height + row_gap
    return max(int((box.height + row_gap) // row), 0)


@requires_test_font
def test_check_overflow_is_clean_for_a_reasonable_point_list() -> None:
    tokens = tokens_for()
    blocks = {
        "headline": "Two paths forward",
        "left_title": "Add hardware",
        "right_title": "Rewrite the kernel",
        "left_points": ["Cost scales linearly with load.", "Six to nine weeks to capacity."],
        "right_points": ["One-off cost; savings compound.", "Three weeks on the fleet."],
    }
    assert check_overflow(blocks, "two_column_compare", tokens) == []


@requires_test_font
def test_left_points_is_optional() -> None:
    tokens = tokens_for()
    blocks = {
        "headline": "Two paths forward",
        "left_title": "Add hardware",
        "right_title": "Rewrite the kernel",
    }
    assert check_overflow(blocks, "two_column_compare", tokens) == []


@requires_test_font
def test_big_number_has_no_supporting_points_slot_by_default() -> None:
    tokens = tokens_for()
    spec = spec_for("big_number", tokens)
    assert "supporting_points" not in [slot.name for slot in spec.slots]


@requires_test_font
def test_big_number_supporting_points_narrows_the_figure_column() -> None:
    """The carried finding: writing `supporting_points` switches the renderer to a
    two-column layout, so `figure` must be narrower — not the full-width box the no-points
    spec declares."""
    tokens = tokens_for()
    wide = spec_for("big_number", tokens)
    narrow = spec_for("big_number", tokens, variant="with_supporting_points")
    assert narrow.slot("figure").box.width < wide.slot("figure").box.width
    assert narrow.slot("figure_label").box.width < wide.slot("figure_label").box.width
    supporting = narrow.slot("supporting_points")
    assert supporting.repeatable
    assert supporting.item_box is not None
    assert supporting.box.width == pytest.approx(narrow.slot("figure").box.width)


@requires_test_font
def test_check_overflow_resolves_the_big_number_variant_from_the_blocks_given() -> None:
    """A caller never names a variant — `check_overflow` resolves it from whether `blocks`
    actually carries non-empty `supporting_points`, using the component's own rule."""
    tokens = tokens_for()
    wide_figure = budget_for("big_number", "figure", tokens)
    long_figure = "9" * (wide_figure.max_chars + 1) if wide_figure.max_chars else "9" * 500

    blocks = {
        "headline": "Growth accelerated across every region",
        "figure": long_figure,
        "figure_label": "YoY revenue growth",
        "supporting_points": ["Median cost fell.", "No quality regression."],
    }
    findings = check_overflow(blocks, "big_number", tokens)
    # The figure is narrower once supporting_points is present, so the SAME text that just
    # fit the full-width budget may now also overflow the narrower one — either way, the
    # check must have measured the narrow box, not the wide one silently kept around.
    narrow_figure = budget_for("big_number", "figure", tokens, variant="with_supporting_points")
    expected_overflow = not narrow_figure.fits(long_figure)
    assert any("big_number.figure:" in f for f in findings) == expected_overflow


@requires_test_font
def test_render_budgets_mentions_the_supporting_points_variant() -> None:
    tokens = tokens_for()
    block = render_budgets("big_number", tokens)
    assert "supporting_points" in block
    assert "narrower" in block.lower() or "NARROWER" in block


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


def test_known_components_lists_every_registered_entry() -> None:
    """Updated by task 3a.4's first tranche: three components joined the original two.
    Updated by task 3a.4's second tranche: seven more components added."""
    assert known_components() == [
        "agenda",
        "before_after",
        "big_number",
        "bullets_supporting",
        "callout_takeaway",
        "closing_cta",
        "data_card_grid",
        "evidence_with_figure",
        "quote",
        "section_divider",
        "title",
        "two_column_compare",
    ]


# ---------------------------------------------------------------------------
# The registry: one registration establishes all five fields
# ---------------------------------------------------------------------------


def test_the_registry_is_what_finds_a_renderer() -> None:
    """3b's assembler looks a renderer up here rather than importing the module, so a new
    component reaches it by being registered and by nothing else."""
    assert renderer_for("big_number") is big_number.render
    assert renderer_for("two_column_compare") is two_column_compare.render


def test_a_registration_carries_the_content_class_its_renderer_takes() -> None:
    """Without it the assembler needs its own component -> content-class table, which is
    the fourth parallel list the registry exists to prevent."""
    assert registration("big_number").content_type is big_number.BigNumberContent
    assert (
        registration("two_column_compare").content_type
        is two_column_compare.TwoColumnCompareContent
    )


def test_a_registration_without_a_committed_preview_is_detectable() -> None:
    """Fifteen components are coming, most written by cheaper models. "Did this one ever
    get a golden preview committed" has to be answerable from the registry rather than by
    looking in a directory — and today, honestly, the answer is no for both."""
    missing = components_missing_previews()
    for name in known_components():
        declared = registration(name).preview
        assert (name in missing) == (declared is None or not declared.exists())


def test_a_component_declares_which_slot_selects_each_of_its_layouts() -> None:
    """The generic API names no component: `variant_for` asks the registration, and the
    registration is the only place `supporting_points` is mentioned."""
    assert variant_for("big_number", {}) == "default"
    assert variant_for("big_number", {"supporting_points": []}) == "default"
    assert (
        variant_for("big_number", {"supporting_points": ["One."]}) == "with_supporting_points"
    )


def test_a_component_with_one_layout_always_resolves_to_its_default() -> None:
    assert variant_for("two_column_compare", {"left_points": ["One."]}) == "default"


def test_an_unknown_variant_names_the_known_ones() -> None:
    with pytest.raises(UnknownComponentError, match="with_supporting_points"):
        spec_for("big_number", tokens_for(), variant="not_a_real_variant")


def test_registering_a_name_twice_is_refused() -> None:
    with pytest.raises(RegistrationError, match="already registered"):
        register(
            name="big_number",
            narrative_roles=("headline metric",),
            renderer=big_number.render,
            content_type=big_number.BigNumberContent,
            preview=None,
            slots=lambda canvas: [],
        )


def test_a_registration_must_declare_slots_or_variants_but_not_both() -> None:
    for kwargs in (
        {},
        {
            "slots": lambda canvas: [],
            "variants": (ComponentVariant(name="default", slots=lambda canvas: []),),
        },
    ):
        with pytest.raises(RegistrationError, match="not both and not neither"):
            register(
                name="never_registered",
                narrative_roles=("test",),
                renderer=big_number.render,
                content_type=big_number.BigNumberContent,
                preview=None,
                **kwargs,  # type: ignore[arg-type]
            )


def test_exactly_one_variant_is_the_default() -> None:
    with pytest.raises(RegistrationError, match="default variants"):
        register(
            name="never_registered",
            narrative_roles=("test",),
            renderer=big_number.render,
            content_type=big_number.BigNumberContent,
            preview=None,
            variants=(
                ComponentVariant(name="a", slots=lambda canvas: []),
                ComponentVariant(name="b", slots=lambda canvas: []),
            ),
        )


def test_a_variant_the_writer_cannot_be_told_about_is_refused() -> None:
    """A variant with no note never appears in the content prompt, so the writer can be put
    into it by what it writes and never learn that its budgets changed."""
    with pytest.raises(RegistrationError, match="no note"):
        register(
            name="never_registered",
            narrative_roles=("test",),
            renderer=big_number.render,
            content_type=big_number.BigNumberContent,
            preview=None,
            variants=(
                ComponentVariant(name="default", slots=lambda canvas: []),
                ComponentVariant(
                    name="extra", slots=lambda canvas: [], when_filled="something"
                ),
            ),
        )


def test_every_registered_component_is_one_the_outline_may_choose() -> None:
    """The outline's `CATALOG` is the planned fifteen and the registry is what is built so
    far, so the registry is a subset — but a *disagreement* (a component that renders and
    that the outline may never assign) would be invisible without this."""
    from autodeck.agents.outline import CATALOG

    assert set(known_components()) <= set(CATALOG)


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
