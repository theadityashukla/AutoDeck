"""A concept's palette reaches the tokens, the QA and the render."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import run, slide_args

from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.models import Slide


def fonts_available() -> bool:
    try:
        DesignTokens.load(run.DEFAULT_TOKENS_PATH).require_fonts()
    except Exception:
        return False
    return True


def test_palette_override_reaches_the_tokens(bench_dir: Path) -> None:
    before = run.DEFAULT_TOKENS_PATH.read_bytes()
    concept = run.load_concept(bench_dir / "concepts" / "ticket.yaml")
    base = DesignTokens.load(run.DEFAULT_TOKENS_PATH)
    tokens = run.tokens_for_concept(concept)
    assert tokens.palette.lt1 == "FFF8E1" and tokens.palette.accent1 == "E4002B"
    assert tokens.palette.dk1 == base.palette.dk1  # omitted slots keep the default
    assert tokens.typography == base.typography and tokens.spacing == base.spacing
    assert tokens.palette.as_scheme()["accent1"] == "E4002B"  # what the theme is built from
    assert run.DEFAULT_TOKENS_PATH.read_bytes() == before  # the repository file is untouched


def test_none_concept_is_the_default_tokens(bench_dir: Path) -> None:
    concept = run.load_concept(bench_dir / "concepts" / "none.yaml")
    assert run.tokens_for_concept(concept) == DesignTokens.load(run.DEFAULT_TOKENS_PATH)


def test_bad_palette_is_refused(bench_dir: Path) -> None:
    with pytest.raises(run.BenchInputError, match="unknown palette slot"):
        run.tokens_for_concept(run.Concept(id="x", palette={"accent9": "#FFFFFF"}))
    with pytest.raises(run.BenchInputError, match="bad palette colour"):
        run.tokens_for_concept(run.Concept(id="x", palette={"accent1": "red"}))


def test_palette_and_roles_appear_in_the_prompt(bench_dir: Path) -> None:
    concept = run.load_concept(bench_dir / "concepts" / "ticket.yaml")
    tokens = run.tokens_for_concept(concept)
    system = run.build_system_prompt(bench_dir, tokens, concept)
    assert "accent1: #E4002B -- the price ticket" in system
    assert "safe area" in system.lower() and "glyph_id" in system
    case = run.load_case(bench_dir / "cases" / "c1.yaml")
    user = run.build_user_text(case, concept)
    assert "Concept: A shelf ticket." in user and "38%: lower serving cost" in user
    none = run.load_concept(bench_dir / "concepts" / "none.yaml")
    assert "None given" in run.build_user_text(case, none)


@pytest.mark.skipif(not fonts_available(), reason="needs the Carlito font to measure text")
def test_palette_override_reaches_qa_contrast(bench_dir: Path) -> None:
    slide = Slide.model_validate({**slide_args()["slide"], "id": "c1"})
    default = DesignTokens.load(run.DEFAULT_TOKENS_PATH)
    assert run.qa_findings(slide, default) == []
    washed = run.tokens_for_concept(
        run.Concept(id="washed", palette={"dk1": "#EEEEEE", "lt1": "#FFFFFF"})
    )
    findings = run.qa_findings(slide, washed)
    assert [f["check"] for f in findings] == ["contrast"]


@pytest.mark.skipif(not fonts_available(), reason="needs the Carlito font to measure text")
def test_an_unknown_icon_is_a_render_finding_not_a_clean_slide() -> None:
    args = slide_args()["slide"]
    args["id"] = "c1"
    args["blocks"].append(
        {
            "id": "i",
            "kind": "icon",
            "icon": {"concept": "x", "glyph_id": "no-such-glyph", "color_token": "accent1"},
        }
    )
    args["layout"]["elements"].append(
        {"type": "icon", "block_id": "i", "frame": {"x": 5, "y": 40, "w": 10, "h": 15}}
    )
    findings = run.qa_findings(
        Slide.model_validate(args), DesignTokens.load(run.DEFAULT_TOKENS_PATH)
    )
    assert [f["check"] for f in findings] == ["render"]


@pytest.mark.render
def test_palette_override_reaches_the_render(bench_dir: Path, tmp_path: Path) -> None:
    from PIL import Image

    concept = run.load_concept(bench_dir / "concepts" / "ticket.yaml")
    tokens = run.tokens_for_concept(concept)
    args = slide_args()["slide"]
    args["id"] = "c1"
    args["layout"]["background"] = "lt1"
    args["layout"]["elements"].insert(
        0,
        {
            "type": "shape",
            "shape": "rect",
            "frame": {"x": 0, "y": 60, "w": 100, "h": 40},
            "fill": "accent1",
        },
    )
    slide = Slide.model_validate(args)
    assert run.qa_findings(slide, tokens) == []
    note = run.render_slide(
        slide, tokens, pptx_path=tmp_path / "s.pptx", png_path=tmp_path / "s.png"
    )
    assert note == ""
    with Image.open(tmp_path / "s.png") as image:
        rgb = image.convert("RGB")
        w, h = rgb.size
        assert rgb.getpixel((w - 5, 5)) == (0xFF, 0xF8, 0xE1)  # background: lt1
        assert rgb.getpixel((w // 2, h - 20)) == (0xE4, 0x00, 0x2B)  # shape: accent1
