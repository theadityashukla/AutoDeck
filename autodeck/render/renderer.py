"""IR → PPTX: the render stage (Phase 3b, task 3b.1).

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
followed by its source line — A1 applies to notes exactly as to the face. A diagram node's
claim is written there too, even though the node itself lives on the face: its box draws
only `node.label`, never the full `claim.text` behind it, so the claim's full text and
source line go to notes instead — see `_write_notes` and `autodeck.audit.post_render`'s
module docstring for what that means for claim survival.

## The generic rule, and where it stops

Most registered components map their face blocks onto their content dataclass one field at
a time, by name: a `str` field takes the one block whose `slot` matches, a `list[str]` field
takes every block with that slot in order, a `DiagramSpec`/`ChartSpec` field takes the one
block's payload unchanged. `_adapt_generic` is that rule, and it covers thirteen of the
fifteen registered components without any component-specific code here.

Two components have content that is not flat — `two_column_compare`'s `left`/`right` are
nested `ComparisonColumn` objects, `data_card_grid`'s `cards` are a list of nested `DataCard`
objects — so a single block's text cannot become one of those objects on its own. `ADAPTERS`
holds the small, explicit function each of those needs; `known_components()` is walked by
`tests/test_renderer.py` to make sure every registered component is covered by one path or
the other, so a sixteenth component that falls through neither is a test failure, not a
silent gap.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, get_args, get_origin, get_type_hints

from autodeck.design.charts import source_line as _design_source_line
from autodeck.design.components import catalog
from autodeck.design.components.renderers.data_card_grid import (
    DataCard,
    DataCardGridContent,
)
from autodeck.design.components.renderers.two_column_compare import (
    ComparisonColumn,
    TwoColumnCompareContent,
)
from autodeck.design.layout_kit import Canvas
from autodeck.design.theme.master_builder import new_presentation, save_themed
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, ChartSpec, Citation, Deck, DiagramSpec, Slide, TypeScale
from autodeck.pipeline.orchestrator import require_safe_to_render

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

#: python-pptx's stock blank layout — the same one `preview.py` builds golden previews on,
#: so a real deck's slides start from the identical layout the component library was
#: designed and measured against.
_BLANK_LAYOUT: Final = 6


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
    require_safe_to_render(deck)

    presentation = new_presentation(tokens)
    warnings: list[StyleNotHonoured] = []
    slide_ids: list[str] = []

    for ir_slide in deck.slides:
        try:
            entry = catalog.registration(ir_slide.component)
        except catalog.UnknownComponentError as exc:
            raise UnknownComponentError(str(exc)) from exc

        content, slide_warnings = adapt_slide(ir_slide, entry.content_type)
        warnings.extend(slide_warnings)

        scaled = scaled_tokens(tokens, ir_slide.style.type_scale)
        canvas = Canvas(scaled)
        pptx_slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
        entry.renderer(pptx_slide, canvas, content)

        pptx_slide.name = f"{SLIDE_TAG_PREFIX}{ir_slide.id}"
        _write_notes(pptx_slide, ir_slide)

        slide_ids.append(ir_slide.id)

    save_themed(presentation, tokens, out_path)
    return RenderedDeck(path=out_path, slide_ids=tuple(slide_ids), warnings=tuple(warnings))


def _write_notes(pptx_slide: Any, ir_slide: Slide) -> None:
    """One paragraph per notes block (a claim's followed by its source line), then every
    face diagram-node claim's full text and source line.

    A diagram node's box shows only `node.label`; `node.claim.text` — the full assertion the
    label stands for — never appears anywhere on the face (`diagrams.place_diagram` draws
    labels only, for every geometry). So it is written here instead, exactly like a notes
    claim, which is what makes it checkable at all: `post_render._claim_survival_findings`
    checks a node claim's text against the notes page rather than the face, for the same
    reason it checks any other notes claim there.
    """
    entries: list[tuple[str, str]] = [
        (_block_text(block), source_line(block.claim.citations) if block.claim else "")
        for block in ir_slide.speaker_notes
    ]
    entries.extend(
        (site.claim.text, source_line(site.claim.citations))
        for site in ir_slide.claim_sites()
        if site.node_id is not None and not site.in_speaker_notes
    )
    if not entries:
        return

    text_frame = pptx_slide.notes_slide.notes_text_frame
    first = True
    for text, source in entries:
        if first:
            text_frame.text = text
            first = False
        else:
            text_frame.add_paragraph().text = text
        if source:
            text_frame.add_paragraph().text = source


# ---------------------------------------------------------------------------
# Slide -> content adaptation
# ---------------------------------------------------------------------------

Adapter = Callable[[Slide], tuple[object, list[StyleNotHonoured]]]


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
      - `source`: `source_line(_face_claim_citations(slide))` — every citation on every face
        claim (`slide.claim_sites()`, not `block.claim is not None`, so a diagram node's
        claim is pooled in too), first-appearance order, de-duplicated. Empty when the face
        has no claim: `source_line` returns `""` rather than a bare `"Source: "`, and no
        block ever fills a `source` slot directly — it is always computed, never authored.
      - `accent`: `slide.style.accent`. `column_balance` / `emphasis` fields, where a
        component has them, from `slide.style`; where it does not and the style field is
        not its default, return a `StyleNotHonoured`.
      - A component whose content does not map one-to-one onto slots (nested dataclasses —
        e.g. `data_card_grid`'s cards, `big_number`'s supporting points) gets an entry in
        `ADAPTERS`, a small explicit function; every registered component must be covered
        by the generic rule or by `ADAPTERS` (a test walks `known_components()`).
      - After building: every face block was consumed, else `UnplacedBlockError` naming it.
    """
    adapter = ADAPTERS.get(content_type)
    if adapter is not None:
        return adapter(slide)
    return _adapt_generic(slide, content_type)


def source_line(citations: list[Citation]) -> str:
    """The caption-band source text. **Reuse** the formatter in `autodeck.design.charts`
    (`source_line`) rather than writing a second one — two descriptions of one format is the
    defect this project keeps finding. `""` for an empty citation set: no caption at all."""
    return _design_source_line(citations)


def scaled_tokens(tokens: DesignTokens, scale: TypeScale) -> DesignTokens:
    """A copy of `tokens` with every type-scale size multiplied by `TYPE_SCALE_FACTORS`.
    `standard` returns `tokens` unchanged (identity, not a copy with factor 1.0)."""
    if scale == "standard":
        return tokens
    factor = TYPE_SCALE_FACTORS[scale]
    typography = tokens.typography.model_copy(
        update={
            "display": tokens.typography.display * factor,
            "title": tokens.typography.title * factor,
            "heading": tokens.typography.heading * factor,
            "body": tokens.typography.body * factor,
            "caption": tokens.typography.caption * factor,
            "minimum": tokens.typography.minimum * factor,
        }
    )
    return tokens.model_copy(update={"typography": typography})


# ---------------------------------------------------------------------------
# Shared helpers — used by the generic path and every `ADAPTERS` entry
# ---------------------------------------------------------------------------


def _group_by_slot(blocks: list[Block]) -> dict[str, list[Block]]:
    by_slot: dict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        by_slot[block.slot].append(block)
    return by_slot


def _block_text(block: Block) -> str:
    """`block.claim.text` for a claim block, `block.text` for framing/section_header —
    verbatim, per this module's "content is copied, never composed" guarantee."""
    if block.claim is not None:
        return block.claim.text
    if block.text is not None:
        return block.text
    raise RenderStageError(
        f"block {block.id!r} (slot {block.slot!r}) carries neither a claim nor text; it "
        "cannot fill a text slot"
    )


def _face_claim_citations(slide: Slide) -> list[Citation]:
    """Every citation on every face claim, first-appearance order, deduped.

    Walks `slide.claim_sites()` — the one enumeration (`ir/models.py`'s own words) — rather
    than re-deriving claims from `block.claim is not None`, which is exactly the walk that
    missed a diagram node's claim: `Block.claim_sites()` reaches a node's claim through
    `DiagramSpec.claim_nodes()`, a second payload a naive `Block.claim` check never sees.
    Restricted to the face (`not site.in_speaker_notes`): a notes claim's citation belongs on
    the notes page via `source_line(block.claim.citations)` in `_write_notes`, not pooled
    into the slide's visible caption.
    """
    citations: list[Citation] = []
    seen: set[tuple[str, int, str]] = set()
    for site in slide.claim_sites():
        if site.in_speaker_notes:
            continue
        for citation in site.claim.citations:
            key = citation.identity()
            if key not in seen:
                seen.add(key)
                citations.append(citation)
    return citations


def expected_caption_lines(slide: Slide) -> frozenset[str]:
    """Every literal caption line this slide's render could draw: the content's own `source`
    text (pooled from every face claim, including a diagram node's) and each chart block's
    own caption — each recomputed from the IR with this same `source_line`.

    Public so `autodeck.audit.post_render` can strip exactly these lines from the text it
    hands the numeric linter, rather than matching any line that merely starts `"Source: "`
    — a prefix match would let a claim whose own text happens to begin that way escape A2.
    An empty result is possible (a slide with no face claim and no chart draws no caption at
    all) and callers should not special-case it: stripping a line that was never drawn is a
    no-op.
    """
    lines = {source_line(_face_claim_citations(slide))}
    lines.update(
        source_line(block.chart.source_citations) for block in slide.blocks if block.chart
    )
    lines.discard("")
    return frozenset(lines)


def _has_default(f: dataclasses.Field[Any]) -> bool:
    return f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING


def _is_list_str(hint: object) -> bool:
    return get_origin(hint) is list and get_args(hint) == (str,)


def _raise_unplaced(consumed: set[str], blocks: list[Block]) -> None:
    unplaced = [block for block in blocks if block.id not in consumed]
    if unplaced:
        names = ", ".join(f"{block.id!r} (slot {block.slot!r})" for block in unplaced)
        raise UnplacedBlockError(
            f"block(s) not placed in any content field: {names}. A block the renderer "
            "silently does not draw is a deleted fact."
        )


def _style_field_warnings(slide: Slide, content_type: type) -> list[StyleNotHonoured]:
    """`column_balance`/`emphasis_block_id` findings for a component with no field for them.

    None of the registered content dataclasses declare a top-level `column_balance` or
    `emphasis` field (the one component that expresses something like emphasis,
    `two_column_compare`, does it through a nested field via its own `ADAPTERS` entry, which
    computes its own warnings instead of this generic check).
    """
    hints = get_type_hints(content_type)
    warnings: list[StyleNotHonoured] = []
    if slide.style.column_balance != "even" and "column_balance" not in hints:
        warnings.append(StyleNotHonoured(slide.id, "column_balance", slide.component))
    if slide.style.emphasis_block_id is not None and "emphasis" not in hints:
        warnings.append(StyleNotHonoured(slide.id, "emphasis_block_id", slide.component))
    return warnings


# ---------------------------------------------------------------------------
# The generic rule
# ---------------------------------------------------------------------------


def _adapt_generic(slide: Slide, content_type: type) -> tuple[object, list[StyleNotHonoured]]:
    hints = get_type_hints(content_type)
    by_slot = _group_by_slot(slide.blocks)
    consumed: set[str] = set()
    kwargs: dict[str, Any] = {}

    for f in dataclasses.fields(content_type):
        name = f.name
        if name == "source":
            continue
        if name == "accent":
            kwargs[name] = slide.style.accent
            continue

        hint = hints[name]

        if hint in (DiagramSpec, ChartSpec):
            blocks = by_slot.get(name, [])
            if not blocks:
                if _has_default(f):
                    continue
                raise RenderStageError(
                    f"{content_type.__name__}.{name!r} has no block filling slot {name!r} "
                    "and no default"
                )
            if len(blocks) > 1:
                raise RenderStageError(
                    f"{content_type.__name__}.{name!r} (slot {name!r}) has "
                    f"{len(blocks)} blocks; expected exactly one"
                )
            block = blocks[0]
            kwargs[name] = block.diagram if hint is DiagramSpec else block.chart
            consumed.add(block.id)
            continue

        if _is_list_str(hint):
            blocks = by_slot.get(name, [])
            kwargs[name] = [_block_text(block) for block in blocks]
            consumed.update(block.id for block in blocks)
            continue

        # A plain str field.
        blocks = by_slot.get(name, [])
        if not blocks:
            if _has_default(f):
                continue
            raise RenderStageError(
                f"{content_type.__name__}.{name!r} has no block filling slot {name!r} "
                "and no default"
            )
        if len(blocks) > 1:
            raise RenderStageError(
                f"{content_type.__name__}.{name!r} (slot {name!r}) has {len(blocks)} "
                "blocks; expected exactly one"
            )
        block = blocks[0]
        kwargs[name] = _block_text(block)
        consumed.add(block.id)

    if "source" in hints:
        kwargs["source"] = source_line(_face_claim_citations(slide))

    content = content_type(**kwargs)
    _raise_unplaced(consumed, slide.blocks)
    return content, _style_field_warnings(slide, content_type)


# ---------------------------------------------------------------------------
# ADAPTERS — components whose content does not map one-to-one onto slots
# ---------------------------------------------------------------------------


def _adapt_two_column_compare(
    slide: Slide,
) -> tuple[TwoColumnCompareContent, list[StyleNotHonoured]]:
    """`left`/`right` are nested `ComparisonColumn`s, so no single-field generic rule applies.

    Slot names mirror `catalog._two_column_compare_slots` exactly: `left_title`/`right_title`
    for each column's heading, `left_points`/`right_points` (repeatable) or the singular
    `left_point`/`right_point` for its rows. `SlideStyle.accent` reaches both columns — one
    theme accent per slide, per this module's guarantee #5 — and `emphasis_block_id` marks
    whichever column's title block it names; naming anything else is reported rather than
    silently dropped, as is any `column_balance` other than the default, since this component
    always splits its two columns evenly.
    """
    by_slot = _group_by_slot(slide.blocks)
    consumed: set[str] = set()

    headline_blocks = by_slot.get("headline", [])
    if len(headline_blocks) != 1:
        raise RenderStageError(
            f"two_column_compare needs exactly one 'headline' block, got {len(headline_blocks)}"
        )
    headline_block = headline_blocks[0]
    consumed.add(headline_block.id)
    headline = _block_text(headline_block)

    def build_column(
        title_slot: str, points_slot: str, point_slot: str
    ) -> tuple[ComparisonColumn, str]:
        title_blocks = by_slot.get(title_slot, [])
        if len(title_blocks) != 1:
            raise RenderStageError(
                f"two_column_compare needs exactly one {title_slot!r} block, got "
                f"{len(title_blocks)}"
            )
        title_block = title_blocks[0]
        consumed.add(title_block.id)

        points: list[str] = []
        for block in (*by_slot.get(points_slot, []), *by_slot.get(point_slot, [])):
            points.append(_block_text(block))
            consumed.add(block.id)

        return ComparisonColumn(title=_block_text(title_block), points=points), title_block.id

    left, left_title_id = build_column("left_title", "left_points", "left_point")
    right, right_title_id = build_column("right_title", "right_points", "right_point")

    left.accent = slide.style.accent
    right.accent = slide.style.accent

    warnings: list[StyleNotHonoured] = []
    emphasis_id = slide.style.emphasis_block_id
    if emphasis_id == left_title_id:
        left.emphasised = True
    elif emphasis_id == right_title_id:
        right.emphasised = True
    elif emphasis_id is not None:
        warnings.append(StyleNotHonoured(slide.id, "emphasis_block_id", "two_column_compare"))

    if slide.style.column_balance != "even":
        warnings.append(StyleNotHonoured(slide.id, "column_balance", "two_column_compare"))

    source = source_line(_face_claim_citations(slide))
    content = TwoColumnCompareContent(headline=headline, left=left, right=right, source=source)
    _raise_unplaced(consumed, slide.blocks)
    return content, warnings


def _adapt_data_card_grid(slide: Slide) -> tuple[DataCardGridContent, list[StyleNotHonoured]]:
    """`cards` is a list of nested `DataCard`s, built from two positionally-paired repeatable
    slots — `card_label` and `card_value` — rather than one slot per card, so a card's label
    and value each stay their own untouched face block (guarantee #3: content copied, never
    composed from parsing a single string)."""
    by_slot = _group_by_slot(slide.blocks)
    consumed: set[str] = set()

    headline_blocks = by_slot.get("headline", [])
    if len(headline_blocks) != 1:
        raise RenderStageError(
            f"data_card_grid needs exactly one 'headline' block, got {len(headline_blocks)}"
        )
    headline_block = headline_blocks[0]
    consumed.add(headline_block.id)
    headline = _block_text(headline_block)

    labels = by_slot.get("card_label", [])
    values = by_slot.get("card_value", [])
    if len(labels) != len(values):
        raise RenderStageError(
            f"data_card_grid has {len(labels)} 'card_label' block(s) but {len(values)} "
            "'card_value' block(s); each card needs exactly one of each, paired by order"
        )
    cards = [
        DataCard(label=_block_text(label_block), value=_block_text(value_block))
        for label_block, value_block in zip(labels, values, strict=True)
    ]
    consumed.update(block.id for block in (*labels, *values))

    warnings: list[StyleNotHonoured] = []
    if slide.style.column_balance != "even":
        warnings.append(StyleNotHonoured(slide.id, "column_balance", "data_card_grid"))
    if slide.style.emphasis_block_id is not None:
        warnings.append(StyleNotHonoured(slide.id, "emphasis_block_id", "data_card_grid"))

    content = DataCardGridContent(headline=headline, cards=cards, accent=slide.style.accent)
    _raise_unplaced(consumed, slide.blocks)
    return content, warnings


ADAPTERS: dict[type, Adapter] = {
    TwoColumnCompareContent: _adapt_two_column_compare,
    DataCardGridContent: _adapt_data_card_grid,
}
