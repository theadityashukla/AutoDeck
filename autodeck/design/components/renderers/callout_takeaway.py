"""`callout_takeaway` — one sentence, held up alone.

The narrative job is the simplest of the fifteen (task 3a.4 picked it as the third
component on purpose, to find out whether the kit makes an easy component easy): a single
statement is the whole point of the slide, set inside a tinted panel with a small eyebrow
label above it and, optionally, one line of elaboration below.

The design job is correspondingly small — one `Stack`, centred in a padded panel, no
headline block above it the way every other component so far has one. That asymmetry with
`quote`/`bullets_supporting`/`big_number` (all headline-then-body) is deliberate rather
than a shortcut: a takeaway slide's whole argument *is* the takeaway, so a separate headline
above it would either repeat the takeaway or dilute it. See the phase handover for whether
that reads as the right call once it is next to the other fourteen.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

#: Panel inset on all four sides. Named the same way `two_column_compare._PANEL_PADDING`
#: is, and kept separate from it rather than shared: the two panels answer different
#: questions (a comparison column's chrome vs. a whole-slide callout's) and a client's
#: token set may reasonably want them to move independently later.
_PANEL_PADDING = 40.0


@dataclass
class CalloutTakeawayContent:
    """The slots this component fills."""

    takeaway: str
    """The one sentence the slide exists to deliver."""
    label: str = "Takeaway"
    """A short eyebrow tag above the takeaway. Kept short on purpose (catalog caps it to
    one line) — this is a tag, not a second headline."""
    support: str = ""
    """One optional line of elaboration under the takeaway."""
    source: str = ""
    """Rendered from the block's citation; the audit report is the authority."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: CalloutTakeawayContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()
    frame.caption(caption, content.source)

    frame.rect(body, fill=content.accent, fill_brightness=0.9)

    stack = frame.stack("callout_takeaway", body.width - _PANEL_PADDING * 2)
    stack.text(content.label, canvas.style("caption", color=content.accent, bold=True))
    stack.text(
        content.takeaway,
        canvas.style("title", face="major", bold=True, line_spacing=1.15),
        gap=canvas.baseline * 2,
    )
    if content.support:
        stack.text(content.support, canvas.style("body", color="dk2"), gap=canvas.baseline * 3)
    stack.place(body.pad(_PANEL_PADDING), valign="middle")
