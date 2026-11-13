"""Base slide → the v2 creative-mode slide that v2's free-layout code draws and checks.

**Why an adapter, and not `renderer.render_deck`.** `render_deck`'s first statement is
`require_safe_to_render`, which runs the A5 framing linter and the A2 numeric linter over
the deck. A base deck has no claims, so every sentence would be framing, and any framing
sentence carrying a number would block the render. That guard is correct for v2 and must
not be loosened (V10), so the studio does not call it. Instead it does what
`render/draft.py` already does: it calls v2's lower-level functions directly,
`free_layout.render_free_layout` (which runs `free_layout_qa.check_free_layout` itself and
refuses to draw a failing layout) and `free_layout_qa.check_free_layout`. No v2 file is
modified and no v2 check is weakened: the layout QA (overflow, safe area, overlap, minimum
size, contrast, hidden text) runs on every base slide exactly as on a creative v2 slide.

**The mapping.** A v2 `Slide` with `component=FREE_LAYOUT_COMPONENT` and the base slide's
own `FreeLayout` object, whose blocks are:

* base `text` → v2 `framing` block with the same id and text (`slot` = the block id). A
  framing block is v2's citation-free text kind; nothing in the drawing path lints it.
* base `chart` → v2 `chart` block whose `ChartSpec` is built with
  `ChartSpec.model_construct(chart_type=c.chart_type, title=c.title,
  categories=list(c.categories), series=list(c.series), x_axis_label=c.x_axis_label,
  y_axis_label=c.y_axis_label, source_citations=[])`. Pass the attribute values (the real
  `ChartSeries` objects), **not** `c.model_dump()`: v2's `ChartSpec` after-validator still
  runs when the v2 `Block` is built, and with dumped dicts in `series` it crashes
  (`len(dict.values)`; found while writing this scaffold).
* base `figure` → v2 `figure` block whose `FigureRef` is built with
  `FigureRef.model_construct(asset_id=..., caption=..., citation=None)`.
* base `icon` → v2 `icon` block with the same `IconRef` (it has no citation to omit).

`model_construct` skips validation, and that is the one deliberate exemption here: v2's
`ChartSpec` and `FigureRef` require a citation (A1), which the base does not have. The
constructed objects are passed only to drawing code that never reads the citation of a
figure and draws no source line for an empty `source_citations` (`charts.source_line([])`
is `""`). They are never serialised, stored or handed to an audit function. With no claim
on the face, `free_layout.source_text_to_draw` returns `""`, so no slide source line is
drawn either. Speaker notes are not mapped: they are plain text, written by
`render.write_notes`.
"""

from __future__ import annotations

from autodeck.design.free_layout_qa import FreeLayoutFinding, check_free_layout
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir import models as v2
from autodeck.studio.errors import MissingLayoutError
from autodeck.studio.models import Block, DeckArtifact, Slide

MISSING_LAYOUT = "missing_layout"
"""`FreeLayoutFinding.check` for a slide that has no layout yet (not a v2 check name)."""

NARRATIVE_ROLE = "base"
"""v2 `Slide.narrative_role` is required; base slides have no such concept."""


def to_render_block(block: Block) -> v2.Block:
    """The v2 block that draws `block` (mapping in the module docstring).

    The v2 block's `id` and `slot` are both `block.id`. `source_note` is dropped: it is
    never drawn in Phase 0. Pure; returns a new object, `block` is not modified.
    """
    if block.kind == "text":
        return v2.Block(id=block.id, slot=block.id, kind="framing", text=block.text)
    if block.kind == "chart":
        c = block.chart
        assert c is not None
        spec = v2.ChartSpec.model_construct(
            chart_type=c.chart_type,
            title=c.title,
            categories=list(c.categories),
            series=list(c.series),
            x_axis_label=c.x_axis_label,
            y_axis_label=c.y_axis_label,
            source_citations=[],
        )
        return v2.Block(id=block.id, slot=block.id, kind="chart", chart=spec)
    if block.kind == "figure":
        f = block.figure
        assert f is not None
        ref = v2.FigureRef.model_construct(
            asset_id=f.asset_id, caption=f.caption, citation=None
        )
        return v2.Block(id=block.id, slot=block.id, kind="figure", figure=ref)
    return v2.Block(id=block.id, slot=block.id, kind="icon", icon=block.icon)


def to_render_slide(slide: Slide) -> v2.Slide:
    """The v2 creative-mode slide that draws `slide`.

    `id` = `slide.id`, `narrative_role` = `NARRATIVE_ROLE`, `component` =
    `v2.FREE_LAYOUT_COMPONENT`, `blocks` = `to_render_block` of each block in order,
    `layout` = `slide.layout` (the same object), `speaker_notes` = `[]`, every other field
    at its v2 default. Constructed normally (not `model_construct`), so v2's own slide
    validators also run; a base slide that passed its own validators always passes them.

    Raises:
        MissingLayoutError: `slide.layout` is None.
    """
    if slide.layout is None:
        raise MissingLayoutError(f"slide {slide.id!r} has no layout yet")
    return v2.Slide(
        id=slide.id,
        narrative_role=NARRATIVE_ROLE,
        component=v2.FREE_LAYOUT_COMPONENT,
        blocks=[to_render_block(b) for b in slide.blocks],
        layout=slide.layout,
        speaker_notes=[],
    )


def check_slide(slide: Slide, tokens: DesignTokens) -> list[FreeLayoutFinding]:
    """v2's free-layout QA on one base slide: `check_free_layout(to_render_slide(slide),
    tokens)`. `[]` when the layout holds.

    A slide with no layout returns one finding, `FreeLayoutFinding(slide.id, "",
    MISSING_LAYOUT, "slide has no layout yet")`, instead of raising, so a deck-wide check
    can report every problem at once.
    """
    if slide.layout is None:
        return [FreeLayoutFinding(slide.id, "", MISSING_LAYOUT, "slide has no layout yet")]
    return check_free_layout(to_render_slide(slide), tokens)


def check_deck(deck: DeckArtifact, tokens: DesignTokens) -> dict[str, list[FreeLayoutFinding]]:
    """`check_slide` for every slide; returns only slides with findings, keyed by slide id,
    in deck order. `{}` when every slide holds."""
    report: dict[str, list[FreeLayoutFinding]] = {}
    for slide in deck.slides:
        findings = check_slide(slide, tokens)
        if findings:
            report[slide.id] = findings
    return report
