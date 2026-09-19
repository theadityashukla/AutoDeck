"""`quote` — a pull-quote as the argument.

The narrative job: someone else says the thing the deck wants to argue, in their own
words, so it lands as external validation rather than as the deck's own claim about
itself. `CONFIDENT_COMPONENTS` (`agents/outline.py`) treats it the same way as
`big_number` and `chart_focus` — a whole slide staked on one piece of evidence — which is
why it still carries a `headline` and a `source`: the quote is being cited, not merely
decorated with, and D12 applies to the headline exactly as it does everywhere else.

The design job is smaller than `big_number`'s: one flexible block (an opening mark, the
quote, its attribution) sitting under the same headline-and-rule chrome every component so
far uses. Nothing here is new relative to `big_number`/`two_column_compare` — which is
itself the finding worth reporting: a third component built from the same two ingredients
(a headline `Stack` and a content `Stack`) is evidence the pattern generalises, not a
coincidence.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

#: The opening curly quotation mark, set oversized above the quote text. Not a
#: `QuoteContent` field — the writer never chooses it, so (like `big_number`'s accent rule)
#: it carries no budget of its own and is reserved as fixed chrome in the catalog.
_MARK = "“"

_RULE_WIDTH = 48.0
_RULE_THICKNESS = 3.0

#: The quote text is set this many times the `title` role — large enough to read as the
#: argument the slide is making, not as a supporting sentence under it. A multiple of a
#: token, per `Canvas.style`'s own rule, so a client's type scale still moves it.
_QUOTE_SCALE = 1.35


@dataclass
class QuoteContent:
    """The slots this component fills."""

    headline: str
    """The talking header framing the quote (D12) — carries the argument, like any other."""
    quote: str
    """The pull-quote itself, verbatim from the source."""
    attribution: str
    """Who said it — name and, usually, role or organisation."""
    source: str = ""
    """Rendered from the block's citation; the audit report is the authority."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: QuoteContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()
    frame.caption(caption, content.source)

    headline = frame.stack("quote headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    headline.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    region = headline.place(body, gutter=canvas.baseline * 4)

    block = frame.stack("quote block", region.width)
    block.text(
        _MARK,
        canvas.style(
            "display", face="major", color=content.accent, bold=True, line_spacing=0.9
        ),
    )
    block.text(
        content.quote,
        canvas.style("title", face="major", scale=_QUOTE_SCALE, italic=True, line_spacing=1.15),
        gap=canvas.baseline * 2,
    )
    block.text(
        content.attribution,
        canvas.style("heading", color="dk2"),
        gap=canvas.baseline * 3,
    )
    block.place(region, valign="middle")
