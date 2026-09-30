"""The render stage (task 3b.1).

Decks rendered here must pass `require_safe_to_render`: claims `supported`, validated
citations. A fixture with `unverified` claims is blocked before any file is written, which
is correct behaviour and is itself one of the tests.
"""

from __future__ import annotations

import dataclasses
import itertools
import re
import zipfile
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from pptx import Presentation

from autodeck.audit.manifest import canonical_pptx_digest
from autodeck.design.components import catalog, preview
from autodeck.design.layout_kit import Canvas
from autodeck.design.theme.master_builder import new_presentation, save_themed
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import (
    Block,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    Deck,
    DiagramAxis,
    DiagramSpec,
    LabelFraming,
    ProcessFlowSpec,
    ProcessStep,
    QuadrantItem,
    Slide,
    SlideStyle,
    TwoByTwoSpec,
    Verdict,
)
from autodeck.pipeline.orchestrator import RenderBlocked
from autodeck.render.extract import extract_slide_text
from autodeck.render.renderer import (
    SLIDE_TAG_PREFIX,
    RenderStageError,
    StyleNotHonoured,
    UnplacedBlockError,
    adapt_slide,
    expected_caption_lines,
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
            [_framing_block("label", "Takeaway"), _claim_block("takeaway", claim_text)],
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
        [_framing_block("label", "Takeaway"), _claim_block("takeaway", "A takeaway.")],
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
# 8. The source line: one walk, real or absent — never a bare "Source:"
# ---------------------------------------------------------------------------

NODE_CLAIM = "Enterprise accounts renewed at 92% across the last four quarters measured."


def _node_claim_diagram(citation: Citation) -> DiagramSpec:
    """A 2x2 whose ONLY claim is on the "Enterprise" node; every other label is framing."""
    return DiagramSpec(
        relationship="classification",
        kind="two_by_two",
        two_by_two=TwoByTwoSpec(
            x_axis=DiagramAxis(name="Cost to serve", low="Low", high="High"),
            y_axis=DiagramAxis(name="Adoption speed", low="Slow", high="Fast"),
            items=[
                QuadrantItem(
                    id="self_serve",
                    label="Self-serve",
                    x=0.15,
                    y=0.85,
                    framing=LabelFraming(reason="category_name"),
                ),
                QuadrantItem(
                    id="enterprise",
                    label="Enterprise",
                    x=0.85,
                    y=0.25,
                    claim=Claim(text=NODE_CLAIM, citations=[citation], verdict="supported"),
                ),
            ],
        ),
    )


def _node_claim_slide(citation: Citation) -> Slide:
    return _slide(
        "s1",
        "framework_diagram",
        [
            _framing_block("headline", "Enterprise deals justify the higher cost to serve"),
            _payload_block("diagram", "diagram", diagram=_node_claim_diagram(citation)),
        ],
    )


def _face_text(presentation: Any, index: int = 0) -> str:
    return "\n".join(
        _shape_text(shape)
        for shape in presentation.slides[index].shapes
        if shape.has_text_frame
    )


def test_a_slide_whose_only_claim_is_on_a_diagram_node_gets_a_real_source_line(
    tmp_path: Path,
) -> None:
    """The source line pools citations from `slide.claim_sites()`, not from
    `Block.kind == "claim"` — which never sees a claim one level down inside a diagram, and
    is how this slide rendered a bare "Source:" before."""
    citation = _citation(quote=NODE_CLAIM, doc_id="q3-segmentation-report", page=6)
    slide = _node_claim_slide(citation)

    content, _ = adapt_slide(slide, catalog.registration("framework_diagram").content_type)
    assert cast(Any, content).source == "Source: q3-segmentation-report p.6"

    out_path = tmp_path / "deck.pptx"
    render_deck(_deck(slide), tokens=tokens_for(), out_path=out_path)
    face = _face_text(Presentation(str(out_path)))

    assert "Source: q3-segmentation-report p.6" in face.splitlines()
    assert "Source:" not in [line.strip() for line in face.splitlines()]


def test_a_diagram_nodes_full_claim_is_written_to_the_notes_not_the_face(
    tmp_path: Path,
) -> None:
    """The node's box draws its label only. The full assertion behind the label goes to the
    notes page, text then source line, like any notes claim."""
    citation = _citation(quote=NODE_CLAIM, doc_id="q3-segmentation-report", page=6)
    out_path = tmp_path / "deck.pptx"
    render_deck(_deck(_node_claim_slide(citation)), tokens=tokens_for(), out_path=out_path)

    presentation = Presentation(str(out_path))
    face = _face_text(presentation)
    assert "Enterprise" in face
    assert NODE_CLAIM not in face

    frame = presentation.slides[0].notes_slide.notes_text_frame
    assert frame is not None
    assert frame.text.splitlines() == [NODE_CLAIM, "Source: q3-segmentation-report p.6"]


def test_node_claims_follow_the_authored_speaker_notes(tmp_path: Path) -> None:
    """Authored speaker notes keep their place first; the diagram-node claims follow."""
    citation = _citation(quote=NODE_CLAIM, doc_id="q3-segmentation-report", page=6)
    slide = _node_claim_slide(citation)
    slide.speaker_notes.append(_framing_block("note", "Say this first."))

    out_path = tmp_path / "deck.pptx"
    render_deck(_deck(slide), tokens=tokens_for(), out_path=out_path)

    frame = Presentation(str(out_path)).slides[0].notes_slide.notes_text_frame
    assert frame is not None
    assert frame.text.splitlines() == [
        "Say this first.",
        NODE_CLAIM,
        "Source: q3-segmentation-report p.6",
    ]


def test_a_slide_with_no_face_claim_draws_no_source_line_at_all(tmp_path: Path) -> None:
    """Nothing to cite means no caption — not a "Source:" that names no source."""
    slide = _slide(
        "s1",
        "bullets_supporting",
        [
            _framing_block("headline", "A plain framing headline"),
            _framing_block("points", "One."),
        ],
    )
    content, _ = adapt_slide(slide, catalog.registration("bullets_supporting").content_type)
    assert cast(Any, content).source == ""

    out_path = tmp_path / "deck.pptx"
    render_deck(_deck(slide), tokens=tokens_for(), out_path=out_path)
    face = _face_text(Presentation(str(out_path)))
    assert "Source" not in face


def test_expected_caption_lines_are_exactly_what_the_slide_draws() -> None:
    citation = _citation(quote=NODE_CLAIM, doc_id="q3-segmentation-report", page=6)
    assert expected_caption_lines(_node_claim_slide(citation)) == frozenset(
        {"Source: q3-segmentation-report p.6"}
    )
    claimless = _slide("s1", "bullets_supporting", [_framing_block("headline", "Plain")])
    assert expected_caption_lines(claimless) == frozenset()


# ---------------------------------------------------------------------------
# 9. Components copy content and never compose it
# ---------------------------------------------------------------------------


def _strings_in(value: Any) -> list[str]:
    """Every string (and float, as `repr` — how charts write them) reachable from `value`."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, float):
        return [repr(value)]
    if isinstance(value, int) and not isinstance(value, bool):
        return [str(value)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _strings_in(v)]
    if isinstance(value, list | tuple):
        return [t for v in value for t in _strings_in(v)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _strings_in(dataclasses.asdict(value))
    dump = getattr(value, "model_dump", None)
    if dump is not None:
        return _strings_in(dump())
    return []


def _citations_in(value: Any) -> list[Citation]:
    """Every `Citation` object reachable from `value` (a chart's, a diagram node's)."""
    if isinstance(value, Citation):
        return [value]
    if isinstance(value, list | tuple):
        return [c for v in value for c in _citations_in(v)]
    if isinstance(value, dict):
        return [c for v in value.values() for c in _citations_in(v)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [
            c for f in dataclasses.fields(value) for c in _citations_in(getattr(value, f.name))
        ]
    fields = getattr(type(value), "model_fields", None)
    if fields is not None:
        return [c for name in fields for c in _citations_in(getattr(value, name))]
    return []


def _words(text: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"\w+", text)}


@pytest.mark.parametrize("name", catalog.known_components())
def test_no_component_renders_a_word_or_number_its_content_did_not_hold(
    name: str, tmp_path: Path
) -> None:
    """Render each component's golden example and require that every word and number on the
    rendered face was already in the content. This is the class of bug the agenda had
    (`f"{index}. {item}"` put "1", "2", "3" on the slide that no block held) and the
    callout's silent "Takeaway" default: a component composing text the IR never saw, which
    a claim-survival check cannot see and only a numeral audit catches sometimes.

    Glyph-only ornaments (bullet dashes, the quote mark) have no word characters and so are
    out of scope here by construction — they cannot carry a fact. They are listed in the
    handover instead.
    """
    example = preview.EXAMPLES[name]
    tokens = tokens_for()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.name = f"{SLIDE_TAG_PREFIX}only"
    catalog.renderer_for(name)(slide, Canvas(tokens), example)
    path = save_themed(presentation, tokens, tmp_path / f"{name}.pptx")

    face = extract_slide_text(path)["only"].face
    # The one sanctioned composition: the caption `source_line` builds from the content's own
    # citations ("Source: doc p.N"). Nothing else may add a word.
    caption = source_line(_citations_in(example))
    held = _words(" ".join(_strings_in(example))) | _words(caption)
    invented = sorted(_words(face) - held)

    assert invented == [], f"{name} rendered words/numbers no content held: {invented}"


def _agenda_deck(*items: str) -> Deck:
    return _deck(
        _slide(
            "s1",
            "agenda",
            [_framing_block("headline", "Three sessions outline the analysis")]
            + [_framing_block("items", item) for item in items],
        )
    )


AGENDA_ITEMS = (
    "Where the original architecture left headroom.",
    "The rewrite: what changed, and what stayed.",
    "The impact by the numbers.",
)


def test_agenda_numbers_are_native_list_formatting_not_text(tmp_path: Path) -> None:
    """One text box, one paragraph per item, each `a:buAutoNum` — so the numbers are
    paragraph formatting the application generates, never a run of text."""
    out_path = tmp_path / "deck.pptx"
    render_deck(_agenda_deck(*AGENDA_ITEMS), tokens=tokens_for(), out_path=out_path)

    with zipfile.ZipFile(out_path) as archive:
        xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
    assert xml.count('<a:buAutoNum type="arabicPeriod"/>') == len(AGENDA_ITEMS)

    presentation = Presentation(str(out_path))
    list_shapes = [
        shape
        for shape in presentation.slides[0].shapes
        if shape.has_text_frame and AGENDA_ITEMS[0] in _shape_text(shape)
    ]
    assert len(list_shapes) == 1, "the list must be ONE box, or every item would read '1.'"
    paragraphs = [p.text for p in _text_frame(list_shapes[0]).paragraphs]
    assert paragraphs == list(AGENDA_ITEMS)


def test_extraction_does_not_read_auto_numbers_as_text(tmp_path: Path) -> None:
    """Auto-numbers are formatting, so the extractor hands over the item text alone. That is
    the point: the digits exist in no IR block, and must not reach the numeric audit."""
    out_path = tmp_path / "deck.pptx"
    render_deck(_agenda_deck(*AGENDA_ITEMS), tokens=tokens_for(), out_path=out_path)

    face = extract_slide_text(out_path)["s1"].face.splitlines()

    assert face == ["Three sessions outline the analysis", *AGENDA_ITEMS]
    assert not any(re.match(r"\s*\d+[.)]", line) for line in face)


def test_agenda_items_with_a_newline_are_refused_not_renumbered() -> None:
    from autodeck.design.components.renderers import agenda

    tokens = tokens_for()
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    with pytest.raises(ValueError, match="newline"):
        agenda.render(
            slide,
            Canvas(tokens),
            agenda.AgendaContent(headline="H", items=["one\ntwo"]),
        )


def test_a_callout_without_a_label_is_refused_not_given_a_word_nobody_wrote() -> None:
    slide = _slide("s1", "callout_takeaway", [_claim_block("takeaway", "A takeaway.")])
    with pytest.raises(RenderStageError, match="label"):
        adapt_slide(slide, catalog.registration("callout_takeaway").content_type)


def test_title_presenter_and_date_are_two_lines_with_no_invented_separator(
    tmp_path: Path,
) -> None:
    deck = _deck(
        _slide(
            "s1",
            "title",
            [
                _framing_block("title", "A Deck Title"),
                _framing_block("presenter", "Engineering leadership"),
                _claim_block("date", "Q3 2025"),
            ],
        )
    )
    out_path = tmp_path / "deck.pptx"
    render_deck(deck, tokens=tokens_for(), out_path=out_path)

    lines = extract_slide_text(out_path)["s1"].face.splitlines()

    assert "Engineering leadership" in lines
    assert "Q3 2025" in lines
    assert not any("·" in line for line in lines)


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
