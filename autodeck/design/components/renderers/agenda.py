"""`agenda` — headline and an ordered list of items.

The narrative job: outline what the deck will cover, in the order it will cover it. An
agenda slide sets expectations and makes the structure transparent to the audience. Three
to five items is the range — enough to cover the main points, few enough to read at a
glance.

The structure follows the headline-and-body pattern: a headline block with a rule, then a
numbered list of agenda items below it. The numbering is semantic rather than a visual
afterthought, so the item that reads as "first" is numbered as such.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

_RULE_WIDTH = 48.0
_RULE_THICKNESS = 3.0


@dataclass
class AgendaContent:
    """The slots this component fills."""

    headline: str
    """The talking header — frames the agenda (D12)."""
    items: list[str] = field(default_factory=list)
    """The agenda items, typically three to five, in the order they will be covered."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: AgendaContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, _caption = frame.body_and_caption()

    # Headline block
    headline = frame.stack("agenda headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    headline.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    region = headline.place(body, gutter=canvas.baseline * 4)

    # Agenda items as a numbered list
    items = frame.stack("agenda items", region.width)
    for index, item in enumerate(content.items, start=1):
        # Format as a number and the item text
        formatted = f"{index}. {item}"
        gap = 0.0 if index == 1 else canvas.baseline * 2.5
        items.text(
            formatted,
            canvas.style("body", color="dk2"),
            gap=gap,
        )
    items.place(region, valign="top")
