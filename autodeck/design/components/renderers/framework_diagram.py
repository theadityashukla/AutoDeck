"""`framework_diagram` — one structural idea, drawn as a native diagram under a headline.

The narrative job: a slide whose argument *is* a relationship — a sequence, a 2x2, a
stack — rather than a list of points. The design job is almost nothing, deliberately: a
headline band exactly like `bullets_supporting`'s, then the whole remaining body region
handed to `autodeck.design.diagrams.place_diagram`. PHASE-3A says diagram-led components
"delegate geometry to the diagram engine rather than carrying bespoke renderer code", so
this module must not place a single node itself.

`_render_headline_and_diagram` below is the shared body of both `render()`s in this pair:
`timeline.render` calls it after checking `content.diagram.kind`, so the headline band's
geometry — the one thing that actually needs to be identical — has exactly one definition
rather than two copies drifting apart.

Contract for `render()`:
  - Caption band via `frame.body_and_caption()` / `frame.caption(...)`, as every component.
  - Headline: `canvas.style("title", face="major", bold=True)`, the accent rule and the
    `canvas.baseline * 3` / `* 4` gaps exactly as `bullets_supporting.render` has them.
    Copy them literally; `_framework_diagram_slots` in `catalog.py` mirrors them.
  - The region left after the headline goes to `place_diagram(frame, region, content.diagram)`
    unchanged. Any geometry `place_diagram` supports is accepted.
  - `content.diagram.title` is **not drawn**. `place_diagram` never draws it, and this
    component must not either: the headline is the slide's one voice, and printing both
    says the same thing twice. A test pins this.
  - No shrinking. A node label that does not physically fit raises `LayoutOverflowError`
    from inside `place_diagram`; let it propagate.

What `check_overflow` can and cannot protect here — state this in the finished docstring:
the headline is a declared slot and is checked before render like any other. The diagram's
labels are **not** catalog slots, because their boxes depend on node count. They are
protected twice, at two different times: by `DiagramSpec`'s word budget when the IR is
constructed (`GEOMETRIES[kind].max_label_words`), and by physical measurement only at
render. So an over-long label that is under its word budget is caught at render, not
before. That is a real difference from every non-diagram component and must be said.

D13: a `diagram_led` slide. One diagram per slide, which this component has by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.diagrams import place_diagram
from autodeck.design.layout_kit import Canvas
from autodeck.ir.models import DiagramSpec

#: The headline band's chrome, copied literally from `bullets_supporting._RULE_WIDTH` /
#: `_RULE_THICKNESS` — `_framework_diagram_slots` (catalog.py) reconstructs the same box
#: from the same two numbers, so a drift here is a drift there too.
_RULE_WIDTH = 64.0
_RULE_THICKNESS = 3.0


@dataclass
class FrameworkDiagramContent:
    """The slots this component fills."""

    headline: str
    """The slide's claim about the structure. A header that asserts a fact is a `claim`
    block upstream (D12); this component only draws the text it is given."""
    diagram: DiagramSpec
    """Already constructed, so every node has already been decided claim or framing (A1).
    The renderer never makes that decision."""
    source: str = ""
    """Rendered from the block's citation; the audit report is the authority."""
    accent: str = "accent1"


def _render_headline_and_diagram(
    slide: Slide,
    canvas: Canvas,
    *,
    headline: str,
    diagram: DiagramSpec,
    source: str,
    accent: str,
) -> None:
    """The headline band (identical to `bullets_supporting.render`'s) plus `place_diagram`
    on whatever body region is left. Shared by `framework_diagram.render` and
    `timeline.render` — see this module's own docstring for why a shared helper rather than
    two copies.
    """
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()
    frame.caption(caption, source)

    headline_stack = frame.stack("framework_diagram headline", body.width)
    headline_stack.text(headline, canvas.style("title", face="major", bold=True))
    headline_stack.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=accent,
        gap=canvas.baseline * 3,
    )
    region = headline_stack.place(body, gutter=canvas.baseline * 4)

    # `content.diagram.title` is never drawn: the headline above is the slide's one voice,
    # and `place_diagram` never draws a geometry's title either — see the module docstring.
    place_diagram(frame, region, diagram)


def render(slide: Slide, canvas: Canvas, content: FrameworkDiagramContent) -> None:
    """Render `content` onto `slide`. See the module docstring for the contract."""
    _render_headline_and_diagram(
        slide,
        canvas,
        headline=content.headline,
        diagram=content.diagram,
        source=content.source,
        accent=content.accent,
    )
