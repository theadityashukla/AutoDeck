"""`data_card_grid` — a grid of small data cards, each with a label and value.

The narrative job: present a set of related metrics or data points in a grid layout, where
each card is self-contained and holds a label (what is being measured) and a value (the
result).

The structure is a grid of independently-sized cards. Each card is a small stack with the
value set large (like `big_number`'s figure, but smaller and in context) and the label
below it. Cards are separated by uniform gutters and contained in a frame or panel.

This component is the first to use Box.grid() rather than the headline-and-body pattern,
because the geometry is genuinely grid-like: rows and columns of equal-sized cells, not
a hierarchy of headline over body.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

#: The figure is set this many times the title size — smaller than big_number's 2.0 because
#: there are multiple figures in a grid and they need to fit without overwhelming the slide.
_VALUE_SCALE = 1.5

#: Padding inside each card around the value and label.
_CARD_PADDING = 16.0


@dataclass
class DataCard:
    """One card in the grid: a label and a value."""

    label: str
    """What is being measured."""
    value: str
    """The measurement result — pre-formatted, never computed."""


@dataclass
class DataCardGridContent:
    """The slots this component fills."""

    headline: str
    """The talking header — carries the argument (D12)."""
    cards: list[DataCard] = field(default_factory=list)
    """The data cards, typically four to six in a 2x2 or 2x3 grid."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: DataCardGridContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()

    # Headline block
    headline = frame.stack("data_card_grid headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    region = headline.place(body, gutter=canvas.baseline * 4)

    # Determine grid dimensions based on card count
    card_count = len(content.cards)
    if card_count <= 2:
        rows, cols = 1, card_count
    elif card_count <= 4:
        rows, cols = 2, 2
    elif card_count <= 6:
        rows, cols = 2, 3
    else:
        rows, cols = (card_count + 2) // 3, 3

    # Create grid of card boxes
    grid = region.grid(rows, cols, gutter=canvas.gutter)

    # Render each card
    for row_index, row_boxes in enumerate(grid):
        for col_index, card_box in enumerate(row_boxes):
            card_index = row_index * cols + col_index
            if card_index < len(content.cards):
                card = content.cards[card_index]
                _render_card(frame, card_box, card, canvas, content.accent)


def _render_card(
    frame,
    box,
    card: DataCard,
    canvas: Canvas,
    accent: str,
) -> None:
    """Render one card (value and label) inside its box."""
    # Background panel for the card
    frame.rect(box, fill=accent, fill_brightness=0.92)

    # Stack for value and label inside the card
    stack = frame.stack("data_card", box.width - _CARD_PADDING * 2)
    stack.text(
        card.value,
        canvas.style("title", face="major", scale=_VALUE_SCALE, bold=True, color=accent),
    )
    stack.text(
        card.label,
        canvas.style("caption", color="dk2"),
        gap=canvas.baseline,
    )
    stack.place(box.pad(_CARD_PADDING), valign="middle")
