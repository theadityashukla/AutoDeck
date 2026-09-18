"""The LibreOffice cross-check — proof that `budgets.py`'s prediction agrees with a render.

Three groups of test here. `measure_ink_height_pt` and `measure_line_pitch_pt` each get
fast, render-free unit tests against a synthetic image, because the "detect ink bands,
convert by DPI" arithmetic does not need a real render to be exercised. `check_against_render`
and `measure_rendered_pitch_pt` need the real thing — `soffice`, a real font, `pdftoppm` —
so those tests carry `render` and skip cleanly without them, following
`tests/test_spotcheck.py`'s pattern. The pitch-comparison tests
(`test_the_rendered_pitch_matches_the_predicted_pitch_*`) are 2b.1's fix: they are what
`check_against_render`'s ink comparison could not be — see `budget_check.py`'s module
docstring for why — and would have caught the line-height bias this task fixed.
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
    measure_line_pitch_pt,
    measure_rendered_pitch_pt,
)
from autodeck.design.budgets import LINE_HEIGHT_FACTOR
from autodeck.design.fonts import is_available

#: LibreOffice ships Liberation as its own metric-compatible substitute set, so wherever
#: `soffice` is installed, Liberation Sans is a safe bet to be installed alongside it —
#: which this module needs for both halves of the check (fontTools *and* the renderer).
FAMILY = "Liberation Sans"

needs_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="LibreOffice not installed"
)
needs_test_font = pytest.mark.skipif(not is_available(FAMILY), reason=f"{FAMILY} not installed")

#: How far a real render's line-to-line pitch may miss `size_pt * line_spacing *
#: LINE_HEIGHT_FACTOR` before this, the tightest check in the module, fails. Unlike
#: `RENDER_TOLERANCE` this has no reason to be generous: `measure_line_pitch_pt` isolates
#: the gap between two adjacent lines directly, with none of `check_against_render`'s
#: per-line headroom or `(N-1)`-vs-`N` slack to absorb error. What is left is rasteriser
#: pixel quantisation at `DEFAULT_DPI` (150dpi -> 0.48pt/px): observed exact-to-the-point
#: agreement (0.00pt delta) across every size/spacing/width combination tried while writing
#: this test, but a small margin above that is honest about the quantisation this checker's
#: own docstring says to expect, rather than pinning to a "happened to be exact" value.
PITCH_TOLERANCE_PT = 0.75

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
# The pitch cross-check — the test that would have caught 2b.1's line-height bias.
#
# `check_against_render` above compares *ink*, which (see `budget_check.py`'s module
# docstring) cannot see a pitch bias: it would have passed, and did pass, against the old,
# under-predicting `_line_height_factor`. These tests compare LibreOffice's real
# line-to-line pitch against `size_pt * line_spacing * LINE_HEIGHT_FACTOR` directly — no
# per-line headroom, no `(N-1)`-vs-`N` slack, nothing for a bias to hide behind.
# ---------------------------------------------------------------------------

#: (size_pt, line_spacing, width_pt) at each of this design system's real spacing regimes —
#: single (1.0), the tight title spacing `big_number`'s headline uses (1.15), and the
#: looser body spacing (1.25) — chosen (per the module docstring's own wrap-to-2+-lines
#: rule for a meaningful comparison) to each wrap `_PITCH_TEXT` to several lines.
_PITCH_CASES = [(22, 1.0, 260), (16, 1.25, 300), (32, 1.15, 340)]

_PITCH_TEXT = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
    "november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu "
) * 6


@pytest.mark.render
@needs_soffice
@needs_test_font
@pytest.mark.parametrize("size_pt,line_spacing,width_pt", _PITCH_CASES)
def test_the_rendered_pitch_matches_the_predicted_pitch(
    size_pt: float, line_spacing: float, width_pt: float, tmp_path: Path
) -> None:
    """This is 2b.1's fix, proved: had `_line_height_factor` still been the old
    ascent+descent figure, `predicted` below would be ~7.4% smaller than `pitch` and this
    assertion would fail loudly, which is exactly what the ink-based tests above could not
    do (see the module docstring)."""
    pitch = measure_rendered_pitch_pt(
        _PITCH_TEXT, FAMILY, size_pt, width_pt, line_spacing=line_spacing, out_dir=tmp_path
    )
    predicted = size_pt * line_spacing * LINE_HEIGHT_FACTOR
    assert pitch == pytest.approx(predicted, abs=PITCH_TOLERANCE_PT)


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_measure_rendered_pitch_pt_refuses_a_single_line(tmp_path: Path) -> None:
    """A single line has no gap to measure a pitch from — see `measure_line_pitch_pt`."""
    with pytest.raises(BudgetCheckError):
        measure_rendered_pitch_pt("One short line.", FAMILY, 16, 2000, out_dir=tmp_path)


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


# ---------------------------------------------------------------------------
# The pitch measurement itself — fast, no render needed
# ---------------------------------------------------------------------------


def test_line_pitch_matches_known_band_starts(tmp_path: Path) -> None:
    """Three 20px bands starting 30px apart: the pitch is the *start*-to-start gap (30px),
    not the band height (20px) or the start-to-end gap — a check that would pass on a
    wrong-but-plausible number if this test only checked the returned value's rough size."""
    image = Image.new("L", (100, 200), 255)
    draw = ImageDraw.Draw(image)
    for top in (10, 40, 70):
        draw.rectangle([10, top, 90, top + 19], fill=0)
    path = tmp_path / "bands.png"
    image.save(path)

    assert measure_line_pitch_pt(path, dpi=150) == pytest.approx(30 / 150 * 72)


def test_line_pitch_uses_the_median_not_the_mean(tmp_path: Path) -> None:
    """Four bands with one outlier gap (80px among three 30px gaps): the median (30px)
    reports the pitch every real line agrees on; the mean (~46.7px) would let one merged-
    or split-band artefact drag the whole measurement away from it."""
    image = Image.new("L", (100, 300), 255)
    draw = ImageDraw.Draw(image)
    for top in (10, 40, 70, 150):  # gaps: 30, 30, 80
        draw.rectangle([10, top, 90, top + 9], fill=0)
    path = tmp_path / "outlier.png"
    image.save(path)

    assert measure_line_pitch_pt(path, dpi=150) == pytest.approx(30 / 150 * 72)


def test_line_pitch_needs_at_least_two_bands(tmp_path: Path) -> None:
    """One band has no gap to measure a pitch from — the same shape of failure as a blank
    image, just one step later."""
    image = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(image).rectangle([10, 10, 90, 29], fill=0)
    path = tmp_path / "one_band.png"
    image.save(path)

    with pytest.raises(BudgetCheckError, match="ink band"):
        measure_line_pitch_pt(path, dpi=150)
