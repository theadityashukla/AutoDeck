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

import re
from pathlib import Path

from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.models import DeckArtifact, Slide
from autodeck.studio.render import RenderReport

THEME_PART = "ppt/theme/theme1.xml"

SYS_CLR = re.compile(r'<a:(dk1|lt1)><a:sysClr [^>]*?lastClr="([0-9A-Fa-f]{6})"[^>]*?/></a:\1>')
"""A `dk1`/`lt1` slot written as a system colour, with the token's hex in `lastClr`."""


def patch_theme_colours(pptx_path):
    import os, zipfile
    with zipfile.ZipFile(pptx_path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]
    patched = False
    for n, (info, data) in enumerate(items):
        if info.filename == THEME_PART:
            t = data.decode("utf-8")
            new = SYS_CLR.sub(r'<a:\1><a:srgbClr val="\2"/></a:\1>', t)
            patched = new != t
            items[n] = (info, new.encode("utf-8"))
    if not patched:
        return False
    tmp = pptx_path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in items:
            z.writestr(info, data)
    os.replace(tmp, pptx_path)
    return True


def build_designed_pptx(deck, *, base, out_path):
    from autodeck.studio import design, render
    built = render.build_pptx(deck, tokens=design.deck_tokens(deck, base), out_path=out_path)
    patch_theme_colours(Path(out_path))
    return built


def render_designed(deck, *, base, out_dir):
    from autodeck.studio import design, render
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    built = build_designed_pptx(deck, base=base, out_path=out_dir / render.PPTX_FILENAME)
    prev = render.render_previews(built.path, out_dir=out_dir / render.PREVIEWS_DIRNAME, tokens=design.deck_tokens(deck, base))
    return RenderReport(built=built, previews=prev)


def render_with_design(base):
    from autodeck.studio import render
    from autodeck.studio.conversation import RenderManifest
    def renderer(deck, out_dir, digest):
        report = render_designed(deck, base=base, out_dir=out_dir)
        p = report.previews
        return RenderManifest(digest=digest, slide_ids=list(report.built.slide_ids), rendered=p.rendered, note=p.note, placeholders=dict(report.built.placeholders), images=[f"{render.PREVIEWS_DIRNAME}/{i.name}" for i in p.images] if p.rendered else [], pptx=render.PPTX_FILENAME, seconds_build=report.built.seconds, seconds_previews=p.seconds)
    return renderer


def renderable(slide, tokens):
    import tempfile
    from autodeck.studio import render
    with tempfile.TemporaryDirectory() as t:
        b = render.build_pptx(DeckArtifact(id="check", client="check", project="check", slides=[slide]), tokens=tokens, out_path=Path(t) / "c.pptx")
    return b.placeholders.get(slide.id)
