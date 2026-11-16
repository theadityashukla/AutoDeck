"""Task 23.2: rendering in a deck's design system (`design_render.py`): the palette's base
slots render as the palette says, in the studio's own PPTX build, without changing v2."""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from autodeck.studio.design_render import (
    THEME_PART,
    build_designed_pptx,
    patch_theme_colours,
    render_with_design,
    renderable,
)
from autodeck.studio.models import DeckArtifact, DesignSystemRef, Slide
from autodeck.studio.render import build_pptx
from tests.studio.helpers import (
    FONTS_AVAILABLE,
    PNG_SIGNATURE,
    dev_tokens,
    flow_designed,
    flow_draft,
)

needs_fonts = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")


def theme_xml(pptx: Path) -> str:
    with zipfile.ZipFile(pptx) as z:
        return z.read(THEME_PART).decode("utf-8")


def dark_deck() -> DeckArtifact:
    draft = flow_draft("Demand curve")
    data = flow_designed("s2", "Demand curve")["slide"]
    slide = Slide.model_validate(
        {"id": "s2", "blocks": data["blocks"], "layout": data["layout"]}
    )
    return DeckArtifact(
        id="d",
        client="c",
        project="p",
        slides=[slide],
        design_system=DesignSystemRef(id="demand-curve", version=1, palette=draft.palette),
    )


@needs_fonts
def test_v2_writes_the_base_slots_as_system_colours_and_the_patch_fixes_them(
    tmp_path: Path,
) -> None:
    deck = dark_deck()
    from autodeck.studio.design import deck_tokens

    built = build_pptx(
        deck, tokens=deck_tokens(deck, dev_tokens()), out_path=tmp_path / "a.pptx"
    )
    before = theme_xml(built.path)
    assert "<a:dk1><a:sysClr" in before  # the gap the bench found (v2 is not changed)
    names = [i.filename for i in zipfile.ZipFile(built.path).infolist()]
    assert patch_theme_colours(built.path) is True
    after = theme_xml(built.path)
    assert '<a:dk1><a:srgbClr val="0B1420"/></a:dk1>' in after
    assert '<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>' in after
    assert "sysClr" not in after
    assert [i.filename for i in zipfile.ZipFile(built.path).infolist()] == names
    assert patch_theme_colours(built.path) is False  # nothing left to patch


def test_a_file_without_a_theme_part_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "x.pptx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
    before = path.read_bytes()
    assert patch_theme_colours(path) is False and path.read_bytes() == before


@needs_fonts
def test_the_designed_build_uses_the_decks_palette_everywhere(tmp_path: Path) -> None:
    deck = dark_deck()
    built = build_designed_pptx(deck, base=dev_tokens(), out_path=tmp_path / "deck.pptx")
    xml = theme_xml(tmp_path / "deck.pptx")
    assert '<a:lt2><a:srgbClr val="0F1D30"/></a:lt2>' in xml
    assert '<a:dk1><a:srgbClr val="0B1420"/></a:dk1>' in xml
    assert built.placeholders == {}  # type: ignore[attr-defined]


@needs_fonts
def test_renderable_reports_what_the_renderer_would_replace(tmp_path: Path) -> None:
    deck = dark_deck()
    from autodeck.studio.design import deck_tokens

    tokens = deck_tokens(deck, dev_tokens())
    assert renderable(deck.slides[0], tokens) is None
    data = deck.slides[0].model_dump()
    data["blocks"].append(
        {
            "id": "ic",
            "kind": "icon",
            "icon": {"concept": "x", "glyph_id": "no-such-glyph", "color_token": "accent1"},
        }
    )
    data["layout"]["elements"].append(
        {"type": "icon", "block_id": "ic", "frame": {"x": 90, "y": 6, "w": 4, "h": 6}}
    )
    reason = renderable(Slide.model_validate(data), tokens)
    assert reason


def test_the_production_renderer_maps_to_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autodeck.render.qa import libreoffice

    calls: list[str] = []

    def fake_render(pptx: Path, out_dir: Path, tokens: object, dpi: int = 0) -> object:
        calls.append(theme_xml(pptx))
        out_dir.mkdir(parents=True, exist_ok=True)
        image = out_dir / f"{pptx.stem}-1.png"
        image.write_bytes(PNG_SIGNATURE)

        return SimpleNamespace(images=[image])

    monkeypatch.setattr(libreoffice, "render_pptx", fake_render)
    if not FONTS_AVAILABLE:
        pytest.skip("Carlito is not installed")
    renderer = render_with_design(dev_tokens())
    out = tmp_path / "r"
    out.mkdir()
    manifest = renderer(dark_deck(), out, "0123456789ab")  # type: ignore[operator]
    assert manifest.rendered and manifest.images == ["previews/deck-1.png"]
    assert manifest.pptx == "deck.pptx" and manifest.slide_ids == ["s2"]
    assert '<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>' in calls[0]


@pytest.mark.render
def test_libreoffice_draws_the_dark_ground(tmp_path: Path) -> None:
    from PIL import Image

    from autodeck.studio.design_render import render_designed

    report = render_designed(dark_deck(), base=dev_tokens(), out_dir=tmp_path)
    assert report.previews.rendered, report.previews.note
    image = Image.open(report.previews.images[0]).convert("RGB")
    r, g, b = image.getpixel((image.width - 5, image.height - 5))
    assert (r, g, b) != (255, 255, 255) and r < 60 and b < 90  # night blue, not white
