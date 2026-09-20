"""Drawing primitives that reference the theme rather than literal colours.

Every fill and every font colour written here is a **theme colour reference**
(`MSO_THEME_COLOR`), not an RGB value. That is what D1 actually requires: a client who
opens the deck and switches the colour variant, or recolours a shape from the palette, must
see everything move together. A literal `RGBColor` produces a deck that looks identical on
screen and behaves like a photograph — and it is invisible until someone tries to restyle
it, which is exactly when it is most annoying.

The same rule is why D11 insists icons are DrawingML shapes: a themed shape recolours, a
picture does not.

Owning phase: 0 (spikes 0.4-0.6); Phase 3a builds the full component library on this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.shapes.autoshape import Shape
from pptx.shapes.connector import Connector
from pptx.slide import Slide
from pptx.util import Emu, Pt

if TYPE_CHECKING:  # pragma: no cover - import cycle, see the note below
    from autodeck.design.layout_kit import Box, TextStyle

# `layout_kit` imports these primitives so that its `Frame`/`Stack` composition layer can
# draw, which makes the dependency mutual. It is only mutual on paper: nothing here needs
# `Box` or `TextStyle` at runtime — both are used through their attributes — so the import
# lives under TYPE_CHECKING and the cycle never exists when the modules are loaded. The
# alternative, a third module holding the geometry types, would put `Box` somewhere no
# reader would look for it.

ThemeColor = Literal[
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
]
"""The token slots a shape may reference.

Spelled out as a Literal for readers and editors, but the drawing functions take a plain
`str` and validate through `theme_color()`. Components carry colours as token *names* on
their content objects, and threading the Literal through every call site produced only a
trail of `# type: ignore` comments — a runtime check that raises with the list of valid
slots is both stricter and more useful than one that is suppressed everywhere.
"""

#: Token slot -> the enum PowerPoint exposes in its own colour UI.
_THEME_COLORS: dict[str, MSO_THEME_COLOR] = {
    "dk1": MSO_THEME_COLOR.TEXT_1,
    "lt1": MSO_THEME_COLOR.BACKGROUND_1,
    "dk2": MSO_THEME_COLOR.TEXT_2,
    "lt2": MSO_THEME_COLOR.BACKGROUND_2,
    "accent1": MSO_THEME_COLOR.ACCENT_1,
    "accent2": MSO_THEME_COLOR.ACCENT_2,
    "accent3": MSO_THEME_COLOR.ACCENT_3,
    "accent4": MSO_THEME_COLOR.ACCENT_4,
    "accent5": MSO_THEME_COLOR.ACCENT_5,
    "accent6": MSO_THEME_COLOR.ACCENT_6,
}

_ALIGNMENTS: dict[str, PP_ALIGN] = {
    "left": PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT,
}

_ANCHORS: dict[str, MSO_ANCHOR] = {
    "top": MSO_ANCHOR.TOP,
    "middle": MSO_ANCHOR.MIDDLE,
    "bottom": MSO_ANCHOR.BOTTOM,
}


def theme_color(name: str) -> MSO_THEME_COLOR:
    """Map a token slot name to its theme-colour enum."""
    try:
        return _THEME_COLORS[name]
    except KeyError:
        known = ", ".join(_THEME_COLORS)
        raise ValueError(f"unknown theme colour {name!r}. Known: {known}") from None


def add_text(slide: Slide, box: Box, text: str, style: TextStyle) -> Shape:
    """Place a text box using the same `TextStyle` the layout measured with.

    Taking a `TextStyle` rather than loose keyword arguments is deliberate: it is what makes
    it impossible for the renderer to apply leading the measurement did not account for.
    See the note on `TextStyle`.

    Word wrap on, autofit off. Autofit would silently shrink overflowing text, hiding
    exactly the failure the budget system (§6.7) exists to surface — and it behaves
    differently in PowerPoint and LibreOffice, so the preview would stop matching the
    deliverable.
    """
    left, top, width, height = box.as_emu()
    shape = slide.shapes.add_textbox(left, top, width, height)

    frame = shape.text_frame
    frame.word_wrap = True
    frame.margin_left = Emu(0)
    frame.margin_right = Emu(0)
    frame.margin_top = Emu(0)
    frame.margin_bottom = Emu(0)
    frame.vertical_anchor = _ANCHORS[style.valign]

    colour = theme_color(style.color)
    for index, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = _ALIGNMENTS[style.align]
        paragraph.line_spacing = style.line_spacing
        if style.space_after:
            paragraph.space_after = Pt(style.space_after)
        run = paragraph.add_run()
        run.text = line
        run.font.name = style.family
        run.font.size = Pt(style.size)
        run.font.bold = style.bold
        run.font.italic = style.italic
        run.font.color.theme_color = colour

    return shape


def add_autoshape(
    slide: Slide,
    box: Box,
    shape_name: str,
    *,
    fill: str | None = None,
    fill_brightness: float | None = None,
    line: str | None = None,
    line_width: float = 1.0,
    rotation: float = 0.0,
) -> Shape:
    """An arbitrary preset autoshape, filled and outlined from the theme palette.

    `shape_name` names a python-pptx `MSO_SHAPE` member — `"CHEVRON"`, `"OVAL"`,
    `"TRAPEZOID"` — from `references/construction.md`'s authoritative column
    (`GEOMETRIES[...].shapes` in `autodeck.ir.models` is the same vocabulary). `add_rect`
    is the one-shape special case this generalises: the diagram engine draws chevrons,
    ovals and stack bands from the same preset family, and a helper per shape would be a
    helper per geometry for no reason — the autoshape API takes the preset as a value, not
    as a different method.

    Raises:
        ValueError: `shape_name` is not a member of `MSO_SHAPE`.
    """
    from pptx.enum.shapes import MSO_SHAPE

    try:
        preset = MSO_SHAPE[shape_name]
    except KeyError:
        raise ValueError(
            f"unknown MSO_SHAPE member {shape_name!r}. See "
            "references/construction.md's python-pptx column, or pptx.enum.shapes.MSO_SHAPE."
        ) from None

    left, top, width, height = box.as_emu()
    shape = slide.shapes.add_shape(preset, left, top, width, height)
    shape.shadow.inherit = False
    if rotation:
        shape.rotation = rotation

    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.theme_color = theme_color(fill)
        if fill_brightness is not None:
            shape.fill.fore_color.brightness = fill_brightness

    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.theme_color = theme_color(line)
        shape.line.width = Pt(line_width)

    # An autoshape arrives with an empty text frame that still reserves internal margins;
    # zeroing them keeps a bare shape from nudging adjacent geometry.
    frame = shape.text_frame
    frame.margin_left = frame.margin_right = Emu(0)
    frame.margin_top = frame.margin_bottom = Emu(0)
    return shape


def add_rect(
    slide: Slide,
    box: Box,
    *,
    fill: str | None = None,
    fill_brightness: float | None = None,
    line: str | None = None,
    line_width: float = 1.0,
) -> Shape:
    """A rectangle filled and outlined from the theme palette."""
    return add_autoshape(
        slide,
        box,
        "RECTANGLE",
        fill=fill,
        fill_brightness=fill_brightness,
        line=line,
        line_width=line_width,
    )


def add_rule(
    slide: Slide,
    box: Box,
    *,
    color: str = "accent1",
    thickness: float = 2.0,
) -> Shape:
    """A horizontal rule — the accent bar that anchors a title block."""
    return add_rect(slide, box.resize(height=thickness), fill=color)


_ARROWHEADS: dict[str, tuple[bool, bool]] = {
    # (head at the connector's start point, head at its end point)
    "none": (False, False),
    "start": (True, False),
    "end": (False, True),
    "both": (True, True),
}


def add_connector(
    slide: Slide,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = "dk1",
    width: float = 1.5,
    arrow: Literal["none", "start", "end", "both"] = "end",
) -> Connector:
    """A straight connector between two points, in theme colour, with an optional arrowhead.

    `start`/`end` are `(x, y)` in points — the diagram engine's own unit — converted to EMU
    here so a caller never has to reach past `Box` for a raw `Emu`.

    python-pptx has no high-level API for arrowheads, so `<a:headEnd>`/`<a:tailEnd>` are
    appended to the connector's `<a:ln>` directly. The same surgical-XML-edit pattern
    `icons.custgeom._replace_geometry` uses for freeform geometry: python-pptx owns
    everything else about the shape (position, colour, width), and only the one element it
    has no setter for is hand-built.
    """
    from pptx.enum.shapes import MSO_CONNECTOR

    from autodeck.design.theme.tokens import points_to_emu

    x1, y1 = start
    x2, y2 = end
    connector = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        Emu(points_to_emu(x1)),
        Emu(points_to_emu(y1)),
        Emu(points_to_emu(x2)),
        Emu(points_to_emu(y2)),
    )
    connector.shadow.inherit = False
    connector.line.color.theme_color = theme_color(color)
    connector.line.width = Pt(width)

    try:
        head, tail = _ARROWHEADS[arrow]
    except KeyError:
        known = ", ".join(_ARROWHEADS)
        raise ValueError(f"unknown arrow style {arrow!r}. Known: {known}") from None

    if head or tail:
        line = connector.line._get_or_add_ln()
        ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        # Schema order inside <a:ln> is headEnd before tailEnd.
        if head:
            line.append(parse_xml(f'<a:headEnd {ns} type="triangle"/>'))
        if tail:
            line.append(parse_xml(f'<a:tailEnd {ns} type="triangle"/>'))

    return connector


def set_background(slide: Slide, color: RGBColor) -> None:
    """Set an explicit slide background.

    The one place a literal colour is correct: a slide-level background override is not a
    palette member, and expressing it as a theme reference would make it move when a client
    switches variants — which is not what a deliberate background is for.
    """
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color
