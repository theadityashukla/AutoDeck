"""The one family, stroke weight and size scale a deck commits to (PHASE-3A 3a.7).

The brief's phrasing is exact: *"one family, stroke weight, and size scale per deck"*. That
is a constraint on the whole deck, not on any one icon placement, so it cannot live as a
default argument on `place_icon` or `Frame.icon` — a renderer that never passes an explicit
size still has to end up drawing from the same small set of sizes as every other renderer in
the deck, or "enforced" is just "the default nobody overrode yet".

`IconStyle` is the shared vocabulary: a build picks one instance and every component that
places an icon reaches for a size *role* from it (`"sm"`, `"md"`, `"lg"`) rather than a bare
point value. `consistency.py` is the enforcement half — it checks what actually got drawn,
which is the only way to catch a renderer that ignored the vocabulary and typed a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

#: The default size scale, in points (the diameter of the square an icon is placed in).
#: Three steps — inline-with-text, card-sized, hero — because a scale with only one size
#: cannot express "this icon matters more than that one", and an unbounded one is not a
#: scale at all.
DEFAULT_ICON_SIZES: MappingProxyType[str, float] = MappingProxyType(
    {"sm": 18.0, "md": 28.0, "lg": 44.0}
)


class UnknownIconSizeError(KeyError):
    """A size role was requested that this deck's `IconStyle` does not define."""


@dataclass(frozen=True)
class IconStyle:
    """A deck's committed icon look: one family, one stroke weight, one size scale.

    `stroke_ratio` is deliberately a ratio of the icon's own side length rather than a fixed
    point value — a hard-coded weight would look right at one size and wrong at another, and
    the ratio is exactly what `place_icon` already defaults to per icon
    (`icon.stroke_width / icon.view_width`). Naming it here makes the deck's choice explicit
    and checkable instead of "whatever the family's own SVGs happened to specify".
    """

    family: str = "lucide"
    stroke_ratio: float = 2.0 / 24.0
    """Stroke width as a fraction of the icon's placed side length. Lucide's own design
    ratio (`stroke-width="2"` on a 24-unit viewBox) is the default because deviating from it
    is exactly the "one stroke weight" rule being broken, not a style choice."""
    sizes: MappingProxyType[str, float] = field(default_factory=lambda: DEFAULT_ICON_SIZES)
    color: str = "accent1"

    def size(self, role: str) -> float:
        """A point size (square side length) from the scale, by role name.

        Raises:
            UnknownIconSizeError: `role` is not in this style's scale.
        """
        try:
            return self.sizes[role]
        except KeyError:
            raise UnknownIconSizeError(
                f"unknown icon size {role!r}. Available: {', '.join(sorted(self.sizes))}"
            ) from None

    def stroke_pt(self, side_pt: float) -> float:
        """The stroke weight, in points, for an icon placed `side_pt` points square."""
        return self.stroke_ratio * side_pt


#: The house default. A build that wants a different family, weight or scale constructs its
#: own `IconStyle` rather than mutating this one.
DEFAULT_ICON_STYLE = IconStyle()
