"""`chart_focus` — one native chart, a headline that says what it shows, and one line more.

SCAFFOLD (Opus). `render()` is Sonnet's to fill; the contract below is decided.

The narrative job: quantitative evidence where the shape of the data is the argument. The
design job: a headline band, a native editable chart filling the body via
`autodeck.design.charts.place_chart`, and an optional one-line takeaway under it. This
module draws no chart element itself — D10 is `charts.py`'s, and a second chart-drawing
path would be a second place for "no image fallback" to fail.

Contract for `render()`:
  - Headline band as `bullets_supporting.render` has it, same literal gaps (mirrored in
    `_chart_focus_slots`).
  - Optional `takeaway`: one line, `canvas.style("body", color="dk2")`, placed at the
    **bottom** of the body region with `Box.reserve`, before the chart gets what is left.
    Reserve first, then chart, so an over-long takeaway raises rather than squeezing the
    chart to nothing.
  - The remaining region goes to `place_chart(frame, region, content.chart)`.
    `place_chart` draws its own source line from `ChartSpec.source_citations`, so this
    component **does not call `frame.caption`** — two source lines would be one too many,
    and the chart's is the one tied to its data. State that in the finished docstring.
  - No shrinking; `LayoutOverflowError` and `ChartConstructionError` propagate.

What `check_overflow` protects: `headline` and `takeaway` are declared slots. The chart's own
title, axis titles, category labels and series names are measured by `charts.py` at render,
the same render-time-only caveat `framework_diagram` states for diagram labels.

A1: the chart's numbers carry `ChartSpec.source_citations`. The open owner question — a
chart receives no A3 verdict, and citations are not linked per data point — is recorded in
the phase handover and is not this component's to solve.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas
from autodeck.ir.models import ChartSpec


@dataclass
class ChartFocusContent:
    """The slots this component fills."""

    headline: str
    chart: ChartSpec
    takeaway: str = ""
    """One optional line under the chart saying what to notice. Capped to one line."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: ChartFocusContent) -> None:
    """Render `content` onto `slide`. See the module docstring for the contract."""
    raise NotImplementedError("scaffold: Sonnet fills this in")
