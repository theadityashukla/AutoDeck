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
from autodeck.design.components.renderers.big_number import BigNumberContent
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
