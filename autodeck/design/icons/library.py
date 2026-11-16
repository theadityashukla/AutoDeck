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

#: The default (and, today, only) vendored family. Named explicitly rather than inferred
#: from `ICON_DIR`'s path, because a client-supplied set registers under its own directory
#: in Phase 4 and `Icon.family` needs a value that survives that move.
DEFAULT_FAMILY = "lucide"

#: SVG elements that carry no visible geometry of their own and are safe to skip while
#: walking a document — the root element, and metadata nodes a design tool adds.
_NON_DRAWING_TAGS = frozenset({"svg", "defs", "title", "desc", "metadata", "style"})

#: Concept -> vendored icon filename. A deck author asks for an idea ("this slide is about
#: risk"), not a filename ("circle-alert.svg") — the whole point of a *semantic* library
#: (§9, PHASE-3A 3a.7). Keys are the vocabulary content authors and prompts are expected to
#: use; extend this table rather than reaching for `load_icon` with a literal filename.
CONCEPT_TO_ICON: dict[str, str] = {
    "warning": "circle-alert",
    "risk": "circle-alert",
    "alert": "circle-alert",
    "issue": "circle-alert",
    "time": "clock",
    "schedule": "clock",
    "deadline": "clock",
    "duration": "clock",
    "process": "git-branch",
    "workflow": "git-branch",
    "branch": "git-branch",
    "decision_path": "git-branch",
    "architecture": "layers",
    "stack": "layers",
    "layers": "layers",
    "infrastructure": "layers",
    "security": "shield-check",
    "trust": "shield-check",
    "compliance": "shield-check",
    "protection": "shield-check",
    "goal": "target",
    "objective": "target",
    "focus": "target",
    "milestone": "target",
    "decline": "trending-down",
    "decrease": "trending-down",
    "downturn": "trending-down",
    "risk_trend": "trending-down",
    "growth": "trending-up",
    "increase": "trending-up",
    "improvement": "trending-up",
    "momentum": "trending-up",
    "team": "users",
    "people": "users",
    "audience": "users",
    "customers": "users",
    "speed": "zap",
    "energy": "zap",
    "performance": "zap",
    "power": "zap",
}


class IconNotFoundError(KeyError):
    """No icon by that name — or concept — in the library."""


class UnsupportedIconElementError(ValueError):
    """An SVG element this converter cannot turn into geometry.

    Raised rather than silently skipped: a `<mask>`, `<use>`, or embedded `<image>` inside a
    vendored icon would otherwise disappear from the shape with no error at all, which is
    the same failure D10/D11 forbid a raster fallback for — a glyph that renders incomplete
    or wrong is not something to discover by eye in the golden preview. Escalate instead of
    guessing at a conversion (PHASE-3A 3a.7: "no image fallback, ever").
    """


@dataclass(frozen=True)
class Icon:
    """A parsed icon: its geometry plus the viewBox that geometry is expressed in."""

    name: str
    subpaths: list[SubPath]
    view_width: float
    view_height: float
    stroke_width: float
    """The family's design stroke width, in viewBox units. Scaled with the icon."""
    family: str = DEFAULT_FAMILY
    """Which vendored (or client-registered, Phase 4) icon set this came from — carried
    through to the placed shape's name so a deck that ends up mixing two families is
    something `check_deck_icon_consistency` can actually detect, not just something a
    reviewer might notice."""

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
    """Parse an icon's SVG into normalised subpaths, by its literal filename.

    Prefer `resolve_icon` at call sites that are choosing an icon for a concept — this is
    the low-level lookup it falls back to.

    Raises:
        IconNotFoundError: no such icon.
    """
    return parse_svg(icon_path(name).read_text(encoding="utf-8"), name=name)


def available_concepts() -> list[str]:
    """Every concept the semantic library maps to a glyph, alphabetically."""
    return sorted(CONCEPT_TO_ICON)


def resolve_icon(concept: str) -> Icon:
    """The icon for a concept — a deck asks for an idea, not a filename (§9).

    Tries the semantic concept table first (`"risk"` -> `circle-alert`), then falls back to
    treating `concept` as a literal vendored filename, so a caller that already knows the
    exact glyph it wants is not forced through the concept vocabulary.

    Raises:
        IconNotFoundError: `concept` is neither a known concept nor a known icon filename.
    """
    icon_name = CONCEPT_TO_ICON.get(concept, concept)
    try:
        return load_icon(icon_name)
    except IconNotFoundError:
        raise IconNotFoundError(
            f"no icon for concept or name {concept!r}. Known concepts: "
            f"{', '.join(available_concepts())}. Known icon files: {', '.join(icon_names())}"
        ) from None


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

    if tag in _NON_DRAWING_TAGS:
        return []

    raise UnsupportedIconElementError(
        f"<{tag}> cannot be converted to custGeom shapes. D10/D11 forbid a raster "
        "fallback, so a vendored icon using this element is an escalation, not a .png: "
        "either the SVG needs simplifying to the supported element vocabulary (path, "
        "circle, rect, line, polyline, polygon, ellipse) before vendoring, or this "
        "converter needs to grow support for it."
    )
