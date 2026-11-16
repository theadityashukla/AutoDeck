"""Deterministic checks for a creative-mode slide (B69), run before anything is drawn.

A component's text is held to a budget before it is written; a free layout has no budget, so
this is where its promise is made. Every check is geometry, measurement or arithmetic on the
IR and the tokens: no model, no LibreOffice, same answer every time.

* `text_fit`: each text element's text, measured at its real style in its real box
  (`Canvas.measure_block`, the measurement the components use), fits in height, and no word
  is wider than the box. The automatic source line is held to the same test in its band.
* `safe_area`: a text box lies inside the master's safe area. Shapes may bleed.
* `overlap`: no text box overlaps another text box or a visual; no two visuals overlap.
* `source_band`: no text or visual enters the reserved source-line band (only when the slide
  draws a source line).
* `min_size`: text is at least the master's `typography.minimum`.
* `contrast`: each text colour against what is beneath its box (the topmost earlier shape
  that fully covers it, tint applied, else the slide background) is at least 4.5:1, or 3:1
  from 24pt up; the source line likewise, with the best of its three colours.
* `hidden_text`: a shape drawn after a text element and overlapping it would paint over it.

Findings are data. `FreeLayoutQAError` carries them out of the renderer; the draft preview
turns it into a placeholder and the aesthetic loop can read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from autodeck.design.free_layout import (
    CONTRAST_LARGE,
    CONTRAST_NORMAL,
    LARGE_TEXT_PT,
    beneath_hex,
    block_text,
    boxes_overlap,
    contrast_ratio,
    frame_box,
    measure_text,
    palette_hex,
    source_band,
    source_color,
    source_text_to_draw,
    text_style,
)
from autodeck.design.layout_kit import FIT_TOLERANCE, Box, Canvas, LayoutOverflowError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import ShapeElement, Slide, TextElement, VisualElement

SOURCE_ELEMENT = ""
TEXT_FIT = "text_fit"
SAFE_AREA = "safe_area"
OVERLAP = "overlap"
SOURCE_BAND = "source_band"
MIN_SIZE = "min_size"
CONTRAST = "contrast"
HIDDEN_TEXT = "hidden_text"


@dataclass(frozen=True)
class FreeLayoutFinding:
    slide_id: str
    block_id: str
    """The placed block's id; `""` for the source line."""
    check: str
    message: str


class FreeLayoutQAError(LayoutOverflowError):
    """A creative layout failed its checks; `findings` says how. Nothing was drawn."""

    def __init__(self, slide_id: str, findings: list[FreeLayoutFinding]) -> None:
        self.slide_id = slide_id
        self.findings = tuple(findings)
        detail = "; ".join(f"[{f.check}] {f.block_id or f.check}: {f.message}" for f in findings)
        super().__init__(f"slide {slide_id!r} free layout: {detail}")


def check_free_layout(slide: Slide, tokens: DesignTokens) -> list[FreeLayoutFinding]:
    """All checks over `slide.layout`; `[]` when it holds (or the slide has no layout).

    Pass the tokens the slide will be drawn with (`renderer.scaled_tokens` for its type
    scale): sizes and the minimum come from them.
    """
    layout = slide.layout
    if layout is None:
        return []
    canvas = Canvas(tokens)
    blocks = {b.id: b for b in slide.blocks}
    findings: list[FreeLayoutFinding] = []

    def add(element: str, check: str, message: str) -> None:
        findings.append(FreeLayoutFinding(slide.id, element, check, message))

    safe = canvas.safe
    texts: list[tuple[int, TextElement, Box]] = []
    visuals: list[tuple[VisualElement, Box]] = []
    for index, element in enumerate(layout.elements):
        if isinstance(element, TextElement):
            texts.append((index, element, frame_box(canvas, element.frame)))
        elif isinstance(element, VisualElement):
            visuals.append((element, frame_box(canvas, element.frame)))

    source = source_text_to_draw(slide)
    band = source_band(canvas)

    for index, element, box in texts:
        text = block_text(blocks[element.block_id])
        style = text_style(canvas, element)
        name = element.block_id

        if not safe.contains(box):
            add(name, SAFE_AREA, f"text box leaves the {tokens.spacing.safe_area:g}pt safe area")
        if style.size < tokens.typography.minimum - 1e-9:
            add(name, MIN_SIZE, f"{style.size:g}pt is below the minimum {tokens.typography.minimum:g}pt")

        measured = measure_text(canvas, element, text, box.width)
        if measured.too_wide_words:
            words = ", ".join(repr(w) for w in measured.too_wide_words[:3])
            add(name, TEXT_FIT, f"{words} is wider than the {box.width:.0f}pt box at {style.size:g}pt")
        elif measured.height > box.height + FIT_TOLERANCE:
            add(
                name,
                TEXT_FIT,
                f"needs {measured.height:.0f}pt of height at {style.size:g}pt, box has {box.height:.0f}pt",
            )

        ground = beneath_hex(layout, tokens, canvas, index, box)
        ratio = contrast_ratio(palette_hex(tokens, element.color), ground)
        needed = CONTRAST_LARGE if style.size >= LARGE_TEXT_PT else CONTRAST_NORMAL
        if ratio < needed:
            add(name, CONTRAST, f"{element.color} on #{ground} is {ratio:.2f}:1, needs {needed:g}:1")

        for later in layout.elements[index + 1 :]:
            if (
                isinstance(later, ShapeElement)
                and later.fill is not None
                and later.shape in ("rect", "rounded_rect", "ellipse")
                and boxes_overlap(frame_box(canvas, later.frame), box)
            ):
                add(name, HIDDEN_TEXT, "a shape drawn after this text overlaps and would paint over it")
                break

    # Overlaps: text vs text, text vs visual, visual vs visual.
    placed: list[tuple[str, Box, bool]] = [(e.block_id, b, True) for _, e, b in texts]
    placed += [(v.block_id, b, False) for v, b in visuals]
    for (a_id, a_box, a_text), (b_id, b_box, b_text) in combinations(placed, 2):
        if boxes_overlap(a_box, b_box):
            kind = "text" if a_text and b_text else "text and visual" if a_text or b_text else "visuals"
            add(a_id, OVERLAP, f"overlaps {b_id!r} ({kind})")

    if source:
        for block_id, box, _ in placed:
            if boxes_overlap(box, band):
                add(block_id, SOURCE_BAND, "enters the band reserved for the source line")
        caption = canvas.style("caption")
        measured = canvas.measure_block(source, band.width, caption)
        if measured.too_wide_words or measured.height > band.height + FIT_TOLERANCE:
            add(SOURCE_ELEMENT, TEXT_FIT, "the source line does not fit its band")
        colour, ratio = source_color(layout, tokens, canvas)
        if ratio < CONTRAST_NORMAL:
            add(SOURCE_ELEMENT, CONTRAST, f"best source colour {colour} reaches only {ratio:.2f}:1")

    return findings

