"""The render stage (task 3b.1).

Decks rendered here must pass `require_safe_to_render`: claims `supported`, validated
citations. A fixture with `unverified` claims is blocked before any file is written, which
is correct behaviour and is itself one of the tests.
"""

from __future__ import annotations

import dataclasses
import itertools
import zipfile
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from pptx import Presentation

from autodeck.audit.manifest import canonical_pptx_digest
from autodeck.design.components import catalog, preview
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import (
    Block,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    Deck,
    DiagramSpec,
    LabelFraming,
    ProcessFlowSpec,
    ProcessStep,
    Slide,
    SlideStyle,
    Verdict,
)
from autodeck.pipeline.orchestrator import RenderBlocked
from autodeck.render.renderer import (
    SLIDE_TAG_PREFIX,
    StyleNotHonoured,
    UnplacedBlockError,
    adapt_slide,
    render_deck,
    scaled_tokens,
    source_line,
)

TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"

#: Any real installed font does — these tests check the render *plumbing*, never a
#: font-specific value. Same choice `test_catalog.py` and `test_components_13_14_15.py` make.
TEST_FAMILY = "Liberation Sans"


def tokens_for(family: str = TEST_FAMILY) -> DesignTokens:
    base = DesignTokens.load(TOKENS_DIR / "dev.json")
    return base.model_copy(
        update={
            "typography": base.typography.model_copy(update={"major": family, "minor": family})
        }
    )


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_ids = itertools.count(1)


def _next_id() -> str:
    return f"b{next(_ids)}"


def _citation(quote: str = "Cost per token fell from $0.71 to $0.42.", **kw: Any) -> Citation:
    kw.setdefault("doc_id", "vendor-report")
    kw.setdefault("page", 4)
    kw.setdefault("bbox", (10.0, 20.0, 300.0, 44.0))
    kw.setdefault("retrieved_by", "validator")
    return Citation.for_quote(quote=quote, **kw)


def _claim(
    text: str, *, verdict: Verdict = "supported", citations: list[Citation] | None = None
) -> Claim:
    return Claim(text=text, citations=citations or [_citation(quote=text)], verdict=verdict)


def _claim_block(
    slot: str,
    text: str,
    *,
    verdict: Verdict = "supported",
    citations: list[Citation] | None = None,
    block_id: str | None = None,
) -> Block:
    return Block(
        id=block_id or _next_id(),
        kind="claim",
        slot=slot,
        claim=_claim(text, verdict=verdict, citations=citations),
    )


def _framing_block(slot: str, text: str, *, block_id: str | None = None) -> Block:
    return Block(id=block_id or _next_id(), kind="framing", slot=slot, text=text)


def _payload_block(slot: str, kind: str, **payload: Any) -> Block:
    return Block(id=_next_id(), kind=kind, slot=slot, **payload)  # type: ignore[arg-type]


def _slide(
    slide_id: str,
    component: str,
    blocks: list[Block],
    *,
    speaker_notes: list[Block] | None = None,
    style: SlideStyle | None = None,
) -> Slide:
    return Slide(
        id=slide_id,
        narrative_role="test",
        component=component,
        blocks=blocks,
        speaker_notes=speaker_notes or [],
        style=style or SlideStyle(),
    )


def _deck(*slides: Slide) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="a",
        version=1,
        theme_ref="t",
        component_lib_version=catalog.COMPONENT_LIB_VERSION,
        slides=list(slides),
    )


def _text_frame(shape: Any) -> Any:
    """`shape.text_frame` — `shape` is deliberately `Any`: `BaseShape` has no `text_frame`
    attribute in the stub, and every call site here already guards with `has_text_frame`."""
    return shape.text_frame


def _shape_text(shape: Any) -> str:
    text: str = _text_frame(shape).text
    return text


def _bullets_slide(slide_id: str = "s1", *, style: SlideStyle | None = None) -> Slide:
    return _slide(
        slide_id,
        "bullets_supporting",
        [
            _claim_block("headline", "The kernel rewrite cut cost per token by 41%."),
            _framing_block("points", "The attention kernel rewrite removed the bottleneck."),
            _framing_block("points", "Batch composition now adapts to load."),
        ],
        style=style,
    )


# ---------------------------------------------------------------------------
# 1. The gate
# ---------------------------------------------------------------------------


def test_a_safe_deck_renders_one_tagged_slide_per_ir_slide_in_order(tmp_path: Path) -> None:
    """A validated multi-slide deck renders; PPTX slide *i* carries tag
    `autodeck:<deck.slides[i].id>`; `RenderedDeck.slide_ids` matches."""
    deck = _deck(_bullets_slide("s1"), _bullets_slide("s2"))
    out_path = tmp_path / "deck.pptx"

    rendered = render_deck(deck, tokens=tokens_for(), out_path=out_path)

    assert rendered.slide_ids == ("s1", "s2")
    assert out_path.exists()

    presentation = Presentation(str(out_path))
    names = [slide.name for slide in presentation.slides]
    assert names == [f"{SLIDE_TAG_PREFIX}s1", f"{SLIDE_TAG_PREFIX}s2"]


def test_an_unsafe_deck_is_refused_before_any_file_exists(tmp_path: Path) -> None:
    """A deck with one `contradicted` claim raises `RenderBlocked`, and `out_path` does not
    exist afterwards."""
    deck = _deck(
        _slide(
            "s1",
            "bullets_supporting",
            [
                _claim_block(
                    "headline",
                    "The kernel rewrite cut cost per token by 41%.",
                    verdict="contradicted",
                ),
                _framing_block("points", "A point."),
            ],
        )
    )
    out_path = tmp_path / "deck.pptx"

    with pytest.raises(RenderBlocked):
        render_deck(deck, tokens=tokens_for(), out_path=out_path)

    assert not out_path.exists()


# ---------------------------------------------------------------------------
# 2. No fact is dropped
# ---------------------------------------------------------------------------


def test_a_block_with_no_home_is_an_error_not_a_skip() -> None:
    """A face block whose `slot` matches no field of the component's content dataclass
    raises `UnplacedBlockError` naming the block. A dropped block is a deleted fact."""
    content_type = catalog.registration("title").content_type
    slide = _slide(
        "s1",
        "title",
        [
            _framing_block("title", "A Deck Title"),
            _framing_block("nonexistent_slot", "This has nowhere to go."),
        ],
    )

    with pytest.raises(UnplacedBlockError, match="nonexistent_slot"):
        adapt_slide(slide, content_type)


def test_claim_text_reaches_the_slide_character_for_character(tmp_path: Path) -> None:
    """A claim containing an en dash, a non-breaking space, `%` and a trailing period appears
    byte-identical in the rendered slide's text frames."""
    claim_text = "Latency fell 41% – measured on the full suite."  # noqa: RUF001
    deck = _deck(
        _slide(
            "s1",
            "callout_takeaway",
            [_claim_block("takeaway", claim_text)],
        )
    )
    out_path = tmp_path / "deck.pptx"
    render_deck(deck, tokens=tokens_for(), out_path=out_path)

    presentation = Presentation(str(out_path))
    all_text = "\n".join(
        _shape_text(shape) for shape in presentation.slides[0].shapes if shape.has_text_frame
    )
    assert claim_text in all_text


def test_every_registered_component_can_be_adapted() -> None:
    """For each name in `known_components()`, build a slide from its `preview.EXAMPLES`
    content (one block per populated field), adapt it, and assert it equals the example —
    no component is silently unrenderable by the generic rule plus `ADAPTERS`."""
    for name in catalog.known_components():
        _check_component_adapts(name)


def _check_component_adapts(name: str) -> None:
    example = preview.EXAMPLES[name]
    content_type = catalog.registration(name).content_type
    hints = get_type_hints(content_type)

    if name == "two_column_compare":
        _check_two_column_compare_adapts(example, content_type)
        return
    if name == "data_card_grid":
        _check_data_card_grid_adapts(example, content_type)
        return

    blocks: list[Block] = []
    for f in dataclasses.fields(content_type):
        if f.name in ("accent", "source"):
            continue
        value = getattr(example, f.name)
        hint = hints[f.name]
        if hint in (DiagramSpec, ChartSpec):
            payload_field = "diagram" if hint is DiagramSpec else "chart"
            kind = payload_field
            blocks.append(_payload_block(f.name, kind, **{payload_field: value}))
        elif isinstance(value, list):
            blocks.extend(_framing_block(f.name, item) for item in value)
        elif value:
            blocks.append(_framing_block(f.name, value))

    style = SlideStyle(accent=example.accent) if "accent" in hints else SlideStyle()
    slide = _slide("s1", name, blocks, style=style)

    content, warnings = adapt_slide(slide, content_type)
    content = cast(Any, content)

    for f in dataclasses.fields(content_type):
        if f.name in ("accent", "source"):
            continue
        assert getattr(content, f.name) == getattr(example, f.name), (name, f.name)
    if "accent" in hints:
        assert content.accent == example.accent, name
    assert warnings == []


def _check_two_column_compare_adapts(example: Any, content_type: type) -> None:
    blocks = [
        _framing_block("headline", example.headline),
        _framing_block("left_title", example.left.title),
        *[_framing_block("left_points", p) for p in example.left.points],
        _framing_block("right_title", example.right.title),
        *[_framing_block("right_points", p) for p in example.right.points],
    ]
    slide = _slide("s1", "two_column_compare", blocks)

    content, warnings = adapt_slide(slide, content_type)
    content = cast(Any, content)

    assert content.headline == example.headline
    assert content.left.title == example.left.title
    assert content.left.points == example.left.points
    assert content.right.title == example.right.title
    assert content.right.points == example.right.points
    assert content.left.accent == slide.style.accent
    assert content.right.accent == slide.style.accent
    assert warnings == []


def _check_data_card_grid_adapts(example: Any, content_type: type) -> None:
    blocks = [_framing_block("headline", example.headline)]
    for card in example.cards:
        blocks.append(_framing_block("card_label", card.label))
        blocks.append(_framing_block("card_value", card.value))
    slide = _slide("s1", "data_card_grid", blocks, style=SlideStyle(accent=example.accent))

    content, warnings = adapt_slide(slide, content_type)
    content = cast(Any, content)

    assert content.headline == example.headline
    assert content.cards == example.cards
    assert content.accent == example.accent
    assert warnings == []


# ---------------------------------------------------------------------------
# 5. Style is honoured or reported
# ---------------------------------------------------------------------------


def test_style_accent_and_type_scale_are_applied(tmp_path: Path) -> None:
    """`accent="accent3"` puts `accent3` into the content; `type_scale="spacious"` produces a
    larger rendered headline font size than `"standard"` for the same slide."""
    content_type = catalog.registration("callout_takeaway").content_type
    slide = _slide(
        "s1",
        "callout_takeaway",
        [_claim_block("takeaway", "A takeaway.")],
        style=SlideStyle(accent="accent3"),
    )
    content, _ = adapt_slide(slide, content_type)
    assert cast(Any, content).accent == "accent3"

    headline_text = "The kernel rewrite cut cost per token by 41%."

    def render_and_get_size(scale: str) -> float:
        deck = _deck(
            _slide(
                "s1",
                "bullets_supporting",
                [
                    _claim_block("headline", headline_text),
                    _framing_block("points", "A point."),
                ],
                style=SlideStyle(type_scale=scale),  # type: ignore[arg-type]
            )
        )
        out_path = tmp_path / f"deck_{scale}.pptx"
        render_deck(deck, tokens=tokens_for(), out_path=out_path)
        presentation = Presentation(str(out_path))
        for shape in presentation.slides[0].shapes:
            if shape.has_text_frame and headline_text in _shape_text(shape):
                run = _text_frame(shape).paragraphs[0].runs[0]
                assert run.font.size is not None
                return run.font.size.pt
        raise AssertionError("headline shape not found")

    standard_size = render_and_get_size("standard")
    spacious_size = render_and_get_size("spacious")
    assert spacious_size > standard_size


def test_style_a_component_cannot_express_is_reported(tmp_path: Path) -> None:
    """`column_balance="lead_left"` on a component with no such field yields one
    `StyleNotHonoured` in `RenderedDeck.warnings`; the default value yields none."""
    deck_default = _deck(_bullets_slide("s1"))
    rendered_default = render_deck(
        deck_default, tokens=tokens_for(), out_path=tmp_path / "default.pptx"
    )
    assert rendered_default.warnings == ()

    deck_lead_left = _deck(_bullets_slide("s1", style=SlideStyle(column_balance="lead_left")))
    rendered_lead_left = render_deck(
        deck_lead_left, tokens=tokens_for(), out_path=tmp_path / "lead_left.pptx"
    )
    assert rendered_lead_left.warnings == (
        StyleNotHonoured(slide_id="s1", field="column_balance", component="bullets_supporting"),
    )


def test_speaker_notes_are_written_with_their_sources(tmp_path: Path) -> None:
    """A notes claim's text and its `doc p.N` source both appear on that slide's notes page."""
    notes_text = "Internally, throughput improved 62.9% on the same benchmark."
    citation = _citation(quote=notes_text, doc_id="internal-benchmark", page=9)
    deck = _deck(
        _slide(
            "s1",
            "bullets_supporting",
            [
                _claim_block("headline", "Headline claim."),
                _framing_block("points", "A point."),
            ],
            speaker_notes=[_claim_block("note", notes_text, citations=[citation])],
        )
    )
    out_path = tmp_path / "deck.pptx"
    render_deck(deck, tokens=tokens_for(), out_path=out_path)

    presentation = Presentation(str(out_path))
    notes_text_frame = presentation.slides[0].notes_slide.notes_text_frame
    assert notes_text_frame is not None
    notes = notes_text_frame.text

    assert notes_text in notes
    assert source_line([citation]) in notes
    assert "internal-benchmark p.9" in notes


# ---------------------------------------------------------------------------
# 6. Determinism (A6, as corrected by B29)
# ---------------------------------------------------------------------------


def test_two_renders_are_normalised_comparable(tmp_path: Path) -> None:
    """A6 as corrected by B29: rendering the same deck twice gives equal
    `canonical_pptx_digest` values, while the raw bytes are allowed to differ."""
    deck = _deck(_bullets_slide("s1"))
    tokens = tokens_for()

    path_a = tmp_path / "a.pptx"
    path_b = tmp_path / "b.pptx"
    render_deck(deck, tokens=tokens, out_path=path_a)
    render_deck(deck, tokens=tokens, out_path=path_b)

    assert canonical_pptx_digest(path_a) == canonical_pptx_digest(path_b)


# ---------------------------------------------------------------------------
# 7. No image fallback (D10/D11)
# ---------------------------------------------------------------------------


def test_no_image_part_is_written_for_a_deck_without_figures(tmp_path: Path) -> None:
    """A deck with a chart and a diagram — the two native, non-text component families
    registered today — renders with zero `ppt/media/` parts.

    No registered component (`known_components()`) exposes an `IconRef` field, so there is
    no way to exercise an icon-bearing slide through the render stage as it exists today;
    `Frame.icon` draws native vector shapes, never a picture, so it would not produce a
    media part either, but that is not directly exercised here. See the handover report.
    """
    chart_citation = _citation(
        quote="Cost per token fell to $0.42 in Q4.", doc_id="finance", page=2
    )
    chart = ChartSpec(
        chart_type="bar",
        categories=["Q4"],
        series=[ChartSeries(name="Cost per token ($)", values=[0.42])],
        source_citations=[chart_citation],
    )
    diagram = DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        process_flow=ProcessFlowSpec(
            steps=[
                ProcessStep(
                    id="discover",
                    label="Discover",
                    order=1,
                    framing=LabelFraming(reason="stage_name"),
                ),
                ProcessStep(
                    id="build",
                    label="Build",
                    order=2,
                    framing=LabelFraming(reason="stage_name"),
                ),
            ]
        ),
    )
    deck = _deck(
        _slide(
            "s1",
            "chart_focus",
            [
                _framing_block("headline", "Cost per token fell every quarter"),
                _payload_block("chart", "chart", chart=chart),
            ],
        ),
        _slide(
            "s2",
            "framework_diagram",
            [
                _framing_block("headline", "A two-step rollout gets the platform live"),
                _payload_block("diagram", "diagram", diagram=diagram),
            ],
        ),
    )
    out_path = tmp_path / "deck.pptx"
    render_deck(deck, tokens=tokens_for(), out_path=out_path)

    with zipfile.ZipFile(out_path) as archive:
        media = [name for name in archive.namelist() if name.startswith("ppt/media/")]
    assert media == []


# ---------------------------------------------------------------------------
# scaled_tokens
# ---------------------------------------------------------------------------


def test_scaled_tokens_standard_is_identity() -> None:
    tokens = tokens_for()
    assert scaled_tokens(tokens, "standard") is tokens


def test_scaled_tokens_spacious_multiplies_every_size() -> None:
    tokens = tokens_for()
    scaled = scaled_tokens(tokens, "spacious")
    assert scaled.typography.title == pytest.approx(tokens.typography.title * 1.1)
    assert scaled.typography.body == pytest.approx(tokens.typography.body * 1.1)
