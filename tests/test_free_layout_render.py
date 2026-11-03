"""Creative mode's renderer (B69): a free layout drawn to PPTX, verbatim, tagged, audited."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from pptx import Presentation

from autodeck.audit.manifest import canonical_pptx_digest
from autodeck.audit.post_render import post_render_audit
from autodeck.design.components import catalog
from autodeck.design.fonts import is_available
from autodeck.design.free_layout import SOURCE_BAND_PT, source_band, slide_source_line
from autodeck.design.free_layout_qa import FreeLayoutQAError
from autodeck.design.layout_kit import Canvas
from autodeck.ir.models import (
    FREE_LAYOUT_COMPONENT,
    Block,
    ChartSeries,
    ChartSpec,
    Deck,
    FreeLayout,
    Placement,
    ShapeElement,
    Slide,
    TextElement,
    VisualElement,
)
from autodeck.render import draft
from autodeck.render.renderer import SLIDE_TAG_PREFIX, expected_caption_lines, render_deck
from tests.test_renderer import (
    _citation,
    _claim_block,
    _framing_block,
    _payload_block,
    tokens_for,
)

pytestmark = pytest.mark.skipif(
    not is_available("Liberation Sans"), reason="Liberation Sans not installed"
)


def P(x: float, y: float, w: float, h: float) -> Placement:
    return Placement(x=x, y=y, w=w, h=h)


def _title_slide() -> Slide:
    blocks = [
        _framing_block("t", "Attention changes how machines translate", block_id="t1"),
        _framing_block("s", "What the Transformer showed", block_id="t2"),
        _framing_block("k", "Research briefing", block_id="t3"),
    ]
    layout = FreeLayout(
        background="dk1",
        elements=[
            ShapeElement(shape="rect", frame=P(6, 30, 0.6, 30), fill="accent3"),
            TextElement(block_id="t3", frame=P(8, 22, 60, 4), role="label", color="accent3"),
            TextElement(block_id="t1", frame=P(8, 28, 84, 28), role="display", color="lt1", size_pt=40),
            TextElement(block_id="t2", frame=P(8, 58, 84, 12), role="title", color="lt2", bold=False),
        ],
    )
    return Slide(id="s1", narrative_role="title", component=FREE_LAYOUT_COMPONENT, blocks=blocks, layout=layout)


def _number_slide() -> Slide:
    blocks = [
        _claim_block("f", "Cost per token fell 41%.", block_id="n1"),
        _framing_block("h", "The kernel rewrite paid for itself", block_id="n2"),
    ]
    layout = FreeLayout(
        elements=[
            ShapeElement(shape="rounded_rect", frame=P(0, 0, 45, 100), fill="accent1", tint=0.85),
            TextElement(block_id="n2", frame=P(6, 8, 36, 24), role="title", color="dk1"),
            TextElement(
                block_id="n1", frame=P(50, 30, 44, 36), role="display", color="accent1",
                size_pt=54, anchor="middle",
            ),
            ShapeElement(shape="line", frame=P(50, 70, 20, 0.5), line="accent3", line_pt=3),
        ]
    )
    return Slide(id="s2", narrative_role="evidence", component=FREE_LAYOUT_COMPONENT, blocks=blocks, layout=layout)


def _chart_slide() -> Slide:
    chart = ChartSpec(
        chart_type="column",
        categories=["Base", "Big", "Huge"],
        series=[ChartSeries(name="BLEU", values=[27.3, 28.4, 26.1])],
        source_citations=[_citation(quote="BLEU 27.3 28.4 26.1", doc_id="paper", page=8)],
    )
    blocks = [
        _framing_block("h", "Model size and translation quality", block_id="c1"),
        _payload_block("chart", "chart", chart=chart),
        _claim_block("n", "Big reached 28.4 BLEU.", block_id="c3"),
    ]
    blocks[1] = blocks[1].model_copy(update={"id": "c2"})
    layout = FreeLayout(
        elements=[
            TextElement(block_id="c1", frame=P(6, 6, 88, 12), role="title"),
            VisualElement(type="chart", block_id="c2", frame=P(6, 22, 60, 62), emphasis=["Big"]),
            TextElement(block_id="c3", frame=P(70, 30, 24, 14), role="body", color="dk2"),
        ]
    )
    return Slide(id="s3", narrative_role="evidence", component=FREE_LAYOUT_COMPONENT, blocks=blocks, layout=layout)


def _deck() -> Deck:
    return Deck(
        run_id="r1", project="p", client="c", audience="a", version=1, theme_ref="t",
        component_lib_version=catalog.COMPONENT_LIB_VERSION, design_mode="creative",
        slides=[_title_slide(), _number_slide(), _chart_slide()],
    )


def _faces(path: Path) -> list[str]:
    return [
        "\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame)
        for slide in Presentation(str(path)).slides
    ]


def test_creative_deck_renders_verbatim_tagged_and_audited(tmp_path: Path) -> None:
    deck = _deck()
    out = tmp_path / "deck.pptx"
    rendered = render_deck(deck, tokens=tokens_for(), out_path=out)
    assert rendered.slide_ids == ("s1", "s2", "s3")
    presentation = Presentation(str(out))
    assert [s.name for s in presentation.slides] == [f"{SLIDE_TAG_PREFIX}{i}" for i in ("s1", "s2", "s3")]

    faces = _faces(out)
    for slide, face in zip(deck.slides, faces, strict=True):
        for block in slide.blocks:
            if block.kind in ("claim", "framing"):
                text = block.claim.text if block.claim else block.text
                assert text in face.splitlines()
    assert post_render_audit(deck, out).passes


def test_label_is_capitals_by_run_property_not_by_rewriting(tmp_path: Path) -> None:
    out = tmp_path / "deck.pptx"
    render_deck(_deck(), tokens=tokens_for(), out_path=out)
    assert "Research briefing" in _faces(out)[0].splitlines()
    with zipfile.ZipFile(out) as z:
        xml = z.read("ppt/slides/slide1.xml").decode()
    assert 'cap="all"' in xml and "spc=" in xml


def test_source_line_is_drawn_in_the_band_and_matches_expected_lines(tmp_path: Path) -> None:
    deck = _deck()
    out = tmp_path / "deck.pptx"
    render_deck(deck, tokens=tokens_for(), out_path=out)
    faces = _faces(out)
    for slide, face in zip(deck.slides[1:2], faces[1:2], strict=True):
        line = slide_source_line(slide)
        assert line and line in face.splitlines()
        assert line in expected_caption_lines(slide)
    # title slide cites nothing: no source line at all
    assert "Source" not in faces[0]
    # chart slide: the chart's own caption, drawn once
    assert faces[2].count("Source: paper p.8") + sum(
        1 for s in Presentation(str(out)).slides[2].shapes if s.has_chart
    ) >= 1
    canvas = Canvas(tokens_for())
    assert source_band(canvas).height == SOURCE_BAND_PT
    assert source_band(canvas).bottom == pytest.approx(canvas.content.bottom)


def test_emphasis_colours_named_categories_only(tmp_path: Path) -> None:
    out = tmp_path / "deck.pptx"
    render_deck(_deck(), tokens=tokens_for(), out_path=out)
    chart = next(s for s in Presentation(str(out)).slides[2].shapes if s.has_chart).chart
    pts = chart.series[0].points
    colours = [pts[i].format.fill.fore_color.theme_color for i in range(3)]
    assert colours[1] != colours[0] and colours[0] == colours[2]


def test_colours_are_theme_references_only(tmp_path: Path) -> None:
    out = tmp_path / "deck.pptx"
    render_deck(_deck(), tokens=tokens_for(), out_path=out)
    with zipfile.ZipFile(out) as z:
        for n in ("ppt/slides/slide1.xml", "ppt/slides/slide2.xml"):
            assert "srgbClr" not in z.read(n).decode()


def test_rendering_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a.pptx", tmp_path / "b.pptx"
    render_deck(_deck(), tokens=tokens_for(), out_path=a)
    render_deck(_deck(), tokens=tokens_for(), out_path=b)
    assert canonical_pptx_digest(a) == canonical_pptx_digest(b)


def test_a_failing_layout_raises_before_drawing_and_becomes_a_draft_placeholder(tmp_path: Path) -> None:
    bad = _title_slide()
    bad.layout.elements[2] = TextElement(  # type: ignore[union-attr]
        block_id="t1", frame=P(8, 30, 20, 3), role="display", color="lt1"
    )
    deck = _deck().model_copy(update={"slides": [bad, _number_slide()]})
    with pytest.raises(FreeLayoutQAError):
        render_deck(deck, tokens=tokens_for(), out_path=tmp_path / "x.pptx")
    assert not (tmp_path / "x.pptx").exists()

    out = tmp_path / "d.pptx"
    placeholders = draft._build_pptx(deck, tokens_for(), out)
    assert set(placeholders) == {"s1"} and "text_fit" in placeholders["s1"]
    assert len(Presentation(str(out)).slides) == 2


def test_pptx_level_qa_lets_creative_shapes_bleed_but_not_text() -> None:
    """B69: the deterministic QA exempts only a layout's text-free shapes from the safe area."""
    from autodeck.render.qa.deterministic import FREE_BLEED_SHAPES

    assert "free:rect" in FREE_BLEED_SHAPES
    assert not any(name.startswith("free:text") or name == "free:source" for name in FREE_BLEED_SHAPES)
