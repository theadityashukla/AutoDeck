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

## Why an exact match is not, and should not be, the target

`measure_height` predicts **line-box** height: the pitch a layout engine advances by, line
to line, from the font's declared vertical metrics. That is the number a renderer actually
consumes when it decides where the next element goes, and it is what a budget must bound.
This checker can only see **ink** — the pixels the glyphs actually paint — and ink is
structurally shorter than the line box that contains it, for two reasons found while
building this check, not assumed going in:

1. **A single line rarely fills its own line box.** A line box reserves room for the
   tallest ascender and deepest descender the font ships, including glyphs (accents,
   non-Latin) a given string never uses. For one line this gap can be enormous relative to
   the line's own height — measured at 28% of the predicted height for one plain-English
   caption during calibration (§ below) — and it shrinks as a share of the total the more
   lines there are, because interior line-to-line pitch is unaffected by it. So this module
   only means anything for text that **wraps to two or more lines**; the tests choose
   text/width pairs accordingly rather than special-casing single lines in code.
2. **LibreOffice's own single-spacing pitch does not equal the font's hhea ascent+descent**
   that `_line_height_factor` uses. Measured against Liberation Sans (ascent+descent ~=
   1.117x the point size) at `line_spacing=1.0`, LibreOffice's actual line-to-line pitch
   came out at 1.2x the point size — a ~7% gap with no dependence on this checker's DPI,
   threshold or sampling. This is a real, previously unverified mismatch in `budgets.py`'s
   model of "single" spacing, not a rendering artefact; see the tolerance comment below and
   the task report for what it means going forward. It was **not** fixed here — 2b.1 is
   scoped to add verification, and `budgets.py` is extended, not rewritten, this task.

Owning phase: 2b (task 2b.1), extending the Phase 0 budgets engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from autodeck.design.budgets import measure_height, wrap_text
from autodeck.design.draw import add_text
from autodeck.design.layout_kit import Box, TextStyle
from autodeck.design.theme.tokens import DesignTokens, Typography
from autodeck.render.qa.libreoffice import DEFAULT_DPI, render_pptx

#: How far "measured" (line-box, from font metrics) and "rendered" (ink, from a real
#: LibreOffice PNG) may diverge before the cross-check fails, as a fraction of the measured
#: height. Calibrated against six title/heading/body/caption combinations at this design
#: system's real type-scale sizes and line spacings, restricted to text wrapping to 2+
#: lines (see the module docstring for why): the worst was 3.9%, most sat under 3%. 6%
#: leaves real margin above every multi-line case actually observed while still catching a
#: gross error — an accidentally-doubled line height, or a budget measured against the
#: wrong family, would miss by far more than this.
RENDER_TOLERANCE = 0.06

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
        single line is measuring the font's unused ascent/descent headroom, not this
        module's accuracy, and this property does not attempt to compensate for that.
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
