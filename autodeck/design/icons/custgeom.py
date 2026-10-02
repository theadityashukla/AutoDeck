"""Icon geometry → DrawingML `custGeom` freeform shapes (D11).

This is the load-bearing piece of the icon system. An icon placed as a `custGeom` shape is
a genuine PowerPoint object: selectable, losslessly scalable, and recolourable from the
theme palette. A raster icon is a picture — it blurs when scaled and ignores the palette,
which is why D11 forbids it outright.

Two decisions worth stating, both learned from the spike:

* **Each subpath becomes its own shape, grouped.** DrawingML allows several `<a:path>`
  elements in one `custGeom`, but PowerPoint applies a single fill rule across them, so a
  stroke-based icon whose subpaths are meant to be separate strokes renders as one filled
  blob. Separate shapes in a group keep each stroke a stroke and remain individually
  selectable, which is what the gate criterion asks for.
* **Stroke, not fill.** Lucide icons are drawn with `fill="none"` and a stroke, so the
  shapes carry `a:noFill` and a themed `a:ln`. Recolouring then means changing the *line*
  colour, and the icon stays visually identical to the source SVG.

Owning phase: 0 (spike 0.6); productionised in Phase 3a.
"""

from __future__ import annotations

from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.shapes.autoshape import Shape
from pptx.slide import Slide
from pptx.util import Emu, Pt

from autodeck.design.draw import ThemeColor, theme_color
from autodeck.design.icons.library import Icon
from autodeck.design.icons.svg_path import Close, Cubic, Line, Move, SubPath
from autodeck.design.layout_kit import Box, pt_to_emu

#: `custGeom` path coordinates are integers in a local space. 100k units across the icon
#: keeps sub-unit precision after scaling a 24-unit viewBox without risking overflow.
PATH_SPACE = 100_000


def _scale(value: float, extent: float) -> int:
    """Map a viewBox coordinate into the shape's local path space."""
    if extent <= 0:
        return 0
    return round(value / extent * PATH_SPACE)


def subpath_xml(subpath: SubPath, view_width: float, view_height: float) -> str:
    """One subpath as the body of an `<a:path>` element."""
    parts: list[str] = []

    def point(x: float, y: float) -> str:
        return f'<a:pt x="{_scale(x, view_width)}" y="{_scale(y, view_height)}"/>'

    for segment in subpath:
        if isinstance(segment, Move):
            parts.append(f"<a:moveTo>{point(segment.x, segment.y)}</a:moveTo>")
        elif isinstance(segment, Line):
            parts.append(f"<a:lnTo>{point(segment.x, segment.y)}</a:lnTo>")
        elif isinstance(segment, Cubic):
            parts.append(
                "<a:cubicBezTo>"
                f"{point(segment.x1, segment.y1)}"
                f"{point(segment.x2, segment.y2)}"
                f"{point(segment.x, segment.y)}"
                "</a:cubicBezTo>"
            )
        elif isinstance(segment, Close):
            parts.append("<a:close/>")

    return "".join(parts)


def custgeom_xml(subpath: SubPath, view_width: float, view_height: float) -> str:
    """A complete `<a:custGeom>` for one subpath.

    `fill="none"` on the path tells PowerPoint not to close and fill an open stroke — the
    difference between a tick mark and a filled wedge.
    """
    body = subpath_xml(subpath, view_width, view_height)
    return (
        "<a:custGeom>"
        "<a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>"
        '<a:rect l="0" t="0" r="r" b="b"/>'
        "<a:pathLst>"
        f'<a:path w="{PATH_SPACE}" h="{PATH_SPACE}" fill="none">{body}</a:path>'
        "</a:pathLst>"
        "</a:custGeom>"
    )


def place_icon(
    slide: Slide,
    box: Box,
    icon: Icon,
    *,
    color: ThemeColor = "accent1",
    stroke_width: float | None = None,
) -> list[Shape]:
    """Place `icon` inside `box` as native, theme-recolourable DrawingML shapes.

    Args:
        stroke_width: line weight in points. Defaults to the family's design weight scaled
            to the placement size, which keeps a 24pt icon and a 96pt icon looking like the
            same family rather than the same drawing enlarged.

    Returns:
        The shapes created, one per subpath.
    """
    from pptx.enum.shapes import MSO_SHAPE

    side = min(box.width, box.height)
    if stroke_width is None:
        stroke_width = icon.stroke_width / icon.view_width * side

    square = Box(box.center_x - side / 2, box.center_y - side / 2, side, side)
    left, top, width, height = square.as_emu()

    shapes: list[Shape] = []
    for subpath in icon.subpaths:
        if not subpath:
            continue
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
        shape.shadow.inherit = False
        _replace_geometry(shape, custgeom_xml(subpath, icon.view_width, icon.view_height))

        shape.fill.background()
        shape.line.color.theme_color = theme_color(color)
        shape.line.width = Pt(stroke_width)
        _round_caps_and_joins(shape)

        shape.name = f"icon:{icon.family}:{icon.name}"
        shapes.append(shape)

    return shapes


def _replace_geometry(shape: Shape, geometry_xml: str) -> None:
    """Swap a preset rectangle's `prstGeom` for our `custGeom`.

    python-pptx has no API for freeform geometry, so the shape is created as a rectangle
    and its geometry element replaced. The rest of the shape — position, size, line, fill —
    stays under python-pptx's control, which is why this is a two-line surgical edit rather
    than hand-building a `<p:sp>`.
    """
    properties = shape._element.spPr
    for tag in ("a:prstGeom", "a:custGeom"):
        existing = properties.find(qn(tag))
        if existing is not None:
            properties.remove(existing)

    namespaced = geometry_xml.replace(
        "<a:custGeom>",
        '<a:custGeom xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">',
        1,
    )
    element = parse_xml(namespaced)

    # Geometry must precede fill and line in `spPr`, after any transform.
    transform = properties.find(qn("a:xfrm"))
    if transform is None:
        properties.insert(0, element)
    else:
        properties.insert(list(properties).index(transform) + 1, element)


def _round_caps_and_joins(shape: Shape) -> None:
    """Round line caps and joins, matching the source family's drawing style.

    Lucide sets `stroke-linecap="round"` and `stroke-linejoin="round"` on every icon;
    without them the strokes end square and the icons read as a different, blockier family.
    """
    line = shape.line._get_or_add_ln()
    line.set("cap", "rnd")
    if line.find(qn("a:round")) is None:
        line.append(
            parse_xml(
                '<a:round xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
            )
        )


def icon_emu_size(box: Box) -> tuple[Emu, Emu]:
    """The square EMU extent an icon will occupy inside `box`."""
    side = pt_to_emu(min(box.width, box.height))
    return Emu(side), Emu(side)
