"""`framework_diagram` — one structural idea, drawn as a native diagram under a headline.

SCAFFOLD (Opus). `render()` is Sonnet's to fill; the contract below is decided.

The narrative job: a slide whose argument *is* a relationship — a sequence, a 2x2, a
stack — rather than a list of points. The design job is almost nothing, deliberately: a
headline band exactly like `bullets_supporting`'s, then the whole remaining body region
handed to `autodeck.design.diagrams.place_diagram`. PHASE-3A says diagram-led components
"delegate geometry to the diagram engine rather than carrying bespoke renderer code", so
this module must not place a single node itself.

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

from autodeck.design.layout_kit import Canvas
from autodeck.ir.models import DiagramSpec


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


def render(slide: Slide, canvas: Canvas, content: FrameworkDiagramContent) -> None:
    """Render `content` onto `slide`. See the module docstring for the contract."""
    raise NotImplementedError("scaffold: Sonnet fills this in")
