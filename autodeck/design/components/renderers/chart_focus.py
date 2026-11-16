"""`chart_focus` — one native chart, a headline that says what it shows, and one line more.

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

from autodeck.design.charts import place_chart
from autodeck.design.layout_kit import Box, Canvas
from autodeck.ir.models import ChartSpec

#: The headline band's chrome, copied literally from `bullets_supporting._RULE_WIDTH` /
#: `_RULE_THICKNESS` — `_chart_focus_slots` (catalog.py) reconstructs the same box from the
#: same two numbers, so a drift here is a drift there too.
_RULE_WIDTH = 64.0
_RULE_THICKNESS = 3.0


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
    frame = canvas.on(slide)

    # No `frame.body_and_caption()` / `frame.caption(...)` here, on purpose: this
    # component's only source line is `place_chart`'s own, drawn from
    # `ChartSpec.source_citations`. The region handed to it is `canvas.content` (the whole
    # content area, minus the headline band below), which `place_chart` splits for its own
    # chart-plus-caption band itself — exactly the split every other component gets from
    # `Canvas.body_and_caption`, done once, by the one caller that needs it.
    region = canvas.content

    headline = frame.stack("chart_focus headline", region.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    headline.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    body = headline.place(region, gutter=canvas.baseline * 4)

    if content.takeaway:
        takeaway_style = canvas.style("body", color="dk2")
        takeaway_height = canvas.measure(content.takeaway, body.width, takeaway_style)
        # Reserve first, at the bottom, before the chart gets whatever is left — an
        # over-long takeaway raises `LayoutOverflowError` here rather than the chart being
        # squeezed to make room for it.
        takeaway_box = body.reserve(
            takeaway_height, valign="bottom", what="chart_focus takeaway"
        )
        frame.text(takeaway_box, content.takeaway, takeaway_style)
        gap = canvas.baseline * 3
        chart_region = Box(body.x, body.y, body.width, max(takeaway_box.y - gap - body.y, 0.0))
    else:
        chart_region = body

    place_chart(frame, chart_region, content.chart)
