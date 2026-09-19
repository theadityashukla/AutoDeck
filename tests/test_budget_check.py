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

The line-count tests are 3a.6's equivalent, one bias later. `check_overflow` compares a
predicted line count against the box it has to fit, so both sides come from the same
predictor and no amount of bias can make them disagree; these compare the predicted line
count against the one LibreOffice actually draws. `test_the_check_can_see_the_bias_it_was_
built_for` is the deliverable the fix is judged on: it fails on the pre-3a.6 predictor and
passes on this one, and it stays sensitive afterwards because it asserts what the old
predictor said, not merely what the new one says.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from autodeck.design.budget_check import (
    RENDER_HEADROOM_FRACTION,
    BudgetCheckError,
    check_against_render,
    check_line_count_against_render,
    count_ink_bands,
    measure_ink_height_pt,
    measure_line_pitch_pt,
    measure_rendered_pitch_pt,
    render_measurement_slide,
)
from autodeck.design.budgets import LINE_HEIGHT_FACTOR, load_metrics, wrap_text
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
#: `RENDER_HEADROOM_FRACTION` this has no reason to be generous:
#: `measure_line_pitch_pt` isolates the gap between two adjacent lines directly, with
#: none of `check_against_render`'s per-line headroom or `(N-1)`-vs-`N` slack to
#: absorb error. What is left is rasteriser
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
        f"delta {result.delta_pt:.2f}pt exceeds {RENDER_HEADROOM_FRACTION:.0%} of the "
        f"{result.line_box_pt:.2f}pt line box"
    )


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_body_copy_at_the_themes_line_height_matches_within_tolerance(tmp_path: Path) -> None:
    result = check_against_render(BODY, FAMILY, 16, 420, line_spacing=1.25, out_dir=tmp_path)
    assert result.line_count >= 2
    assert result.within_tolerance, (
        f"delta {result.delta_pt:.2f}pt exceeds {RENDER_HEADROOM_FRACTION:.0%} of the "
        f"{result.line_box_pt:.2f}pt line box"
    )


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_a_narrower_column_still_matches_within_tolerance(tmp_path: Path) -> None:
    """A different width changes where every line breaks, not just how many there are."""
    result = check_against_render(BODY, FAMILY, 16, 260, line_spacing=1.25, out_dir=tmp_path)
    assert result.line_count >= 2
    assert result.within_tolerance, (
        f"delta {result.delta_pt:.2f}pt exceeds {RENDER_HEADROOM_FRACTION:.0%} of the "
        f"{result.line_box_pt:.2f}pt line box"
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
@pytest.mark.parametrize("line_count_words", [4, 9, 14, 20, 30])
def test_the_ink_allowance_holds_at_every_length(line_count_words: int, tmp_path: Path) -> None:
    """The recalibration, asserted where the old constant failed.

    `RENDER_HEADROOM_FRACTION` replaced a flat fraction of the measured height, which
    could not be right at both ends: the same render's delta is 36% of the total at one
    line and 3.3% at six, so 0.15 — calibrated in 2b.1 on three cases of 3, 4 and 5 lines
    — rejected correct predictions either side of that window. This sweeps one text from
    one line to about eight and asserts the allowance holds throughout, which is the
    property a length-independent unit buys and the flat fraction never had."""
    text = " ".join(_PITCH_TEXT.split()[:line_count_words])
    result = check_against_render(text, FAMILY, 16, 300, line_spacing=1.25, out_dir=tmp_path)
    assert result.within_tolerance, (
        f"{result.line_count} line(s): delta {result.delta_pt:.2f}pt exceeds "
        f"{RENDER_HEADROOM_FRACTION:.0%} of the {result.line_box_pt:.2f}pt line box"
    )


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


# ---------------------------------------------------------------------------
# The line-count cross-check — prediction against render, not against itself.
#
# `check_against_render` above compares two *different* quantities (a predicted line box
# against rendered ink) and needs a 15% tolerance to reconcile them; PHASE-2B.md 6.2 is
# the record of a bias surviving inside exactly that kind of gap. These compare one
# quantity — how many lines the text wraps to — against itself, exactly, with no tolerance
# for a bias to hide in.
# ---------------------------------------------------------------------------


def _boundary_width_pt(text: str, size_pt: float) -> float:
    """A box width with ~2% of headroom for the REGULAR face of `FAMILY` at `size_pt`.

    Derived from the installed font rather than written down, so the case stays in the
    danger zone whichever Liberation build is present. Choosing the width from the regular
    metrics is deliberate: it reproduces the situation 3a.4 hit, where a headline sat a
    couple of percent inside its box by the only measurement anyone was taking. Nothing is
    *asserted* from that measurement — every assertion below is against the render.
    """
    return round(load_metrics(FAMILY).text_width(text, size_pt) * 1.02, 1)


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_the_check_can_see_the_bias_it_was_built_for(tmp_path: Path) -> None:
    """3a.6, proved end to end — and the one test here that would have FAILED before it.

    At a width with 2% of regular-weight headroom, the pre-3a.6 predictor (`wrap_text`
    with no face, which is all it could take) says one line; LibreOffice draws two, because
    Liberation Sans Bold sets this string 8.5% wider than the roman. That gap is the whole
    defect: a headline promised a line it does not have, with `check_overflow` agreeing
    because it only ever compared that same prediction to the box.

    The first assertion pins what the old predictor said. Keeping it is what stops this
    test decaying into "the current code agrees with itself" once the fix is old news — if
    a future change made the regular measurement wrap to two lines as well, the case would
    stop exercising the bias and this test says so rather than passing quietly.
    """
    width = _boundary_width_pt(HEADLINE, 32)
    assert wrap_text(HEADLINE, FAMILY, 32, width).line_count == 1

    result = check_line_count_against_render(
        HEADLINE, FAMILY, 32, width, line_spacing=1.15, bold=True, out_dir=tmp_path
    )
    assert result.rendered_lines == 2, result.describe()
    assert result.agrees, result.describe()


@pytest.mark.render
@needs_soffice
@needs_test_font
@pytest.mark.parametrize(
    "face",
    [
        pytest.param({}, id="regular"),
        pytest.param({"bold": True}, id="bold"),
        pytest.param({"italic": True}, id="italic"),
        pytest.param({"bold": True, "italic": True}, id="bold-italic"),
    ],
)
def test_predicted_and_rendered_line_counts_agree_for_every_face(
    face: dict[str, bool], tmp_path: Path
) -> None:
    """Every face the design system draws with, wrapped to several lines and checked
    against the render. Italic is covered even though Liberation's italic advances are
    identical to its roman — that identity is a property of this font, not of italics, and
    a test that skipped italic would stop covering the next family that differs."""
    result = check_line_count_against_render(
        BODY, FAMILY, 16, 420, line_spacing=1.25, out_dir=tmp_path, **face
    )
    assert result.predicted_lines >= 2
    assert result.agrees, result.describe()


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_the_ink_check_covers_bold_too(tmp_path: Path) -> None:
    """`check_against_render`'s own comparison, now exercised against a bold render —
    before 3a.6 nothing here rendered anything but regular, which is why the calibration
    behind `RENDER_HEADROOM_FRACTION` had never seen a bold case."""
    result = check_against_render(
        BODY, FAMILY, 16, 420, line_spacing=1.25, bold=True, out_dir=tmp_path
    )
    assert result.line_count >= 3
    assert result.within_tolerance, (
        f"delta {result.delta_pt:.2f}pt exceeds {RENDER_HEADROOM_FRACTION:.0%} of the "
        f"{result.line_box_pt:.2f}pt line box"
    )


@pytest.mark.render
@needs_soffice
@needs_test_font
def test_counting_bands_refuses_a_blank_render(tmp_path: Path) -> None:
    with pytest.raises(BudgetCheckError):
        render_measurement_slide("", FAMILY, 16, 300, out_dir=tmp_path)


def test_count_ink_bands_counts_separated_bands(tmp_path: Path) -> None:
    """The render-free half: three bands with clear background between them are three
    lines. Shares `_band_start_rows` with the pitch measurement, so this pins the count
    rather than the geometry that test already covers."""
    image = Image.new("L", (100, 200), 255)
    draw = ImageDraw.Draw(image)
    for top in (10, 40, 70):
        draw.rectangle([10, top, 90, top + 19], fill=0)
    path = tmp_path / "three.png"
    image.save(path)

    assert count_ink_bands(path, dpi=150, size_pt=16) == 3


def test_a_tittle_does_not_count_as_its_own_line(tmp_path: Path) -> None:
    """The artefact this counter was corrected for, reproduced synthetically.

    A real 32pt render of "romeo sierra" paints two bands: the dot of the `i`, 13px clear
    of the x-height band under it at 150dpi, is the only ink that line puts above
    x-height. Counting bands naively made that one line read as two and the cross-check
    reported a disagreement that was not there — see `_BAND_MERGE_FRACTION`. The geometry
    below is that render's, to the pixel: bands 92px apart are separate lines; a 13px
    island is part of the line under it."""
    image = Image.new("L", (200, 400), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, 190, 60], fill=0)  # an ordinary line
    draw.rectangle([20, 102, 30, 110], fill=0)  # the tittle
    draw.rectangle([10, 115, 190, 155], fill=0)  # its own line's x-height band
    path = tmp_path / "tittle.png"
    image.save(path)

    assert count_ink_bands(path, dpi=150, size_pt=32) == 2


def test_count_ink_bands_refuses_a_blank_image(tmp_path: Path) -> None:
    """Returning 0 would compare as a real disagreement with any prediction, which reads
    as a measurement failure rather than as "nothing was rendered"."""
    image = Image.new("L", (100, 100), 255)
    path = tmp_path / "blank.png"
    image.save(path)

    with pytest.raises(BudgetCheckError, match="no ink"):
        count_ink_bands(path, dpi=150, size_pt=16)
