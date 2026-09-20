"""Deck-wide icon consistency, enforced against what actually got placed (PHASE-3A 3a.7).

"One family, one stroke weight, one size scale per deck, enforced rather than hoped for" —
`style.IconStyle` gives renderers a shared vocabulary to draw from, but a vocabulary is only
ever a convention: nothing stops a renderer from ignoring it and typing a bespoke stroke
width, or a client-supplied icon (Phase 4) getting mixed in next to the house family.

This module is the check, not the convention. It walks a rendered `Presentation` for the
shapes `place_icon` tagged (`icon:<family>:<name>`) and raises if two families are mixed, if
the stroke-to-size ratio drifts (the visual "weight" of the family), or if the sizes used
fan out past a small, deck-wide scale. It costs nothing to call after a render — no state
needs threading through every `Frame.icon` call to get here — and it is the mechanism that
turns "a deck mixing two icon families" from something a reviewer might notice into
something a build fails on.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.presentation import Presentation as PresentationType

#: `place_icon` names every shape it creates `icon:<family>:<name>` — see `custgeom.py`.
ICON_NAME_PREFIX = "icon:"

#: Rounding grain for comparing placed sizes. Two icons meant to be "the same size" can
#: differ by sub-point EMU-conversion noise; anything coarser than this is a real size.
SIZE_ROUNDING_PT = 0.5

#: How far a stroke-to-size ratio may drift from the deck's first icon before it counts as a
#: different weight rather than rounding noise from `custgeom._scale`'s integer path space.
STROKE_RATIO_TOLERANCE = 0.02

#: How many distinct (rounded) sizes a deck may use before that stops being "a size scale"
#: and starts being "every icon its own size". Matches `style.DEFAULT_ICON_SIZES`'s three
#: steps, with one spare step for a deck that reasonably needs a fourth.
MAX_DISTINCT_SIZES = 4


class IconConsistencyError(RuntimeError):
    """A deck-wide icon rule was broken by what was actually placed on the slides."""


@dataclass(frozen=True)
class PlacedIcon:
    """One icon shape as it actually rendered, read back off the presentation."""

    family: str
    name: str
    slide_index: int
    stroke_pt: float
    side_pt: float


def placed_icons(prs: PresentationType) -> list[PlacedIcon]:
    """Every icon shape `place_icon` created, across every slide, in slide order.

    Reads geometry back off the python-pptx tree rather than tracking placements as they
    happen, so calling this needs nothing from the render path but the finished
    presentation — the same reason `budget_check.py` renders and re-measures rather than
    instrumenting the renderer.
    """
    found: list[PlacedIcon] = []
    for slide_index, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if not shape.name.startswith(ICON_NAME_PREFIX):
                continue
            family, _, name = shape.name[len(ICON_NAME_PREFIX) :].partition(":")
            width_pt = shape.width.pt
            height_pt = shape.height.pt
            side_pt = min(width_pt, height_pt)
            # `.line` is only on the concrete autoshape `Shape`, not the `BaseShape` that
            # iterating `slide.shapes` is typed as — every shape reaching here actually is
            # one, since `place_icon` is the only thing that names a shape `icon:...`.
            line_width = getattr(shape, "line").width  # noqa: B009
            stroke_pt = line_width.pt if line_width is not None else 0.0
            found.append(
                PlacedIcon(
                    family=family,
                    name=name,
                    slide_index=slide_index,
                    stroke_pt=stroke_pt,
                    side_pt=side_pt,
                )
            )
    return found


def check_deck_icon_consistency(prs: PresentationType) -> None:
    """Raise if the icons placed in `prs` do not share one family, weight and size scale.

    Silent when fewer than two icons were placed — there is nothing to be inconsistent
    with. Call this once, after a deck is built, the same way `check_against_render` proves
    a budget rather than trusting the prediction that produced it.

    Raises:
        IconConsistencyError: two icon families are mixed; the stroke-to-size ratio (the
            family's visual weight) drifts between icons; or more than `MAX_DISTINCT_SIZES`
            distinct sizes are in use.
    """
    icons = placed_icons(prs)
    if len(icons) < 2:
        return

    families = {icon.family for icon in icons}
    if len(families) > 1:
        raise IconConsistencyError(
            f"deck mixes icon families: {', '.join(sorted(families))}. One family per deck "
            "(PHASE-3A 3a.7)."
        )

    # A list, not a dict keyed by name: two icons can share a name across slides (the same
    # glyph used twice), and keying by name would silently drop one's ratio from the check.
    ratios = [(icon, icon.stroke_pt / icon.side_pt) for icon in icons if icon.side_pt > 0]
    if ratios:
        values = [ratio for _, ratio in ratios]
        low, high = min(values), max(values)
        if high - low > STROKE_RATIO_TOLERANCE:
            outlier, _ = max(ratios, key=lambda pair: abs(pair[1] - low))
            raise IconConsistencyError(
                f"icon stroke weight is not consistent across the deck: ratios range from "
                f"{low:.4f} to {high:.4f} of icon size (furthest outlier: {outlier.name!r} "
                f"on slide {outlier.slide_index}). One stroke weight per deck "
                "(PHASE-3A 3a.7)."
            )

    sizes = {round(icon.side_pt / SIZE_ROUNDING_PT) * SIZE_ROUNDING_PT for icon in icons}
    if len(sizes) > MAX_DISTINCT_SIZES:
        raise IconConsistencyError(
            f"icons use {len(sizes)} distinct sizes ({sorted(sizes)}pt), more than the "
            f"{MAX_DISTINCT_SIZES}-step scale a deck should commit to. One size scale per "
            "deck (PHASE-3A 3a.7) — place icons from `style.IconStyle.size(role)`, not "
            "arbitrary boxes."
        )
