"""`icon_pillars` — three or four side-by-side pillars, each an icon over a label (B35).

The narrative job: capability pillars, workstreams, principles — a small set of parallel
ideas a reader should take in as a set, each anchored by a glyph. This is the component the
`icon_anchored` communication mode (D13, plan §6.11.2) was named for, and until it existed
no component could place an icon on a slide face at all (B35).

Structure: a headline across the top; below it, the body split into equal columns, one per
pillar. Each column is a stack: the icon, then its label directly beneath, then an optional
one-line point. The icon and its label are drawn in **one stack**, so their adjacency is a
construction fact, not a geometric coincidence `grammar.check_icon_adjacency` has to infer
(that module's docstring names the missing structural pairing; this is it for this
component).

**The icon drawn is the IR's resolved glyph, not a re-resolution of its concept.**
`PillarIcon.glyph` is `IconRef.glyph_id`; `Frame.icon` falls back from concept to literal
filename, so passing the glyph id draws exactly that file. Re-resolving the concept here
would make `SwapGlyph`'s recorded `glyph_id` decorative — the deck would show whatever the
concept table says today, not what the IR says.

Owning phase: 3a catalog, added during 3b per B35.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast, get_args

from pptx.slide import Slide

from autodeck.design.draw import ThemeColor
from autodeck.design.layout_kit import Canvas, Frame, Stack

#: Fewer than three is not a set; more than four will not fit an icon, a label and a point
#: per column at the client's type scale. Enforced by the adapter and the slot budget.
MIN_PILLARS = 3
MAX_PILLARS = 4

#: The icon's square edge, as a multiple of the token baseline.
_ICON_BASELINES = 6


@dataclass
class PillarIcon:
    glyph: str
    """`IconRef.glyph_id` — the resolved, vendored glyph file name."""
    color: str = "accent1"
    """`IconRef.color_token` — a theme accent, never a literal colour (D1)."""


@dataclass
class Pillar:
    icon: PillarIcon
    label: str
    """A short framing label — what this pillar is. Uncited framing, so under A5's fence."""
    point: str | None = None
    """An optional one-line claim — what is true of it. Cited when present."""


@dataclass
class IconPillarsContent:
    """The slots this component fills."""

    headline: str
    """The talking header — carries the argument (D12)."""
    pillars: list[Pillar] = field(default_factory=list)
    source: str = ""
    """Computed by the renderer from the face's citations; never authored."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: IconPillarsContent) -> None:
    """Render `content` onto `slide`.

    Contract:
      - `frame.body_and_caption()`; headline as `data_card_grid` does (title style, major
        face, bold), placed with `gutter=canvas.baseline * 4`; `content.source` in the
        caption band exactly as the other cited components write it.
      - The region below splits into `len(content.pillars)` equal columns with
        `canvas.gutter` between (`Box.grid(1, n, ...)`).
      - Each column: one `frame.stack(f"icon_pillars pillar {i}", ...)` holding, top to
        bottom, the icon (square, `_ICON_BASELINES * canvas.baseline`, centred), the label
        (`canvas.style("body", bold=True)`, centred), and the point when present
        (`canvas.style("body")`, centred). The icon is drawn with
        `frame.icon(box, pillar.icon.glyph, color=pillar.icon.color)`.
        If `Stack` has no item for an icon, add the smallest honest one to `layout_kit`
        (`Stack.icon(...)`, measured as its box height) rather than placing the icon outside
        the stack — the stack is what makes adjacency structural.
      - `len(pillars)` outside `MIN_PILLARS..MAX_PILLARS` → `ValueError` naming the count.
      - Overflow raises `LayoutOverflowError` like every other component; no shrinking.
    """
    count = len(content.pillars)
    if not MIN_PILLARS <= count <= MAX_PILLARS:
        raise ValueError(
            f"icon_pillars needs {MIN_PILLARS} to {MAX_PILLARS} pillars, got {count}"
        )
    for pillar in content.pillars:
        if pillar.icon.color not in get_args(ThemeColor):
            raise ValueError(
                f"icon_pillars: icon colour {pillar.icon.color!r} is not a theme colour "
                f"({', '.join(get_args(ThemeColor))}); icons take a theme slot, never a literal"
            )

    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()

    headline = frame.stack("icon_pillars headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    region = headline.place(body, gutter=canvas.baseline * 4)

    columns = region.grid(1, count, gutter=canvas.gutter)[0]

    # Every column's stack is declared before any is placed, so the row can be one band as
    # tall as its tallest pillar: icons then share a top edge across the slide, and the
    # whole row is centred in the space under the headline as a unit.
    stacks = [
        _pillar_stack(frame, canvas, index, pillar, column.width)
        for index, (pillar, column) in enumerate(zip(content.pillars, columns, strict=True))
    ]
    band_height = max(stack.height for stack in stacks)
    band = region.reserve(band_height, valign="middle", what="icon_pillars pillars")
    for stack, column in zip(stacks, columns, strict=True):
        stack.place(column.resize(height=band.height).offset(dy=band.y - column.y))

    frame.caption(caption, content.source)


def _pillar_stack(
    frame: Frame, canvas: Canvas, index: int, pillar: Pillar, width: float
) -> Stack:
    """One column: icon, then label directly beneath, then the optional point."""
    stack = frame.stack(f"icon_pillars pillar {index}", width)
    stack.icon(
        pillar.icon.glyph,
        size=_ICON_BASELINES * canvas.baseline,
        color=cast(ThemeColor, pillar.icon.color),
    )
    stack.text(
        pillar.label,
        canvas.style("body", bold=True, align="center"),
        gap=canvas.baseline * 2,
    )
    if pillar.point:
        stack.text(
            pillar.point,
            canvas.style("body", align="center"),
            gap=canvas.baseline,
        )
    return stack
