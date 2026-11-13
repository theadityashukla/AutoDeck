"""Render a base deck to a real PPTX and PNG previews, and time both (plan §12 Phase 0, §13).

The drawing loop mirrors v2's `renderer.render_deck` for a creative slide, built from the
same public pieces `render/draft.py` uses: `master_builder.new_presentation(tokens)`, one
slide per base slide on python-pptx's blank layout (index 6, v2's `_BLANK_LAYOUT`),
`free_layout.render_free_layout` on a `layout_kit.Canvas(tokens)`, the slide tagged
`cSld/@name = "autodeck:<slide id>"` (v2's `SLIDE_TAG_PREFIX`), then
`master_builder.save_themed`. See `render_adapter` for why `render_deck` itself is not
called.

A slide that cannot be drawn (no layout yet, layout QA fails, or a chart/icon cannot be
built) is drawn as a plain placeholder naming the slide and the reason, and is reported in
`BuiltDeck.placeholders`; the rest of the deck still renders (the draft preview's rule).
No DRAFT marker is added: in the base there are no approvals to be "not yet" (V6).

**Preview speed is the plan's first risk.** `build_pptx` and `render_previews` each time
themselves with `time.perf_counter()` and report seconds, so the demo and the phase report
can say how long a preview takes. Phase 0 measures only: no caching, no parallelism.

Tokens are passed in explicitly. The design system (Phase 3) will decide them; for now the
caller chooses, e.g. `config/tokens/dev.json`, whose fonts can be installed locally.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

from autodeck.design.charts import ChartConstructionError
from autodeck.design.free_layout import render_free_layout
from autodeck.design.icons.library import IconNotFoundError
from autodeck.design.layout_kit import Canvas, LayoutOverflowError
from autodeck.design.theme.master_builder import new_presentation, save_themed
from autodeck.design.theme.tokens import DesignTokens
from autodeck.render.qa import libreoffice
from autodeck.render.renderer import _BLANK_LAYOUT, SLIDE_TAG_PREFIX
from autodeck.studio import render_adapter
from autodeck.studio.models import DeckArtifact

PPTX_FILENAME = "deck.pptx"
PREVIEWS_DIRNAME = "previews"
PLACEHOLDER_NAME = "autodeck:studio-placeholder"
"""python-pptx shape name of a placeholder's text box, so tests can find it."""


@dataclass(frozen=True)
class BuiltDeck:
    """What `build_pptx` wrote."""

    path: Path
    slide_ids: tuple[str, ...]
    """Base slide ids in rendered order, one per PPTX slide (placeholders included)."""
    placeholders: dict[str, str] = field(default_factory=dict)
    """slide id -> why it was drawn as a placeholder. `{}` when every slide drew."""
    seconds: float = 0.0
    """Wall time of the whole build, presentation creation to file saved."""


@dataclass(frozen=True)
class PreviewSet:
    """What `render_previews` produced."""

    images: list[Path]
    """One PNG per slide, in slide order; `[]` when `rendered` is False."""
    rendered: bool
    """False when LibreOffice, pdftoppm or a declared font is missing; never raises for it."""
    note: str = ""
    """The `RenderError` message when `rendered` is False, else `""`."""
    seconds: float = 0.0
    """Wall time of the rasterisation (PPTX → PDF → PNGs), including the font check."""
    dpi: int = libreoffice.DEFAULT_DPI


@dataclass(frozen=True)
class RenderReport:
    """A full render: the PPTX and its previews."""

    built: BuiltDeck
    previews: PreviewSet

    def timing_lines(self) -> list[str]:
        """Exactly two lines, for the demo and the phase report:

            f"pptx build: {built.seconds:.2f}s for {n} slides"
            f"previews:   {previews.seconds:.2f}s for {len(previews.images)} images"
              (or f"previews:   not rendered ({previews.note})" when not rendered)

        where `n = len(built.slide_ids)`.
        """
        n = len(self.built.slide_ids)
        previews = self.previews
        if previews.rendered:
            second = f"previews:   {previews.seconds:.2f}s for {len(previews.images)} images"
        else:
            second = f"previews:   not rendered ({previews.note})"
        return [f"pptx build: {self.built.seconds:.2f}s for {n} slides", second]


def write_notes(pptx_slide: Any, notes: str) -> None:
    """Write plain speaker notes to the slide's notes page, verbatim.

    Empty (or whitespace-only) `notes`: do nothing, so no notes slide is created. Otherwise
    set `pptx_slide.notes_slide.notes_text_frame.text = notes` (python-pptx turns each
    `\\n` into a paragraph).
    """
    if not notes.strip():
        return
    pptx_slide.notes_slide.notes_text_frame.text = notes


def draw_placeholder(presentation: Any, pptx_slide: Any, slide_id: str, reason: str) -> None:
    """Draw one text box named `PLACEHOLDER_NAME` filling the slide inside a 600000-EMU
    margin, reading `f"Slide {slide_id} could not be drawn"` (28pt, bold) and `reason`
    (16pt) as a second paragraph. Literal greys are acceptable here (the v2 draft
    placeholder does the same): a placeholder is not deck content."""
    width, height = int(presentation.slide_width), int(presentation.slide_height)
    margin = 600_000
    box = pptx_slide.shapes.add_textbox(
        Emu(margin), Emu(margin), Emu(width - 2 * margin), Emu(height - 2 * margin)
    )
    box.name = PLACEHOLDER_NAME
    frame = box.text_frame
    frame.word_wrap = True
    heading = frame.paragraphs[0].add_run()
    heading.text = f"Slide {slide_id} could not be drawn"
    heading.font.size = Pt(28)
    heading.font.bold = True
    heading.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    detail = frame.add_paragraph().add_run()
    detail.text = reason
    detail.font.size = Pt(16)
    detail.font.color.rgb = RGBColor(0x60, 0x60, 0x60)


def build_pptx(deck: DeckArtifact, *, tokens: DesignTokens, out_path: Path) -> BuiltDeck:
    """Draw `deck` to `out_path` (parents created) in `tokens`' theme; return what was built.

    For each slide, in order: add a blank-layout slide, tag it `SLIDE_TAG_PREFIX + id`, then
    if `slide.layout` is None draw a placeholder with reason "slide has no layout yet";
    otherwise call `render_free_layout(pptx_slide, Canvas(tokens),
    render_adapter.to_render_slide(slide))`, and on `LayoutOverflowError` (which includes
    v2's `FreeLayoutQAError`), `ChartConstructionError` or `IconNotFoundError` remove any
    shapes already drawn on that slide and draw a placeholder whose reason is `str(exc)`.
    Then `write_notes(pptx_slide, slide.speaker_notes)`. Save with `save_themed`.

    Deterministic: two builds of the same deck and tokens have equal
    `autodeck.audit.manifest.canonical_pptx_digest`.

    Raises:
        FontNotFoundError: a declared font cannot be measured (v2's; not caught, because
            no honest layout check is possible without it).
    """
    started = time.perf_counter()
    presentation = new_presentation(tokens)
    placeholders: dict[str, str] = {}
    slide_ids: list[str] = []
    for slide in deck.slides:
        pptx_slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
        pptx_slide.name = f"{SLIDE_TAG_PREFIX}{slide.id}"
        if slide.layout is None:
            reason = "slide has no layout yet"
            placeholders[slide.id] = reason
            draw_placeholder(presentation, pptx_slide, slide.id, reason)
        else:
            try:
                render_free_layout(
                    pptx_slide, Canvas(tokens), render_adapter.to_render_slide(slide)
                )
            except (LayoutOverflowError, ChartConstructionError, IconNotFoundError) as exc:
                for shape in list(pptx_slide.shapes):
                    shape._element.getparent().remove(shape._element)
                placeholders[slide.id] = str(exc)
                draw_placeholder(presentation, pptx_slide, slide.id, str(exc))
        write_notes(pptx_slide, slide.speaker_notes)
        slide_ids.append(slide.id)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_themed(presentation, tokens, out_path)
    return BuiltDeck(
        path=out_path,
        slide_ids=tuple(slide_ids),
        placeholders=placeholders,
        seconds=time.perf_counter() - started,
    )


def render_previews(
    pptx: Path, *, out_dir: Path, tokens: DesignTokens, dpi: int = libreoffice.DEFAULT_DPI
) -> PreviewSet:
    """Rasterise `pptx` to one PNG per slide in `out_dir` with v2's
    `render.qa.libreoffice.render_pptx`, timing it.

    Call it as `libreoffice.render_pptx(pptx, out_dir, tokens, dpi=dpi)` through the module
    attribute (not a `from ... import render_pptx` name), so tests can monkeypatch
    `autodeck.render.qa.libreoffice.render_pptx` without LibreOffice installed.

    `out_dir` is created if missing. Stale `<pptx stem>-*.png` files in `out_dir` are
    deleted first so the image list is never mixed with an earlier render. On success,
    `images` is `RenderResult.images` (sorted, one per slide), `rendered=True`, `note=""`.
    `libreoffice.RenderError` (which includes `FontSubstitutionRisk`: no honest image is
    possible) is caught and returned as `rendered=False`, `images=[]`, its `str()` in
    `note`; `seconds` is still the time spent. Any other exception propagates.

    Raises:
        FileNotFoundError: `pptx` does not exist (checked before anything else).
    """
    pptx = Path(pptx)
    if not pptx.exists():
        raise FileNotFoundError(pptx)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(f"{pptx.stem}-*.png"):
        stale.unlink()
    started = time.perf_counter()
    try:
        result = libreoffice.render_pptx(pptx, out_dir, tokens, dpi=dpi)
    except libreoffice.RenderError as exc:
        return PreviewSet(
            images=[],
            rendered=False,
            note=str(exc),
            seconds=time.perf_counter() - started,
            dpi=dpi,
        )
    return PreviewSet(
        images=list(result.images),
        rendered=True,
        note="",
        seconds=time.perf_counter() - started,
        dpi=dpi,
    )


def render_artifact(deck: DeckArtifact, *, tokens: DesignTokens, out_dir: Path) -> RenderReport:
    """`build_pptx` to `out_dir / PPTX_FILENAME`, then `render_previews` into
    `out_dir / PREVIEWS_DIRNAME`. `out_dir` is created if missing. For an artifact in a
    store, pass `ArtifactPaths.renders`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    built = build_pptx(deck, tokens=tokens, out_path=out_dir / PPTX_FILENAME)
    previews = render_previews(built.path, out_dir=out_dir / PREVIEWS_DIRNAME, tokens=tokens)
    return RenderReport(built=built, previews=previews)
