"""`closing_cta` — headline and a short call to action.

The narrative job: end the deck with a clear next step. A closing call-to-action tells the
audience what to do now that they have seen the argument — sign up, contact someone,
schedule a meeting, whatever the appropriate action is.

The structure is headline-and-body: a headline block framing the action, then a short block
of text with the call to action itself. The call-to-action text is set in a tinted panel to
give it visual weight and make it distinct from supporting argument.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

_RULE_WIDTH = 48.0
_RULE_THICKNESS = 3.0
_PANEL_PADDING = 32.0


@dataclass
class ClosingCtaContent:
    """The slots this component fills."""

    headline: str
    """The talking header — frames the call to action (D12)."""
    cta: str
    """The call to action text — what the audience should do next."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: ClosingCtaContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, _caption = frame.body_and_caption()

    # Headline block
    headline = frame.stack("closing_cta headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    headline.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    region = headline.place(body, gutter=canvas.baseline * 4)

    # CTA block with tinted background
    frame.rect(
        region.resize(
            height=canvas.measure(
                content.cta,
                region.width - _PANEL_PADDING * 2,
                canvas.style("heading", face="major", bold=True),
            )
            + _PANEL_PADDING * 2
        ),
        fill=content.accent,
        fill_brightness=0.9,
    )

    cta_stack = frame.stack("closing_cta cta", region.width - _PANEL_PADDING * 2)
    cta_stack.text(
        content.cta,
        canvas.style("heading", face="major", bold=True),
    )
    cta_stack.place(region.pad(_PANEL_PADDING), valign="middle")
