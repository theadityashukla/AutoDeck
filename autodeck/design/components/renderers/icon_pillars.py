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

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

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
    raise NotImplementedError("scaffold: Sonnet fills this in")
