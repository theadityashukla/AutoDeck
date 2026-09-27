"""Deterministic render QA (task 3b.2).

Fixture PPTXs are built directly with python-pptx — plain textboxes and rectangles, tagged
`cSld/@name = "autodeck:<id>"` by hand — so none of this depends on the render stage, which
is being built on another branch. The one exception is
`test_every_registered_component_preview_passes_clean`, which draws each component's own
golden `preview.EXAMPLES` content through its real renderer (still python-pptx only, no
LibreOffice) precisely because it is pinning that *real* output is arithmetically clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx.dml.color import RGBColor
from pptx.presentation import Presentation as PresentationType
from pptx.shapes.base import BaseShape
from pptx.slide import Slide
from pptx.util import Pt

from autodeck.design.components import catalog
from autodeck.design.components.preview import EXAMPLES
from autodeck.design.draw import theme_color
from autodeck.design.layout_kit import Box, Canvas
from autodeck.design.theme.master_builder import new_presentation
from autodeck.design.theme.tokens import DesignTokens
from autodeck.render.qa.deterministic import (
    CONTRAST_LARGE,
    CONTRAST_NORMAL,
    OVERLAP_TOLERANCE_PT,
    contrast_ratio,
    run_deterministic_qa,
)
from autodeck.render.renderer import SLIDE_TAG_PREFIX

TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"

_BLANK_LAYOUT = 6


def _tokens() -> DesignTokens:
    return DesignTokens.load(TOKENS_DIR / "dev.json")


def _tag(slide: Slide, slide_id: str) -> None:
    slide.name = f"{SLIDE_TAG_PREFIX}{slide_id}"


def _add_text(
    slide: Slide,
    box: Box,
    text: str,
    *,
    size: float | None = 16.0,
    color: str = "dk1",
    bold: bool = False,
) -> BaseShape:
    """A plain textbox with one run — the shape this file's checks are exercised against."""
    shape = slide.shapes.add_textbox(*box.as_emu())
    frame = shape.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    run = paragraph.add_run()
    run.text = text
    if size is not None:
        run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.theme_color = theme_color(color)
    return shape


def _add_rect(slide: Slide, box: Box, *, fill: str) -> BaseShape:
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *box.as_emu())
    shape.fill.solid()
    shape.fill.fore_color.theme_color = theme_color(fill)
    shape.line.fill.background()
    return shape


def _save(presentation: PresentationType, tmp_path: Path, name: str = "fixture.pptx") -> Path:
    path = tmp_path / name
    presentation.save(str(path))
    return path


# ---------------------------------------------------------------------------
# contrast_ratio
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fg", "bg", "ratio"),
    [("000000", "FFFFFF", 21.0), ("FFFFFF", "FFFFFF", 1.0), ("777777", "FFFFFF", 4.48)],
)
def test_contrast_ratio_matches_wcag(fg: str, bg: str, ratio: float) -> None:
    """To two decimal places, and symmetric: `contrast_ratio(bg, fg)` is the same."""
    assert round(contrast_ratio(fg, bg), 2) == ratio
    assert round(contrast_ratio(bg, fg), 2) == ratio


# ---------------------------------------------------------------------------
# The golden previews
# ---------------------------------------------------------------------------


def test_every_registered_component_preview_passes_clean(tmp_path: Path) -> None:
    """Render each component's `preview.EXAMPLES` content onto a tagged slide; zero findings.
    The golden previews were judged by eye; this pins that they are arithmetically clean too.
    """
    tokens = _tokens()
    presentation = new_presentation(tokens)
    canvas = Canvas(tokens)

    for name in catalog.known_components():
        renderer = catalog.renderer_for(name)
        slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
        renderer(slide, canvas, EXAMPLES[name])
        _tag(slide, name)

    path = _save(presentation, tmp_path, "gallery.pptx")
    findings = run_deterministic_qa(path, tokens)
    assert findings == []


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------


def test_two_overlapping_text_boxes_are_found(tmp_path: Path) -> None:
    """Two text boxes overlapping by 20pt: one "overlap" finding naming both shapes."""
    tokens = _tokens()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _tag(slide, "s1")

    box_a = Box(100.0, 100.0, 100.0, 100.0)
    box_b = Box(180.0, 180.0, 100.0, 100.0)
    shape_a = _add_text(slide, box_a, "First box")
    shape_b = _add_text(slide, box_b, "Second box")

    findings = run_deterministic_qa(_save(presentation, tmp_path), tokens)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check == "overlap"
    assert finding.slide_id == "s1"
    assert set(finding.shapes) == {shape_a.name, shape_b.name}
    assert finding.measured == pytest.approx(20.0)
    assert finding.threshold == OVERLAP_TOLERANCE_PT


def test_text_over_its_own_panel_is_not_an_overlap(tmp_path: Path) -> None:
    """A text box inside a filled rectangle with no text: no "overlap" finding."""
    tokens = _tokens()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _tag(slide, "s1")

    panel = Box(100.0, 100.0, 300.0, 150.0)
    _add_rect(slide, panel, fill="lt2")
    _add_text(slide, panel.pad(10.0), "Text on its own panel", color="dk1")

    findings = run_deterministic_qa(_save(presentation, tmp_path), tokens)

    assert findings == []


# ---------------------------------------------------------------------------
# Safe area
# ---------------------------------------------------------------------------


def test_a_shape_outside_the_safe_area_is_found(tmp_path: Path) -> None:
    """A text box 10pt past the right margin: "outside safe area", remedy `slot`."""
    tokens = _tokens()
    canvas = Canvas(tokens)
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _tag(slide, "s1")

    # The real `title` slot, shifted right so it still overlaps that declared slot (proving
    # the "slot" remedy) while its right edge sits exactly 10pt past the safe area.
    slot_box = catalog.spec_for("title", tokens).slot("title").box
    overshoot = 10.0
    shift = (canvas.safe.right + overshoot) - slot_box.right
    box = slot_box.offset(dx=shift).resize(height=40.0)

    shape = _add_text(slide, box, "Past the margin")

    findings = run_deterministic_qa(_save(presentation, tmp_path), tokens)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check == "outside safe area"
    assert finding.slide_id == "s1"
    assert finding.shapes == (shape.name,)
    assert finding.measured == pytest.approx(overshoot)
    assert finding.threshold == 0.0
    assert finding.remedy == "slot"
    # Some registered component declares a slot at this geometry (the shifted `title.title`
    # box itself, at minimum) — which one is not the point under test.
    assert "." in finding.remedy_detail


# ---------------------------------------------------------------------------
# Minimum size
# ---------------------------------------------------------------------------


def test_a_run_below_the_minimum_size_is_found(tmp_path: Path) -> None:
    """An 8pt run with the dev tokens' 10pt minimum: "below minimum size", measured 8,
    threshold 10, remedy `token`."""
    tokens = _tokens()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _tag(slide, "s1")

    box = Box(100.0, 100.0, 200.0, 40.0)
    shape = _add_text(slide, box, "Too small to read", size=8.0)

    findings = run_deterministic_qa(_save(presentation, tmp_path), tokens)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check == "below minimum size"
    assert finding.shapes == (shape.name,)
    assert finding.measured == pytest.approx(8.0)
    assert finding.threshold == pytest.approx(tokens.typography.minimum)
    assert finding.threshold == pytest.approx(10.0)
    assert finding.remedy == "token"


def test_a_run_with_no_explicit_size_is_resolved_not_skipped(tmp_path: Path) -> None:
    """A run inheriting its size from the theme is checked at the inherited size."""
    tokens = _tokens()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _tag(slide, "s1")

    box = Box(100.0, 100.0, 200.0, 40.0)
    shape = slide.shapes.add_textbox(*box.as_emu())
    frame = shape.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.font.size = Pt(8.0)  # the paragraph's own default — "the theme" a bare run
    # inherits from when it sets no size of its own.
    run = paragraph.add_run()
    run.text = "Inherits its size"
    run.font.color.theme_color = theme_color("dk1")
    assert run.font.size is None  # the run itself sets nothing — this is the case under test

    findings = run_deterministic_qa(_save(presentation, tmp_path), tokens)

    size_findings = [f for f in findings if f.check == "below minimum size"]
    assert len(size_findings) == 1
    assert size_findings[0].measured == pytest.approx(8.0)
    assert size_findings[0].threshold == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------


def test_low_contrast_text_on_a_filled_panel_is_found(tmp_path: Path) -> None:
    """Light grey text on a light accent panel: "insufficient contrast" with the measured
    ratio, remedy `token`."""
    tokens = _tokens()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _tag(slide, "s1")

    fg_hex, bg_hex = "AAAAAA", "CCCCCC"
    expected_ratio = contrast_ratio(fg_hex, bg_hex)
    assert expected_ratio < CONTRAST_NORMAL  # the fixture is genuinely low-contrast

    from pptx.enum.shapes import MSO_SHAPE

    panel = Box(100.0, 100.0, 300.0, 150.0)
    rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *panel.as_emu())
    rect.fill.solid()
    rect.fill.fore_color.rgb = RGBColor.from_string(bg_hex)
    rect.line.fill.background()

    box = panel.pad(10.0)
    shape = slide.shapes.add_textbox(*box.as_emu())
    frame = shape.text_frame
    frame.word_wrap = True
    run = frame.paragraphs[0].add_run()
    run.text = "Hard to read"
    run.font.size = Pt(16.0)
    run.font.color.rgb = RGBColor.from_string(fg_hex)

    findings = run_deterministic_qa(_save(presentation, tmp_path), tokens)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check == "insufficient contrast"
    assert finding.shapes == (shape.name,)
    assert finding.measured == pytest.approx(round(expected_ratio, 2))
    assert finding.threshold == CONTRAST_NORMAL
    assert finding.remedy == "token"


def test_large_bold_text_uses_the_large_threshold(tmp_path: Path) -> None:
    """A colour pair at ratio ~3.5: flagged for 12pt text, not flagged for 14pt bold text."""
    tokens = _tokens()
    fg_hex, bg_hex = "808080", "FFFFFF"  # ~3.95:1 — below CONTRAST_NORMAL, at/above LARGE
    ratio = contrast_ratio(fg_hex, bg_hex)
    assert CONTRAST_LARGE <= ratio < CONTRAST_NORMAL

    presentation = new_presentation(tokens)

    def _slide_with_run(slide_id: str, *, size: float, bold: bool) -> None:
        slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
        _tag(slide, slide_id)
        box = Box(100.0, 100.0, 200.0, 40.0)
        shape = slide.shapes.add_textbox(*box.as_emu())
        frame = shape.text_frame
        frame.word_wrap = True
        run = frame.paragraphs[0].add_run()
        run.text = "Borderline contrast"
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor.from_string(fg_hex)

    _slide_with_run("normal", size=12.0, bold=False)
    _slide_with_run("large_bold", size=14.0, bold=True)

    findings = run_deterministic_qa(_save(presentation, tmp_path), tokens)
    by_slide = {f.slide_id: f for f in findings if f.check == "insufficient contrast"}

    assert "normal" in by_slide
    assert by_slide["normal"].threshold == CONTRAST_NORMAL
    assert "large_bold" not in by_slide


# ---------------------------------------------------------------------------
# Attribution and purity
# ---------------------------------------------------------------------------


def test_an_untagged_slide_raises(tmp_path: Path) -> None:
    """`ValueError` — findings must be attributable to an IR slide."""
    tokens = _tokens()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _add_text(slide, Box(100.0, 100.0, 200.0, 40.0), "No tag on this slide")
    # `slide.name` is left at its default (empty) — never tagged.

    with pytest.raises(ValueError):
        run_deterministic_qa(_save(presentation, tmp_path), tokens)


def test_qa_is_pure(tmp_path: Path) -> None:
    """The file's bytes are identical before and after; two runs return equal lists."""
    tokens = _tokens()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[_BLANK_LAYOUT])
    _tag(slide, "s1")
    panel = Box(100.0, 100.0, 300.0, 150.0)
    _add_rect(slide, panel, fill="lt2")
    _add_text(slide, panel.pad(10.0), "Stable content", color="dk1")

    path = _save(presentation, tmp_path)
    before = path.read_bytes()

    first = run_deterministic_qa(path, tokens)
    second = run_deterministic_qa(path, tokens)

    assert first == second
    assert path.read_bytes() == before
