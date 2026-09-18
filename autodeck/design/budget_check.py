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
gap. Ink-based deltas after the fix are *larger*, not smaller (see `RENDER_TOLERANCE`'s
comment): a correct, bigger line-box prediction naturally sits further above the same
(unavoidably shorter) ink footprint, which is the expected shape once the two questions are
told apart rather than a sign of a new problem.

Owning phase: 2b (task 2b.1), extending the Phase 0 budgets engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from autodeck.design.budgets import measure_height, wrap_text
from autodeck.design.draw import add_text
from autodeck.design.layout_kit import Box, TextStyle
from autodeck.design.theme.tokens import DesignTokens, Typography
from autodeck.render.qa.libreoffice import DEFAULT_DPI, render_pptx

#: How far "measured" (line-box, from `budgets.LINE_HEIGHT_FACTOR`) and "rendered" (ink,
#: from a real LibreOffice PNG) may diverge before the cross-check fails, as a fraction of
#: the measured height.
#:
#: This was `0.06` before 2b.1's line-height fix, calibrated (wrongly, as it turned out —
#: see the module docstring) against a *biased* prediction that happened to sit close to
#: ink height. Fixing the bias made `measured_pt` bigger by design — the corrected pitch is
#: genuinely larger than the old one — while `rendered_pt` (real ink) is unchanged, so every
#: delta below grew by roughly the same ~7.4% the fix added. Recalibrated against the same
#: three multi-line title/body combinations the render-marked tests below use:
#:
#: - headline, 32pt, ls=1.15, 4 lines: 7.9%
#: - body copy, 16pt, ls=1.25, 3 lines: 12.0%   (fewest lines here, so point 1's headroom
#:   is the largest share of the total — the expected shape, not an outlier)
#: - body copy narrower, 16pt, ls=1.25, 5 lines: 7.2%
#:
#: 0.15 leaves margin above the worst of those (12.0%) while still catching a gross error —
#: an accidentally-doubled line height, or a budget measured against the wrong family, moves
#: `measured_pt` by far more than 15% in every case tried during this fix. This tolerance
#: exists for the ink comparison only; `measure_line_pitch_pt`'s render test uses a tight,
#: separate tolerance because pitch does not carry point 1's per-line headroom to begin
#: with, and is the check that actually protects `LINE_HEIGHT_FACTOR`'s value.
RENDER_TOLERANCE = 0.15

#: A floor under `RENDER_TOLERANCE` for short text, where 6% of the measured height can be
#: smaller than a single rendered pixel at `DEFAULT_DPI` (150dpi → 0.48pt/px) and the check
#: would fail on rasteriser quantisation rather than a real disagreement.
RENDER_TOLERANCE_FLOOR_PT = 2.0

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
    style = TextStyle(family=family, size=size_pt, line_spacing=line_spacing)
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
        text, family, size_pt, width_pt, line_spacing=line_spacing, out_dir=out_dir, dpi=dpi
    )
    return measure_line_pitch_pt(rendered.image, dpi)


@dataclass(frozen=True)
class BudgetCheckResult:
    """One comparison between `budgets.py`'s prediction and a real LibreOffice render."""

    measured_pt: float
    """What `measure_height` predicted."""
    rendered_pt: float
    """What the LibreOffice render's ink actually measured."""
    line_count: int
    """How many lines `wrap_text` folded the text into — see `within_tolerance`."""
    image: Path
    """The rendered PNG, kept for a human to open when a check fails."""

    @property
    def delta_pt(self) -> float:
        return self.measured_pt - self.rendered_pt

    @property
    def within_tolerance(self) -> bool:
        """Whether `delta_pt` sits inside `RENDER_TOLERANCE` of the measured height.

        Meaningful only for `line_count >= 2` (module docstring); a caller checking a
        single line is measuring the predicted line box's own unused headroom (module
        docstring, point 1), not this module's accuracy, and this property does not
        attempt to compensate for that.
        """
        allowed = max(self.measured_pt * RENDER_TOLERANCE, RENDER_TOLERANCE_FLOOR_PT)
        return abs(self.delta_pt) <= allowed


def check_against_render(
    text: str,
    family: str,
    size_pt: float,
    width_pt: float,
    *,
    line_spacing: float = 1.0,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
) -> BudgetCheckResult:
    """Compare `budgets.measure_height` against a real LibreOffice render of the same text.

    This is the whole point of the module — everything above exists to produce the two
    numbers compared here.
    """
    measured = measure_height(text, family, size_pt, width_pt, line_spacing)
    rendered = render_measurement_slide(
        text, family, size_pt, width_pt, line_spacing=line_spacing, out_dir=out_dir, dpi=dpi
    )
    lines = wrap_text(text, family, size_pt, width_pt).line_count
    return BudgetCheckResult(
        measured_pt=measured,
        rendered_pt=rendered.height_pt,
        line_count=lines,
        image=rendered.image,
    )
