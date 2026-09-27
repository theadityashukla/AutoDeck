"""IR → PPTX: the render stage (Phase 3b, task 3b.1).

SCAFFOLD (Opus). Bodies raising `NotImplementedError` are Sonnet's to implement to their
docstrings. Tests: `tests/test_renderer.py`.

What this module guarantees, regardless of what any component does:

1. **It is the render stage's gate.** `render_deck` calls
   `autodeck.pipeline.orchestrator.require_safe_to_render(deck)` before it creates a file.
   The Phase 2b review found that guard had no production caller at all — it was reached
   only from tests while GATE 2 re-implemented three of its four conditions. This is its
   first real call site, and the only one the render path has.
2. **No fact is dropped.** Every face block is placed in a content-dataclass field whose
   name equals its `slot`. A block with no such field raises `UnplacedBlockError` — a block
   the renderer silently does not draw is a deleted fact, however cleanly the slide looks.
3. **Content is copied, never composed.** A claim's `text`, a framing block's `text`, a chart
   and a diagram reach their component unchanged. Nothing is truncated, re-cased, rounded or
   reformatted here; a component that did so would be caught by
   `autodeck.audit.post_render`, which reads the rendered file back.
4. **Every PPTX slide is tagged with its IR slide id** (`cSld/@name = "autodeck:<id>"`), so
   the post-render pass attributes text by identity, not by position.
5. **Style is honoured or reported, never silently dropped.** `SlideStyle.accent` and
   `type_scale` apply to every component. `column_balance` and `emphasis_block_id` apply
   only where a component's content dataclass has a field for them; anywhere else the
   renderer records a `StyleNotHonoured` warning, so the aesthetic loop can learn that an
   action changed nothing rather than repeating it.

Speaker notes are written to each slide's notes page, one block per paragraph, each
followed by its source line — A1 applies to notes exactly as to the face.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Citation, Deck, Slide, TypeScale

SLIDE_TAG_PREFIX: Final = "autodeck:"
"""Prefix on each PPTX slide's `cSld/@name`. `autodeck.render.extract` reads it back."""

TYPE_SCALE_FACTORS: Final[dict[TypeScale, float]] = {
    "compact": 0.9,
    "standard": 1.0,
    "spacious": 1.1,
}
"""Multipliers applied to every size in the token type scale for one slide. A step on the
client's scale, never a point size. A slide rendered `spacious` may overflow where
`standard` fitted; that raises `LayoutOverflowError` like any other overflow, and the
aesthetic loop treats it as a rejected action."""


class RenderStageError(RuntimeError):
    """The deck cannot be rendered as it stands."""


class UnplacedBlockError(RenderStageError):
    """A face block whose `slot` names no field of its component's content dataclass."""


class UnknownComponentError(RenderStageError):
    """`Slide.component` is not registered in the catalog."""


@dataclass(frozen=True)
class StyleNotHonoured:
    """A `SlideStyle` field the slide's component has no way to express."""

    slide_id: str
    field: str
    component: str


@dataclass(frozen=True)
class RenderedDeck:
    path: Path
    slide_ids: tuple[str, ...]
    """IR slide ids in rendered order — one per PPTX slide."""
    warnings: tuple[StyleNotHonoured, ...] = field(default=())


def render_deck(deck: Deck, *, tokens: DesignTokens, out_path: Path) -> RenderedDeck:
    """Render `deck` to `out_path` in the client theme.

    Contract:
      - First statement: `require_safe_to_render(deck)`. `RenderBlocked` propagates and **no
        file is written** — check `out_path` does not exist afterwards in the test.
      - Presentation built with `autodeck.design.theme.master_builder` for `tokens`; saved
        with `save_themed` so the theme part is the client's.
      - One PPTX slide per IR slide, in order. For each: resolve
        `catalog.registration(slide.component)` (`UnknownComponentError` if absent), build
        its content with `adapt_slide`, draw with the registration's renderer on a `Canvas`
        built from `scaled_tokens(tokens, slide.style.type_scale)`, tag the slide, write notes.
      - Deterministic: two calls on the same deck and tokens produce PPTX files with equal
        `autodeck.audit.manifest.canonical_pptx_digest` (A6 as corrected by B29).
    """
    raise NotImplementedError("scaffold: Sonnet fills this in")


def adapt_slide(slide: Slide, content_type: type) -> tuple[object, list[StyleNotHonoured]]:
    """Build `content_type` (a component's content dataclass) from `slide`'s face blocks.

    Contract, per dataclass field, by name:
      - `str` field: the single face block whose `slot` equals the field name. Its value is
        `block.claim.text` for a claim, `block.text` for framing/section_header — verbatim.
        No block → the field's default if it has one, else `RenderStageError` naming the
        slot (a missing required slot should already have surfaced as `incomplete_slots`).
        More than one block → `RenderStageError`.
      - `list[str]` field: every face block with that slot, in block order, same rule.
      - `DiagramSpec` / `ChartSpec` field: the block's payload, unchanged.
      - `source`: `source_line(...)` over the citations of every claim block on the face,
        in first-appearance order, de-duplicated.
      - `accent`: `slide.style.accent`. `column_balance` / `emphasis` fields, where a
        component has them, from `slide.style`; where it does not and the style field is
        not its default, return a `StyleNotHonoured`.
      - A component whose content does not map one-to-one onto slots (nested dataclasses —
        e.g. `data_card_grid`'s cards, `big_number`'s supporting points) gets an entry in
        `ADAPTERS`, a small explicit function; every registered component must be covered
        by the generic rule or by `ADAPTERS` (a test walks `known_components()`).
      - After building: every face block was consumed, else `UnplacedBlockError` naming it.
    """
    raise NotImplementedError("scaffold: Sonnet fills this in")


def source_line(citations: list[Citation]) -> str:
    """The caption-band source text. **Reuse** the formatter in `autodeck.design.charts`
    (`_source_line`, promoted to a public name) rather than writing a second one — two
    descriptions of one format is the defect this project keeps finding."""
    raise NotImplementedError("scaffold: Sonnet fills this in")


def scaled_tokens(tokens: DesignTokens, scale: TypeScale) -> DesignTokens:
    """A copy of `tokens` with every type-scale size multiplied by `TYPE_SCALE_FACTORS`.
    `standard` returns `tokens` unchanged (identity, not a copy with factor 1.0)."""
    raise NotImplementedError("scaffold: Sonnet fills this in")
