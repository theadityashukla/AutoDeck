"""`evidence_with_figure` — headline, supporting text, and a figure.

The narrative job: pair an argument with visual evidence. The headline frames the claim,
a supporting paragraph provides context, and a figure placeholder reserves space for the
visual evidence that proves the point.

The structure is headline-and-body: a headline block with a rule, then supporting text and
a figure region side by side or stacked depending on space. The figure is left to the caller
to fill, so the renderer reserves a box for it.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

_RULE_WIDTH = 48.0
_RULE_THICKNESS = 3.0


@dataclass
class EvidenceWithFigureContent:
    """The slots this component fills."""

    headline: str
    """The talking header — carries the argument (D12)."""
    supporting_text: str
    """Context and support for the headline claim."""
    figure: str = ""
    """A placeholder or description for the visual evidence. Rendered as body text."""
    source: str = ""
    """Rendered from the block's citation; the audit report is the authority."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: EvidenceWithFigureContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()
    frame.caption(caption, content.source)

    # Headline block
    headline = frame.stack("evidence_with_figure headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    headline.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    region = headline.place(body, gutter=canvas.baseline * 4)

    # Split into text and figure columns
    text_area, figure_area = region.split_columns(2, canvas.gutter * 2)

    # Supporting text
    text_stack = frame.stack("evidence_with_figure text", text_area.width)
    text_stack.text(content.supporting_text, canvas.style("body", color="dk2"))
    text_stack.place(text_area, valign="top")

    # Figure area — reserved for visual content
    if content.figure:
        figure_stack = frame.stack("evidence_with_figure figure", figure_area.width)
        figure_stack.text(
            content.figure,
            canvas.style("body", color="dk2", italic=True),
        )
        figure_stack.place(figure_area, valign="middle")
