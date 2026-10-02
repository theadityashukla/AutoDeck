"""`two_column_compare` — two options set against each other.

The narrative job: make a comparison legible at a glance, and make the *shape* of the
comparison carry meaning — matching rows across the two columns, so the eye can read down
one side or across both. The design job is the harder of the two Phase 0 components,
because a comparison layout fails in a specific way: unequal row heights make the columns
drift apart and the comparison stops being a comparison.

Two things keep them locked together, and both are now said once rather than maintained:

* every row takes the height its **taller** side needs (`_row_heights`), handed to the
  stack as each item's `min_height`;
* both columns are built as stacks of the **same inner width** and placed in boxes of the
  same reserved height, so the emphasised panel's padding cannot push its title half a
  line below its neighbour — which is precisely what the first spike render did.

Owning phase: 0 (spike 0.5); rewritten against the productionised kit in 3a.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.slide import Slide

from autodeck.design.layout_kit import MARKER, MARKER_INSET, Canvas, Frame, Stack

_PANEL_PADDING = 22.0
_RULE_WIDTH = 40.0
_RULE_THICKNESS = 2.5

#: Bullet geometry belongs to the kit (`layout_kit.MARKER_INSET`) so that every component's
#: bullets hang at the same place. Named here because the catalog reconstructs this
#: renderer's text width from its own constants and should read the value this file uses.
_MARKER_INSET = MARKER_INSET


@dataclass
class ComparisonColumn:
    """One side of the comparison."""

    title: str
    points: list[str] = field(default_factory=list)
    accent: str = "accent1"
    emphasised: bool = False
    """The recommended option. Gets a tinted panel — one visual difference, not three."""


@dataclass
class TwoColumnCompareContent:
    headline: str
    left: ComparisonColumn
    right: ComparisonColumn
    source: str = ""


def render(slide: Slide, canvas: Canvas, content: TwoColumnCompareContent) -> None:
    """Render the comparison onto `slide`."""
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()
    frame.caption(caption, content.source)

    headline = frame.stack("two_column_compare headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    body_area = headline.place(body, gutter=canvas.baseline * 5)

    left_area, right_area = body_area.split_columns(2, canvas.gutter * 1.5)
    row_heights = _row_heights(canvas, content, left_area.width)
    columns = [
        (area, column, _column_stack(frame, area.width, column, row_heights))
        for area, column in ((left_area, content.left), (right_area, content.right))
    ]

    # One height for both panels — the taller column's requirement — so the emphasis panel
    # encloses its own content and the two sides stay symmetrical. `reserve` is also the
    # overflow check: a comparison too tall for the slide is an error, never a squeeze.
    panel_height = max(stack.height for _, _, stack in columns) + _PANEL_PADDING * 2

    for area, column, stack in columns:
        # Centred in the body band rather than pinned to its top: a content-sized panel
        # hung from the top leaves all its slack in one block under the slide, which reads
        # as an unfinished slide rather than as deliberate space.
        panel = area.reserve(panel_height, valign="middle", what="two_column_compare columns")
        if column.emphasised:
            # A tint of the column's own accent: present enough to mark the recommendation,
            # quiet enough that the text still reads as body copy.
            frame.rect(panel, fill=column.accent, fill_brightness=0.88)
        stack.place(panel.pad(_PANEL_PADDING))


def _text_width(column_width: float) -> float:
    """Usable text width inside a column.

    Computed from the padded geometry both columns share, so the two sides wrap at the
    same width and a row's height means the same thing on either side.
    """
    return column_width - _PANEL_PADDING * 2 - _MARKER_INSET


def _row_heights(
    canvas: Canvas, content: TwoColumnCompareContent, column_width: float
) -> list[float]:
    """Height of each comparison row: whichever side needs more.

    This is the function that keeps the columns aligned. Rows are matched by position, so
    point *n* on the left sits level with point *n* on the right — which is what makes the
    layout readable across as well as down.
    """
    width = _text_width(column_width)
    style = canvas.style("body", color="dk2")
    return [
        max(
            canvas.measure(column.points[index], width, style)
            for column in (content.left, content.right)
            if index < len(column.points)
        )
        for index in range(max(len(content.left.points), len(content.right.points)))
    ]


def _column_stack(
    frame: Frame, column_width: float, column: ComparisonColumn, row_heights: list[float]
) -> Stack:
    """One column: title, accent rule, then the rows — every row present on both sides."""
    canvas = frame.canvas
    stack = frame.stack(
        f"two_column_compare {column.title!r}", column_width - _PANEL_PADDING * 2
    )
    stack.text(column.title, canvas.style("heading", bold=True))
    stack.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=column.accent,
        gap=canvas.baseline * 1.5,
    )

    text_style = canvas.style("body", color="dk2")
    marker_style = canvas.style("body", color=column.accent, bold=True)
    for index, height in enumerate(row_heights):
        gap = canvas.baseline * 3 if index == 0 else canvas.baseline * 2.5
        if index < len(column.points):
            stack.text(
                column.points[index],
                text_style,
                gap=gap,
                min_height=height,
                marker=MARKER,
                marker_style=marker_style,
                marker_inset=_MARKER_INSET,
            )
        else:
            # An absent row still consumes its height, so the next pair stays level.
            stack.space(height, gap=gap)
    return stack
