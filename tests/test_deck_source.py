"""Phase 3d ingestion: a client deck becomes a run-local, citable source document."""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches

from autodeck.ingest.deck_source import deck_doc_id, ingest_deck, run_source_root
from autodeck.ingest.document_store import DocumentStore, UncitableSourceError

BULLET = "Revenue grew 12% in 2024"
NOTE = "Mention the Berlin pilot before the numbers."


def _build(path: Path) -> Path:
    prs = Presentation()
    title = prs.slides.add_slide(prs.slide_layouts[0])
    title.shapes.title.text = "Acme Annual Review"
    title.placeholders[1].text = "Prepared for the board"

    bullets = prs.slides.add_slide(prs.slide_layouts[1])
    bullets.shapes.title.text = "Highlights"
    bullets.placeholders[1].text_frame.text = f"{BULLET}\nChurn fell to 3.1%"
    bullets.notes_slide.notes_text_frame.text = NOTE

    blank = prs.slides.add_slide(prs.slide_layouts[6])
    table = blank.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(1)).table
    for (r, c), value in {
        (0, 0): "Region",
        (0, 1): "Sales",
        (1, 0): "EMEA",
        (1, 1): "412 units",
    }.items():
        table.cell(r, c).text = value
    blank.shapes.add_picture(str(_png(path.parent)), Inches(6), Inches(1), Inches(1), Inches(1))
    group = blank.shapes.add_group_shape()
    box = group.shapes.add_textbox(Inches(1), Inches(4), Inches(3), Inches(1))
    box.text_frame.text = "Grouped caption"
    blank.shapes.add_textbox(Inches(1), Inches(6), Inches(2), Inches(1))  # empty: skipped

    prs.save(path)
    return path


def _png(folder: Path) -> Path:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = zlib.compress(b"\x00\xff\x00\x00")
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )
    target = folder / "pic.png"
    target.write_bytes(png)
    return target


@pytest.fixture
def deck(tmp_path: Path) -> Path:
    return _build(tmp_path / "Acme Review.pptx")


def test_pages_and_elements(deck: Path, tmp_path: Path) -> None:
    root = run_source_root(tmp_path / "runs", "r1")
    document = ingest_deck(deck, store_root=root)

    assert document.doc_id == "client-deck--acme-review"
    assert document.page_count == 3
    assert document.title == "Acme Annual Review"
    by_page = {p: [e for e in document.elements if e.page == p] for p in (1, 2, 3)}
    assert [e.kind for e in by_page[1]] == ["title", "text"]
    # One element per bullet (paragraph), then the notes.
    assert [e.kind for e in by_page[2]] == ["title", "text", "text", "text"]
    assert by_page[2][-1].element_id == "s2-notes"
    assert by_page[2][-1].text == NOTE
    kinds3 = [e.kind for e in by_page[3]]
    assert sorted(kinds3) == ["figure", "table", "text"]  # empty textbox skipped
    assert [by_page[2][1].text, by_page[2][2].text] == [BULLET, "Churn fell to 3.1%"]
    assert by_page[2][1].bbox == by_page[2][2].bbox  # the frame's box: no per-line position


def test_every_citable_element_resolves(deck: Path, tmp_path: Path) -> None:
    root = run_source_root(tmp_path / "runs", "r1")
    document = ingest_deck(deck, store_root=root)
    store = DocumentStore(root)

    citable = document.citable_elements()
    assert citable
    for element in citable:
        citation = store.resolve_quote(
            document.doc_id, element.text, element_id=element.element_id
        )
        assert citation.page == element.page
        assert citation.quote == element.text
    assert store.resolve_quote(document.doc_id, BULLET).page == 2
    assert store.resolve_quote(document.doc_id, "412 units").page == 3
    assert store.resolve_quote(document.doc_id, "Berlin pilot").page == 2

    table = next(e for e in document.elements if e.kind == "table")
    cell = store.resolve_cell(document.doc_id, table.element_id, 1, 1)
    assert cell.quote == "412 units" and cell.page == 3


def test_picture_is_not_citable(deck: Path, tmp_path: Path) -> None:
    root = run_source_root(tmp_path / "runs", "r1")
    document = ingest_deck(deck, store_root=root)
    picture = next(e for e in document.elements if e.kind == "figure")
    assert not picture.is_citable
    assert picture.description == "picture"
    with pytest.raises(UncitableSourceError):
        DocumentStore(root).resolve_quote(
            document.doc_id, "picture", element_id=picture.element_id
        )


def test_bboxes_are_top_left_points_inside_the_slide(deck: Path, tmp_path: Path) -> None:
    document = ingest_deck(deck, store_root=tmp_path / "s")
    for element in document.elements:
        x0, y0, x1, y1 = element.bbox
        assert 0 <= x0 < x1 <= 720.01 and 0 <= y0 < y1 <= 540.01
    grouped = next(e for e in document.elements if e.text == "Grouped caption")
    assert grouped.bbox[0] == pytest.approx(72.0)  # Inches(1) in points
    assert grouped.bbox[1] == pytest.approx(288.0)


def test_deterministic(deck: Path, tmp_path: Path) -> None:
    a = ingest_deck(deck, store_root=tmp_path / "a")
    b = ingest_deck(deck, store_root=tmp_path / "b")
    assert a.model_dump_json() == b.model_dump_json()
    assert [e.element_id for e in a.elements] == [e.element_id for e in b.elements]


def test_store_is_run_local_and_isolated(deck: Path, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    corpus_store = DocumentStore(corpus)

    root1 = run_source_root(runs, "run-1")
    root2 = run_source_root(runs, "run-2")
    assert root1 == runs / "run-1" / "source"
    path = ingest_deck(deck, store_root=root1)

    assert (root1 / "client-deck--acme-review.json").exists()
    assert DocumentStore(root1).doc_ids() == ["client-deck--acme-review"]
    assert DocumentStore(root2).doc_ids() == []
    assert corpus_store.doc_ids() == []
    assert list(corpus.iterdir()) == []
    assert not (runs / "run-2").exists()
    assert path.doc_id.startswith("client-deck--")


def test_reingest_overwrites_cleanly(deck: Path, tmp_path: Path) -> None:
    root = run_source_root(tmp_path / "runs", "r1")
    ingest_deck(deck, store_root=root)
    prs = Presentation(str(deck))
    prs.slides[1].shapes.title.text = "Highlights, revised"
    prs.save(deck)
    ingest_deck(deck, store_root=root)

    store = DocumentStore(root)
    assert store.doc_ids() == ["client-deck--acme-review"]
    assert store.resolve_quote("client-deck--acme-review", "Highlights, revised").page == 2


def test_name_override_and_missing_file(deck: Path, tmp_path: Path) -> None:
    assert deck_doc_id("Q3 / Board Deck!") == "client-deck--q3-board-deck"
    document = ingest_deck(deck, store_root=tmp_path / "s", name="Board Deck")
    assert document.doc_id == "client-deck--board-deck"
    from autodeck.ingest.document_store import IngestError

    with pytest.raises(IngestError):
        ingest_deck(tmp_path / "nope.pptx", store_root=tmp_path / "s")
