"""Studio-side layout rules: flaws a person sees at once that v2's free-layout QA lets through.

v2's `free_layout_qa.check_free_layout` checks text fit, the safe area, overlapping text,
minimum size, contrast, the source band and hidden text. It deliberately exempts some things
(a line shape never hides text; a shape may bleed), and v2 code is not changed here. The
rules below run beside it, inside `render_adapter.check_slide`, so every caller (the
designer's loop, the preview, the dry build) gets them. Each returns the same
`FreeLayoutFinding` as v2's checks, with a rule name, the block id (or `shape N` for a shape,
N counting elements from 0 in layout order) and a message saying what is wrong and how to
fix it.

**What a rule judges.** Geometry only, in points on the master's canvas, and never a guess
at taste. Text is judged by the *measured extent of its ink*, not by its frame: each wrapped
line is as wide as v2's own font metrics say, aligned the way the element aligns it, and as
tall as `INK_HEIGHT_EM` of the type size, centred in its line box. A short word in a wide
frame therefore owns only the space the word occupies. A line is judged as the segment v2
draws (`free_layout._draw_shape`): horizontal through the frame's vertical centre when the
frame is at least as wide as tall, else vertical through its horizontal centre, `line_pt`
thick. A "rule" is a `line` shape, or a filled `rect` / `rounded_rect` thinner than
`RULE_MAX_PT` in one direction.

**The rules.**

* `line_through_text`: a rule crosses the ink of a text element. The ink is shrunk by
  `LINE_CROSS_MARGIN_EM` of the type size at its top and bottom (a rule at the baseline, an
  underline or an overline touches that margin, and is allowed), and the crossing must be at
  least `MIN_CROSS_PT` long. Fix: move the rule clear of the text, or shorten it.
* `line_through_chart`: a rule crosses the inside of a chart or diagram frame (inset
  `CHART_EDGE_PT` from each edge, crossing at least `MIN_CROSS_PT`). Fix: end the rule at
  the chart's edge or move it outside the frame.
* `straddle`: a text element's ink, or a rule, lies partly on a filled card, panel or band
  and partly off it. The shape must be a filled `rect` / `rounded_rect` / `ellipse` drawn
  earlier than the element, not full-bleed (a background), and not itself a rule. "Partly" is
  more than `STRADDLE_TOLERANCE_PT` inside and more than `STRADDLE_TOLERANCE_PT` outside (on
  the side it crosses), both measured on the object's extent. Fully inside, fully outside,
  or touching the edge within the tolerance is fine. Nesting is handled because each shape is
  judged on its own: text wholly inside a card that sits on a panel is clean; text crossing
  the card's edge is a finding even though it is inside the panel.
"""

from __future__ import annotations

from dataclasses import dataclass

from autodeck.design.budgets import load_metrics
from autodeck.design.free_layout import (
    frame_box,
    measure_text,
    text_style,
)
from autodeck.design.free_layout_qa import FreeLayoutFinding
from autodeck.design.layout_kit import Box, Canvas
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import ShapeElement, TextElement, VisualElement
from autodeck.studio.models import Slide

LINE_THROUGH_TEXT = "line_through_text"
STRADDLE = "straddle"
LINE_THROUGH_CHART = "line_through_chart"

INK_HEIGHT_EM = 0.68
"""Height of a text line's ink band (capitals and digits), as a fraction of the type size."""

BASELINE_EM = 0.22
"""How far above the bottom of its line box the baseline sits, as a fraction of the type
size. Both constants were measured on the renders of the thirty bench slides (LibreOffice,
Carlito): capitals and digits span `bottom - 0.90 size` to `bottom - 0.22 size` of the line
box, whatever the size or the line spacing, because extra leading goes above the line."""

LINE_CROSS_MARGIN_EM = 0.10
"""How far into the ink band (top and bottom) a rule may reach without being 'through' it."""

MIN_CROSS_PT = 2.0
"""A crossing shorter than this (along the rule) is a touch, not a crossing."""

RULE_MAX_PT = 3.0
"""A filled rect thinner than this in one direction is a rule, not a panel."""

STRADDLE_TOLERANCE_PT = 3.0

CHART_EDGE_PT = 6.0
"""A rule within this distance of a chart's frame edge only borders the chart."""

FULL_BLEED_FRACTION = 0.9
"""A shape covering this fraction of the slide in both directions is a background."""


@dataclass(frozen=True)
class _Segment:
    """A drawn line: a thin box (`box`) and the direction it runs in."""

    box: Box
    horizontal: bool


def _line_box(shape: ShapeElement, canvas: Canvas) -> _Segment | None:
    frame = frame_box(canvas, shape.frame)
    if shape.shape == "line":
        thickness = shape.line_pt
        if frame.width >= frame.height:
            return _Segment(
                Box(frame.x, frame.center_y - thickness / 2, frame.width, thickness), True
            )
        return _Segment(
            Box(frame.center_x - thickness / 2, frame.y, thickness, frame.height), False
        )
    thin = min(frame.width, frame.height) < RULE_MAX_PT
    if shape.fill is not None and shape.shape in ("rect", "rounded_rect") and thin:
        return _Segment(frame, frame.width >= frame.height)
    return None


def _ink_lines(canvas: Canvas, element: TextElement, text: str, box: Box) -> list[Box]:
    """The ink band of each wrapped line of `text`, in points."""
    style = text_style(canvas, element)
    measured = measure_text(canvas, element, text, box.width)
    lines = [line for line in measured.lines] or [text]
    height = measured.height
    line_h = height / len(lines)
    if element.anchor == "top":
        top = box.y
    elif element.anchor == "middle":
        top = box.center_y - height / 2
    else:
        top = box.bottom - height
    metrics = load_metrics(style.family, bold=style.bold, italic=style.italic)
    ink_h = INK_HEIGHT_EM * style.size
    out: list[Box] = []
    for i, line in enumerate(lines):
        shown = line.upper() if element.role == "label" else line
        width = metrics.text_width(shown, style.size)
        if element.role == "label":
            width += len(shown) * style.size * 0.10
        width = min(width, box.width) if width > 0 else 0.0
        if element.align == "left":
            x = box.x
        elif element.align == "center":
            x = box.center_x - width / 2
        else:
            x = box.right - width
        y = top + (i + 1) * line_h - BASELINE_EM * style.size - ink_h
        out.append(Box(x, y, width, ink_h))
    return out


def _intersection(a: Box, b: Box) -> tuple[float, float]:
    """(dx, dy) of the overlap of two boxes; either can be <= 0 (no overlap)."""
    return (
        min(a.right, b.right) - max(a.x, b.x),
        min(a.bottom, b.bottom) - max(a.y, b.y),
    )


def _extent(boxes: list[Box]) -> Box:
    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.right for b in boxes)
    y1 = max(b.bottom for b in boxes)
    return Box(x0, y0, x1 - x0, y1 - y0)


def _ground_shapes(canvas: Canvas, layout_elements: list, upto: int) -> list[tuple[int, Box]]:
    """Filled, area-bearing, non-rule, non-background shapes drawn before element `upto`."""
    grounds: list[tuple[int, Box]] = []
    for index in range(upto):
        element = layout_elements[index]
        if not isinstance(element, ShapeElement) or element.fill is None:
            continue
        if element.shape not in ("rect", "rounded_rect", "ellipse"):
            continue
        frame = frame_box(canvas, element.frame)
        if min(frame.width, frame.height) < RULE_MAX_PT:
            continue
        if (
            frame.width >= canvas.width * FULL_BLEED_FRACTION
            and frame.height >= canvas.height * FULL_BLEED_FRACTION
        ):
            continue
        grounds.append((index, frame))
    return grounds


def _straddles(obj: Box, ground: Box, tolerance: float) -> bool:
    """`obj` has more than `tolerance` inside `ground` and more than `tolerance` outside it,
    along at least one axis, while overlapping it on both."""
    dx, dy = _intersection(obj, ground)
    if dx <= tolerance or dy <= tolerance:
        return False
    outside_x = obj.width - dx
    outside_y = obj.height - dy
    return outside_x > tolerance or outside_y > tolerance


def _line_straddles(segment: _Segment, ground: Box, tolerance: float) -> bool:
    """A rule runs partly inside `ground` and partly outside it along its own direction."""
    box = segment.box
    if segment.horizontal:
        cross = box.center_y
        if not ground.y < cross < ground.bottom:
            return False
        inside = min(box.right, ground.right) - max(box.x, ground.x)
        length = box.width
    else:
        cross = box.center_x
        if not ground.x < cross < ground.right:
            return False
        inside = min(box.bottom, ground.bottom) - max(box.y, ground.y)
        length = box.height
    return inside > tolerance and length - inside > tolerance


def check_layout_rules(slide: Slide, tokens: DesignTokens) -> list[FreeLayoutFinding]:
    """Every rule in this module over `slide.layout`; `[]` when it holds or has no layout."""
    layout = slide.layout
    if layout is None:
        return []
    canvas = Canvas(tokens)
    blocks = {b.id: b for b in slide.blocks}
    findings: list[FreeLayoutFinding] = []

    def add(name: str, rule: str, message: str) -> None:
        findings.append(FreeLayoutFinding(slide.id, name, rule, message))

    elements = list(layout.elements)
    texts: list[tuple[int, TextElement, list[Box]]] = []
    rules: list[tuple[int, _Segment]] = []
    for index, element in enumerate(elements):
        if isinstance(element, TextElement):
            block = blocks.get(element.block_id)
            if block is None or (block.text is None):
                continue
            box = frame_box(canvas, element.frame)
            texts.append((index, element, _ink_lines(canvas, element, block.text, box)))
        elif isinstance(element, ShapeElement):
            segment = _line_box(element, canvas)
            if segment is not None:
                rules.append((index, segment))

    # line_through_text
    for rule_index, segment in rules:
        for _, element, lines in texts:
            style_size = text_style(canvas, element).size
            margin = LINE_CROSS_MARGIN_EM * style_size
            for ink in lines:
                core = Box(ink.x, ink.y + margin, ink.width, max(ink.height - 2 * margin, 0.0))
                dx, dy = _intersection(segment.box, core)
                if dx <= 0 or dy <= 0:
                    continue
                along = dx if segment.horizontal else dy
                if along < MIN_CROSS_PT:
                    continue
                add(
                    element.block_id,
                    LINE_THROUGH_TEXT,
                    f"the line at shape {rule_index} runs through this text, like a "
                    "strike-through; move it clear of the words (an underline sits just "
                    "below them) or shorten it",
                )
                break
            else:
                continue
            break

    # line_through_chart
    for rule_index, segment in rules:
        for element in elements:
            if not isinstance(element, VisualElement) or element.type not in (
                "chart",
                "diagram",
            ):
                continue
            core = frame_box(canvas, element.frame).pad(CHART_EDGE_PT)
            dx, dy = _intersection(segment.box, core)
            if dx > 0 and dy > 0 and (dx if segment.horizontal else dy) >= MIN_CROSS_PT:
                add(
                    element.block_id,
                    LINE_THROUGH_CHART,
                    f"the line at shape {rule_index} runs across this {element.type}; a "
                    "rule drawn over a chart cuts its bars and labels; end it at the "
                    "chart's edge or move it outside the chart's frame",
                )
                break

    # straddle
    for index, element, lines in texts:
        extent = _extent(lines)
        for g_index, ground in _ground_shapes(canvas, elements, index):
            if _straddles(extent, ground, STRADDLE_TOLERANCE_PT):
                add(
                    element.block_id,
                    STRADDLE,
                    f"the text lies partly on the shape at index {g_index} and partly off "
                    "it; put it wholly inside that shape, or wholly clear of it",
                )
                break
    for index, segment in rules:
        for g_index, ground in _ground_shapes(canvas, elements, index):
            if _line_straddles(segment, ground, STRADDLE_TOLERANCE_PT):
                add(
                    f"shape {index}",
                    STRADDLE,
                    f"this line lies partly on the shape at index {g_index} and partly off "
                    "it; end it at the shape's edge, or keep it wholly inside or wholly clear",
                )
                break
    return findings
