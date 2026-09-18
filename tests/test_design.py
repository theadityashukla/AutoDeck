"""Design system: fonts, budgets, layout kit, theme XML, and the SVG converter.

Everything here is pure computation or XML generation, so it runs in CI. The parts that
need LibreOffice and an installed font stack carry the `render` marker and stay local
per B10.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.budgets import compute_budget, load_metrics, wrap_text
from autodeck.design.fonts import FontNotFoundError, is_available, resolve_family
from autodeck.design.icons.custgeom import custgeom_xml
from autodeck.design.icons.library import IconNotFoundError, icon_names, load_icon, parse_svg
from autodeck.design.icons.svg_path import (
    Close,
    Cubic,
    Line,
    Move,
    SvgPathError,
    circle_subpath,
    parse_path,
)
from autodeck.design.layout_kit import Box, Canvas, TextStyle
from autodeck.design.theme.master_builder import apply_theme, build_theme_xml, new_presentation
from autodeck.design.theme.tokens import DesignTokens, Typography

TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"

#: The container/CI font. Present because tests need *a* real font file to measure;
#: nothing here asserts anything about Aptos, which cannot be installed here (B11).
TEST_FAMILY = "Inter"

requires_test_font = pytest.mark.skipif(
    not is_available(TEST_FAMILY), reason=f"{TEST_FAMILY} not installed"
)


# ---------------------------------------------------------------------------
# Fonts — a missing family must be loud
# ---------------------------------------------------------------------------


def test_a_missing_family_raises_rather_than_substituting() -> None:
    """The invariant of this module. A fallback here corrupts every budget silently."""
    with pytest.raises(FontNotFoundError, match="not found"):
        resolve_family("Definitely Not An Installed Typeface")


def test_the_error_explains_the_aptos_case() -> None:
    """Whoever hits this is usually setting the project up for the first time."""
    with pytest.raises(FontNotFoundError, match="Microsoft 365"):
        resolve_family("Aptos Nonexistent Variant")


def test_tokens_declaring_a_missing_font_fail_up_front() -> None:
    tokens = DesignTokens(
        name="broken", typography=Typography(major="No Such Face", minor="No Such Face")
    )
    with pytest.raises(FontNotFoundError):
        tokens.require_fonts()


@requires_test_font
def test_resolve_returns_a_real_file() -> None:
    assert resolve_family(TEST_FAMILY).path.exists()


# ---------------------------------------------------------------------------
# Budgets — measured from real glyph metrics
# ---------------------------------------------------------------------------


@requires_test_font
def test_metrics_come_from_the_font_file() -> None:
    metrics = load_metrics(TEST_FAMILY)
    assert metrics.units_per_em > 0
    assert metrics.advances
    assert metrics.char_width("W", 16) > metrics.char_width("i", 16)


@requires_test_font
def test_wrapping_respects_the_measured_width() -> None:
    text = "The quick brown fox jumps over the lazy dog and keeps on running."
    narrow = wrap_text(text, TEST_FAMILY, 16, 120)
    wide = wrap_text(text, TEST_FAMILY, 16, 600)
    assert narrow.line_count > wide.line_count
    assert narrow.width_pt <= 120


@requires_test_font
def test_a_word_wider_than_the_box_is_reported_not_broken() -> None:
    """The fix is a smaller size or a different component, not a hyphen we cannot render."""
    measurement = wrap_text(
        "Pneumonoultramicroscopicsilicovolcanoconiosis", TEST_FAMILY, 40, 60
    )
    assert measurement.overflow_width


@requires_test_font
def test_newlines_start_new_lines() -> None:
    assert wrap_text("one\ntwo\nthree", TEST_FAMILY, 12, 500).line_count == 3


@requires_test_font
def test_budget_fits_short_text_and_rejects_long_text() -> None:
    budget = compute_budget(
        slot="body", family=TEST_FAMILY, size_pt=16, width_pt=300, height_pt=100
    )
    assert budget.max_lines >= 1
    assert budget.fits("A short line.")
    assert not budget.fits("word " * 400)


@requires_test_font
def test_budget_describes_itself_for_a_prompt() -> None:
    """§6.7: budgets reach the content agent as hard constraints in its prompt."""
    budget = compute_budget(
        slot="headline", family=TEST_FAMILY, size_pt=32, width_pt=600, height_pt=90
    )
    assert "headline" in budget.describe()
    assert str(budget.max_lines) in budget.describe()


@requires_test_font
def test_equal_character_counts_can_need_very_different_widths() -> None:
    """v1's `chars_per_line` heuristic assumed a character count predicts a line's width;
    this is the property that assumption gets wrong, and the property `wrap_text` has to
    get right instead. Ten narrow glyphs and ten wide ones are the same length by
    `len()` and nothing alike by advance width — a heuristic keyed on the former cannot
    represent the latter, which is why none exists anywhere in this module (PHASE-2B.md
    2b.1: "v1's `chars_per_line` heuristic is not reproduced")."""
    narrow = wrap_text("l" * 10, TEST_FAMILY, 24, 2000)
    wide = wrap_text("W" * 10, TEST_FAMILY, 24, 2000)
    assert wide.width_pt > narrow.width_pt * 2


def test_no_character_count_heuristic_is_exposed() -> None:
    """Static companion to the property test above, and the one part of it that needs no
    font at all: `chars_per_line` (or any spelling of it) must not exist as an importable
    name, so nothing downstream can reach for the shortcut budgets.py exists to replace."""
    import autodeck.design.budgets as budgets_module

    names = " ".join(dir(budgets_module)).lower()
    assert "charsperline" not in names.replace("_", "")


# ---------------------------------------------------------------------------
# Layout kit
# ---------------------------------------------------------------------------


def test_columns_share_the_width_and_the_gutter() -> None:
    columns = Box(0, 0, 100, 50).split_columns(3, gutter=5)
    assert len(columns) == 3
    assert columns[0].width == pytest.approx(30)
    assert columns[1].x == pytest.approx(35)
    assert columns[-1].right == pytest.approx(100)


def test_columns_that_cannot_fit_raise() -> None:
    with pytest.raises(ValueError, match="do not fit"):
        Box(0, 0, 10, 10).split_columns(4, gutter=20)


def test_split_top_returns_the_remainder_below_the_gutter() -> None:
    taken, rest = Box(0, 0, 100, 100).split_top(30, gutter=10)
    assert (taken.height, rest.y, rest.height) == (30, 40, 60)


def test_split_bottom_mirrors_split_top() -> None:
    rest, taken = Box(0, 0, 100, 100).split_bottom(30, gutter=10)
    assert (taken.y, taken.height, rest.height) == (70, 30, 60)


def test_grid_produces_rows_of_columns() -> None:
    grid = Box(0, 0, 100, 100).grid(2, 3, gutter=4)
    assert len(grid) == 2
    assert all(len(row) == 3 for row in grid)


def test_align_within_centres() -> None:
    outer = Box(0, 0, 100, 100)
    centred = Box(0, 0, 20, 10).align_within(outer, horizontal="center", vertical="middle")
    assert (centred.center_x, centred.center_y) == (50, 50)


def test_snap_to_baseline_rounds_down() -> None:
    assert Box(0, 17, 10, 10).snap_to_baseline(6).y == 12


def test_contains_is_the_safe_area_check() -> None:
    outer = Box(0, 0, 100, 100)
    assert outer.contains(Box(10, 10, 50, 50))
    assert not outer.contains(Box(80, 80, 50, 50))


# ---------------------------------------------------------------------------
# Measurement and rendering must not diverge — the bug TextStyle exists to prevent
# ---------------------------------------------------------------------------


@requires_test_font
def test_measurement_accounts_for_line_spacing() -> None:
    """The first spike render put an accent rule through a headline because it did not."""
    canvas = Canvas(DesignTokens.load(TOKENS_DIR / "dev.json"))
    text = "A headline long enough to wrap onto a second line in this column."
    single = TextStyle(family=TEST_FAMILY, size=16, line_spacing=1.0)
    loose = single.with_(line_spacing=1.5)
    assert canvas.measure(text, 300, loose) > canvas.measure(text, 300, single)


@requires_test_font
def test_measurement_accounts_for_paragraph_spacing() -> None:
    canvas = Canvas(DesignTokens.load(TOKENS_DIR / "dev.json"))
    text = "First paragraph.\nSecond paragraph."
    tight = TextStyle(family=TEST_FAMILY, size=16)
    spaced = tight.with_(space_after=12.0)
    assert canvas.measure(text, 300, spaced) == pytest.approx(
        canvas.measure(text, 300, tight) + 12.0
    )


@requires_test_font
def test_fit_returns_a_box_of_the_measured_height() -> None:
    canvas = Canvas(DesignTokens.load(TOKENS_DIR / "dev.json"))
    style = canvas.style("body")
    region = Box(0, 0, 300, 400)
    fitted = canvas.fit("Some text that wraps a couple of times over here.", region, style)
    assert fitted.height == pytest.approx(
        canvas.measure("Some text that wraps a couple of times over here.", 300, style)
    )
    assert fitted.height < region.height


# ---------------------------------------------------------------------------
# Tokens and theme XML
# ---------------------------------------------------------------------------


def test_both_shipped_token_sets_load() -> None:
    for name in ("aptos", "dev"):
        assert DesignTokens.load(TOKENS_DIR / f"{name}.json").name


def test_aptos_is_the_deliverable_default() -> None:
    """B11. The dev set exists for containers; it must not become the default."""
    aptos = DesignTokens.load(TOKENS_DIR / "aptos.json")
    assert aptos.typography.major == "Aptos Display"
    assert aptos.typography.minor == "Aptos"


def test_the_dev_token_set_mirrors_the_aptos_type_structure() -> None:
    """Same major/minor split and type scale, so layout work transfers between them."""
    aptos = DesignTokens.load(TOKENS_DIR / "aptos.json")
    dev = DesignTokens.load(TOKENS_DIR / "dev.json")
    assert aptos.typography.model_dump(exclude={"major", "minor"}) == dev.typography.model_dump(
        exclude={"major", "minor"}
    )
    assert aptos.palette == dev.palette


def test_theme_xml_carries_the_palette_and_fonts() -> None:
    tokens = DesignTokens.load(TOKENS_DIR / "dev.json")
    xml = build_theme_xml(tokens)
    assert f'<a:latin typeface="{tokens.typography.major}"/>' in xml
    assert tokens.palette.accent1.upper() in xml
    assert "<a:clrScheme" in xml and "<a:fontScheme" in xml


def test_theme_xml_declares_all_twelve_colour_slots() -> None:
    xml = build_theme_xml(DesignTokens.load(TOKENS_DIR / "dev.json"))
    for slot in ("dk1", "lt1", "dk2", "lt2", "hlink", "folHlink"):
        assert f"<a:{slot}>" in xml
    for index in range(1, 7):
        assert f"<a:accent{index}>" in xml


def test_theme_xml_has_three_entries_in_every_format_list() -> None:
    """Fewer than three makes the package invalid and PowerPoint offers to repair it."""
    xml = build_theme_xml(DesignTokens.load(TOKENS_DIR / "dev.json"))
    assert xml.count("<a:effectStyle>") == 3
    assert xml.count("<a:ln ") == 3


def test_text_and_background_slots_use_sysclr() -> None:
    """PowerPoint's text/background UI pairs them wrongly with a plain srgbClr."""
    xml = build_theme_xml(DesignTokens.load(TOKENS_DIR / "dev.json"))
    assert '<a:sysClr val="windowText"' in xml
    assert '<a:sysClr val="window"' in xml


@requires_test_font
def test_applying_a_theme_replaces_only_the_theme_part() -> None:
    import io
    import zipfile

    tokens = DesignTokens.load(TOKENS_DIR / "dev.json")
    buffer = io.BytesIO()
    new_presentation(tokens).save(buffer)
    original = buffer.getvalue()

    themed = apply_theme(original, build_theme_xml(tokens))

    with (
        zipfile.ZipFile(io.BytesIO(original)) as before,
        zipfile.ZipFile(io.BytesIO(themed)) as after,
    ):
        assert before.namelist() == after.namelist()
        changed = [n for n in before.namelist() if before.read(n) != after.read(n)]
        assert changed == ["ppt/theme/theme1.xml"]


def test_applying_a_theme_to_a_package_without_one_fails() -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("hello.txt", "not a pptx")
    with pytest.raises(ValueError, match="no ppt/theme"):
        apply_theme(buffer.getvalue(), "<a:theme/>")


# ---------------------------------------------------------------------------
# SVG path parsing
# ---------------------------------------------------------------------------


def test_absolute_and_relative_lines_agree() -> None:
    absolute = parse_path("M 10 10 L 20 20")[0]
    relative = parse_path("m 10 10 l 10 10")[0]
    assert absolute == relative == [Move(10, 10), Line(20, 20)]


def test_horizontal_and_vertical_shorthands() -> None:
    assert parse_path("M0 0 H 10 V 5")[0] == [Move(0, 0), Line(10, 0), Line(10, 5)]


def test_implicit_repeat_after_moveto_is_a_lineto() -> None:
    assert parse_path("M0 0 10 10 20 20")[0] == [Move(0, 0), Line(10, 10), Line(20, 20)]


def test_compound_paths_produce_several_subpaths() -> None:
    assert len(parse_path("M0 0 L1 1 Z M5 5 L6 6 Z")) == 2


def test_quadratics_are_elevated_to_cubics() -> None:
    segments = parse_path("M0 0 Q 10 0 10 10")[0]
    assert isinstance(segments[1], Cubic)
    assert (segments[1].x, segments[1].y) == (10, 10)


def test_smooth_cubic_reflects_the_previous_control_point() -> None:
    segments = parse_path("M0 0 C 0 5 5 10 10 10 S 20 5 20 0")[0]
    reflected = segments[2]
    assert isinstance(reflected, Cubic)
    assert (reflected.x1, reflected.y1) == (15, 10)  # mirror of (5, 10) about (10, 10)


def test_arcs_become_cubics() -> None:
    segments = parse_path("M0 0 A 10 10 0 0 1 10 10")[0]
    assert all(isinstance(s, Cubic) for s in segments[1:])
    assert (segments[-1].x, segments[-1].y) == pytest.approx((10, 10))  # type: ignore[union-attr]


def test_packed_arc_flags_parse_correctly() -> None:
    """The bug Lucide's `zap` icon exposed: `0 00-2.474` is three values, not two.

    A regex tokeniser reads `00` as the single number 0 and every argument after it shifts.
    """
    segments = parse_path("M15.914 4a1.5 1.5 0 00-2.474-1.561")[0]
    assert (segments[-1].x, segments[-1].y) == pytest.approx((13.44, 2.439))  # type: ignore[union-attr]


def test_a_degenerate_arc_becomes_a_line() -> None:
    segments = parse_path("M0 0 A 0 0 0 0 1 10 10")[0]
    assert (segments[-1].x, segments[-1].y) == (10, 10)  # type: ignore[union-attr]


def test_closepath_returns_to_the_subpath_start() -> None:
    segments = parse_path("M5 5 L10 10 Z L20 20")[0]
    assert isinstance(segments[2], Close)
    assert segments[3] == Line(20, 20)


def test_empty_path_data_is_empty() -> None:
    assert parse_path("") == []
    assert parse_path("   ") == []


def test_path_data_starting_with_a_number_is_rejected() -> None:
    with pytest.raises(SvgPathError, match="starts with a number"):
        parse_path("10 10 L 20 20")


def test_an_unsupported_command_is_rejected() -> None:
    with pytest.raises(SvgPathError):
        parse_path("M0 0 X 5")


def test_a_circle_becomes_four_cubics_returning_to_the_start() -> None:
    segments = circle_subpath(10, 10, 5)
    assert isinstance(segments[0], Move)
    assert sum(isinstance(s, Cubic) for s in segments) == 4
    assert (segments[-2].x, segments[-2].y) == pytest.approx((15, 10))  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Icon library and custGeom
# ---------------------------------------------------------------------------


def test_the_vendored_library_is_present_and_licensed() -> None:
    """Lucide is ISC — redistributable, but only with the notice alongside it."""
    assert len(icon_names()) >= 5
    license_file = Path(__file__).resolve().parents[1] / "autodeck/design/icons/lucide/LICENSE"
    assert license_file.exists()
    assert "ISC License" in license_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", icon_names())
def test_every_vendored_icon_parses_and_converts(name: str) -> None:
    """Ten icons exercising lines, arcs, circles and compound paths."""
    icon = load_icon(name)
    assert icon.subpaths
    assert icon.view_width == icon.view_height == 24
    for subpath in icon.subpaths:
        xml = custgeom_xml(subpath, icon.view_width, icon.view_height)
        assert xml.startswith("<a:custGeom>")
        assert "<a:moveTo>" in xml


def test_an_unknown_icon_lists_what_is_available() -> None:
    with pytest.raises(IconNotFoundError, match="Available"):
        load_icon("no-such-icon")


def test_svg_primitives_all_convert() -> None:
    source = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke-width="2">
      <path d="M1 1 L2 2"/><circle cx="12" cy="12" r="6"/>
      <rect x="1" y="1" width="4" height="4"/><line x1="0" y1="0" x2="9" y2="9"/>
      <polyline points="1,1 2,2 3,3"/><polygon points="4,4 5,5 6,4"/>
      <ellipse cx="8" cy="8" rx="3" ry="2"/>
    </svg>"""
    icon = parse_svg(source, name="mixed")
    assert len(icon.subpaths) == 7
    assert icon.stroke_width == 2


def test_custgeom_declares_an_unfilled_path() -> None:
    """`fill="none"` is what keeps a stroke a stroke instead of a filled wedge."""
    icon = load_icon("trending-up")
    xml = custgeom_xml(icon.subpaths[0], icon.view_width, icon.view_height)
    assert 'fill="none"' in xml
    assert "<a:pathLst>" in xml


def test_custgeom_coordinates_scale_into_the_path_space() -> None:
    from autodeck.design.icons.custgeom import PATH_SPACE

    xml = custgeom_xml([Move(0, 0), Line(24, 24)], 24, 24)
    assert 'x="0"' in xml
    assert f'x="{PATH_SPACE}"' in xml
