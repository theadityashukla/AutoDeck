"""The golden-preview loop (D5, task 3a.4): render every registered component to a PNG.

`catalog.components_missing_previews()` could already say which components have never had
a golden PNG committed; nothing before this module closed that gap. This is the mechanism,
and it is written to be run again for components 6-15 by a cheaper model without
reconstructing any of this reasoning: register the component (as every component already
must, per `catalog.py`), add one line to `EXAMPLES` below, then run

    uv run autodeck components preview

which regenerates *every* registered component's preview, not just the new one — so a
`layout_kit` change that shifts every component's geometry shows up as a diff across every
PNG, not a stale subset of them.

## The render path is the production path

Each preview is built exactly the way a real deck would build that slide — `new_presentation`,
a real `Canvas` over real `DesignTokens`, `catalog.renderer_for(name)` — then rendered
through `render.qa.libreoffice.render_pptx`, the same headless-LibreOffice pipeline
`budget_check.py` already uses. There is deliberately no second, hand-rolled render path
here: a preview loop that rendered its own way could pass while the real one failed.

## Why the example content lives here, not on each renderer

A renderer's own module (`renderers/quote.py`) knows how to draw a quote; it has no
opinion about what a *representative* quote says, and it should not need one to be
imported or tested. That content is a property of the gallery, not of the component, so it
belongs in one dict here rather than scattered across fifteen modules — which is also what
lets `render_previews()` regenerate all of them from one loop instead of importing each
renderer's own "example" by hand.

Owning phase: 3a (task 3a.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodeck.design.components import catalog
from autodeck.design.components.renderers.agenda import AgendaContent
from autodeck.design.components.renderers.before_after import BeforeAfterContent
from autodeck.design.components.renderers.big_number import BigNumberContent
from autodeck.design.components.renderers.bullets_supporting import BulletsSupportingContent
from autodeck.design.components.renderers.callout_takeaway import CalloutTakeawayContent
from autodeck.design.components.renderers.closing_cta import ClosingCtaContent
from autodeck.design.components.renderers.data_card_grid import (
    DataCard,
    DataCardGridContent,
)
from autodeck.design.components.renderers.evidence_with_figure import (
    EvidenceWithFigureContent,
)
from autodeck.design.components.renderers.quote import QuoteContent
from autodeck.design.components.renderers.section_divider import SectionDividerContent
from autodeck.design.components.renderers.title import TitleContent
from autodeck.design.components.renderers.two_column_compare import (
    ComparisonColumn,
    TwoColumnCompareContent,
)
from autodeck.design.layout_kit import Canvas
from autodeck.design.theme.master_builder import new_presentation, save_themed
from autodeck.design.theme.tokens import DesignTokens
from autodeck.render.qa.libreoffice import check_render_fonts, render_pptx

_BLANK_LAYOUT = 6

#: One representative content object per registered component — real copy, not
#: `"lorem ipsum"`, because a golden PNG is a visual judgement about actual text (D5) and a
#: placeholder cannot stand in for that judgement. Keyed by the name each was `register()`ed
#: under; `render_previews()` fails loudly rather than silently skipping a component whose
#: entry is missing here.
#:
#: Adding component eleven: register it in `catalog.py`, then add its entry here. Nothing
#: else in this module names a component.
EXAMPLES: dict[str, Any] = {
    "big_number": BigNumberContent(
        headline="Kernel rewrite cut inference cost faster than headcount ever could",
        figure="62.9%",
        figure_label="increase in training throughput",
        support=(
            "Measured on a single A100-80GB node across the full benchmark suite, with no "
            "change to model architecture or batch composition."
        ),
        source="Source: Kaplan et al. 2024, p.4 — figures re-verified at validation.",
        accent="accent1",
        # Each point is capped to one line by the `with_supporting_points` variant's own
        # geometry (narrower than the full-width slots above) — this example was the first
        # thing this module's own overflow test caught, and it is kept short on purpose so
        # the gallery demonstrates a component that fits, not one that quietly does not.
        supporting_points=[
            "Median cost per token fell to $0.42.",
            "No regression on any benchmark.",
            "Only the attention kernel changed.",
        ],
    ),
    "two_column_compare": TwoColumnCompareContent(
        headline="Rewriting the kernel beats buying capacity on every axis that matters",
        left=ComparisonColumn(
            title="Add hardware",
            accent="accent6",
            points=[
                "Cost scales linearly with load.",
                "Six to nine weeks to any capacity.",
                "Leaves the inefficiency in place.",
                "No benefit to other teams.",
            ],
        ),
        right=ComparisonColumn(
            title="Rewrite the kernel",
            accent="accent2",
            emphasised=True,
            points=[
                "One-off cost; savings compound.",
                "Three weeks on the existing fleet.",
                "Removes the inefficiency outright.",
                "Every team on the runtime gains.",
            ],
        ),
        source="Source: internal benchmark, Q3 2025 — see audit report for derivations.",
    ),
    "quote": QuoteContent(
        # 3a.4 chose this headline to stay clear of the wrap boundary, because
        # `budgets.py` then measured wrapping against the REGULAR-weight font file
        # whatever `TextStyle.bold` said: a bold headline within a few percent of its box
        # width wrapped to one more line than predicted, and the accent rule struck
        # through the second line in the committed PNG. That author reported the gap
        # upstream instead of quietly working around it, which is why 3a.6 exists.
        #
        # 3a.6 checked whether the fix lets that copy come back, because the example that
        # nearly broke would be the best regression fixture this gallery has. It does not,
        # and the reason is worth keeping: the boundary copy is now *honestly* measurable
        # and the honest measurement says the slide will not hold it. Reconstructed into
        # the same band (842.6pt of Inter Display Regular at 32pt against an 852pt box —
        # 1.1% of headroom, beside the 839.8pt/1.4% case 3a.4 reported; 890.4pt bold), it
        # correctly predicts TWO lines, and a second headline line costs 44.2pt where this
        # component has 26.1pt to spare: the quote block needs 297.5pt and is left 279.5pt.
        # `render()` raises `LayoutOverflowError`, which is the rule working (§6.7 —
        # nothing shrinks text to fit), not a measurement that is still wrong. Any two-line
        # headline does this, so there is no danger-band copy to restore here; the fixture
        # now lives in `tests/test_budget_check.py` where it can fail without a component
        # having to be over-full to hold it.
        #
        # Worth recording separately, because it is a hole rather than a design choice:
        # `check_overflow` reports NO findings for that copy. Each slot's budget is derived
        # assuming its SIBLINGS take their one-line floor (see `_quote_slots`), so the
        # headline may claim four lines and the quote block three, and nothing checks that
        # both can be true at once. The deterministic gate passes content the renderer then
        # refuses — the same "compares a prediction against itself" family as the defect
        # 3a.6 fixed, one level up. Reported, not fixed here.
        headline="Clients notice the difference immediately",
        quote=(
            "This is the first vendor deck where I did not have to fact-check a single "
            "number myself before sending it to the board."
        ),
        attribution="VP of Strategy, Fortune 500 client",
        source="Source: client debrief call, 12 Mar 2026 — quoted with permission.",
        accent="accent3",
    ),
    "bullets_supporting": BulletsSupportingContent(
        headline="Three changes account for nearly all of the improvement",
        points=[
            "The attention kernel rewrite removed the single largest source of latency.",
            "Batch composition now adapts to load instead of using a fixed size.",
            "A caching layer in front of the tokenizer cut preprocessing time in half.",
        ],
        source="Source: internal benchmark, Q3 2025 — see audit report for derivations.",
        accent="accent2",
    ),
    "callout_takeaway": CalloutTakeawayContent(
        takeaway="The kernel rewrite pays for itself in under six weeks.",
        label="Takeaway",
        support="Every week after that is pure margin, compounding as load grows.",
        source="Source: internal benchmark, Q3 2025 — see audit report for derivations.",
        accent="accent4",
    ),
    "title": TitleContent(
        title="Kernel Rewrite: Delivering More Value, Less Cost",
        subtitle="Three weeks to six figures of savings",
        presenter="Engineering leadership",
        date="Q3 2025",
        accent="accent1",
    ),
    "section_divider": SectionDividerContent(
        section_number="3",
        section_name="The Technical Solution",
        accent="accent3",
    ),
    "agenda": AgendaContent(
        headline="Three sessions outline the full analysis",
        items=[
            "Where the original architecture left headroom — and why it stayed empty.",
            "The rewrite: what changed, and what stayed locked in place.",
            "The impact by the numbers: throughput, cost, and time-to-revenue.",
        ],
        accent="accent2",
    ),
    "closing_cta": ClosingCtaContent(
        headline="Ready to move forward",
        cta=(
            "Contact the engineering team to discuss implementation. "
            "We're available to walk through the architecture and timeline."
        ),
        accent="accent1",
    ),
    "before_after": BeforeAfterContent(
        headline="The old way cost more and left capacity unused",
        before_label="Add hardware",
        before_text=(
            "Cost scales linearly. Capacity locked to batch size. No efficiency gain elsewhere."
        ),
        after_label="Rewrite the kernel",
        after_text=(
            "One-time cost. Scales with load. Every downstream team benefits immediately."
        ),
        accent="accent2",
    ),
    "evidence_with_figure": EvidenceWithFigureContent(
        headline="The numbers prove the investment was worth it",
        supporting_text=(
            "Measured across the full Q3 benchmark suite on real workloads. "
            "No architectural change, no model shift — only the kernel "
            "implementation changed."
        ),
        figure="[Figure: throughput graph showing 62.9% gain]",
        source="Source: internal measurement, verified at validation.",
        accent="accent3",
    ),
    "data_card_grid": DataCardGridContent(
        headline="Four metrics that matter",
        cards=[
            DataCard(label="Throughput gain", value="62.9%"),
            DataCard(label="Cost per token", value="$0.42"),
            DataCard(label="Time to deploy", value="3 weeks"),
            DataCard(label="Teams affected", value="8+"),
        ],
        accent="accent1",
    ),
}


@dataclass(frozen=True)
class ComponentPreview:
    """What rendering one component's preview produced."""

    name: str
    png: Path
    font_major: str
    font_minor: str


def render_previews(
    tokens: DesignTokens,
    *,
    only: tuple[str, ...] | None = None,
    out_dir: Path | None = None,
) -> list[ComponentPreview]:
    """Render every registered component (or just `only`) to its golden preview PNG.

    Regenerates unconditionally — there is no "already exists, skip" shortcut — because the
    point of running this after a `layout_kit` change is to see every component move at
    once (module docstring), not a stale subset that happened not to be touched. Writes into
    `catalog.PREVIEW_DIR` by default, which is exactly where every `register()`'s `preview=`
    path points, so a full run of this function is what turns
    `catalog.components_missing_previews()` from non-empty to empty.

    Fonts are checked once, before any component is built, so a run either produces
    trustworthy previews for all of them or fails before wasting time on any (B11).

    Raises:
        FontSubstitutionRisk: a font `tokens` declares is not installed here.
        UnknownComponentError: `only` names something not in the registry.
        KeyError: a registered component has no entry in `EXAMPLES`.
    """
    check_render_fonts(tokens)

    out_dir = out_dir or catalog.PREVIEW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    names = only or tuple(catalog.known_components())

    return [_render_one(name, tokens, out_dir) for name in names]


def _render_one(name: str, tokens: DesignTokens, out_dir: Path) -> ComponentPreview:
    renderer = catalog.renderer_for(name)  # raises UnknownComponentError for a bad name
    if name not in EXAMPLES:
        raise KeyError(
            f"{name!r} is registered but has no example content in "
            "autodeck/design/components/preview.py's EXAMPLES — add one before rendering "
            "its preview."
        )

    presentation = new_presentation(tokens)
    canvas = Canvas(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    renderer(slide, canvas, EXAMPLES[name])

    # A scratch file, not a preview: built and rendered in `out_dir` (the same idiom
    # `budget_check.render_measurement_slide` uses) and deleted once the PNG is out.
    pptx_path = out_dir / f"_{name}.pptx"
    save_themed(presentation, tokens, pptx_path)
    try:
        result = render_pptx(pptx_path, out_dir, tokens)
    finally:
        pptx_path.unlink(missing_ok=True)

    target = out_dir / f"{name}.png"
    result.images[0].replace(target)

    return ComponentPreview(
        name=name,
        png=target,
        font_major=tokens.typography.major,
        font_minor=tokens.typography.minor,
    )


def write_provenance(previews: list[ComponentPreview], path: Path) -> Path:
    """Record which font family each committed preview was actually rendered with.

    `fonts/README.md` requires preview output to say which face rendered: this container
    has Inter, not Aptos, and a PNG that does not say so is a preview of something that is
    not the deliverable (B11). Mirrors `spikes.write_provenance`'s sidecar one level down,
    with one difference — it merges into whatever is already at `path` rather than
    overwriting it, so a `--only` run updates just its own entries and leaves the rest of
    the gallery's provenance intact.
    """
    path = Path(path)
    existing: dict[str, Any] = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8")).get("components", {})

    existing.update(
        {
            preview.name: {"font_major": preview.font_major, "font_minor": preview.font_minor}
            for preview in previews
        }
    )
    payload = {
        "note": (
            "Fonts recorded per component. A visual judgement is only valid for the "
            "family listed here; Aptos is the deliverable target (B11)."
        ),
        "components": dict(sorted(existing.items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
