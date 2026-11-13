"""Base slide -> the v2 creative slide that v2's free-layout code draws and checks."""

from __future__ import annotations

import pytest

from autodeck.design.free_layout_qa import TEXT_FIT
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir import models as v2
from autodeck.ir.models import IconRef
from autodeck.studio.errors import MissingLayoutError
from autodeck.studio.models import Block, DeckArtifact, FigureData, SourceNote
from autodeck.studio.render_adapter import (
    MISSING_LAYOUT,
    NARRATIVE_ROLE,
    check_deck,
    check_slide,
    to_render_block,
    to_render_slide,
)
from tests.studio.helpers import FONTS_AVAILABLE, overflowing, with_slide_changes

needs_fonts = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")


def test_text_becomes_framing(base_deck: DeckArtifact) -> None:
    block = base_deck.slide("s2").block("number")
    assert block.source_note is not None
    rendered = to_render_block(block)
    assert isinstance(rendered, v2.Block)
    assert (rendered.id, rendered.slot, rendered.kind, rendered.text) == (
        "number",
        "number",
        "framing",
        "41%",
    )
    assert rendered.claim is None


def test_chart_keeps_its_data_and_has_no_citation(base_deck: DeckArtifact) -> None:
    block = base_deck.slide("s3").block("chart")
    assert block.chart is not None
    rendered = to_render_block(block)
    assert rendered.kind == "chart" and rendered.slot == "chart" and rendered.chart is not None
    spec = rendered.chart
    assert spec.chart_type == block.chart.chart_type
    assert spec.categories == block.chart.categories
    assert [(s.name, s.values) for s in spec.series] == [
        (s.name, s.values) for s in block.chart.series
    ]
    assert all(isinstance(s, v2.ChartSeries) for s in spec.series)
    assert spec.source_citations == []


def test_figure_and_icon() -> None:
    figure = Block(id="fig", kind="figure", figure=FigureData(asset_id="a1", caption="Rack"))
    rendered = to_render_block(figure)
    assert rendered.kind == "figure" and rendered.figure is not None
    assert (rendered.figure.asset_id, rendered.figure.caption) == ("a1", "Rack")
    icon_ref = IconRef(concept="growth", glyph_id="trending-up", color_token="accent1")
    icon = Block(
        id="ico", kind="icon", icon=icon_ref, source_note=SourceNote(doc_id="d", page=1)
    )
    rendered = to_render_block(icon)
    assert rendered.kind == "icon" and rendered.icon == icon_ref and rendered.slot == "ico"


def test_the_input_block_is_not_modified(base_deck: DeckArtifact) -> None:
    block = base_deck.slide("s3").block("chart")
    before = block.model_dump()
    to_render_block(block)
    assert block.model_dump() == before


@pytest.mark.parametrize("slide_id", ["s1", "s2", "s3", "s4"])
def test_every_fixture_slide_maps_to_a_valid_creative_slide(
    base_deck: DeckArtifact, slide_id: str
) -> None:
    slide = base_deck.slide(slide_id)
    rendered = to_render_slide(slide)
    assert isinstance(rendered, v2.Slide)
    assert rendered.id == slide_id
    assert rendered.narrative_role == NARRATIVE_ROLE
    assert rendered.component == v2.FREE_LAYOUT_COMPONENT
    assert rendered.layout is slide.layout
    assert [b.id for b in rendered.blocks] == [b.id for b in slide.blocks]
    assert rendered.speaker_notes == []


def test_a_slide_without_layout_cannot_be_mapped(base_deck: DeckArtifact) -> None:
    deck = with_slide_changes(base_deck, "s2", layout=None)
    with pytest.raises(MissingLayoutError):
        to_render_slide(deck.slide("s2"))


@needs_fonts
def test_the_fixture_passes_v2_layout_qa(base_deck: DeckArtifact, tokens: DesignTokens) -> None:
    assert check_deck(base_deck, tokens) == {}
    assert check_slide(base_deck.slide("s3"), tokens) == []


def test_a_missing_layout_is_a_finding_not_an_error(
    base_deck: DeckArtifact, tokens: DesignTokens
) -> None:
    deck = with_slide_changes(base_deck, "s2", layout=None)
    findings = check_slide(deck.slide("s2"), tokens)
    assert [(f.slide_id, f.block_id, f.check) for f in findings] == [("s2", "", MISSING_LAYOUT)]


@needs_fonts
def test_an_overflowing_layout_is_reported(
    base_deck: DeckArtifact, tokens: DesignTokens
) -> None:
    deck = with_slide_changes(overflowing(base_deck), "s2", layout=None)
    report = check_deck(deck, tokens)
    assert list(report) == ["s2", "s4"]  # deck order, only slides with findings
    assert any(f.check == TEXT_FIT and f.block_id == "heading" for f in report["s4"])
    assert [f.check for f in report["s2"]] == [MISSING_LAYOUT]
