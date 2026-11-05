"""Reference-deck ingestion and the four profiles (Phase 4, tasks 4.2 and 4.8).

The accuracy rule (A1) is tested structurally: deck-derived text cannot satisfy a citation,
ingestion writes nothing to the corpus or a run's `source/`, and no profile key is one a
`DocumentStore` would accept. A4: another client's deck, `..` and paths outside `decks/` are
refused.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches, Pt

from autodeck.design.headers.profile import HeaderStyleProfile
from autodeck.design.reference import analyse_gaps, ingest_client_decks
from autodeck.design.reference.profiles import (
    derive_design,
    derive_headers,
    derive_profiles,
    derive_storyline,
    derive_voice,
)
from autodeck.ingest.deck_ingest import (
    ReferenceDeckError,
    ReferenceStore,
    deck_slug,
)
from autodeck.ingest.document_store import Document, DocumentElement
from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import ClientIsolationError, KnowledgeLoader

TITLES = {
    "content1": "Shrink costs 4.2 percent of revenue across our stores",
    "content2": "Automated counts cut stock errors by 31 percent",
    "content3": "We can recover 12 stores of margin this year",
    "two_col": "Stores that automate reduce waste by 12 percent",
    "chart": "Shrink is rising faster than sales in 2025",
    "odd": "Regional matrix of store formats",
}


def _text(slide, left, top, width, height, lines, *, size=None):  # type: ignore[no-untyped-def]
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    for i, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.text = line
        if size:
            for run in paragraph.runs:
                run.font.size = Pt(size)
                run.font.name = "Calibri"
    return box


def _body(slide, lines):  # type: ignore[no-untyped-def]
    frame = slide.placeholders[1].text_frame
    for i, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.text = line


def build_deck(path: Path, *, odd_slides: int = 1, odd_columns: int = 5) -> Path:
    """Title, agenda, divider, 3 content, two-column, chart, odd layout(s), closing."""
    prs = Presentation()
    layouts = prs.slide_layouts

    s = prs.slides.add_slide(layouts[0])
    s.shapes.title.text = "Retail margin review"
    s.placeholders[1].text = "Northwind Retail"

    s = prs.slides.add_slide(layouts[1])
    s.shapes.title.text = "Agenda"
    _body(s, ["Where we are", "What we found", "What to do"])

    s = prs.slides.add_slide(layouts[2])
    s.shapes.title.text = "Where we are today"

    for key, body in (
        ("content1", ["We lose inventory at the door.", "Shrink is highest in grocery."]),
        ("content2", ["Our pilot counted inventory nightly.", "Shrink fell where counts ran."]),
        (
            "content3",
            ["You can fund the rollout from shrink.", "Inventory accuracy pays back."],
        ),
    ):
        s = prs.slides.add_slide(layouts[1])
        s.shapes.title.text = TITLES[key]
        _body(s, body)

    s = prs.slides.add_slide(layouts[5])
    s.shapes.title.text = TITLES["two_col"]
    _text(s, 0.5, 1.8, 4.2, 3.0, ["Automated stores track inventory daily."], size=18)
    _text(s, 5.2, 1.8, 4.2, 3.0, ["Manual stores count inventory monthly."], size=18)

    s = prs.slides.add_slide(layouts[5])
    s.shapes.title.text = TITLES["chart"]
    data = CategoryChartData()
    data.categories = ["2023", "2024", "2025"]
    data.add_series("Shrink", (1.0, 1.4, 2.1))
    s.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1.8), Inches(8), Inches(4.5), data
    )

    for _ in range(odd_slides):
        s = prs.slides.add_slide(layouts[5])
        s.shapes.title.text = TITLES["odd"]
        for i in range(odd_columns):
            _text(s, 0.3 + i * 1.9, 1.8 + (i % 2) * 1.5, 1.7, 1.0, [f"Format {i}"], size=12)
        s.shapes.add_table(3, 3, Inches(0.5), Inches(5.0), Inches(8), Inches(1.5))

    s = prs.slides.add_slide(layouts[1])
    s.shapes.title.text = "Next steps"
    _body(s, ["Approve the pilot", "Name an owner"])
    s.notes_slide.notes_text_frame.text = "Speaker note that must never become evidence."

    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return path


def make_knowledge(root: Path, *clients: str) -> Path:
    for client in clients:
        folder = root / "clients" / client
        (folder / "decks").mkdir(parents=True)
        (folder / "client.md").write_text("# client\n", encoding="utf-8")
        (folder / "value_prop.md").write_text("value\n", encoding="utf-8")
    return root


@pytest.fixture
def world(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = make_knowledge(tmp_path / "knowledge", "acme", "other")
    deck = build_deck(root / "clients" / "acme" / "decks" / "Margin Review.pptx")
    return root, deck, ClientNamespace(client="acme", knowledge_root=root)


def read(world):  # type: ignore[no-untyped-def]
    _root, deck, ns = world
    return ReferenceStore(ns).read_deck(deck)


# -- reading ---------------------------------------------------------------------------------


def test_the_deck_is_read_with_titles_notes_layouts_and_shape_kinds(world) -> None:  # type: ignore[no-untyped-def]
    deck = read(world)
    assert len(deck.slides) == 10
    assert deck.slides[3].title == TITLES["content1"]
    assert deck.slides[0].layout_name == "Title Slide"
    assert "never become evidence" in deck.slides[-1].notes
    assert deck.slides[7].count("chart") == 1
    assert deck.slides[8].count("table") == 1
    assert any(s.font_names == ["Calibri"] for s in deck.slides[6].shapes if s.kind == "text")


# -- the four profiles -----------------------------------------------------------------------


def test_storyline_roles_carry_the_rule_that_set_them(world) -> None:  # type: ignore[no-untyped-def]
    storyline = derive_storyline(read(world))
    roles = {r.slide: (r.role, r.rule) for r in storyline.roles}
    assert roles[1] == ("title", "first-slide")
    assert roles[2] == ("agenda", "agenda-title")
    assert roles[3][0] == "divider"
    assert all(roles[i][0] == "content" for i in (4, 5, 6, 7, 8, 9))
    assert roles[10] == ("closing", "closing-title")
    assert storyline.slide_count == 10
    assert storyline.role_counts["content"] == 6
    assert storyline.sections == [{"start": 1, "slides": 2}, {"start": 3, "slides": 8}]
    assert storyline.titles[3] == TITLES["content1"]


def test_appendix_slides_stay_appendix_once_started(tmp_path: Path) -> None:
    prs = Presentation()
    for title in ("Intro", "Findings", "Appendix: method", "Detail A", "Detail B"):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = title
    path = tmp_path / "a.pptx"
    prs.save(str(path))
    from autodeck.ingest.deck_ingest import reference_deck_from_presentation

    roles = [
        r.role
        for r in derive_storyline(
            reference_deck_from_presentation(Presentation(str(path)), name="a")
        ).roles
    ]
    assert roles[2:] == ["appendix", "appendix", "appendix"]


def test_derived_header_profile_loads_through_from_mapping(world) -> None:  # type: ignore[no-untyped-def]
    deck = read(world)
    header = derive_headers(deck, derive_storyline(deck))
    loaded = HeaderStyleProfile.from_mapping(header.profile)
    assert loaded.style == "assertion"
    assert loaded.sentence_case is True
    assert loaded.terminal_punctuation is False
    assert loaded.numbers_in_headers == "allowed"
    assert loaded.max_words == 9  # 90th percentile of the six content titles
    assert header.question_share == 0.0
    assert header.exemplar_headers[0] == TITLES["content1"]
    assert header.exemplar_headers == [
        TITLES[k] for k in ("content1", "content2", "content3", "two_col", "chart", "odd")
    ]


def test_topic_titles_without_numbers_are_topic_led_and_discourage_numbers(
    tmp_path: Path,
) -> None:
    from autodeck.ingest.deck_ingest import reference_deck_from_presentation

    prs = Presentation()
    for title in ("Cover", "Store formats", "Regional overview", "Pricing", "Logistics"):
        prs.slides.add_slide(prs.slide_layouts[1]).shapes.title.text = title
    deck = reference_deck_from_presentation(prs, name="t")
    header = derive_headers(deck, derive_storyline(deck))
    loaded = HeaderStyleProfile.from_mapping(header.profile)
    assert loaded.style == "topic_led"
    assert loaded.numbers_in_headers == "discouraged"


def test_voice_profile(world) -> None:  # type: ignore[no-untyped-def]
    voice = derive_voice(read(world))
    assert voice.avoided == []
    assert voice.sentences > 0 and voice.mean_sentence_words > 0
    assert voice.person["we"] > 0 and voice.person["you"] > 0
    assert voice.person["we"] + voice.person["you"] + voice.person["they"] == pytest.approx(
        1.0, abs=0.01
    )
    assert voice.bullet_share > 0.4
    terms = dict(voice.terms)
    assert terms["inventory"] >= 4 and terms["shrink"] >= 2
    assert "the" not in terms and all(n >= 2 for n in terms.values())
    assert len(voice.terms) <= 25


def test_design_profile_maps_layouts_to_catalog_components(world) -> None:  # type: ignore[no-untyped-def]
    from autodeck.design.components.catalog import known_components

    deck = read(world)
    design = derive_design(deck, derive_storyline(deck))
    by_slide = {d.slide: d for d in design.slides}
    assert by_slide[1].component == "title"
    assert by_slide[2].component == "agenda"
    assert by_slide[3].component == "section_divider"
    assert by_slide[4].component == "bullets_supporting" and by_slide[4].confidence >= 0.8
    assert by_slide[7].component == "two_column_compare" and by_slide[7].columns == 2
    assert by_slide[8].component == "chart_focus" and by_slide[8].charts == 1
    assert by_slide[9].confidence < 0.5  # the odd layout the catalog lacks
    assert by_slide[10].component == "closing_cta"
    assert {d.component for d in design.slides} <= set(known_components())
    assert design.low_confidence_slides == [9]
    assert design.fonts[0][0] == "Calibri"
    assert design.margin_pt is not None and design.margin_pt > 0


# -- determinism and the stored files --------------------------------------------------------


def test_reingesting_is_byte_identical(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    decks = root / "clients" / "acme" / "decks"
    ingest_client_decks(ns)
    first = {p.name: p.read_bytes() for p in decks.glob("*.json")}
    ingest_client_decks(ns)
    second = {p.name: p.read_bytes() for p in decks.glob("*.json")}
    assert first == second
    assert set(first) == {"margin-review.profile.json", "profile.json", "gaps.json"}
    assert json.loads(first["profile.json"])["deck_count"] == 1


def test_the_aggregate_covers_every_deck_even_when_one_is_ingested(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    decks = root / "clients" / "acme" / "decks"
    build_deck(decks / "second.pptx", odd_slides=2)
    ingest_client_decks(ns, ["Margin Review.pptx"])
    result = ingest_client_decks(ns, ["second.pptx"])
    assert sorted(result.aggregate["decks"]) == ["margin-review", "second"]
    assert result.aggregate["slide_count"] == 21
    assert result.aggregate["header"]["profile"]["style"] == "assertion"
    HeaderStyleProfile.from_mapping(result.aggregate["header"]["profile"])
    assert len(result.aggregate["header"]["exemplar_headers"]) <= 8


def test_style_headers_yaml_is_never_overwritten(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    style = root / "clients" / "acme" / "style"
    style.mkdir()
    (style / "headers.yaml").write_text("style: blot\n", encoding="utf-8")
    ingest_client_decks(ns)
    assert (style / "headers.yaml").read_text(encoding="utf-8") == "style: blot\n"


def test_the_loader_exposes_the_aggregate_profile(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    loader = KnowledgeLoader(root)
    assert loader.load_client("acme").reference_profile is None
    ingest_client_decks(ns)
    profile = loader.load_client("acme").reference_profile
    assert profile is not None and profile["client"] == "acme"
    assert loader.load_client("other").reference_profile is None


# -- A1 --------------------------------------------------------------------------------------


def test_a_claim_quoting_a_reference_deck_title_fails_citation_resolution(
    world, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from autodeck.agents.compose import ComposeDraft
    from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
    from autodeck.ir.models import CLIENT_DECK_DOC_PREFIX
    from tests.test_compose import compose_draft, run_compose, slide

    _root, _deck, ns = world
    ingest_client_decks(ns)
    title = TITLES["content1"]

    def deck_claim(doc_id: str) -> ProposedBlock:
        return ProposedBlock(
            id="b9",
            kind="claim",
            slot="headline",
            claim=ProposedClaim(
                text=title, citations=[ProposedCitation(doc_id=doc_id, quote=title)]
            ),
        )

    for doc_id in ("margin-review", f"{CLIENT_DECK_DOC_PREFIX}margin-review", "Margin Review"):
        draft: ComposeDraft = compose_draft(slides=[slide("s1", ["km1"], deck_claim(doc_id))])
        result, *_ = run_compose(tmp_path / doc_id.replace(" ", "_"), draft)
        assert any("not among the evidence shown" in r for r in result.rejections), doc_id
        assert not result.deck.slides or all(
            title not in (b.claim.text if b.claim else "")
            for sl in result.deck.slides
            for b in sl.blocks
        )


def test_ingestion_writes_only_inside_the_clients_decks_folder(world, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    ingest_client_decks(ns)
    created = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    decks = (root / "clients" / "acme" / "decks").resolve()
    assert created and all(decks in p.resolve().parents for p in created)
    assert not (tmp_path / "corpus").exists()
    assert not list(tmp_path.rglob("source"))
    assert not list((root / "clients" / "other").rglob("*.json"))


PROFILE_KEYS_FORBIDDEN = set(Document.model_fields) | set(DocumentElement.model_fields)


def _keys(value: object) -> set[str]:
    """Field names in the payload. A `*_counts` histogram is keyed by role or component
    name (`title` is a role), which is data, not a field, so its keys are skipped."""
    if isinstance(value, dict):
        kept = {k: v for k, v in value.items() if not k.endswith("_counts")}
        return set(kept) | {k for v in kept.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_no_profile_key_is_one_a_document_store_would_accept(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    result = ingest_client_decks(ns)
    decks = root / "clients" / "acme" / "decks"
    for name in ("margin-review.profile.json", "profile.json", "gaps.json"):
        payload = json.loads((decks / name).read_text(encoding="utf-8"))
        assert not (_keys(payload) & PROFILE_KEYS_FORBIDDEN), name
        with pytest.raises(Exception):  # noqa: B017
            Document.model_validate(payload)
    assert result.aggregate  # silence unused


def test_no_code_path_builds_a_document_from_a_reference_deck() -> None:
    forbidden = {
        "Document",
        "DocumentElement",
        "DocumentStore",
        "RetrievedSpan",
        "CachedClaim",
        "document_from_presentation",
        "ingest_deck",
    }
    package = Path(__file__).resolve().parent.parent / "autodeck"
    files = [
        package / "ingest" / "deck_ingest.py",
        *sorted((package / "design" / "reference").glob("*.py")),
    ]
    assert len(files) >= 5
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"))
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom | ast.Import)
            for alias in node.names
        }
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not ((names | used) & forbidden), file.name


# -- A4 --------------------------------------------------------------------------------------


def test_another_clients_deck_is_refused(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    foreign = build_deck(root / "clients" / "other" / "decks" / "theirs.pptx")
    with pytest.raises(ClientIsolationError):
        ingest_client_decks(ns, [foreign])
    with pytest.raises(ClientIsolationError):
        ReferenceStore(ns).read_deck(foreign)
    assert not list((root / "clients" / "acme" / "decks").glob("theirs*"))


def test_dotdot_and_outside_decks_paths_are_refused(world, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    store = ReferenceStore(ns)
    stray = build_deck(root / "clients" / "acme" / "stray.pptx")
    with pytest.raises(ReferenceDeckError):
        store.resolve_deck(root / "clients" / "acme" / "decks" / ".." / "stray.pptx")
    with pytest.raises(ReferenceDeckError):
        store.resolve_deck(stray)
    outside = build_deck(tmp_path / "elsewhere.pptx")
    with pytest.raises(ReferenceDeckError):
        store.resolve_deck(outside)
    with pytest.raises(ReferenceDeckError):
        store.write_json(root / "clients" / "acme" / "profile.json", {})
    with pytest.raises(ClientIsolationError):
        store.write_json(root / "clients" / "other" / "decks" / "profile.json", {})


def test_a_missing_or_non_pptx_deck_is_an_error(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    with pytest.raises(ReferenceDeckError, match="not found"):
        ingest_client_decks(ns, ["nope.pptx"])
    (root / "clients" / "acme" / "decks" / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ReferenceDeckError, match=r"\.pptx"):
        ingest_client_decks(ns, ["notes.txt"])


def test_deck_slug() -> None:
    assert deck_slug("Q3 Review (final).pptx") == "q3-review-final"
    with pytest.raises(ReferenceDeckError):
        deck_slug("!!!.pptx")


# -- 4.8 gap analysis ------------------------------------------------------------------------


def test_gaps_are_clustered_and_ranked_by_frequency(world) -> None:  # type: ignore[no-untyped-def]
    root, _deck, ns = world
    decks = root / "clients" / "acme" / "decks"
    build_deck(decks / "second.pptx", odd_slides=2)
    build_deck(decks / "third.pptx", odd_slides=1, odd_columns=3)
    result = ingest_client_decks(ns)
    gaps = result.gaps["gaps"]
    assert gaps == analyse_gaps(result.decks)["gaps"]
    assert [g["rank"] for g in gaps] == list(range(1, len(gaps) + 1))
    top = gaps[0]
    assert top["count"] == 3 and top["decks"] == ["margin-review", "second"]
    assert top["signature"].startswith("text5-") and top["signature"].endswith("table1")
    assert top["confidence"] < 0.5 and top["best_match"] == "data_card_grid"
    assert {"deck": "second", "slide": 9} in top["examples"]
    assert gaps[1]["count"] == 1 and gaps[1]["decks"] == ["third"]
    assert [g["count"] for g in gaps] == sorted((g["count"] for g in gaps), reverse=True)
    stored = json.loads((decks / "gaps.json").read_text(encoding="utf-8"))
    assert stored["threshold"] == 0.5 and stored["gaps"] == gaps


def test_a_deck_the_catalog_covers_has_no_gaps(tmp_path: Path) -> None:
    from autodeck.ingest.deck_ingest import reference_deck_from_presentation

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[0]).shapes.title.text = "Cover"
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Margins are 4 points under plan"
    slide.placeholders[1].text = "One point"
    profile = derive_profiles(reference_deck_from_presentation(prs, name="ok"), slug="ok")
    assert analyse_gaps([profile])["gaps"] == []
