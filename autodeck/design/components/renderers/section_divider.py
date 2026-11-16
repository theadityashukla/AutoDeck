"""`section_divider` — section number and section name.

The narrative job: mark a major structural break in the deck and name the section that
follows. A section divider is a simple heading with just two pieces: which section this is
(a number or label) and what it is called. The design job is correspondingly minimal — make
the number prominent, the name readable, and the whole slide breathe.

The structure is a single centered stack with the section number, the section name below it,
and an optional accent rule for visual interest.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

_RULE_WIDTH = 64.0
_RULE_THICKNESS = 3.0


@dataclass
class SectionDividerContent:
    """The slots this component fills."""

    section_number: str
    """The section label — often a number like '1' or '2', but may be anything."""
    section_name: str
    """The name of the section."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: SectionDividerContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, _caption = frame.body_and_caption()

    # Single centered stack for section number, rule, and name
    section = frame.stack("section_divider", body.width * 0.8)
    section.text(content.section_number, canvas.style("title", face="major", bold=True))
    section.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    section.text(
        content.section_name,
        canvas.style("heading", face="major", bold=True),
        gap=canvas.baseline * 3,
    )
    section.place(body, valign="middle")
