"""`big_number` — one figure carrying the slide.

The narrative job: a single number is the argument, everything else is support. The design
job is hierarchy so steep that the eye lands on the figure before it reads anything, which
means the type scale does the work rather than colour or decoration.

Authored natively against `layout_kit` per D5. Nothing here computes a position: each
block is declared as a `Stack` and placed, so a two-line headline pushes the rule and the
figure down instead of being overlapped by them, and the figure block is measured by the
same declaration that draws it.

The figure and the supporting points share one band height (the taller of the two), which
is what puts the first supporting point level with the top of the figure rather than
floating at its own centre. Two blocks centred independently look like two decisions.

Owning phase: 0 (spike 0.5); rewritten against the productionised kit in 3a.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas, Frame, Stack

#: The figure is set this many times the display size. Large enough that the number is the
#: only possible entry point; the label then reads as caption, not as competition.
_FIGURE_SCALE = 2.0

_RULE_WIDTH = 64.0
_RULE_THICKNESS = 3.0


@dataclass
class BigNumberContent:
    """The slots this component fills."""

    headline: str
    """The talking header — carries the argument (D12), so it is a claim like any other."""
    figure: str
    """The number itself, pre-formatted. Never computed here."""
    figure_label: str
    """What the number measures."""
    support: str = ""
    """One sentence of context."""
    source: str = ""
    """Rendered from the block's citation; the audit report is the authority."""
    accent: str = "accent1"
    supporting_points: list[str] = field(default_factory=list)


def render(slide: Slide, canvas: Canvas, content: BigNumberContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()
    frame.caption(caption, content.source)

    headline = frame.stack("big_number headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    headline.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    region = headline.place(body, gutter=canvas.baseline * 4)

    if content.supporting_points:
        figure_area, points_area = region.split_columns(2, canvas.gutter * 2)
    else:
        figure_area, points_area = region, None

    figure = _figure_stack(frame, figure_area.width, content)
    points = None if points_area is None else _points_stack(frame, points_area.width, content)

    band = max(figure.height, 0.0 if points is None else points.height)
    figure.place(figure_area.reserve(band, valign="middle", what="big_number figure block"))
    if points is not None and points_area is not None:
        points.place(
            points_area.reserve(band, valign="middle", what="big_number supporting points"),
            snap_baseline=True,
        )


def _figure_stack(frame: Frame, width: float, content: BigNumberContent) -> Stack:
    """The figure, its label, and the optional sentence under them."""
    canvas = frame.canvas
    stack = frame.stack("big_number figure block", width)
    stack.text(
        content.figure,
        canvas.style(
            "display",
            face="major",
            scale=_FIGURE_SCALE,
            color=content.accent,
            bold=True,
            line_spacing=0.95,
        ),
    )
    stack.text(content.figure_label, canvas.style("heading", color="dk2"), gap=canvas.baseline)
    if content.support:
        stack.text(content.support, canvas.style("body", color="dk2"), gap=canvas.baseline * 3)
    return stack


def _points_stack(frame: Frame, width: float, content: BigNumberContent) -> Stack:
    """Supporting points beside the figure, snapped to the baseline grid when placed."""
    canvas = frame.canvas
    return frame.stack("big_number supporting points", width).items(
        content.supporting_points,
        canvas.style("body", color="dk2"),
        row_gap=canvas.baseline * 2.5,
        marker_style=canvas.style("body", color=content.accent, bold=True),
    )
