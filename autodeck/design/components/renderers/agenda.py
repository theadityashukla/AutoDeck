"""`agenda` — headline and an ordered list of items.

The narrative job: outline what the deck will cover, in the order it will cover it. An
agenda slide sets expectations and makes the structure transparent to the audience. Three
to five items is the range — enough to cover the main points, few enough to read at a
glance.

The structure follows the headline-and-body pattern: a headline block with a rule, then a
numbered list of agenda items below it. The numbering is semantic rather than a visual
afterthought, so the item that reads as "first" is numbered as such.

## The numbers are list formatting, not text

An earlier version drew `f"{index}. {item}"`: a component composing digits into the slide's
text. Those digits exist in no IR block, so the post-render numeric audit (A2) correctly
flagged every clean agenda render as carrying numerals nobody wrote — "a template with a
number baked in", the very thing that audit exists to catch. Components copy content and
never compose it.

So the items are **one text box with one paragraph per item**, each carrying PowerPoint's
native auto-numbering (`a:buAutoNum`, `arabicPeriod`). The numbers are paragraph formatting
the application generates, never a text run, and a client who reorders or inserts an item in
PowerPoint sees the numbers follow — which a per-item text box (every one reading "1.") or
typed digits could not do. One box rather than several is what makes the numbering continue.

The text is measured at the width it really gets: the box's width less the hanging indent
(`number_indent`), which is also what `catalog._agenda_slots` budgets against.

Owning phase: 3a (task 3a.4), the first tranche; numbering made native in 3b.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls
from pptx.slide import Slide
from pptx.util import Pt

from autodeck.design.layout_kit import Canvas, LayoutOverflowError

_RULE_WIDTH = 48.0
_RULE_THICKNESS = 3.0

#: The hanging indent the auto-number sits in, as a multiple of the body size. 1.75 em is
#: room for "9." with a gap after it (and "10." with a slightly tighter one) at any type
#: scale, since it scales with the size it is measured from.
_NUMBER_INDENT_EM = 1.75


def number_indent(canvas: Canvas) -> float:
    """Points between the list's left edge and its text — where the auto-number hangs.

    Public because the catalog must budget each item against the width the text really gets,
    `region.width - number_indent(canvas)`, and two modules each computing the indent is two
    answers to one question.
    """
    return canvas.size("body") * _NUMBER_INDENT_EM


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

    if not content.items:
        return

    # One text box, one paragraph per item, each natively auto-numbered: see the module
    # docstring. A newline inside an item would start a second paragraph and so a second
    # number for one agenda item, which is not something to do quietly.
    for item in content.items:
        if "\n" in item:
            raise ValueError(
                f"agenda item {item!r} contains a newline; one item is one line of the list"
            )

    style = canvas.style("body", color="dk2")
    indent = number_indent(canvas)
    text_width = region.width - indent
    gap = canvas.baseline * 2.5

    heights: list[float] = []
    for item in content.items:
        block = canvas.measure_block(item, text_width, style)
        if block.too_wide_words:
            raise LayoutOverflowError(
                f"agenda items: {', '.join(repr(w) for w in block.too_wide_words[:3])} "
                f"{'is' if len(block.too_wide_words) == 1 else 'are'} wider than the "
                f"{text_width:.0f}pt an item has, at {style.size:g}pt {style.family}. "
                "Wrapping cannot fix a single over-wide word — shorten it."
            )
        heights.append(block.height)

    total = sum(heights) + gap * (len(heights) - 1)
    box = region.reserve(total, valign="top", what="agenda items")
    shape = frame.text(box, "\n".join(content.items), style)

    for index, paragraph in enumerate(shape.text_frame.paragraphs):
        if index > 0:
            paragraph.space_before = Pt(gap)
        _number(paragraph, indent)


def _number(paragraph: Any, indent: float) -> None:
    """Hang a native auto-number (`1.`, `2.`, …) in `indent` points of left margin.

    `a:buAutoNum` goes after `lnSpc`/`spcBef`/`spcAft` in `a:pPr`'s sequence, so this runs
    after the spacing has been set. The number takes the text's own font, size and colour.
    """
    properties = paragraph._p.get_or_add_pPr()
    properties.set("marL", str(int(Pt(indent))))
    properties.set("indent", str(-int(Pt(indent))))
    properties.append(parse_xml(f'<a:buAutoNum {nsdecls("a")} type="arabicPeriod"/>'))
