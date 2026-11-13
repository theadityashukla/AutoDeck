"""PPTX build, previews and timing. Building needs only the fonts (layout QA measures
text); previews need LibreOffice and carry the repo's `render` marker (`-m render`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation

from autodeck.audit.manifest import canonical_pptx_digest
from autodeck.design.theme.tokens import DesignTokens
from autodeck.render.qa import libreoffice
from autodeck.render.renderer import SLIDE_TAG_PREFIX
from autodeck.studio.models import DeckArtifact
from autodeck.studio.render import (
    PLACEHOLDER_NAME,
    PPTX_FILENAME,
    PREVIEWS_DIRNAME,
    BuiltDeck,
    PreviewSet,
    RenderReport,
    build_pptx,
    render_artifact,
    render_previews,
    write_notes,
)
from tests.studio.helpers import FONTS_AVAILABLE, overflowing, with_slide_changes

needs_fonts = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")


def _notes(slide) -> str:
    """The notes page text (python-pptx types the frame as optional)."""
    frame = slide.notes_slide.notes_text_frame
    assert frame is not None
    return frame.text


def _texts(slide) -> list[str]:
    return [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame]


# -- build ---------------------------------------------------------------------------


@needs_fonts
def test_build_draws_every_slide(
    base_deck: DeckArtifact, tokens: DesignTokens, tmp_path: Path
) -> None:
    out = tmp_path / "nested" / "deck.pptx"
    built = build_pptx(base_deck, tokens=tokens, out_path=out)
    assert built.path == out and out.is_file()
    assert built.slide_ids == ("s1", "s2", "s3", "s4")
    assert built.placeholders == {}
    assert built.seconds > 0
    presentation = Presentation(str(out))
    slides = list(presentation.slides)
    assert [s.name for s in slides] == [f"{SLIDE_TAG_PREFIX}{i}" for i in built.slide_ids]
    # Text is copied verbatim; nothing is a placeholder.
    assert any("Serving cost now decides" in t for t in _texts(slides[0]))
    assert any(t == "41%" for t in _texts(slides[1]))
    assert all(shape.name != PLACEHOLDER_NAME for s in slides for shape in s.shapes)
    # The chart is a native chart (D10).
    assert any(getattr(shape, "has_chart", False) for shape in slides[2].shapes)


@needs_fonts
def test_speaker_notes_are_plain_text(
    base_deck: DeckArtifact, tokens: DesignTokens, tmp_path: Path
) -> None:
    built = build_pptx(base_deck, tokens=tokens, out_path=tmp_path / "deck.pptx")
    slides = list(Presentation(str(built.path)).slides)
    assert _notes(slides[1]) == base_deck.slide("s2").speaker_notes
    assert not slides[2].has_notes_slide  # s3 has no notes, so no notes page is made


@needs_fonts
def test_build_is_deterministic(
    base_deck: DeckArtifact, tokens: DesignTokens, tmp_path: Path
) -> None:
    a = build_pptx(base_deck, tokens=tokens, out_path=tmp_path / "a.pptx")
    b = build_pptx(base_deck, tokens=tokens, out_path=tmp_path / "b.pptx")
    assert canonical_pptx_digest(a.path) == canonical_pptx_digest(b.path)


@needs_fonts
def test_undrawable_slides_become_placeholders(
    base_deck: DeckArtifact, tokens: DesignTokens, tmp_path: Path
) -> None:
    deck = with_slide_changes(overflowing(base_deck), "s2", layout=None)
    built = build_pptx(deck, tokens=tokens, out_path=tmp_path / "deck.pptx")
    assert built.slide_ids == ("s1", "s2", "s3", "s4")
    assert list(built.placeholders) == ["s2", "s4"]
    assert built.placeholders["s2"] == "slide has no layout yet"
    assert "s4" in built.placeholders["s4"] and "text_fit" in built.placeholders["s4"]
    slides = list(Presentation(str(built.path)).slides)
    for index in (1, 3):
        names = [shape.name for shape in slides[index].shapes]
        assert names == [PLACEHOLDER_NAME]  # nothing half-drawn is left behind
        assert "could not be drawn" in _texts(slides[index])[0]
    # Notes are still written on a placeholder slide.
    assert _notes(slides[3]) == "Ask for a decision today."


def test_write_notes_skips_blank_notes(tmp_path: Path) -> None:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    write_notes(slide, "   ")
    assert not slide.has_notes_slide
    write_notes(slide, "one\ntwo")
    assert _notes(slide) == "one\ntwo"
    frame = slide.notes_slide.notes_text_frame
    assert frame is not None
    assert [p.text for p in frame.paragraphs] == ["one", "two"]


# -- timing lines --------------------------------------------------------------------


def test_timing_lines(tmp_path: Path) -> None:
    built = BuiltDeck(path=tmp_path / "d.pptx", slide_ids=("s1", "s2"), seconds=0.123)
    shown = PreviewSet(
        images=[tmp_path / "d-1.png", tmp_path / "d-2.png"], rendered=True, seconds=2.5
    )
    assert RenderReport(built, shown).timing_lines() == [
        "pptx build: 0.12s for 2 slides",
        "previews:   2.50s for 2 images",
    ]
    missing = PreviewSet(images=[], rendered=False, note="soffice not found", seconds=0.01)
    assert RenderReport(built, missing).timing_lines() == [
        "pptx build: 0.12s for 2 slides",
        "previews:   not rendered (soffice not found)",
    ]


# -- previews without LibreOffice ------------------------------------------------------


def test_a_render_error_is_reported_not_raised(
    tokens: DesignTokens, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"not really a pptx")
    out = tmp_path / "previews"
    out.mkdir()
    (out / "deck-1.png").write_bytes(b"stale")

    def fail(*args: object, **kwargs: object) -> object:
        raise libreoffice.FontSubstitutionRisk("Carlito is missing")

    monkeypatch.setattr(libreoffice, "render_pptx", fail)
    previews = render_previews(pptx, out_dir=out, tokens=tokens)
    assert not previews.rendered and previews.images == []
    assert "Carlito is missing" in previews.note
    assert previews.seconds >= 0
    assert not (out / "deck-1.png").exists()  # stale images are cleared first


def test_previews_of_a_missing_file(tokens: DesignTokens, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        render_previews(tmp_path / "nope.pptx", out_dir=tmp_path / "p", tokens=tokens)


# -- previews with LibreOffice ---------------------------------------------------------


@pytest.mark.render
def test_render_artifact_writes_pptx_and_one_png_per_slide(
    base_deck: DeckArtifact, tokens: DesignTokens, tmp_path: Path
) -> None:
    report = render_artifact(base_deck, tokens=tokens, out_dir=tmp_path / "renders")
    assert report.built.path == tmp_path / "renders" / PPTX_FILENAME
    assert report.built.placeholders == {}
    previews = report.previews
    assert previews.rendered, previews.note
    assert len(previews.images) == 4
    assert all(p.parent == tmp_path / "renders" / PREVIEWS_DIRNAME for p in previews.images)
    assert all(p.stat().st_size > 0 for p in previews.images)
    assert previews.seconds > 0
    assert len(report.timing_lines()) == 2


@pytest.mark.render
def test_a_second_render_replaces_the_first(
    base_deck: DeckArtifact, tokens: DesignTokens, tmp_path: Path
) -> None:
    render_artifact(base_deck, tokens=tokens, out_dir=tmp_path)
    shorter = base_deck.model_copy(update={"slides": base_deck.slides[:2]})
    report = render_artifact(shorter, tokens=tokens, out_dir=tmp_path)
    assert len(report.previews.images) == 2
    assert sorted((tmp_path / PREVIEWS_DIRNAME).glob("*.png")) == report.previews.images
