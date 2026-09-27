"""`timeline` — a sequence over time, drawn by the diagram engine's `process_flow`.

SCAFFOLD (Opus). `render()` is Sonnet's to fill; the contract below is decided.

Why this takes a `DiagramSpec` and not a list of date strings — the decision this module
exists to carry: **a date is a fact.** "Q3 2024: vLLM released" asserts something checkable,
so each milestone must arrive already decided as a `claim` (with citations) or `framing`
(a stage name with no date), exactly as `DiagramNode` requires. A timeline component that
built nodes from plain strings would be making the A1 decision itself, and a renderer must
never do that.

Why it renders as chevrons: the engine's only sequence geometry is `process_flow`. A true
dated axis — points on a line, spacing proportional to time — is a geometry the engine
cannot express yet. PHASE-3A's escalation trigger for that is explicit: "record as a
catalog gap; do not bolt a special case onto a renderer". So this renders the sequence
honestly as a sequence, and the dated axis is recorded as a gap in the phase handover.

Contract for `render()`:
  - Refuse, with `ValueError` naming the kind it got, any `content.diagram` whose `kind` is
    not `"process_flow"`. A timeline that silently drew a 2x2 would be lying about time.
  - Otherwise identical to `framework_diagram.render`: caption band, the same headline
    band with the same literal gaps, then `place_diagram` on the remaining region, never
    drawing `diagram.title`, never shrinking. Sharing a private helper with
    `framework_diagram` is fine and probably right — say so in both docstrings if you do.

The `check_overflow` caveat in `framework_diagram`'s docstring applies here unchanged.
D13: `diagram_led`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas
from autodeck.ir.models import DiagramSpec


@dataclass
class TimelineContent:
    """The slots this component fills."""

    headline: str
    diagram: DiagramSpec
    """Must be `kind="process_flow"`; `render` refuses anything else."""
    source: str = ""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: TimelineContent) -> None:
    """Render `content` onto `slide`. See the module docstring for the contract."""
    raise NotImplementedError("scaffold: Sonnet fills this in")
