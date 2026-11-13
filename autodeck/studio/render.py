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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autodeck.design.theme.tokens import DesignTokens
from autodeck.render.qa import libreoffice
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
        raise NotImplementedError


def write_notes(pptx_slide: Any, notes: str) -> None:
    """Write plain speaker notes to the slide's notes page, verbatim.

    Empty (or whitespace-only) `notes`: do nothing, so no notes slide is created. Otherwise
    set `pptx_slide.notes_slide.notes_text_frame.text = notes` (python-pptx turns each
    `\\n` into a paragraph).
    """
    raise NotImplementedError


def draw_placeholder(presentation: Any, pptx_slide: Any, slide_id: str, reason: str) -> None:
    """Draw one text box named `PLACEHOLDER_NAME` filling the slide inside a 600000-EMU
    margin, reading `f"Slide {slide_id} could not be drawn"` (28pt, bold) and `reason`
    (16pt) as a second paragraph. Literal greys are acceptable here (the v2 draft
    placeholder does the same): a placeholder is not deck content."""
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


def render_artifact(deck: DeckArtifact, *, tokens: DesignTokens, out_dir: Path) -> RenderReport:
    """`build_pptx` to `out_dir / PPTX_FILENAME`, then `render_previews` into
    `out_dir / PREVIEWS_DIRNAME`. `out_dir` is created if missing. For an artifact in a
    store, pass `ArtifactPaths.renders`."""
    raise NotImplementedError
