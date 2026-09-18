"""The LibreOffice cross-check — proof that `budgets.py`'s prediction agrees with a render.

Two groups of test here. `measure_ink_height_pt` gets fast, render-free unit tests against
a synthetic image, because the "detect ink, convert by DPI" arithmetic does not need a real
render to be exercised. `check_against_render` needs the real thing — `soffice`, a real
font, `pdftoppm` — so those tests carry `render` and skip cleanly without them, following
`tests/test_spotcheck.py`'s pattern.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from autodeck.design.budget_check import (
    RENDER_TOLERANCE,
    BudgetCheckError,
    check_against_render,
    measure_ink_height_pt,
)
from autodeck.design.fonts import is_available

#: LibreOffice ships Liberation as its own metric-compatible substitute set, so wherever
#: `soffice` is installed, Liberation Sans is a safe bet to be installed alongside it —
#: which this module needs for both halves of the check (fontTools *and* the renderer).
FAMILY = "Liberation Sans"

needs_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="LibreOffice not installed"
)
needs_test_font = pytest.mark.skipif(not is_available(FAMILY), reason=f"{FAMILY} not installed")

# Both wrap to several lines at the widths used below — single-line ink is not a meaningful
# comparison for this checker; see the module docstring in `budget_check.py`.
HEADLINE = "Margin expansion outpaced revenue growth for the third straight quarter"
BODY = (
    "The pricing change lifted gross margin by three points while unit volumes held "
    "steady across every region we track, which is the clearest signal finance had"
)


# Stacked on every test below that actually renders — `soffice`, a real font, and the
# `render` marker so `-m "not render"` deselects it (per pyproject's own default addopts).
# The ink-measurement tests further down need none of this and stay unmarked.
@pytest.mark.render
@needs_soffice
@needs_test_font
def test_a_wrapped_headline_matches_within_tolerance(tmp_path: Path) -> None:
    """Title-scale, tight line spacing — the style `big_number`'s headline actually uses."""
    result = check_against_render(
        HEADLINE, FAMILY, 32, 300, line_spacing=1.15, out_dir=tmp_path
    )
    assert result.line_count >= 2
    assert result.within_tolerance, (
        f"delta {result.delta_pt:.2f}pt on {result.measured_pt:.2f}pt exceeds "
        f"{RENDER_TOLERANCE:.0%}"
    )


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_body_copy_at_the_themes_line_height_matches_within_tolerance(tmp_path: Path) -> None:
    result = check_against_render(BODY, FAMILY, 16, 420, line_spacing=1.25, out_dir=tmp_path)
    assert result.line_count >= 2
    assert result.within_tolerance, (
        f"delta {result.delta_pt:.2f}pt on {result.measured_pt:.2f}pt exceeds "
        f"{RENDER_TOLERANCE:.0%}"
    )


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_a_narrower_column_still_matches_within_tolerance(tmp_path: Path) -> None:
    """A different width changes where every line breaks, not just how many there are."""
    result = check_against_render(BODY, FAMILY, 16, 260, line_spacing=1.25, out_dir=tmp_path)
    assert result.line_count >= 2
    assert result.within_tolerance, (
        f"delta {result.delta_pt:.2f}pt on {result.measured_pt:.2f}pt exceeds "
        f"{RENDER_TOLERANCE:.0%}"
    )


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_the_delta_is_reported_not_hidden(tmp_path: Path) -> None:
    """A9-shaped: a caller can see *how* wrong a prediction was, not just pass/fail."""
    result = check_against_render(
        HEADLINE, FAMILY, 32, 300, line_spacing=1.15, out_dir=tmp_path
    )
    assert result.delta_pt == pytest.approx(result.measured_pt - result.rendered_pt)


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_render_measurement_slide_refuses_blank_text(tmp_path: Path) -> None:
    """Empty text renders a blank slide; there is nothing to measure, and pretending
    otherwise (e.g. returning 0.0) would look like a perfect, meaningless match."""
    from autodeck.design.budget_check import render_measurement_slide

    with pytest.raises(BudgetCheckError):
        render_measurement_slide("", FAMILY, 16, 300, out_dir=tmp_path)


# ---------------------------------------------------------------------------
# The ink measurement itself — fast, no render needed
# ---------------------------------------------------------------------------


def test_ink_height_matches_a_known_drawn_block(tmp_path: Path) -> None:
    image = Image.new("L", (200, 300), 255)
    ImageDraw.Draw(image).rectangle([10, 50, 190, 149], fill=0)  # 100px tall, rows 50-149
    path = tmp_path / "block.png"
    image.save(path)

    assert measure_ink_height_pt(path, dpi=150) == pytest.approx(100 / 150 * 72)


def test_ink_height_treats_near_white_as_background(tmp_path: Path) -> None:
    """A pixel a shade off pure white is anti-aliasing along a glyph edge, not ink; one
    that is meaningfully darker is. The threshold has to draw that line somewhere real."""
    image = Image.new("L", (50, 50), 255)
    ImageDraw.Draw(image).point([(10, 10)], fill=254)  # background, not ink
    ImageDraw.Draw(image).point([(10, 20)], fill=100)  # ink
    path = tmp_path / "faint.png"
    image.save(path)

    # Only the row at y=20 should register: the bbox's height in pixels is 1.
    assert measure_ink_height_pt(path, dpi=150) == pytest.approx(1 / 150 * 72)


def test_a_blank_image_has_nothing_to_measure(tmp_path: Path) -> None:
    image = Image.new("L", (200, 300), 255)
    path = tmp_path / "blank.png"
    image.save(path)

    with pytest.raises(BudgetCheckError, match="no ink"):
        measure_ink_height_pt(path, dpi=150)
