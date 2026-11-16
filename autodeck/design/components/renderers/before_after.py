"""`before_after` — two labelled states side by side.

The narrative job: show how something has changed, by placing the old state and the new
state next to each other for direct comparison. Unlike `two_column_compare`, which is about
recommendations, this component is about transformation or evolution.

The structure is two columns with labels at the top and content below, centred vertically
so the two states read as a matched pair. Each side is its own stack, and both are placed
in boxes of the same height so they stay aligned.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas, Frame, Stack

_PANEL_PADDING = 22.0
_RULE_WIDTH = 40.0
_RULE_THICKNESS = 2.5


@dataclass
class BeforeAfterContent:
    """The slots this component fills."""

    headline: str
    """The talking header — carries the argument (D12)."""
    before_label: str
    """Label for the before/initial state."""
    before_text: str
    """Description of the before state."""
    after_label: str
    """Label for the after/new state."""
    after_text: str
    """Description of the after state."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: BeforeAfterContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, _caption = frame.body_and_caption()

    # Headline block
    headline = frame.stack("before_after headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    body_area = headline.place(body, gutter=canvas.baseline * 5)

    # Split into before and after columns
    before_area, after_area = body_area.split_columns(2, canvas.gutter * 1.5)

    # Build before stack
    before_stack = _state_stack(
        frame, before_area.width, content.before_label, content.before_text
    )

    # Build after stack
    after_stack = _state_stack(frame, after_area.width, content.after_label, content.after_text)

    # Place both stacks with equal height so they align
    panel_height = max(before_stack.height, after_stack.height) + _PANEL_PADDING * 2

    before_panel = before_area.reserve(
        panel_height, valign="middle", what="before_after before"
    )
    frame.rect(before_panel, fill="accent6", fill_brightness=0.94)
    before_stack.place(before_panel.pad(_PANEL_PADDING))

    after_panel = after_area.reserve(panel_height, valign="middle", what="before_after after")
    frame.rect(after_panel, fill=content.accent, fill_brightness=0.88)
    after_stack.place(after_panel.pad(_PANEL_PADDING))


def _state_stack(frame: Frame, width: float, label: str, text: str) -> Stack:
    """One state: label, rule, and description text."""
    canvas = frame.canvas
    stack = frame.stack("before_after state", width - _PANEL_PADDING * 2)
    stack.text(label, canvas.style("heading", bold=True))
    stack.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color="accent6",
        gap=canvas.baseline * 1.5,
    )
    stack.text(text, canvas.style("body", color="dk2"), gap=canvas.baseline * 2)
    return stack
