"""LibreOffice cross-check for `budgets.py` — proves the measurement, doesn't repeat it.

`budgets.py` predicts wrapped-text height from font-file glyph metrics alone, deliberately
free of any renderer, so the content agent and CI can import it without a display stack
(see its own module docstring). That leaves the brief's actual done-when unanswered:
*"measured height matches LibreOffice-rendered height within tolerance."* Nothing before
this module checked that a prediction and a real render agree — a budget could have been
confidently, silently wrong since Phase 0. This module is the check, kept separate so the
dependency it needs (`soffice`, `pdftoppm`, a real installed font) never leaks into
`budgets.py` and CI stays exactly as fast and font-free as before.

The method: build a one-slide PPTX with the same text/family/size/width/line-spacing
`compute_budget` was given, render it through the same `render/qa/libreoffice` pipeline the
design-loop preview uses (not a second, hand-rolled `soffice` invocation that could quietly
drift from the real one), and measure how tall the rendered *ink* actually is.

## Two different questions, both answered here

`measure_height` predicts **line-box** height: the pitch a layout engine advances by, line
to line, from `budgets.LINE_HEIGHT_FACTOR`. That pitch is the number a renderer actually
consumes when it decides where the next element goes, and it is what a budget must bound.
Two functions below check it two different ways, and neither replaces the other:

* `measure_ink_height_pt` measures **ink** — the pixels the glyphs actually paint, top of
  the first ascender to bottom of the last descender. It answers "does the overall block
  roughly match?" and is what `check_against_render`/`BudgetCheckResult` use.
* `measure_line_pitch_pt` measures **pitch** directly — the vertical gap between one line's
  ink and the next's, which is what a font's line-height model actually claims to predict.
  It answers "is the *spacing* right?", and it is the one that would have caught 2b.1's
  line-height bug; ink height would not have, for the structural reason below.

## Why ink height cannot see a pitch bias

Ink is structurally shorter than the line boxes that contain it, for two reasons found
while building this check, not assumed going in:

1. **A single line rarely fills its own line box.** A line box reserves room for the
   tallest ascender and deepest descender the font ships, including glyphs (accents,
   non-Latin) a given string never uses. For one line this gap can be enormous relative to
   the line's own height — measured at 28% of the predicted height for one plain-English
   caption during calibration (§ below) — and it shrinks as a share of the total the more
   lines there are, because interior line-to-line pitch is unaffected by it. So `ink`-based
   comparisons only mean anything for text that **wraps to two or more lines**; the tests
   choose text/width pairs accordingly rather than special-casing single lines in code.

2. **For N lines, total ink spans `(N-1) x pitch + one line's own ink`, never `N x pitch`.**
   That `-1` is exactly wide enough to hide a pitch bias: 2b.1 first shipped `budgets.py`
   deriving the line box from the font's hhea `ascent + descent` (~1.117x the point size
   for Liberation Sans), which under-predicted LibreOffice's real single-spaced pitch
   (1.2x) by ~7.4%. Comparing *that* prediction against ink height gave deltas of +1.1%,
   +5.5% and +0.3% on the three cases below — inside tolerance, reading as agreement. It
   was not agreement: the under-predicted pitch and point 1's per-line headroom (present in
   the ink figure but absent from a pitch-only prediction) both push the comparison the
   same way by coincidence for these particular line counts, and partly cancelled the
   7.4% error rather than exposing it. `measure_line_pitch_pt` cannot be fooled by this,
   because it never sums N lines together — it measures the gap between two adjacent ones
   directly, which is exactly what a wrong per-font factor or a wrong constant gets wrong.

`_line_height_factor`'s replacement (`budgets.LINE_HEIGHT_FACTOR`) is now correct — see its
docstring for the fix — so this module's numbers above describe history, not the present
gap. Ink-based deltas after the fix are *larger*, not smaller: a correct, bigger line-box
prediction naturally sits further above the same (unavoidably shorter) ink footprint,
which is the expected shape once the two questions are told apart rather than a sign of a
new problem. Point 2's arithmetic also fixes the *shape* of the ink allowance — it is one
line's headroom, constant in N, which is why `RENDER_HEADROOM_FRACTION` is a fraction of a
line box rather than of the measured total.

## Same quantity, compared exactly: the line count

Both functions above reconcile two quantities that differ by construction, and both
therefore need a tolerance — which is where PHASE-2B.md 6.2's bias hid. 3a.6 added the
comparison that needs none: `check_line_count_against_render` puts the predicted line
count beside the rendered one. One quantity, integers, no tolerance. It exists because
`catalog.check_overflow` — the gate that decides whether written content may be rendered
— compares a predicted line count against the box, which is the same predictor on both
sides and so cannot detect a biased predictor at all. See that function's docstring.

Owning phase: 2b (task 2b.1), extending the Phase 0 budgets engine. The line-count check
and the recalibrated ink allowance are 3a.6's.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from autodeck.design.budgets import LINE_HEIGHT_FACTOR, measure_height, wrap_text
from autodeck.design.draw import add_text
from autodeck.design.layout_kit import Box, TextStyle
from autodeck.design.theme.tokens import DesignTokens, Typography
from autodeck.render.qa.libreoffice import DEFAULT_DPI, render_pptx

#: How far "measured" (line-box, from `budgets.LINE_HEIGHT_FACTOR`) and "rendered" (ink,
#: from a real LibreOffice PNG) may diverge before the cross-check fails — as a fraction of
#: **one line box**, not of the measured height.
#:
#: That unit is the whole of 3a.6's recalibration, and it is derived rather than fitted.
#: The module docstring's point 2 says total ink spans `(N-1) x pitch + one line's own ink`
#: where the prediction is `N x pitch`, so the difference is
#:
#:     delta = pitch - (one line's ink)
#:
#: which is **constant in N**. Measured on Liberation Sans, N sweeping 1 to 6 (the raw
#: figures; the two values per row are lines whose tallest glyph differs, quantised to the
#: 150dpi pixel grid):
#:
#: - 16pt, ls=1.25 (pitch 24.00pt): delta 8.64 or 11.52pt -> at most 0.480 of a pitch
#: - 32pt, ls=1.15 (pitch 44.16pt): delta 13.92 or 20.16pt -> at most 0.457 of a pitch
#: - 22pt, ls=1.00 (pitch 26.40pt): delta 5.28 or 9.60pt  -> at most 0.436 of a pitch
#:
#: The same deltas as a fraction of the measured height — what this constant used to be —
#: run from 36.0% at N=1 to 3.3% at N=6 on those very rows. A flat fraction therefore
#: cannot be right at both ends, and 0.15 was not: it was calibrated in 2b.1 on three
#: cases of 3, 4 and 5 lines and it **rejects a correct 2-line prediction** (measured
#: 24.0% here, and 15.8% for the bold headline that started 3a.6). Calibrating a
#: wrong-shaped constant on a narrow sample is how it came to look settled — the same
#: mistake as 2b.1's, in the axis 2b.1 was not looking at.
#:
#: 0.65 leaves 35% of headroom above the worst measured case (0.480) and stays below 1.0,
#: which matters: `delta < pitch` holds by construction whenever the line counts agree, so
#: a threshold of one whole pitch would be a tautology that passes everything. What this
#: value actually asserts is **"the rendered block is within two-thirds of a line of the
#: prediction"** — a sensitivity that no longer changes with the length of the text, where
#: 15% of the measured height meant two-thirds of a line at N=4 and four whole lines at
#: N=27.
#:
#: Bold and italic were included in the sweep for the first time here (nothing in this
#: module rendered anything but regular before 3a.6). They move the ink figure by a pixel
#: or two and nothing else: a bold face paints slightly taller glyphs, so its ink is
#: marginally *closer* to the prediction, not further.
RENDER_HEADROOM_FRACTION = 0.65

#: Anything this dark or darker, on the greyscale render, counts as ink. Not pure black:
#: anti-aliasing fades a glyph's edge gradually to white, and requiring exact white for
#: "background" would clip that fading edge out of the measurement.
_INK_THRESHOLD = 250

#: Well inside the safe area on every slide size this codebase uses, and tall enough that
#: no plausible calibration text is clipped — `add_text` renders with autofit off (its own
#: docstring explains why), so a box too short here would silently under-measure instead of
#: raising, which is exactly the failure this checker exists to catch elsewhere.
_BOX_ORIGIN = 72.0
_BOX_MAX_HEIGHT = 4500.0


class BudgetCheckError(RuntimeError):
    """The render pipeline produced nothing this module could measure."""


@dataclass(frozen=True)
class RenderedInk:
    """What one rendered PNG actually shows for a measurement slide."""

    height_pt: float
    image: Path


def measure_ink_height_pt(image_path: Path, dpi: int) -> float:
    """The vertical span of non-background pixels in `image_path`, in points.

    Split out from `render_measurement_slide` so the "detect ink, convert by DPI" logic has
    its own fast, render-free test against a synthetic image — the full LibreOffice pipeline
    only needs to be exercised for the cross-check itself, not for this arithmetic.

    Raises:
        BudgetCheckError: the image is entirely background; there is nothing to measure.
    """
    from PIL import Image

    def _ink_mask(value: int) -> int:
        return 255 if value < _INK_THRESHOLD else 0

    with Image.open(image_path) as raw:
        # `.point()` + `.getbbox()` is PIL's own (C-implemented) scan, which is what makes
        # this fast enough to run once per test rather than a hand-rolled pixel loop.
        mask = raw.convert("L").point(_ink_mask)
        box = mask.getbbox()

    if box is None:
        raise BudgetCheckError(
            f"{image_path} has no ink above the {_INK_THRESHOLD}/255 threshold; nothing "
            "was rendered, or the calibration text was blank."
        )
    _, top, _, bottom = box  # getbbox()'s lower/right edges are exclusive, so no +1 needed.
    return (bottom - top) / dpi * 72.0


def _ink_row_mask(image_path: Path) -> tuple[list[bool], int]:
    """Which rows of `image_path` contain at least one ink pixel, top to bottom.

    Shared scanning step behind `measure_line_pitch_pt`: `measure_ink_height_pt` only needs
    the overall bounding box, which PIL's own `getbbox()` gives in one C call, but a pitch
    needs to know *where each line starts*, which means walking rows.
    """
    from PIL import Image

    def _ink_mask(value: int) -> int:
        return 255 if value < _INK_THRESHOLD else 0

    with Image.open(image_path) as raw:
        mask = raw.convert("L").point(_ink_mask)
        width, height = mask.size
        rows = mask.tobytes()  # mode "L": one byte per pixel, row-major.

    has_ink = [any(rows[y * width : (y + 1) * width]) for y in range(height)]
    return has_ink, height


def _band_start_rows(has_ink: list[bool]) -> list[int]:
    """Row indices where an ink band begins: ink immediately after a background row."""
    starts = []
    previous = False
    for y, ink in enumerate(has_ink):
        if ink and not previous:
            starts.append(y)
        previous = ink
    return starts


def measure_line_pitch_pt(image_path: Path, dpi: int) -> float:
    """The line-to-line pitch in `image_path`, in points: the median gap between the
    *starts* of consecutive ink bands.

    A different question from `measure_ink_height_pt` — see the module docstring's "Two
    different questions" section for why the two cannot substitute for each other. This one
    isolates the spacing a layout engine actually advances by, which is what
    `budgets.LINE_HEIGHT_FACTOR` claims to predict and what an under- or over-predicting
    factor gets wrong directly, with no `(N-1)`-vs-`N` cancellation in the way.

    The median, not the mean, of the gaps: at typical rendering DPI a line's detected top
    can land on either side of its true position by a pixel depending on whether that
    particular line happens to have an ascender right at its left margin, which nudges
    individual gaps up or down by under a point without moving the real pitch — the median
    shrugs that off, where a mean would not. It also refuses to be dragged by the rare
    merged- or split-band artefact (two lines' ink touching, or a stray speck) that a mean
    would average in as if it were real data.

    Raises:
        BudgetCheckError: fewer than two ink bands were found; a pitch needs at least two
            line starts to measure the gap between.
    """
    has_ink, _ = _ink_row_mask(image_path)
    starts = _band_start_rows(has_ink)
    if len(starts) < 2:
        raise BudgetCheckError(
            f"{image_path} has {len(starts)} ink band(s); a pitch needs at least two lines "
            "to measure the gap between one and the next."
        )

    gaps_px = sorted(b - a for a, b in pairwise(starts))
    mid = len(gaps_px) // 2
    median_px = gaps_px[mid] if len(gaps_px) % 2 else (gaps_px[mid - 1] + gaps_px[mid]) / 2
    return median_px / dpi * 72.0


def render_measurement_slide(
    text: str,
    family: str,
    size_pt: float,
    width_pt: float,
    *,
    line_spacing: float = 1.0,
    bold: bool = False,
    italic: bool = False,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
) -> RenderedInk:
    """Render `text` alone on a slide and measure its ink height from the resulting PNG.

    Builds a throwaway one-slide deck with `text` in a textbox of `width_pt`, using exactly
    the `TextStyle` `compute_budget` would have sized it with, then renders it through
    `render.qa.libreoffice.render_pptx` — the same pipeline the design-loop preview uses,
    so this checker is honestly measuring the real preview path rather than a parallel one
    that could quietly drift from it.

    Raises:
        FontSubstitutionRisk: `family` is not installed for LibreOffice to render with
            (`render_pptx` checks before rendering; see its own docstring).
        RenderError: LibreOffice or the rasteriser failed.
        BudgetCheckError: the render produced no ink at all.
    """
    tokens = DesignTokens(
        name="budget-check", typography=Typography(major=family, minor=family)
    )
    presentation = Presentation()
    presentation.slide_width = Emu(tokens.slide_width_emu)
    presentation.slide_height = Emu(tokens.slide_height_emu)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])  # blank layout

    box = Box(x=_BOX_ORIGIN, y=_BOX_ORIGIN, width=width_pt, height=_BOX_MAX_HEIGHT)
    style = TextStyle(
        family=family, size=size_pt, line_spacing=line_spacing, bold=bold, italic=italic
    )
    add_text(slide, box, text, style)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = out_dir / "measurement.pptx"
    presentation.save(str(pptx_path))

    result = render_pptx(pptx_path, out_dir, tokens, dpi=dpi)
    height_pt = measure_ink_height_pt(result.images[0], result.dpi)
    return RenderedInk(height_pt=height_pt, image=result.images[0])


def measure_rendered_pitch_pt(
    text: str,
    family: str,
    size_pt: float,
    width_pt: float,
    *,
    line_spacing: float = 1.0,
    bold: bool = False,
    italic: bool = False,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
) -> float:
    """Render `text` and return LibreOffice's real line-to-line pitch, in points.

    The pitch half of the cross-check, sitting beside `check_against_render`'s ink half —
    thin composition of `render_measurement_slide` (for the PNG, so both halves render
    through the identical path) and `measure_line_pitch_pt` (for the gap between ink
    bands). This is the function that would have caught 2b.1's bias; see the module
    docstring for why the ink half could not.

    Raises:
        FontSubstitutionRisk, RenderError: as `render_measurement_slide`.
        BudgetCheckError: the render was blank, or wrapped to fewer than two lines — choose
            `text`/`width_pt` so it wraps to at least two.
    """
    rendered = render_measurement_slide(
        text,
        family,
        size_pt,
        width_pt,
        line_spacing=line_spacing,
        bold=bold,
        italic=italic,
        out_dir=out_dir,
        dpi=dpi,
    )
    return measure_line_pitch_pt(rendered.image, dpi)


#: Two ink bands closer together than this fraction of the point size are parts of one
#: rendered line, not two lines. Found empirically, not assumed: rendering "romeo sierra"
#: at 32pt produced two bands where the line-count check expected one, because the only
#: ink that line paints above x-height is the tittle of its `i` — a 13px island 13px clear
#: of the band below it at 150dpi (0.20em), while real lines sat 92px apart. Accents and
#: any other floating diacritic do the same thing.
#:
#: 0.5 sits well clear of both sides of that measurement and does so structurally rather
#: than by luck: the smallest line-to-line pitch this codebase can produce is
#: `size_pt * 0.9 * LINE_HEIGHT_FACTOR` (the `quote` mark's spacing), which is 1.08em and
#: cannot be mistaken for 0.5em, while a tittle's clearance is a fraction of x-height.
#:
#: The threshold is a fraction of the **point size**, which is an input the caller handed
#: to the renderer, not an output of `budgets.py`. That matters: a merge rule keyed on
#: anything the predictor produced would let a biased predictor quietly edit the render it
#: is being checked against, which is the failure this whole module exists to avoid.
_BAND_MERGE_FRACTION = 0.5


def count_ink_bands(image_path: Path, *, dpi: int, size_pt: float) -> int:
    """How many rendered **lines** of text `image_path` contains.

    Bands of ink, with bands closer than `_BAND_MERGE_FRACTION` of the point size merged
    into one line — see that constant for the measured reason a line can paint two bands.
    For a measurement slide holding nothing but wrapped text, the result is the number of
    lines the renderer drew; `check_line_count_against_render` states the remaining
    conditions that make that so, and is the only caller that depends on it.

    Raises:
        BudgetCheckError: the image is entirely background.
    """
    has_ink, _ = _ink_row_mask(image_path)
    starts = _band_start_rows(has_ink)
    if not starts:
        raise BudgetCheckError(
            f"{image_path} has no ink above the {_INK_THRESHOLD}/255 threshold; nothing "
            "was rendered, or the calibration text was blank."
        )

    minimum_gap_px = _BAND_MERGE_FRACTION * size_pt / 72.0 * dpi
    lines = 1
    previous = starts[0]
    for start in starts[1:]:
        if start - previous >= minimum_gap_px:
            lines += 1
            previous = start
    return lines


@dataclass(frozen=True)
class LineCountCheck:
    """Predicted line count against rendered line count, for one piece of text.

    Both numbers answer the **same** question — *how many lines does this text wrap to at
    this width, in this face?* — which is the whole point of this dataclass existing
    separately from `BudgetCheckResult`. See `check_line_count_against_render`.
    """

    predicted_lines: int
    """What `budgets.wrap_text` said, from glyph advance widths alone."""
    rendered_lines: int
    """How many lines LibreOffice actually drew, counted as bands of ink."""
    image: Path
    """The rendered PNG, kept for a human to open when the two disagree."""

    @property
    def agrees(self) -> bool:
        """Exact equality. A line count is an integer and there is nothing to round."""
        return self.predicted_lines == self.rendered_lines

    def describe(self) -> str:
        return (
            f"predicted {self.predicted_lines} line(s), rendered "
            f"{self.rendered_lines} ({self.image})"
        )


def check_line_count_against_render(
    text: str,
    family: str,
    size_pt: float,
    width_pt: float,
    *,
    line_spacing: float = 1.0,
    bold: bool = False,
    italic: bool = False,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
) -> LineCountCheck:
    """Compare the line count `budgets.wrap_text` predicts against the one LibreOffice
    renders.

    ## Why this exists, and what it is not

    `catalog.check_overflow` — the deterministic gate that decides whether written content
    may be rendered — asks "does the predicted line count fit the box?". Both sides of that
    comparison come from the same predictor, so it compares a prediction against itself and
    **cannot detect a biased predictor**, only an over-long string. That is how 3a.6's
    defect reached a committed PNG with every automated check green: `budgets.py` measured
    bold text against the regular face, `check_overflow` agreed with it, and the only thing
    that disagreed was a human looking at the picture.

    This function is the check that can disagree. It is the twin of PHASE-2B.md 6.2's
    lesson (*a cross-check that measures a different quantity than the thing it is checking
    will report agreement it has not established*), so it is worth being exact about the
    quantity, as that finding demands:

    * **Predicted**: `wrap_text(...).line_count` — how many lines the greedy wrap folds
      `text` into, from the advance widths of the requested face.
    * **Rendered**: bands of ink in the PNG — how many lines LibreOffice actually drew.

    Same quantity, same units, independently arrived at, and compared **exactly**: a line
    count is an integer, so there is no tolerance to hide a bias behind. That is the
    difference from `check_against_render`, which compares a predicted line *box* against
    rendered *ink* — two different quantities, reconciled by a 15% tolerance wide enough
    that 2b.1's 7.4% bias read as agreement inside it.

    ## When a band is a line

    Three conditions, all of which the caller owns and none of which this function can
    check for itself:

    1. **The slide holds nothing but this text.** `render_measurement_slide` guarantees it.
    2. **No line is blank.** An empty line paints no ink and produces no band, so `text`
       must not contain blank lines. `wrap_text` emits one for a blank paragraph, so the
       two would disagree for a reason that has nothing to do with measurement.
    3. **Adjacent lines' ink does not touch.** A descender meeting the next line's
       ascender merges two bands into one. At this codebase's line spacings (0.9 and up,
       against `LINE_HEIGHT_FACTOR` 1.2) there is real space between lines and observed
       band counts match line counts exactly across 54 rendered cases; at a tight enough
       spacing they would not. A merge under-counts the render, which biases this check
       towards *reporting a disagreement that is not there* — the safe direction for a
       check to fail in.

    The converse — one line painting two bands — is real and is handled rather than
    assumed away: see `_BAND_MERGE_FRACTION`, which exists because this check found such a
    case on its first sweep and reported it as a disagreement, exactly as designed.

    Raises:
        FontSubstitutionRisk, RenderError: as `render_measurement_slide`.
        BudgetCheckError: the render produced no ink at all.
    """
    predicted = wrap_text(text, family, size_pt, width_pt, bold=bold, italic=italic)
    rendered = render_measurement_slide(
        text,
        family,
        size_pt,
        width_pt,
        line_spacing=line_spacing,
        bold=bold,
        italic=italic,
        out_dir=out_dir,
        dpi=dpi,
    )
    return LineCountCheck(
        predicted_lines=predicted.line_count,
        rendered_lines=count_ink_bands(rendered.image, dpi=dpi, size_pt=size_pt),
        image=rendered.image,
    )


@dataclass(frozen=True)
class BudgetCheckResult:
    """One comparison between `budgets.py`'s prediction and a real LibreOffice render."""

    measured_pt: float
    """What `measure_height` predicted."""
    rendered_pt: float
    """What the LibreOffice render's ink actually measured."""
    line_count: int
    """How many lines `wrap_text` folded the text into."""
    size_pt: float
    line_spacing: float
    """The type size and spacing the slide was rendered at. Carried because the allowance
    in `within_tolerance` is one line box wide, and a line box is made of these two."""
    image: Path
    """The rendered PNG, kept for a human to open when a check fails."""

    @property
    def delta_pt(self) -> float:
        return self.measured_pt - self.rendered_pt

    @property
    def line_box_pt(self) -> float:
        """One line's predicted height — the unit the allowance below is measured in."""
        return self.size_pt * self.line_spacing * LINE_HEIGHT_FACTOR

    @property
    def within_tolerance(self) -> bool:
        """Whether `delta_pt` sits inside `RENDER_HEADROOM_FRACTION` of one line box.

        Not a fraction of the measured height: the gap between a predicted line box and
        rendered ink is one line's unused headroom, which does not grow with the text (see
        `RENDER_HEADROOM_FRACTION` for the measurement). Because the allowance is now in
        the same units as the thing it allows for, this is meaningful at any line count,
        including one — the old fraction-of-total form was the only reason a single line
        had to be excluded.
        """
        return abs(self.delta_pt) <= self.line_box_pt * RENDER_HEADROOM_FRACTION


def check_against_render(
    text: str,
    family: str,
    size_pt: float,
    width_pt: float,
    *,
    line_spacing: float = 1.0,
    bold: bool = False,
    italic: bool = False,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
) -> BudgetCheckResult:
    """Compare `budgets.measure_height` against a real LibreOffice render of the same text.

    This is the whole point of the module — everything above exists to produce the two
    numbers compared here.
    """
    measured = measure_height(
        text, family, size_pt, width_pt, line_spacing, bold=bold, italic=italic
    )
    rendered = render_measurement_slide(
        text,
        family,
        size_pt,
        width_pt,
        line_spacing=line_spacing,
        bold=bold,
        italic=italic,
        out_dir=out_dir,
        dpi=dpi,
    )
    lines = wrap_text(text, family, size_pt, width_pt, bold=bold, italic=italic).line_count
    return BudgetCheckResult(
        measured_pt=measured,
        rendered_pt=rendered.height_pt,
        line_count=lines,
        size_pt=size_pt,
        line_spacing=line_spacing,
        image=rendered.image,
    )
