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
from pptx.shapes.autoshape import Shape
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
    from pptx.enum.shapes import MSO_SHAPE

    left, top, width, height = box.as_emu()
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.shadow.inherit = False

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
    # zeroing them keeps a bare rectangle from nudging adjacent geometry.
    frame = shape.text_frame
    frame.margin_left = frame.margin_right = Emu(0)
    frame.margin_top = frame.margin_bottom = Emu(0)
    return shape


def add_rule(
    slide: Slide,
    box: Box,
    *,
    color: str = "accent1",
    thickness: float = 2.0,
) -> Shape:
    """A horizontal rule — the accent bar that anchors a title block."""
    return add_rect(slide, box.resize(height=thickness), fill=color)


def set_background(slide: Slide, color: RGBColor) -> None:
    """Set an explicit slide background.

    The one place a literal colour is correct: a slide-level background override is not a
    palette member, and expressing it as a theme reference would make it move when a client
    switches variants — which is not what a deliberate background is for.
    """
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color
