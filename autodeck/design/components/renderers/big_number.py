"""`big_number` — one figure carrying the slide.

The narrative job: a single number is the argument, everything else is support. The design
job is hierarchy so steep that the eye lands on the figure before it reads anything, which
means the type scale does the work rather than colour or decoration.

Authored natively against `layout_kit` per D5. Every vertical position is derived from a
measured height rather than a guess — the headline is measured with the same `TextStyle`
that renders it, so a two-line headline pushes the rule and the figure down instead of
being overlapped by them.

Owning phase: 0 (spike 0.5). The first of the two components that prove D5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.slide import Slide

from autodeck.design.draw import add_rule, add_text
from autodeck.design.layout_kit import Box, Canvas, LayoutOverflowError, TextStyle

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
    region, source_area = canvas.content.split_bottom(
        canvas.size("caption") * 1.6, gutter=canvas.gutter
    )

    region = _render_headline(slide, canvas, region, content)
    _render_body(slide, canvas, region, content)

    if content.source:
        add_text(
            slide,
            source_area,
            content.source,
            canvas.style("caption", color="accent6", valign="bottom"),
        )


def _render_headline(
    slide: Slide, canvas: Canvas, region: Box, content: BigNumberContent
) -> Box:
    """Headline plus accent rule. Returns the region left below them."""
    style = canvas.style("title", face="major", color="dk1", bold=True)
    headline_box = canvas.fit(content.headline, region, style)
    add_text(slide, headline_box, content.headline, style)

    _, below = region.split_top(headline_box.height, gutter=canvas.baseline * 3)
    rule_box, below = below.split_top(_RULE_THICKNESS, gutter=canvas.baseline * 4)
    add_rule(
        slide,
        rule_box.resize(width=_RULE_WIDTH),
        color=content.accent,
        thickness=_RULE_THICKNESS,
    )
    return below


def _render_body(slide: Slide, canvas: Canvas, region: Box, content: BigNumberContent) -> None:
    """The figure and its label, with supporting points beside it when there are any.

    The block is centred in whatever vertical space the headline left, so a one-line and a
    two-line headline both produce a balanced slide instead of the second one leaving a
    visible band of dead space under the figure.
    """
    if content.supporting_points:
        figure_area, support_area = region.split_columns(2, canvas.gutter * 2)
    else:
        figure_area, support_area = region, None

    block_height = _figure_block_height(canvas, content, figure_area.width)
    if block_height > region.height:
        raise LayoutOverflowError(
            f"big_number needs {block_height:.0f}pt below its headline but only "
            f"{region.height:.0f}pt remain. Shorten the headline or the support line."
        )

    centred = figure_area.resize(height=block_height).align_within(
        figure_area, vertical="middle"
    )
    _render_figure(slide, canvas, centred, content)

    if support_area is not None:
        _render_supporting_points(
            slide,
            canvas,
            support_area.resize(height=block_height).align_within(
                support_area, vertical="middle"
            ),
            content,
        )


def _figure_block_height(canvas: Canvas, content: BigNumberContent, width: float) -> float:
    """Measured height of figure + label + support, gaps included."""
    figure_style = _figure_style(canvas, content)
    height = canvas.measure(content.figure, width, figure_style) + canvas.baseline

    label_style = canvas.style("heading", color="dk2")
    height += canvas.measure(content.figure_label, width, label_style)

    if content.support:
        height += canvas.baseline * 3
        height += canvas.measure(content.support, width, canvas.style("body", color="dk2"))
    return height


def _figure_style(canvas: Canvas, content: BigNumberContent) -> TextStyle:
    return canvas.style(
        "display",
        face="major",
        color=content.accent,
        bold=True,
        line_spacing=0.95,
    ).with_(size=canvas.size("display") * _FIGURE_SCALE)


def _render_figure(slide: Slide, canvas: Canvas, area: Box, content: BigNumberContent) -> None:
    figure_style = _figure_style(canvas, content)
    figure_box = canvas.fit(content.figure, area, figure_style)
    add_text(slide, figure_box, content.figure, figure_style)

    _, below = area.split_top(figure_box.height, gutter=canvas.baseline)

    label_style = canvas.style("heading", color="dk2")
    label_box = canvas.fit(content.figure_label, below, label_style)
    add_text(slide, label_box, content.figure_label, label_style)

    if content.support:
        _, under_label = below.split_top(label_box.height, gutter=canvas.baseline * 3)
        support_style = canvas.style("body", color="dk2")
        add_text(
            slide,
            canvas.fit(content.support, under_label, support_style),
            content.support,
            support_style,
        )


def _render_supporting_points(
    slide: Slide, canvas: Canvas, area: Box, content: BigNumberContent
) -> None:
    """Supporting points as a measured stack, each snapped to the baseline grid."""
    text_style = canvas.style("body", color="dk2")
    marker_style = canvas.style("body", color=content.accent, bold=True)
    marker_inset = 18.0

    cursor = area.snap_to_baseline(canvas.baseline)
    for point in content.supporting_points:
        text_box = cursor.inset(left=marker_inset)
        measured = canvas.fit(point, text_box, text_style)

        add_text(
            slide, cursor.resize(width=10.0, height=text_style.size * 1.4), "—", marker_style
        )
        add_text(slide, measured, point, text_style)

        _, cursor = cursor.split_top(measured.height, gutter=canvas.baseline * 2.5)
