"""Rendering in a deck's design system (Phase 2-3).

Two things the slide bench found are needed for a design system's palette to render as the
palette says, and both are done here, in the studio's own PPTX build, without changing v2:

1. **Tokens per deck.** The palette comes from the deck (`design.deck_tokens`), so layout
   QA and the render read the same colours.
2. **The two base theme slots.** v2's theme writer emits `dk1` and `lt1` as `sysClr`
   (system colours, a documented gap in `master_builder._colour_value`); LibreOffice then
   draws the system black and white whatever the palette says, while layout QA judges
   contrast against the palette. `patch_theme_colours` rewrites those two slots in the
   studio's own copy of the file as plain `srgbClr` with the palette's value. The bench did
   the same (`bench/slides/run.py`, `patch_theme_colours`).

`render_with_design(base)` is the production `previews.Renderer`; `__main__` uses it in
place of Phase 1's `render_with_libreoffice(tokens)`. `renderable` is the designer's dry
build check: layout QA does not notice everything the renderer would replace with a
placeholder (an icon glyph not in the library, a chart that cannot be built), so the
designer builds the slide in memory on every attempt and treats a placeholder as a finding.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import cast

from autodeck.design.fonts import FontNotFoundError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio import render
from autodeck.studio.conversation import RenderManifest
from autodeck.studio.design import deck_tokens
from autodeck.studio.models import DeckArtifact, Slide
from autodeck.studio.render import BuiltDeck, RenderReport

THEME_PART = "ppt/theme/theme1.xml"

SYS_CLR = re.compile(r'<a:(dk1|lt1)><a:sysClr [^>]*?lastClr="([0-9A-Fa-f]{6})"[^>]*?/></a:\1>')
"""A `dk1`/`lt1` slot written as a system colour, with the token's hex in `lastClr`."""


def patch_theme_colours(pptx_path: Path) -> bool:
    """Rewrite `dk1` and `lt1` in the PPTX's theme part as `<a:srgbClr val="<hex>"/>`, in
    place. Returns True when the file was changed.

    Read every member of the zip; in `THEME_PART` replace each `SYS_CLR` match with
    `<a:\\1><a:srgbClr val="\\2"/></a:\\1>` (the hex is the `lastClr` v2 wrote, which is the
    token's value). When nothing matched, return False without writing. Otherwise write all
    members, in their original order and with their original `ZipInfo`, to a sibling
    temporary file (`.tmp` suffix) with `ZIP_DEFLATED`, then `os.replace` it over the
    original. Never raises for a file without a theme part (returns False).
    """
    pptx_path = Path(pptx_path)
    with zipfile.ZipFile(pptx_path) as zin:
        members = [(info, zin.read(info.filename)) for info in zin.infolist()]
    changed = False
    for index, (info, data) in enumerate(members):
        if info.filename != THEME_PART:
            continue
        text = data.decode("utf-8")
        new_text = SYS_CLR.sub(r'<a:\1><a:srgbClr val="\2"/></a:\1>', text)
        if new_text != text:
            changed = True
            members[index] = (info, new_text.encode("utf-8"))
    if not changed:
        return False
    tmp = pptx_path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in members:
            zout.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, pptx_path)
    return True


def build_designed_pptx(deck: DeckArtifact, *, base: DesignTokens, out_path: Path) -> object:
    """`render.build_pptx(deck, tokens=design.deck_tokens(deck, base), out_path=out_path)`,
    then `patch_theme_colours(out_path)`. Returns the `render.BuiltDeck`."""
    built = render.build_pptx(deck, tokens=deck_tokens(deck, base), out_path=out_path)
    patch_theme_colours(built.path)
    return built


def render_designed(deck: DeckArtifact, *, base: DesignTokens, out_dir: Path) -> RenderReport:
    """As `render.render_artifact`, in the deck's design: `build_designed_pptx` to
    `out_dir / render.PPTX_FILENAME`, then `render.render_previews` of it into
    `out_dir / render.PREVIEWS_DIRNAME` with the deck's tokens. `out_dir` is created."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    built = cast(
        BuiltDeck,
        build_designed_pptx(deck, base=base, out_path=out_dir / render.PPTX_FILENAME),
    )
    previews = render.render_previews(
        built.path,
        out_dir=out_dir / render.PREVIEWS_DIRNAME,
        tokens=deck_tokens(deck, base),
    )
    return RenderReport(built=built, previews=previews)


def render_with_design(base: DesignTokens) -> object:
    """The production `previews.Renderer` (`(deck, out_dir, digest12) -> RenderManifest`):
    exactly `previews.render_with_libreoffice`'s mapping to a manifest, but rendering with
    `render_designed(deck, base=base, out_dir=out_dir)`. v2's `FontNotFoundError` becomes
    `rendered=False` with its message, as there. Returns the callable."""

    def renderer(deck: DeckArtifact, out_dir: Path, digest: str) -> RenderManifest:
        try:
            report = render_designed(deck, base=base, out_dir=out_dir)
        except FontNotFoundError as exc:
            return RenderManifest(
                digest=digest, slide_ids=deck.slide_ids(), rendered=False, note=str(exc)
            )
        previews = report.previews
        images = [f"{render.PREVIEWS_DIRNAME}/{image.name}" for image in previews.images]
        return RenderManifest(
            digest=digest,
            slide_ids=list(report.built.slide_ids),
            rendered=previews.rendered,
            note=previews.note,
            placeholders=dict(report.built.placeholders),
            images=images if previews.rendered else [],
            pptx=render.PPTX_FILENAME,
            seconds_build=report.built.seconds,
            seconds_previews=previews.seconds,
        )

    return renderer


def renderable(slide: Slide, tokens: DesignTokens) -> str | None:
    """Why the renderer would draw `slide` as a placeholder, or None when it would draw it.

    Build a one-slide deck (`DeckArtifact(id="check", client="check", project="check",
    slides=[slide])`) with `render.build_pptx(..., tokens=tokens, out_path=<a file in a
    temporary directory>)` and return `built.placeholders.get(slide.id)`. v2's
    `FontNotFoundError` propagates (no honest check is possible without the font).
    """
    slide_deck = DeckArtifact(id="check", client="check", project="check", slides=[slide])
    with tempfile.TemporaryDirectory() as scratch:
        built = render.build_pptx(
            slide_deck, tokens=tokens, out_path=Path(scratch) / "check.pptx"
        )
        return built.placeholders.get(slide.id)
