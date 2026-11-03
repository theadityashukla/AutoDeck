"""Draft previews (task 3c.8, B43): the IR as it stands, drawn, and marked as not approved.

The point of a draft is that an owner can *see* the deck before approving anything, so it
must render with `unsupported` claims on it and with no approval recorded. That is the
opposite of `renderer.render_deck`, whose first statement is the A3/A5 guard. Two decisions
follow, and both are about keeping the final deck unreachable from here:

* **This module builds its own PPTX from the renderer's drawing helpers rather than calling
  `render_deck` or loosening its guard.** The final renderer stays byte-for-byte what it was;
  the guard is not parameterised, so no flag exists anywhere that could switch it off.
* **It cannot write `deck.pptx`.** The target is fixed at `<out_dir>/draft.pptx`, asserted to
  be inside `out_dir`, and `out_dir` is refused if it holds the run's own state (that is the
  run root, where `deck.pptx` lives). It imports nothing that records an approval or a final
  assessment.

A draft is deliberately the IR as it is: no art direction, no aesthetic loop (those belong to
the final deck and would spend model calls on content nobody has accepted), and every slide
carries a visible "DRAFT - not approved" box so a screenshot of one cannot be mistaken for
the deliverable. The box is added to the draft file only, after the normal drawing.

Owning phase: 3c.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

from autodeck.audit.verdicts import blocking_blocks, unverified_claims
from autodeck.design.components import catalog
from autodeck.design.charts import ChartConstructionError
from autodeck.design.free_layout import render_free_layout
from autodeck.design.icons.library import IconNotFoundError
from autodeck.design.layout_kit import Canvas, LayoutOverflowError
from autodeck.design.theme.master_builder import new_presentation, save_themed
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Deck
from autodeck.render.qa.libreoffice import RenderError, render_pptx
from autodeck.render.renderer import (
    _BLANK_LAYOUT,
    SLIDE_TAG_PREFIX,
    RenderStageError,
    UnknownComponentError,
    _write_notes,
    adapt_slide,
    scaled_tokens,
    section_number_of,
)

DRAFT_FILENAME = "draft.pptx"
DRAFT_MARKER_TEXT = "DRAFT — not approved"
DRAFT_MARKER_NAME = "autodeck:draft-marker"
PLACEHOLDER_NAME = "autodeck:draft-placeholder"

#: Files whose presence marks a directory as a run root (where `deck.pptx` is written).
_RUN_ROOT_MARKERS = ("state.json", "deck.pptx")


@dataclass
class DraftPreview:
    pptx: Path
    """`<out_dir>/draft.pptx` - never the run's `deck.pptx`."""
    images: list[Path]
    """One PNG per slide, in order; empty when `rendered` is False."""
    flags: dict[str, str]
    """slide_id -> "blocking" | "partial" | "unsourced" | "from_you" | "story" | "" (`slide_flags`)."""
    rendered: bool
    """False when no PNGs could be made (LibreOffice or a declared font missing); the pptx
    is still written."""
    note: str = field(default="")
    """Why `rendered` is False, when it is."""
    placeholders: dict[str, str] = field(default_factory=dict)
    """slide_id -> why that slide is drawn as a placeholder instead of its component."""


def slide_flags(deck: Deck) -> dict[str, str]:
    """Per slide, the most serious flag (one value), else "".

    * "blocking": a claim would bar the final render or was never judged, or the
      validator found the headline overstates the slide (B62);
    * "partial": a claim is only partially supported;
    * "unsourced" (B55): a claim rests on the model's general knowledge (`basis`
      "unsourced"), which the person should know about; it never blocks;
    * "from_you" (B55): a claim cites what the person typed (`source_class` "conversation");
    * "story" (B70): the deck-level storyline check has a finding for this slide's header.
      Advisory like "unsourced": it never blocks and is the least serious flag.

    "Blocking" is `verdicts.blocking_blocks` (the IR's own `Claim.blocks_render`, diagram
    nodes and notes included) plus `unverified_claims`; nothing is re-derived here.
    """
    blocking = {b.slide_id for b in blocking_blocks(deck)}
    blocking |= {b.slide_id for b in unverified_claims(deck)}
    # B62: an overstated talking header bars the render like an unsupported claim.
    blocking |= {
        s.id
        for s in deck.slides
        if s.headline_check is not None and s.headline_check.verdict == "overstates"
    }
    sites = deck.claim_sites()
    partial = {s.slide_id for s in sites if s.claim.verdict == "partially_supported"}
    unsourced = {s.slide_id for s in sites if s.claim.basis == "unsourced"}
    from_you = {
        s.slide_id
        for s in sites
        if any(c.source_class == "conversation" for c in s.claim.citations)
    }

    story = {
        f.slide_id
        for f in (deck.storyline_check.findings if deck.storyline_check is not None else [])
    }

    def flag(slide_id: str) -> str:
        for name, members in (
            ("blocking", blocking),
            ("partial", partial),
            ("unsourced", unsourced),
            ("from_you", from_you),
            ("story", story),
        ):
            if slide_id in members:
                return name
        return ""

    return {slide.id: flag(slide.id) for slide in deck.slides}


def render_draft(deck: Deck, *, out_dir: Path, tokens: DesignTokens) -> DraftPreview:
    """Draw `deck` as it is into `out_dir`, marked DRAFT, and rasterise it if possible.

    Raises:
        ValueError: `out_dir` looks like a run root (it could then sit beside `deck.pptx`).
        UnknownComponentError / FontNotFoundError: the deck genuinely cannot be drawn.
    """
    out_dir = Path(out_dir)
    target = _checked_target(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("draft-*.png"):
        stale.unlink()

    placeholders = _build_pptx(deck, tokens, target)
    _mark_as_draft(target)

    images: list[Path] = []
    rendered = False
    note = ""
    try:
        images = render_pptx(target, out_dir, tokens).images
        rendered = True
    except RenderError as exc:  # includes FontSubstitutionRisk: no honest image possible
        note = str(exc)
    return DraftPreview(
        pptx=target,
        images=images,
        flags=slide_flags(deck),
        rendered=rendered,
        note=note,
        placeholders=placeholders,
    )


def _checked_target(out_dir: Path) -> Path:
    """The only path this module writes a deck to, proven to be inside `out_dir`."""
    resolved = out_dir.resolve()
    if any((resolved / marker).exists() for marker in _RUN_ROOT_MARKERS):
        raise ValueError(
            f"{out_dir} looks like a run root; drafts go in a subdirectory "
            "(runs/<run>/previews/draft), never beside deck.pptx."
        )
    target = resolved / DRAFT_FILENAME
    assert target.parent == resolved and target.name != "deck.pptx"
    return target


def _build_pptx(deck: Deck, tokens: DesignTokens, out_path: Path) -> dict[str, str]:
    """`render_deck`'s drawing loop without its render guard (see module docstring).

    A slide its component cannot draw — typically a required slot left empty because the
    block meant for it was dropped (its citation did not resolve) — becomes a placeholder
    saying so, instead of failing the whole preview: a draft shows the deck as it is, gaps
    included. Returns slide_id -> reason for each placeholder.
    """
    presentation = new_presentation(tokens)
    placeholders: dict[str, str] = {}
    for ir_slide in deck.slides:
        if ir_slide.layout is not None:
            pptx_slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
            pptx_slide.name = f"{SLIDE_TAG_PREFIX}{ir_slide.id}"
            canvas = Canvas(scaled_tokens(tokens, ir_slide.style.type_scale))
            try:
                render_free_layout(pptx_slide, canvas, ir_slide)
            except (LayoutOverflowError, ChartConstructionError, IconNotFoundError) as exc:
                # B69: a creative layout that fails its checks is drawn as what it is, a
                # slide that needs revising, exactly like a component that overflows.
                for shape in list(pptx_slide.shapes):
                    shape._element.getparent().remove(shape._element)
                placeholders[ir_slide.id] = str(exc)
                _draw_placeholder(presentation, pptx_slide, ir_slide.id, ir_slide.component, exc)
            _write_notes(pptx_slide, ir_slide)
            continue
        try:
            entry = catalog.registration(ir_slide.component)
        except catalog.UnknownComponentError as exc:
            raise UnknownComponentError(str(exc)) from exc
        pptx_slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
        pptx_slide.name = f"{SLIDE_TAG_PREFIX}{ir_slide.id}"
        try:
            content, _warnings = adapt_slide(
                ir_slide, entry.content_type, section_number=section_number_of(deck, ir_slide)
            )
        except RenderStageError as exc:
            placeholders[ir_slide.id] = str(exc)
            _draw_placeholder(presentation, pptx_slide, ir_slide.id, ir_slide.component, exc)
        else:
            canvas = Canvas(scaled_tokens(tokens, ir_slide.style.type_scale))
            try:
                entry.renderer(pptx_slide, canvas, content)
            except (LayoutOverflowError, ChartConstructionError) as exc:
                # Slots that each fit their budget can still overflow the region they share
                # (design gallery, 2026-10-13). One such slide used to abort the whole
                # preview; now it is drawn as what it is, a slide that needs revising.
                for shape in list(pptx_slide.shapes):
                    shape._element.getparent().remove(shape._element)
                placeholders[ir_slide.id] = str(exc)
                _draw_placeholder(presentation, pptx_slide, ir_slide.id, ir_slide.component, exc)
        _write_notes(pptx_slide, ir_slide)
    save_themed(presentation, tokens, out_path)
    return placeholders


def _draw_placeholder(
    presentation: Any, pptx_slide: Any, slide_id: str, component: str, reason: Exception
) -> None:
    """A plain box naming the slide, its component, and what is missing."""
    width, height = int(presentation.slide_width), int(presentation.slide_height)
    margin = Emu(600_000)
    box = pptx_slide.shapes.add_textbox(
        margin, margin * 2, Emu(width - 2 * margin), Emu(height - 4 * margin)
    )
    box.name = PLACEHOLDER_NAME
    frame = box.text_frame
    frame.word_wrap = True
    heading = frame.paragraphs[0].add_run()
    heading.text = f"Slide {slide_id} ({component}) could not be drawn"
    heading.font.size = Pt(28)
    heading.font.bold = True
    heading.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    detail = frame.add_paragraph().add_run()
    if isinstance(reason, LayoutOverflowError | ChartConstructionError | IconNotFoundError):
        detail.text = (
            f"{reason}. The slide's text does not fit its layout as a whole. Shorten the "
            "headline or the body, drop an optional part, or ask for a different layout."
        )
    else:
        detail.text = (
            f"{reason}. A block this layout needs was dropped, usually because its "
            "citation did not resolve. Revise the slide or ask for a different layout."
        )
    detail.font.size = Pt(16)
    detail.font.color.rgb = RGBColor(0x60, 0x60, 0x60)


def _mark_as_draft(path: Path) -> None:
    """Add the DRAFT box to every slide of the draft file, in neutral grey, top-right."""
    presentation = Presentation(str(path))
    width = int(presentation.slide_width)
    box_w, box_h, margin = Emu(2_000_000), Emu(300_000), Emu(150_000)
    for slide in presentation.slides:
        box = slide.shapes.add_textbox(Emu(width - box_w - margin), margin, box_w, box_h)
        box.name = DRAFT_MARKER_NAME
        paragraph = box.text_frame.paragraphs[0]
        run = paragraph.add_run()
        run.text = DRAFT_MARKER_TEXT
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x6A, 0x6A, 0x6A)  # 5.4:1 on white (WCAG AA)
    presentation.save(str(path))
