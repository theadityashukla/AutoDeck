"""The semantic icon library: vendored SVGs parsed to geometry.

Icons are chosen deliberately by concept, not decoratively (§6.11.3), so the library keeps
the source SVGs and the mapping from concept to glyph rather than baking geometry into
code. Client-supplied sets register per client in Phase 4 and take precedence.

Lucide is the default family: ISC-licensed (verified at implementation time — see
`icons/lucide/LICENSE`), stroke-simple, and geometrically consistent, which is exactly the
family shape §9 recommends to keep the SVG→DrawingML converter's edge cases manageable.

Owning phase: 0 (spike 0.6); productionised in Phase 3a.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

from autodeck.design.icons.svg_path import (
    SubPath,
    circle_subpath,
    ellipse_subpath,
    parse_path,
    polyline_subpath,
    rect_subpath,
)

SVG_NS = "http://www.w3.org/2000/svg"
ICON_DIR = Path(__file__).parent / "lucide"


class IconNotFoundError(KeyError):
    """No icon by that name in the library."""


@dataclass(frozen=True)
class Icon:
    """A parsed icon: its geometry plus the viewBox that geometry is expressed in."""

    name: str
    subpaths: list[SubPath]
    view_width: float
    view_height: float
    stroke_width: float
    """The family's design stroke width, in viewBox units. Scaled with the icon."""

    @property
    def is_stroke_based(self) -> bool:
        """Lucide draws with strokes and no fill, which is why icons recolour so cleanly."""
        return True


def icon_path(name: str) -> Path:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        available = ", ".join(icon_names())
        raise IconNotFoundError(f"no icon named {name!r}. Available: {available}")
    return path


def icon_names() -> list[str]:
    """Every icon in the vendored library, alphabetically."""
    if not ICON_DIR.is_dir():
        return []
    return sorted(path.stem for path in ICON_DIR.glob("*.svg"))


@lru_cache(maxsize=128)
def load_icon(name: str) -> Icon:
    """Parse an icon's SVG into normalised subpaths.

    Raises:
        IconNotFoundError: no such icon.
    """
    return parse_svg(icon_path(name).read_text(encoding="utf-8"), name=name)


def parse_svg(source: str, *, name: str = "icon") -> Icon:
    """Parse an SVG document into `Icon` geometry.

    Handles the element vocabulary Lucide actually uses — `path`, `circle`, `rect`, `line`,
    `polyline`, `polygon`, `ellipse` — and ignores presentation attributes, since colour is
    supplied by the theme at placement time rather than by the source file.
    """
    root = ElementTree.fromstring(source)
    view_width, view_height = _view_box(root)
    stroke_width = float(root.get("stroke-width", "2"))

    subpaths: list[SubPath] = []
    for element in root.iter():
        subpaths.extend(_element_subpaths(element))

    return Icon(
        name=name,
        subpaths=subpaths,
        view_width=view_width,
        view_height=view_height,
        stroke_width=stroke_width,
    )


def _view_box(root: ElementTree.Element) -> tuple[float, float]:
    view_box = root.get("viewBox")
    if view_box:
        parts = view_box.replace(",", " ").split()
        if len(parts) == 4:
            return float(parts[2]), float(parts[3])
    return float(root.get("width", "24")), float(root.get("height", "24"))


def _tag(element: ElementTree.Element) -> str:
    return element.tag.split("}")[-1]


def _number(element: ElementTree.Element, attribute: str, default: float = 0.0) -> float:
    value = element.get(attribute)
    return float(value) if value is not None else default


def _points(element: ElementTree.Element) -> list[tuple[float, float]]:
    raw = (element.get("points") or "").replace(",", " ").split()
    values = [float(value) for value in raw]
    return list(zip(values[0::2], values[1::2], strict=False))


def _element_subpaths(element: ElementTree.Element) -> list[SubPath]:
    """Geometry for one SVG element, or nothing if it draws nothing."""
    tag = _tag(element)

    if tag == "path":
        data = element.get("d")
        return parse_path(data) if data else []

    if tag == "circle":
        return [
            circle_subpath(
                _number(element, "cx"), _number(element, "cy"), _number(element, "r")
            )
        ]

    if tag == "ellipse":
        return [
            ellipse_subpath(
                _number(element, "cx"),
                _number(element, "cy"),
                _number(element, "rx"),
                _number(element, "ry"),
            )
        ]

    if tag == "rect":
        return [
            rect_subpath(
                _number(element, "x"),
                _number(element, "y"),
                _number(element, "width"),
                _number(element, "height"),
                _number(element, "rx"),
            )
        ]

    if tag == "line":
        return [
            polyline_subpath(
                [
                    (_number(element, "x1"), _number(element, "y1")),
                    (_number(element, "x2"), _number(element, "y2")),
                ]
            )
        ]

    if tag == "polyline":
        return [polyline_subpath(_points(element))]

    if tag == "polygon":
        return [polyline_subpath(_points(element), close=True)]

    return []
