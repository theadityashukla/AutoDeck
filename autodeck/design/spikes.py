"""GATE 0 spike artifacts: theme (0.4), components (0.5), icon (0.6).

Each function builds a PPTX the owner opens **in PowerPoint** — that is the gate criterion,
and it is not something a report can stand in for. Every render also records which font
family it actually used, because a preview in a substituted face proves nothing (B11).

Owning phase: 0.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from autodeck.design.components.renderers import big_number, two_column_compare
from autodeck.design.components.renderers.big_number import BigNumberContent
from autodeck.design.components.renderers.two_column_compare import (
    ComparisonColumn,
    TwoColumnCompareContent,
)
from autodeck.design.draw import add_rect, add_text
from autodeck.design.icons.custgeom import place_icon
from autodeck.design.icons.library import icon_names, load_icon
from autodeck.design.layout_kit import Box, Canvas
from autodeck.design.theme.master_builder import new_presentation, save_themed
from autodeck.design.theme.tokens import DesignTokens

BLANK_LAYOUT = 6


@dataclass(frozen=True)
class SpikeArtifact:
    """One built file plus the provenance a reviewer needs."""

    name: str
    pptx: Path
    font_major: str
    font_minor: str
    build_seconds: float

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "pptx": str(self.pptx),
            "font_major": self.font_major,
            "font_minor": self.font_minor,
            "build_seconds": round(self.build_seconds, 3),
        }


def _artifact(name: str, path: Path, tokens: DesignTokens, seconds: float) -> SpikeArtifact:
    return SpikeArtifact(
        name=name,
        pptx=path,
        font_major=tokens.typography.major,
        font_minor=tokens.typography.minor,
        build_seconds=seconds,
    )


# ---------------------------------------------------------------------------
# 0.4 — theme
# ---------------------------------------------------------------------------


def build_theme_spike(tokens: DesignTokens, output: Path) -> SpikeArtifact:
    """A deck for confirming the theme in PowerPoint's own UI.

    Slide 1 states what to check. Slide 2 is a palette board: every accent as a themed
    shape, so the owner can select one, open the colour picker, and see it sitting in the
    theme row rather than under "recent colours".
    """
    started = time.perf_counter()
    presentation = new_presentation(tokens)
    canvas = Canvas(tokens)
    blank = presentation.slide_layouts[BLANK_LAYOUT]

    intro = presentation.slides.add_slide(blank)
    region = canvas.content

    title_style = canvas.style("title", face="major", color="dk1", bold=True)
    title = f"{tokens.name}\ntheme check"
    title_box = canvas.fit(title, region, title_style)
    add_text(intro, title_box, title, title_style)

    _, region = region.split_top(title_box.height, gutter=canvas.gutter)
    body_style = canvas.style("body", color="dk2", space_after=10.0)
    checks = "\n".join(
        [
            "1. Design tab -> Variants: the palette on the next slide should appear as "
            "this deck's theme colours.",
            "2. Insert a new slide by hand: it should inherit these fonts and colours.",
            "3. Select any swatch, open the fill colour picker, and confirm the swatch "
            "sits in the Theme Colors row rather than under Recent Colors.",
            f"Headings are set in {tokens.typography.major}; body in "
            f"{tokens.typography.minor}.",
        ]
    )
    add_text(intro, canvas.fit(checks, region, body_style), checks, body_style)

    board = presentation.slides.add_slide(blank)
    _palette_board(board, canvas, tokens)

    path = save_themed(presentation, tokens, output)
    return _artifact("theme", path, tokens, time.perf_counter() - started)


def _palette_board(slide, canvas: Canvas, tokens: DesignTokens) -> None:
    region = canvas.content
    title_style = canvas.style("heading", face="major", color="dk1", bold=True)
    title_box = canvas.fit("Theme palette", region, title_style)
    add_text(slide, title_box, "Theme palette", title_style)
    _, region = region.split_top(title_box.height, gutter=canvas.gutter)

    slots = ["accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]
    swatches = region.split_columns(len(slots), canvas.gutter * 0.75)
    scheme = tokens.palette.as_scheme()

    for slot, cell in zip(slots, swatches, strict=True):
        chip, caption = cell.split_top(cell.height * 0.62, gutter=canvas.baseline * 2)
        add_rect(slide, chip, fill=slot)
        add_text(
            slide, caption, f"{slot}\n#{scheme[slot]}", canvas.style("caption", color="dk2")
        )


# ---------------------------------------------------------------------------
# 0.5 — components
# ---------------------------------------------------------------------------


def build_component_spike(tokens: DesignTokens, output: Path) -> SpikeArtifact:
    """`big_number` and `two_column_compare`, rendered to the visual bar."""
    started = time.perf_counter()
    presentation = new_presentation(tokens)
    canvas = Canvas(tokens)
    blank = presentation.slide_layouts[BLANK_LAYOUT]

    big_number.render(
        presentation.slides.add_slide(blank),
        canvas,
        BigNumberContent(
            headline="Kernel rewrite cut inference cost faster than headcount ever could",
            figure="62.9%",
            figure_label="increase in training throughput",
            support=(
                "Measured on a single A100-80GB node across the full benchmark suite, "
                "with no change to model architecture or batch composition."
            ),
            source="Source: Kaplan et al. 2024, p.4 — figures re-verified at validation.",
            accent="accent1",
            supporting_points=[
                "Median inference cost fell to $0.42 per million tokens.",
                "No regression on any quality benchmark in the suite.",
                "Change is confined to the attention kernel; the training loop is untouched.",
            ],
        ),
    )

    two_column_compare.render(
        presentation.slides.add_slide(blank),
        canvas,
        TwoColumnCompareContent(
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
    )

    path = save_themed(presentation, tokens, output)
    return _artifact("components", path, tokens, time.perf_counter() - started)


# ---------------------------------------------------------------------------
# 0.6 — icon
# ---------------------------------------------------------------------------


def build_icon_spike(tokens: DesignTokens, output: Path) -> SpikeArtifact:
    """Library SVGs converted to DrawingML `custGeom` and placed as native shapes."""
    started = time.perf_counter()
    presentation = new_presentation(tokens)
    canvas = Canvas(tokens)
    blank = presentation.slide_layouts[BLANK_LAYOUT]

    slide = presentation.slides.add_slide(blank)
    region = canvas.content

    title_style = canvas.style("title", face="major", color="dk1", bold=True)
    title = "Icons as native vector shapes"
    title_box = canvas.fit(title, region, title_style)
    add_text(slide, title_box, title, title_style)
    _, region = region.split_top(title_box.height, gutter=canvas.baseline * 4)

    body_style = canvas.style("body", color="dk2", space_after=8.0)
    checks = "\n".join(
        [
            "Click any icon below. It should select as a shape, not as a picture.",
            "Drag a corner handle: the strokes should stay crisp at any size.",
            "Open the shape outline colour picker: the colour should sit in the Theme "
            "Colors row, and changing the theme variant should recolour the icon.",
        ]
    )
    instructions = canvas.fit(checks, region, body_style)
    add_text(slide, instructions, checks, body_style)
    _, region = region.split_top(instructions.height, gutter=canvas.baseline * 6)

    names = icon_names()[:5]
    accents = ["accent1", "accent2", "accent3", "accent4", "accent5"]
    cells = region.split_columns(len(names), canvas.gutter)

    for name, accent, cell in zip(names, accents, cells, strict=True):
        glyph_area, caption = cell.split_top(84.0, gutter=canvas.baseline * 3)
        square = Box(glyph_area.center_x - 36, glyph_area.y, 72, 72)
        place_icon(slide, square, load_icon(name), color=accent, stroke_width=2.6)  # type: ignore[arg-type]
        add_text(slide, caption, name, canvas.style("caption", color="dk2", align="center"))

    path = save_themed(presentation, tokens, output)
    return _artifact("icon", path, tokens, time.perf_counter() - started)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_provenance(artifacts: list[SpikeArtifact], path: Path) -> Path:
    """Record which fonts each artifact was actually built with.

    The sidecar exists so nobody has to remember whether a given PNG was rendered in Aptos
    or in the container's stand-in. A visual verdict is only meaningful against a known
    face.
    """
    payload = {
        "note": (
            "Fonts recorded per artifact. A visual judgement is only valid for the family "
            "listed here; Aptos is the deliverable target (B11)."
        ),
        "artifacts": [artifact.as_dict() for artifact in artifacts],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
