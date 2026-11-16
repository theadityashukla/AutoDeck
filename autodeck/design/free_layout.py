"""Creative mode's renderer (B69): draw a `FreeLayout` the writer placed itself.

In structured mode a slide fills a catalog component's slots and the budgets promise it
fits. In creative mode the writer chooses where every block goes, so nothing promises
anything in advance: `render_free_layout` runs `free_layout_qa.check_free_layout` first and
raises `FreeLayoutQAError` (a `LayoutOverflowError`) if the layout does not hold, then draws.
The deck is checked by rendering it, not by budgets.

What carries over from the component renderers, unchanged:

* **Content is copied, never composed.** Text is `claim.text` or `block.text`, verbatim. A
  `label` role is capitals and letter-spaced through run properties (`cap="all"`, `spc`),
  never by rewriting the string, so the read-back audit still finds the words it expects.
* **Colour is a theme reference** (`draw.theme_color`), never a literal; the slide
  background too. A shape's `tint` is the theme colour's brightness moved toward the
  background (lighter on a light slide, darker on a dark one).
* **No shrinking.** Text that does not fit its box is a QA finding, not a smaller font.
* **Charts and diagrams are the existing native drawing code** (`charts.place_chart`,
  `diagrams.place_diagram`) inside the element's box. A chart draws its own source line
  inside its box, as it does everywhere.

The slide's source line has no slot in a free layout, so it is drawn automatically in the
caption style on the master's caption strip (`Canvas.caption_strip`), in whichever of
`dk2`/`dk1`/`lt1` reads best against what is beneath it. It is the same text the components
draw (`renderer.source_line` over the face claims' citations), which is what keeps
`expected_caption_lines` and the post-render audit true.

A `figure` has no image in the IR's reach here (the library draws none), so it is drawn as
a quiet framed panel carrying the figure's caption; an `icon` is the library glyph, in the
element's `accent`.

Owning phase: B69.
"""

from __future__ import annotations

import colorsys
from typing import Any

from pptx.slide import Slide as PptxSlide

from autodeck.design.charts import place_chart, source_line as chart_source_line
from autodeck.design.diagrams import place_diagram
from autodeck.design.draw import add_autoshape, add_connector, add_text, theme_color
from autodeck.design.layout_kit import Box, Canvas, TextStyle
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import (
    Block,
    FreeLayout,
    LayoutElement,
    Placement,
    ShapeElement,
    Slide,
    TextElement,
    VisualElement,
)

#: Roles set on the major face and bold by default.
HEADING_ROLES = frozenset({"display", "title", "heading"})

#: `label` is caption size in capitals; the extra width its letter-spacing takes is
#: `LABEL_SPACING_EM` of the size per character, which QA measures as a narrower box.
LABEL_SPACING_EM = 0.10
_LABEL_WIDTH_FACTOR = 1.0 + LABEL_SPACING_EM / 0.55  # 0.55em: a typical capital's advance

#: Text at or above this size needs 3:1 against its ground rather than 4.5:1.
LARGE_TEXT_PT = 24.0
CONTRAST_NORMAL = 4.5
CONTRAST_LARGE = 3.0

#: Source-line colours tried in order of preference.
SOURCE_COLOR_CHOICES = ("dk2", "dk1", "lt1")

#: Height of the reserved source-line band, in points, measured up from the bottom of the
#: master's content area (slide height - margin_y). 12pt caption x `CAPTION_STRIP_FACTOR`
#: (1.6), the strip the components use. Text and visuals stay out of it when a source
#: line is drawn; QA also checks the caption fits it.
SOURCE_BAND_PT = 19.2

_COVERING_SHAPES = frozenset({"rect", "rounded_rect", "ellipse"})
_PRESET = {"rect": "RECTANGLE", "rounded_rect": "ROUNDED_RECTANGLE", "ellipse": "OVAL"}

_FIGURE_PAD = 12.0


# ---------------------------------------------------------------------------
# Geometry and style — shared with free_layout_qa so both read the layout the same way
# ---------------------------------------------------------------------------


def frame_box(canvas: Canvas, frame: Placement) -> Box:
    """A `Placement` (percent of the slide) as a `Box` in points."""
    return Box(
        canvas.width * frame.x / 100.0,
        canvas.height * frame.y / 100.0,
        canvas.width * frame.w / 100.0,
        canvas.height * frame.h / 100.0,
    )


def text_style(canvas: Canvas, element: TextElement) -> TextStyle:
    """The one `TextStyle` a text element is measured with and drawn with."""
    role = "caption" if element.role == "label" else element.role
    heading = element.role in HEADING_ROLES
    style = canvas.style(
        role,
        face="major" if heading else "minor",
        color=element.color,
        bold=heading if element.bold is None else element.bold,
        align=element.align,
        valign=element.anchor,
    )
    if element.size_pt is not None:
        style = style.with_(size=float(element.size_pt))
    return style


def source_band(canvas: Canvas) -> Box:
    """The reserved source-line band: `SOURCE_BAND_PT` tall, on the content area's foot."""
    content = canvas.content
    return Box(content.x, content.bottom - SOURCE_BAND_PT, content.width, SOURCE_BAND_PT)


def block_text(block: Block) -> str:
    """`claim.text` for a claim, `text` for framing/section_header — verbatim."""
    if block.claim is not None:
        return block.claim.text
    if block.text is not None:
        return block.text
    raise ValueError(f"block {block.id!r} carries neither a claim nor text")


def measure_text(canvas: Canvas, element: TextElement, text: str, width: float) -> Any:
    """`canvas.measure_block` for a text element, allowing for a label's capitals/spacing."""
    style = text_style(canvas, element)
    if element.role == "label":
        return canvas.measure_block(text.upper(), width / _LABEL_WIDTH_FACTOR, style)
    return canvas.measure_block(text, width, style)


def slide_source_line(slide: Slide) -> str:
    """The slide's face source line: what the components draw, from the renderer's own walk."""
    from autodeck.render.renderer import _face_claim_citations, source_line

    return source_line(_face_claim_citations(slide))


def source_text_to_draw(slide: Slide) -> str:
    """The automatic source line, or `""` when none is needed.

    None when the face cites nothing, or when a chart on the slide already draws exactly
    that line inside its own box (two identical lines would be clutter, not provenance).
    """
    text = slide_source_line(slide)
    if not text or slide.layout is None:
        return ""
    placed = {e.block_id for e in slide.layout.elements if isinstance(e, VisualElement)}
    for block in slide.blocks:
        if block.id in placed and block.chart is not None:
            if chart_source_line(block.chart.source_citations) == text:
                return ""
    return text


# ---------------------------------------------------------------------------
# Colour — what the renderer will write, computed the way OOXML will resolve it
# ---------------------------------------------------------------------------


def palette_hex(tokens: DesignTokens, name: str) -> str:
    """The token slot's hex, upper-case."""
    value = getattr(tokens.palette, name)
    assert isinstance(value, str)
    return value.upper()


def relative_luminance(hex_color: str) -> float:
    channels = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def linear(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a_hex: str, b_hex: str) -> float:
    """WCAG 2.x contrast; symmetric, 1.0 to 21.0."""
    hi, lo = sorted((relative_luminance(a_hex), relative_luminance(b_hex)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def tint_brightness(background_hex: str, tint: float) -> float:
    """The brightness written for a tinted fill: toward white on a light slide, toward
    black on a dark one (python-pptx `brightness`: lumMod/lumOff on the theme colour)."""
    if tint <= 0.0:
        return 0.0
    return tint if relative_luminance(background_hex) >= 0.18 else -tint


def apply_brightness(hex_color: str, brightness: float) -> str:
    """OOXML's lumMod/lumOff transform for `ColorFormat.brightness`, in HSL like PowerPoint."""
    if brightness == 0.0:
        return hex_color
    mod, off = (1.0 - brightness, brightness) if brightness > 0 else (1.0 + brightness, 0.0)
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    light = min(max(light * mod + off, 0.0), 1.0)
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return "".join(f"{round(c * 255):02X}" for c in (r, g, b))


def fill_hex(tokens: DesignTokens, shape: ShapeElement, background_hex: str) -> str | None:
    """The colour a shape's fill resolves to, tint applied; None when it has no fill."""
    if shape.fill is None:
        return None
    base = palette_hex(tokens, shape.fill)
    return apply_brightness(base, tint_brightness(background_hex, shape.tint))


def covers(shape: ShapeElement, canvas: Canvas, box: Box) -> bool:
    """Whether a filled, area-bearing shape wholly covers `box` (an ellipse must cover the
    corners, not just the bounding rectangle)."""
    if shape.fill is None or shape.shape not in _COVERING_SHAPES:
        return False
    outer = frame_box(canvas, shape.frame)
    if not outer.contains(box, tolerance=0.01):
        return False
    if shape.shape != "ellipse":
        return True
    cx, cy = outer.center_x, outer.center_y
    rx, ry = outer.width / 2, outer.height / 2
    corners = ((box.x, box.y), (box.right, box.y), (box.x, box.bottom), (box.right, box.bottom))
    return all(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0 for x, y in corners)


def beneath_hex(layout: FreeLayout, tokens: DesignTokens, canvas: Canvas, index: int, box: Box) -> str:
    """What is under `box` for the element at `index`: the topmost earlier shape that
    fully covers it (tint applied), else the slide background."""
    background = palette_hex(tokens, layout.background)
    for earlier in range(index - 1, -1, -1):
        candidate = layout.elements[earlier]
        if isinstance(candidate, ShapeElement) and covers(candidate, canvas, box):
            return fill_hex(tokens, candidate, background) or background
    return background


def grounds_under(layout: FreeLayout, tokens: DesignTokens, canvas: Canvas, box: Box) -> list[str]:
    """Every colour that can sit under any part of `box`: the background plus each filled
    shape that overlaps it (used for the source line, which sits wherever it sits)."""
    background = palette_hex(tokens, layout.background)
    grounds = [background]
    for element in layout.elements:
        if isinstance(element, ShapeElement) and element.fill is not None:
            if element.shape in _COVERING_SHAPES and boxes_overlap(frame_box(canvas, element.frame), box):
                hex_value = fill_hex(tokens, element, background)
                if hex_value is not None:
                    grounds.append(hex_value)
    return grounds


def source_color(layout: FreeLayout, tokens: DesignTokens, canvas: Canvas) -> tuple[str, float]:
    """The source line's theme colour and its worst contrast against what can be under it.

    The first of `dk2`, `dk1`, `lt1` that clears 4.5:1 everywhere; else the best of them.
    """
    grounds = grounds_under(layout, tokens, canvas, source_band(canvas))
    scored = [
        (name, min(contrast_ratio(palette_hex(tokens, name), g) for g in grounds))
        for name in SOURCE_COLOR_CHOICES
    ]
    for name, ratio in scored:
        if ratio >= CONTRAST_NORMAL:
            return name, ratio
    return max(scored, key=lambda pair: pair[1])


def boxes_overlap(a: Box, b: Box, tolerance: float = 0.5) -> bool:
    """Strict overlap of two boxes by more than `tolerance` points on both axes."""
    dx = min(a.right, b.right) - max(a.x, b.x)
    dy = min(a.bottom, b.bottom) - max(a.y, b.y)
    return dx > tolerance and dy > tolerance


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def render_free_layout(pptx_slide: PptxSlide, canvas: Canvas, slide: Slide) -> None:
    """Draw `slide.layout` onto `pptx_slide`.

    Raises:
        FreeLayoutQAError: the layout fails deterministic QA (nothing has been drawn).
        LayoutOverflowError / ChartConstructionError: a chart, diagram or figure caption
            would not fit the box it was given.
    """
    from autodeck.design.free_layout_qa import FreeLayoutQAError, check_free_layout

    layout = slide.layout
    if layout is None:
        raise ValueError(f"slide {slide.id!r} has no free layout")
    findings = check_free_layout(slide, canvas.tokens)
    if findings:
        raise FreeLayoutQAError(slide.id, findings)

    _set_background(pptx_slide, layout.background)
    blocks = {b.id: b for b in slide.blocks}
    for element in layout.elements:
        _draw_element(pptx_slide, canvas, element, blocks, layout)

    source = source_text_to_draw(slide)
    if source:
        colour, _ = source_color(layout, canvas.tokens, canvas)
        shape = canvas.on(pptx_slide).caption(source_band(canvas), source, color=colour)
        if shape is not None:
            shape.name = "free:source"


def _set_background(pptx_slide: PptxSlide, token: str) -> None:
    fill = pptx_slide.background.fill
    fill.solid()
    fill.fore_color.theme_color = theme_color(token)


def _draw_element(
    pptx_slide: PptxSlide,
    canvas: Canvas,
    element: LayoutElement,
    blocks: dict[str, Block],
    layout: FreeLayout,
) -> None:
    box = frame_box(canvas, element.frame)
    if isinstance(element, ShapeElement):
        _draw_shape(pptx_slide, canvas, element, box, layout)
    elif isinstance(element, TextElement):
        _draw_text(pptx_slide, canvas, element, box, blocks[element.block_id])
    else:
        _draw_visual(pptx_slide, canvas, element, box, blocks[element.block_id])


def _draw_text(
    pptx_slide: PptxSlide, canvas: Canvas, element: TextElement, box: Box, block: Block
) -> None:
    shape = add_text(pptx_slide, box, block_text(block), text_style(canvas, element))
    shape.name = f"free:text:{block.id}"
    if element.role == "label":
        spacing = round(text_style(canvas, element).size * LABEL_SPACING_EM * 100)
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                properties = run._r.get_or_add_rPr()  # python-pptx has no setter for these
                properties.set("cap", "all")
                properties.set("spc", str(spacing))


def _draw_shape(
    pptx_slide: PptxSlide, canvas: Canvas, element: ShapeElement, box: Box, layout: FreeLayout
) -> None:
    if element.shape == "line":
        colour = element.line or element.fill
        assert colour is not None
        if box.width >= box.height:
            start, end = (box.x, box.center_y), (box.right, box.center_y)
        else:
            start, end = (box.center_x, box.y), (box.center_x, box.bottom)
        connector = add_connector(
            pptx_slide, start, end, color=colour, width=element.line_pt, arrow="none"
        )
        connector.name = "free:line"
        return
    background = palette_hex(canvas.tokens, layout.background)
    brightness = tint_brightness(background, element.tint)
    shape = add_autoshape(
        pptx_slide,
        box,
        _PRESET[element.shape],
        fill=element.fill,
        fill_brightness=brightness if element.fill is not None and brightness else None,
        line=element.line,
        line_width=element.line_pt,
    )
    shape.name = f"free:{element.shape}"


def _draw_visual(
    pptx_slide: PptxSlide, canvas: Canvas, element: VisualElement, box: Box, block: Block
) -> None:
    frame = canvas.on(pptx_slide)
    if element.type == "chart":
        assert block.chart is not None
        graphic = place_chart(
            frame, box, block.chart, emphasis=element.emphasis, accent=element.accent
        )
        graphic.name = f"free:chart:{block.id}"
    elif element.type == "diagram":
        assert block.diagram is not None
        place_diagram(frame, box, block.diagram)
    elif element.type == "icon":
        from autodeck.design.icons.custgeom import place_icon
        from autodeck.design.icons.library import load_icon

        assert block.icon is not None
        place_icon(pptx_slide, box, load_icon(block.icon.glyph_id), color=element.accent)
    else:
        _draw_figure(pptx_slide, canvas, element, box, block)


def _draw_figure(
    pptx_slide: PptxSlide, canvas: Canvas, element: VisualElement, box: Box, block: Block
) -> None:
    panel = add_autoshape(
        pptx_slide, box, "RECTANGLE", fill="lt2", line="accent6", line_width=0.75
    )
    panel.name = f"free:figure:{block.id}"
    assert block.figure is not None
    if block.figure.caption:
        frame = canvas.on(pptx_slide)
        stack = frame.stack(f"figure {block.id} caption", box.width - 2 * _FIGURE_PAD)
        stack.text(
            block.figure.caption,
            canvas.style("caption", color="dk2", italic=True, align="center"),
        )
        stack.place(box.pad(_FIGURE_PAD), valign="middle")
