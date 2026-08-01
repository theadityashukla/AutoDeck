"""`two_column_compare` — two options set against each other.

The narrative job: make a comparison legible at a glance, and make the *shape* of the
comparison carry meaning — matching rows across the two columns, so the eye can read down
one side or across both. The design job is the harder of the two Phase 0 components,
because a comparison layout fails in a specific way: unequal row heights make the columns
drift apart and the comparison stops being a comparison.

Two things keep them locked together:

* every row takes the height its **taller** side needs, measured with real glyph metrics;
* both columns use the **same inner geometry**, so the emphasised panel's padding cannot
  push its title half a line below its neighbour — which is precisely what the first spike
  render did.

Owning phase: 0 (spike 0.5). The second of the two components that prove D5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.slide import Slide

from autodeck.design.draw import add_rect, add_rule, add_text
from autodeck.design.layout_kit import Box, Canvas, LayoutOverflowError, TextStyle

_PANEL_PADDING = 22.0
_MARKER_INSET = 17.0
_RULE_WIDTH = 40.0
_RULE_THICKNESS = 2.5


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
    region, source_area = canvas.content.split_bottom(
        canvas.size("caption") * 1.6, gutter=canvas.gutter
    )

    headline_style = canvas.style("title", face="major", color="dk1", bold=True)
    headline_box = canvas.fit(content.headline, region, headline_style)
    add_text(slide, headline_box, content.headline, headline_style)

    _, body_area = region.split_top(headline_box.height, gutter=canvas.baseline * 5)
    left_area, right_area = body_area.split_columns(2, canvas.gutter * 1.5)

    text_style = canvas.style("body", color="dk2")
    title_style = canvas.style("heading", color="dk1", bold=True)
    row_heights = _row_heights(canvas, content, left_area.width, text_style)

    # Both columns are drawn to one height — the taller side's requirement — so the
    # emphasis panel encloses its own content and the two sides stay symmetrical.
    panel_height = max(
        _content_height(canvas, column, row_heights, title_style, left_area.width)
        for column in (content.left, content.right)
    )
    if panel_height > body_area.height:
        raise LayoutOverflowError(
            f"two_column_compare needs {panel_height:.0f}pt of column height but the slide "
            f"offers {body_area.height:.0f}pt. Shorten the points, drop a row, or move to a "
            "component with more room — text budgets (§6.7) exist to prevent this reaching "
            "a render."
        )

    for area, column in ((left_area, content.left), (right_area, content.right)):
        # Centred in the body band rather than pinned to its top: a content-sized panel
        # hung from the top leaves all its slack in one block under the slide, which reads
        # as an unfinished slide rather than as deliberate space.
        panel = area.resize(height=panel_height).align_within(area, vertical="middle")
        _render_column(slide, canvas, panel, column, row_heights, text_style, title_style)

    if content.source:
        add_text(
            slide,
            source_area,
            content.source,
            canvas.style("caption", color="accent6", valign="bottom"),
        )


def _text_width(column_width: float) -> float:
    """Usable text width inside a column.

    Computed from the padded geometry both columns share, so the two sides wrap at the
    same width and a row's height means the same thing on either side.
    """
    return column_width - _PANEL_PADDING * 2 - _MARKER_INSET


def _row_heights(
    canvas: Canvas,
    content: TwoColumnCompareContent,
    column_width: float,
    style: TextStyle,
) -> list[float]:
    """Height of each comparison row: whichever side needs more.

    This is the function that keeps the columns aligned. Rows are matched by position, so
    point *n* on the left sits level with point *n* on the right — which is what makes the
    layout readable across as well as down.
    """
    width = _text_width(column_width)
    heights: list[float] = []
    for index in range(max(len(content.left.points), len(content.right.points))):
        heights.append(
            max(
                canvas.measure(column.points[index], width, style)
                for column in (content.left, content.right)
                if index < len(column.points)
            )
        )
    return heights


def _rows_height(canvas: Canvas, row_heights: list[float]) -> float:
    """Total height of the row stack, including the gaps between rows."""
    if not row_heights:
        return 0.0
    return sum(row_heights) + canvas.baseline * 2.5 * (len(row_heights) - 1)


def _content_height(
    canvas: Canvas,
    column: ComparisonColumn,
    row_heights: list[float],
    title_style: TextStyle,
    column_width: float,
) -> float:
    """How tall this column needs to be, padding included.

    Measured rather than assumed so the emphasis panel is drawn around its content instead
    of being given the whole region and overflowing it — which is what the second spike
    render did with its last row.
    """
    inner_width = column_width - _PANEL_PADDING * 2
    title = canvas.measure(column.title, inner_width, title_style)
    chrome = canvas.baseline * 1.5 + _RULE_THICKNESS + canvas.baseline * 3
    return _PANEL_PADDING * 2 + title + chrome + _rows_height(canvas, row_heights)


def _render_column(
    slide: Slide,
    canvas: Canvas,
    area: Box,
    column: ComparisonColumn,
    row_heights: list[float],
    text_style: TextStyle,
    title_style: TextStyle,
) -> None:
    if column.emphasised:
        # A tint of the column's own accent: present enough to mark the recommendation,
        # quiet enough that the text still reads as body copy.
        add_rect(slide, area, fill=column.accent, fill_brightness=0.88)

    # Both columns inset identically whether or not a panel is drawn. Padding only the
    # emphasised one is what knocked the two titles out of alignment in the first render.
    inner = area.pad(_PANEL_PADDING)

    title_box = canvas.fit(column.title, inner, title_style)
    add_text(slide, title_box, column.title, title_style)

    _, below = inner.split_top(title_box.height, gutter=canvas.baseline * 1.5)
    rule_box, cursor = below.split_top(_RULE_THICKNESS, gutter=canvas.baseline * 3)
    add_rule(
        slide,
        rule_box.resize(width=_RULE_WIDTH),
        color=column.accent,
        thickness=_RULE_THICKNESS,
    )

    marker_style = canvas.style("body", color=column.accent, bold=True)
    gap = canvas.baseline * 2.5

    for index, height in enumerate(row_heights):
        if index < len(column.points):
            add_text(
                slide,
                cursor.resize(width=10.0, height=text_style.size * 1.3),
                "—",
                marker_style,
            )
            add_text(
                slide,
                cursor.inset(left=_MARKER_INSET).resize(height=height),
                column.points[index],
                text_style,
            )
        # An absent row still consumes its height, so the next pair stays level.
        _, cursor = cursor.split_top(height, gutter=gap)
