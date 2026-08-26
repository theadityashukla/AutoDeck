"""Ingestion: the provenance chain from PDF element to citation.

Every citation the system will ever produce resolves through `DocumentStore`, so these
are A1 tests. Two in particular are load-bearing:

- `test_a_vlm_description_can_never_be_cited` — plan §6.3 says descriptions are metadata,
  and the Phase 1 brief requires that enforced in the resolver rather than by convention.
- `test_a_paraphrase_is_not_found` — the resolver refuses to approximate. A citation that
  points at text the source never contained is worse than no citation.

The Docling *mapping* is tested here against hand-built documents; the Docling *pipeline*
needs model weights and is marked `models`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
)

from autodeck.ingest.docling_runner import (
    PROVENANCE_COVERAGE_THRESHOLD,
    _bbox_from_docling,
    document_from_docling,
)
from autodeck.ingest.document_store import (
    Document,
    DocumentElement,
    DocumentStore,
    IngestError,
    ProvenanceError,
    QuoteNotFoundError,
    TableCell,
    TableData,
    UncitableSourceError,
)
from autodeck.ingest.provenance import (
    bbox_is_sane,
    find_span,
    merge_bboxes,
    normalise_text,
)

QUOTE = "Training throughput rose from 412 to 671 sequences per second."


def element(
    element_id: str = "e1",
    *,
    kind: str = "text",
    text: str = QUOTE,
    page: int = 1,
    bbox: tuple[float, float, float, float] = (72.0, 100.0, 523.0, 130.0),
    order: int = 0,
    description: str | None = None,
    table: TableData | None = None,
) -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id="doc-1",
        kind=kind,  # type: ignore[arg-type]
        page=page,
        bbox=bbox,
        reading_order=order,
        text=text,
        description=description,
        table=table,
    )


def store_with(*elements: DocumentElement, tmp_path: Path) -> DocumentStore:
    store = DocumentStore(tmp_path)
    store.add(
        Document(
            doc_id="doc-1",
            source_path="/corpus/doc-1.pdf",
            page_count=1,
            elements=list(elements),
        )
    )
    return store


# ---------------------------------------------------------------------------
# A1 — only verbatim source text is citable
# ---------------------------------------------------------------------------


def test_a_quote_resolves_to_a_verified_citation(tmp_path: Path) -> None:
    store = store_with(element(), tmp_path=tmp_path)
    citation = store.resolve_quote("doc-1", "rose from 412 to 671")
    assert citation.page == 1
    assert citation.quote == "rose from 412 to 671"
    assert store.verify_citation(citation)


def test_the_citation_carries_verbatim_characters_not_the_callers_version(
    tmp_path: Path,
) -> None:
    """The hash must verify, so the citation quotes the document, not the request."""
    store = store_with(element(text="Costs fell by 40 % in the trial."), tmp_path=tmp_path)
    citation = store.resolve_quote("doc-1", "fell by 40 % in the trial")
    assert " " in citation.quote  # the thin space the document actually used
    assert store.verify_citation(citation)


def test_a_paraphrase_is_not_found(tmp_path: Path) -> None:
    """A1 asks for a quote. Returning a nearest match would manufacture evidence."""
    store = store_with(element(), tmp_path=tmp_path)
    with pytest.raises(QuoteNotFoundError, match="verbatim"):
        store.resolve_quote("doc-1", "throughput went up a lot")


def test_a_quote_from_another_document_is_not_found(tmp_path: Path) -> None:
    store = store_with(element(), tmp_path=tmp_path)
    with pytest.raises(QuoteNotFoundError):
        store.resolve_quote("doc-1", "an assertion from an entirely different paper")


def test_mutating_stored_text_breaks_verification(tmp_path: Path) -> None:
    """The drift check: a document re-ingested differently invalidates old citations."""
    store = store_with(element(), tmp_path=tmp_path)
    citation = store.resolve_quote("doc-1", "rose from 412 to 671")

    store_with(element(text="Training throughput rose from 412 to 871."), tmp_path=tmp_path)
    assert not DocumentStore(tmp_path).verify_citation(citation)


def test_an_edited_quote_fails_its_own_hash(tmp_path: Path) -> None:
    store = store_with(element(), tmp_path=tmp_path)
    citation = store.resolve_quote("doc-1", "rose from 412 to 671")
    tampered = citation.model_copy(update={"quote": "rose from 412 to 871"})
    assert not store.verify_citation(tampered)


# ---------------------------------------------------------------------------
# A1 — VLM descriptions are metadata and can never be cited (§6.3)
# ---------------------------------------------------------------------------


def test_a_vlm_description_can_never_be_cited(tmp_path: Path) -> None:
    """The structural enforcement the Phase 1 brief asks for.

    The description is not searched by the resolver at all, so there is no route from a
    good-sounding model description to a citation.
    """
    figure = element(
        "fig-1",
        kind="figure",
        text="",
        description="A bar chart showing throughput rising from 412 to 671.",
    )
    store = store_with(figure, tmp_path=tmp_path)

    with pytest.raises(QuoteNotFoundError):
        store.resolve_quote("doc-1", "throughput rising from 412 to 671")

    with pytest.raises(UncitableSourceError, match="metadata"):
        store.resolve_quote("doc-1", "anything", element_id="fig-1")


def test_a_description_is_still_retrievable(tmp_path: Path) -> None:
    """Descriptions exist to be found. Only citing them is forbidden."""
    figure = element("fig-1", kind="figure", text="", description="A bar chart of throughput.")
    assert "bar chart" in figure.retrieval_text()
    assert not figure.is_citable


@pytest.mark.parametrize("kind", ["figure", "page_header", "page_footer"])
def test_page_furniture_and_figures_are_not_citable(kind: str, tmp_path: Path) -> None:
    store = store_with(element("x", kind=kind, text="Nature | Vol 621 | 14"), tmp_path=tmp_path)
    with pytest.raises(UncitableSourceError):
        store.resolve_quote("doc-1", "Vol 621", element_id="x")


def test_an_uncitable_element_is_skipped_in_a_document_wide_search(tmp_path: Path) -> None:
    """The header text must not be reachable even without naming the element."""
    store = store_with(
        element("h", kind="page_header", text="Nature | Vol 621", order=0),
        element("t", kind="text", text=QUOTE, order=1),
        tmp_path=tmp_path,
    )
    with pytest.raises(QuoteNotFoundError):
        store.resolve_quote("doc-1", "Nature | Vol 621")


# ---------------------------------------------------------------------------
# A1 — no provenance, no citation
# ---------------------------------------------------------------------------


def test_an_element_with_a_degenerate_box_cannot_be_cited(tmp_path: Path) -> None:
    """GATE 1a spot-checks boxes against the source; a zero-area box fails that check."""
    store = store_with(element(bbox=(0.0, 0.0, 0.0, 0.0)), tmp_path=tmp_path)
    with pytest.raises(QuoteNotFoundError):
        store.resolve_quote("doc-1", "rose from 412")


def test_naming_a_provenance_less_element_reports_it_precisely(tmp_path: Path) -> None:
    store = store_with(element(bbox=(0.0, 0.0, 0.0, 0.0)), tmp_path=tmp_path)
    with pytest.raises(UncitableSourceError, match="provenance"):
        store.resolve_quote("doc-1", "rose from 412", element_id="e1")


@pytest.mark.parametrize(
    "bbox",
    [
        (0.0, 0.0, 0.0, 0.0),
        (10.0, 10.0, 5.0, 20.0),
        (10.0, 20.0, 20.0, 10.0),
        (-1.0, 0.0, 5.0, 5.0),
    ],
)
def test_degenerate_boxes_are_rejected(bbox: tuple[float, float, float, float]) -> None:
    assert not bbox_is_sane(bbox)


def test_a_normal_box_is_accepted() -> None:
    assert bbox_is_sane((72.0, 100.0, 523.0, 130.0))


# ---------------------------------------------------------------------------
# Quote matching tolerance
# ---------------------------------------------------------------------------


def test_ligatures_and_curly_quotes_match(tmp_path: Path) -> None:
    """PDF extraction substitutes these constantly; refusing them blocks real citations."""
    store = store_with(
        element(text="The workﬂow was signiﬁcantly faster, the authors’ view."),
        tmp_path=tmp_path,
    )
    citation = store.resolve_quote("doc-1", "workflow was significantly faster")
    assert citation.quote == "workﬂow was signiﬁcantly faster"
    assert store.verify_citation(citation)


def test_a_line_break_hyphen_is_joined(tmp_path: Path) -> None:
    store = store_with(
        element(text="Measured through-\nput improved markedly."), tmp_path=tmp_path
    )
    assert store.resolve_quote("doc-1", "throughput improved").quote


def test_whitespace_differences_are_tolerated(tmp_path: Path) -> None:
    store = store_with(element(text="Costs   fell\n  sharply in Q3."), tmp_path=tmp_path)
    assert store.resolve_quote("doc-1", "Costs fell sharply").quote


def test_matching_is_case_insensitive_but_the_quote_keeps_its_case(tmp_path: Path) -> None:
    store = store_with(element(text="Throughput Rose Sharply."), tmp_path=tmp_path)
    citation = store.resolve_quote("doc-1", "throughput rose sharply")
    assert citation.quote == "Throughput Rose Sharply"


def test_normalise_never_replaces_source_text() -> None:
    """A citation built from normalised text would fail its own hash."""
    original = "The authors’ workﬂow"
    assert normalise_text(original) == "The authors' workflow"
    assert original != normalise_text(original)


def test_find_span_returns_verbatim_offsets() -> None:
    text = "The workﬂow was fast."
    span = find_span(text, "workflow was fast")
    assert span is not None
    assert text[span[0] : span[1]] == "workﬂow was fast"


def test_find_span_returns_none_for_absent_text() -> None:
    assert find_span("some text", "entirely different") is None


def test_find_span_ignores_empty_needles() -> None:
    assert find_span("some text", "   ") is None


def test_merge_bboxes_encloses_all() -> None:
    assert merge_bboxes([(10.0, 10.0, 20.0, 20.0), (15.0, 5.0, 30.0, 18.0)]) == (
        10.0,
        5.0,
        30.0,
        20.0,
    )


def test_merge_bboxes_rejects_an_empty_list() -> None:
    with pytest.raises(ValueError, match="empty list"):
        merge_bboxes([])


# ---------------------------------------------------------------------------
# Table cells (task 1.4, D10)
# ---------------------------------------------------------------------------


def table_element() -> DocumentElement:
    return element(
        "tbl-1",
        kind="table",
        text="build | seq/s\nbaseline | 412\nrewrite | 671",
        table=TableData(
            rows=3,
            columns=2,
            cells=[
                TableCell(row=0, column=0, text="build", is_header=True),
                TableCell(row=0, column=1, text="seq/s", is_header=True),
                TableCell(row=1, column=0, text="baseline"),
                TableCell(row=1, column=1, text="412", bbox=(300.0, 200.0, 340.0, 214.0)),
                TableCell(row=2, column=0, text="rewrite"),
                TableCell(row=2, column=1, text="671", bbox=(300.0, 220.0, 340.0, 234.0)),
            ],
        ),
    )


def test_a_table_cell_cites_with_its_own_bbox(tmp_path: Path) -> None:
    """D10: "table 2" is a location, not evidence for a particular number."""
    store = store_with(table_element(), tmp_path=tmp_path)
    citation = store.resolve_cell("doc-1", "tbl-1", row=2, column=1)
    assert citation.quote == "671"
    assert citation.bbox == (300.0, 220.0, 340.0, 234.0)
    assert store.verify_citation(citation)


def test_a_cell_without_its_own_box_falls_back_to_the_table(tmp_path: Path) -> None:
    store = store_with(table_element(), tmp_path=tmp_path)
    citation = store.resolve_cell("doc-1", "tbl-1", row=1, column=0)
    assert citation.bbox == (72.0, 100.0, 523.0, 130.0)


def test_a_missing_cell_raises(tmp_path: Path) -> None:
    store = store_with(table_element(), tmp_path=tmp_path)
    with pytest.raises(QuoteNotFoundError, match="no non-empty cell"):
        store.resolve_cell("doc-1", "tbl-1", row=9, column=9)


def test_resolve_cell_on_a_non_table_raises(tmp_path: Path) -> None:
    store = store_with(element(), tmp_path=tmp_path)
    with pytest.raises(IngestError, match="not a table"):
        store.resolve_cell("doc-1", "e1", row=0, column=0)


def test_a_table_cell_with_no_provenance_anywhere_raises(tmp_path: Path) -> None:
    broken = element(
        "tbl-2",
        kind="table",
        text="x",
        bbox=(0.0, 0.0, 0.0, 0.0),
        table=TableData(rows=1, columns=1, cells=[TableCell(row=0, column=0, text="412")]),
    )
    store = store_with(broken, tmp_path=tmp_path)
    with pytest.raises((ProvenanceError, UncitableSourceError)):
        store.resolve_cell("doc-1", "tbl-2", row=0, column=0)


# ---------------------------------------------------------------------------
# Store mechanics
# ---------------------------------------------------------------------------


def test_documents_round_trip(tmp_path: Path) -> None:
    store = store_with(element(), table_element(), tmp_path=tmp_path)
    reloaded = DocumentStore(tmp_path).get("doc-1")
    assert reloaded == store.get("doc-1")
    assert DocumentStore(tmp_path).doc_ids() == ["doc-1"]


def test_a_missing_document_raises(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="not in the store"):
        DocumentStore(tmp_path).get("absent")


@pytest.mark.parametrize("doc_id", ["", "..", "a/b"])
def test_invalid_doc_ids_are_refused(tmp_path: Path, doc_id: str) -> None:
    with pytest.raises(IngestError, match="invalid doc_id"):
        DocumentStore(tmp_path).path_for(doc_id)


def test_duplicate_element_ids_are_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="duplicate element ids"):
        Document(
            doc_id="doc-1",
            source_path="x.pdf",
            page_count=1,
            elements=[element("dup"), element("dup", order=1)],
        )


def test_verify_returns_false_for_an_unknown_document(tmp_path: Path) -> None:
    store = store_with(element(), tmp_path=tmp_path)
    citation = store.resolve_quote("doc-1", "rose from 412")
    assert not DocumentStore(tmp_path / "elsewhere").verify_citation(citation)


# ---------------------------------------------------------------------------
# Docling mapping — pure, no model weights
# ---------------------------------------------------------------------------


def prov(page: int, left: float, top: float, right: float, bottom: float) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page,
        bbox=BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.BOTTOMLEFT),
        charspan=(0, 0),
    )


#: Height of the fixture page. Bottom-left to top-left conversion is `height - y`, so a
#: round number keeps the expected boxes readable.
PAGE_HEIGHT = 800.0


def build_docling_document(*, with_page_size: bool = True) -> DoclingDocument:
    doc = DoclingDocument(name="probe")
    if with_page_size:
        doc.add_page(page_no=1, size=Size(width=595.0, height=PAGE_HEIGHT))
    doc.add_title(text="Attention Is All You Need", prov=prov(1, 72, 720, 523, 700))
    doc.add_text(label=DocItemLabel.TEXT, text=QUOTE, prov=prov(1, 72, 660, 523, 640))
    doc.add_text(
        label=DocItemLabel.CAPTION,
        text="Figure 1: throughput by build.",
        prov=prov(1, 72, 400, 523, 388),
    )
    doc.add_text(label=DocItemLabel.PAGE_FOOTER, text="14", prov=prov(1, 300, 40, 320, 30))
    return doc


def test_the_mapping_preserves_page_and_converts_the_bbox_origin() -> None:
    """Docling reports bottom-left origin; the conversion needs the page height."""
    document = document_from_docling(build_docling_document(), doc_id="p", source_path="p.pdf")
    body = next(e for e in document.elements if e.kind == "text")
    assert body.page == 1
    # Bottom-left t=660, b=640 on an 800pt page -> 140..160 from the top.
    assert body.bbox == (72.0, 140.0, 523.0, 160.0)
    assert bbox_is_sane(body.bbox)


def test_an_element_near_the_top_of_the_page_gets_a_small_y() -> None:
    """The regression test for a real bug found on the first real-PDF run.

    Swapping `t` and `b` yields a well-formed rectangle that is still in bottom-left
    space, so a heading at the top of the page reads as y≈690 instead of y≈90 — every
    citation box mirrored about the page centre, plausible until someone checks it.
    """
    document = document_from_docling(build_docling_document(), doc_id="p", source_path="p.pdf")
    title = next(e for e in document.elements if e.kind == "title")
    assert title.bbox == (72.0, 80.0, 523.0, 100.0)
    assert title.bbox[1] < PAGE_HEIGHT / 2, "a title at the top of the page must have a small y"


def test_bottom_left_boxes_are_converted_using_the_page_height() -> None:
    box = BoundingBox(l=10, t=700, r=100, b=680, coord_origin=CoordOrigin.BOTTOMLEFT)
    assert _bbox_from_docling(box, 800.0) == (10.0, 100.0, 100.0, 120.0)


def test_a_bottom_left_box_without_a_page_height_is_refused() -> None:
    """Impossible to convert, so it yields no box rather than a mirrored one.

    A wrong box is worse than no box: the element becomes uncitable, which is loud, instead
    of producing a citation that points at the wrong part of the page.
    """
    box = BoundingBox(l=10, t=700, r=100, b=680, coord_origin=CoordOrigin.BOTTOMLEFT)
    assert _bbox_from_docling(box, None) == (0.0, 0.0, 0.0, 0.0)
    assert not bbox_is_sane(_bbox_from_docling(box, None))


def test_a_document_without_page_sizes_yields_nothing_citable() -> None:
    document = document_from_docling(
        build_docling_document(with_page_size=False), doc_id="p", source_path="p.pdf"
    )
    assert document.citable_elements() == []
    assert document.low_provenance


def test_top_left_boxes_are_left_alone() -> None:
    box = BoundingBox(l=10, t=100, r=100, b=140, coord_origin=CoordOrigin.TOPLEFT)
    assert _bbox_from_docling(box, 800.0) == (10.0, 100.0, 100.0, 140.0)


def test_a_missing_box_becomes_degenerate_not_invented() -> None:
    assert _bbox_from_docling(None, 800.0) == (0.0, 0.0, 0.0, 0.0)


def test_the_mapping_carries_labels_across() -> None:
    document = document_from_docling(build_docling_document(), doc_id="p", source_path="p.pdf")
    assert {e.kind for e in document.elements} == {"title", "text", "caption", "page_footer"}
    assert document.title == "Attention Is All You Need"


def test_page_furniture_survives_the_mapping_but_stays_uncitable() -> None:
    """Dropping it would make the store look cleaner and the corpus less complete."""
    document = document_from_docling(build_docling_document(), doc_id="p", source_path="p.pdf")
    footer = next(e for e in document.elements if e.kind == "page_footer")
    assert not footer.is_citable


def test_reading_order_is_preserved() -> None:
    document = document_from_docling(build_docling_document(), doc_id="p", source_path="p.pdf")
    orders = [e.reading_order for e in document.elements]
    assert orders == sorted(orders)


def test_a_mapped_document_resolves_citations(tmp_path: Path) -> None:
    """End to end on the half that needs no models."""
    document = document_from_docling(build_docling_document(), doc_id="p", source_path="p.pdf")
    store = DocumentStore(tmp_path)
    store.add(document)
    citation = store.resolve_quote("p", "rose from 412 to 671")
    assert citation.page == 1
    assert store.verify_citation(citation)


def test_a_low_provenance_document_is_flagged() -> None:
    """Plan §9: flag for human review rather than papering over with approximate boxes."""
    doc = DoclingDocument(name="messy")
    for index in range(5):
        doc.add_text(label=DocItemLabel.TEXT, text=f"paragraph {index}")  # no prov at all
    document = document_from_docling(doc, doc_id="messy", source_path="messy.pdf")
    assert document.low_provenance
    assert document.provenance_coverage() < PROVENANCE_COVERAGE_THRESHOLD
    assert document.citable_elements() == []


def test_a_clean_document_is_not_flagged() -> None:
    document = document_from_docling(build_docling_document(), doc_id="p", source_path="p.pdf")
    assert not document.low_provenance
    assert document.provenance_coverage() == 1.0
