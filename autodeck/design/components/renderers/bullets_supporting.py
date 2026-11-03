"""`bullets_supporting` — a headline argument, proven by three to five short claims.

The narrative job (plan §6.6): the headline states the point, and a short flat list of
supporting claims is the evidence for it — the single-column counterpart to
`two_column_compare`'s two matched columns. There is no comparison here and nothing to keep
level against a partner column, so the design job is the smaller half of that component:
one headline block, one bulleted `Stack`, nothing else.

Each point is meant to be a short, scannable phrase — a claim, not a paragraph — so it is
capped at a small number of lines the same way `two_column_compare`'s `point` slots are
(see `catalog._two_column_compare_slots`'s corrected docstring for why that cap is about
legibility, not row parity, a reasoning that carries over unchanged since there is no
second column here to keep parity with in the first place).

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pptx.slide import Slide

from autodeck.design.layout_kit import Box, Canvas

_RULE_WIDTH = 64.0
_RULE_THICKNESS = 3.0

_MARKER = "•"
"""A bullet, not the em dash every list used to carry; set bold in the accent colour."""

_MIN_GAP = 3
_MAX_GAP = 7
"""Row gap bounds, in baselines (18pt and 42pt on the dev theme)."""

_TAIL_SHARE = 1.0
"""How much of one gap's worth of free space stays below the last row."""

_DIVIDER_COLOR = "accent6"
_DIVIDER_TINT = 0.55
"""The hairline between rows: the palette's neutral, decoration only (it carries no text)."""


@dataclass
class BulletsSupportingContent:
    """The slots this component fills."""

    headline: str
    """The talking header — the argument the points below exist to prove (D12)."""
    points: list[str] = field(default_factory=list)
    """Three to five short supporting claims, most-important first."""
    source: str = ""
    """Rendered from the block's citation; the audit report is the authority."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: BulletsSupportingContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, caption = frame.body_and_caption()
    frame.caption(caption, content.source)

    headline = frame.stack("bullets_supporting headline", body.width)
    headline.text(content.headline, canvas.style("title", face="major", bold=True))
    headline.rule(
        width=_RULE_WIDTH,
        thickness=_RULE_THICKNESS,
        color=content.accent,
        gap=canvas.baseline * 3,
    )
    region = headline.place(body, gutter=canvas.baseline * 4)

    # Rows open up with the free space (design review, 2026-10-13): a fixed 18pt gap left
    # four points huddled under the headline and the lower half of the slide empty. The gap
    # grows from `MIN_GAP` to `MAX_GAP` baselines; past that, extra space stays below.
    texts = [p for p in content.points if p]
    body_style = canvas.style("body", color="dk1")
    one_line = canvas.measure("Hg", region.width, body_style)
    free = region.height - one_line * max(len(texts), 1)
    gap = canvas.baseline * _MIN_GAP
    if len(texts) > 1:
        gap = min(
            max(free / (len(texts) - 1 + _TAIL_SHARE), canvas.baseline * _MIN_GAP),
            canvas.baseline * _MAX_GAP,
        )
    points = frame.stack("bullets_supporting points", region.width).items(
        texts,
        body_style,
        row_gap=gap,
        marker=_MARKER,
        marker_style=canvas.style("body", color=content.accent, bold=True),
    )
    points.place(region, valign="top")

    # A hairline between rows gives the list its structure without a box around it.
    for upper, lower in zip(points.placed_boxes, points.placed_boxes[1:], strict=False):
        middle = (upper.bottom + lower.y) / 2
        frame.rect(
            Box(upper.x, middle, upper.width, 0.75),
            fill=_DIVIDER_COLOR,
            fill_brightness=_DIVIDER_TINT,
        )
