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

from autodeck.design.layout_kit import Canvas

_RULE_WIDTH = 64.0
_RULE_THICKNESS = 3.0


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

    points = frame.stack("bullets_supporting points", region.width).items(
        content.points,
        canvas.style("body", color="dk2"),
        row_gap=canvas.baseline * 3,
        marker_style=canvas.style("body", color=content.accent, bold=True),
    )
    points.place(region, valign="top")
