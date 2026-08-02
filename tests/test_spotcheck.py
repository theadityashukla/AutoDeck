"""GATE 1a spot-check rendering.

The property worth protecting here is the one the module refuses to have: it produces no
verdict. `write_index` emits unticked checkboxes and prose telling the reviewer that a
passing hash is not evidence the box is right — because the bug this whole sheet exists to
catch (a vertically mirrored bbox) hash-verifies perfectly.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from autodeck.audit.spotcheck import (
    SpotCheck,
    SpotCheckError,
    build_spot_checks,
    render_citation,
    write_index,
)
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.ir.models import Citation

QUOTE = "Throughput rose from 412 to 671 sequences per second."

needs_poppler = pytest.mark.skipif(
    shutil.which("pdftoppm") is None, reason="poppler-utils not installed"
)


def citation(page: int = 1, quote: str = QUOTE) -> Citation:
    return Citation.for_quote(
        doc_id="paper-1",
        page=page,
        bbox=(72.0, 100.0, 523.0, 130.0),
        quote=quote,
        retrieved_by="writer",
    )


def stored(tmp_path: Path) -> DocumentStore:
    store = DocumentStore(tmp_path / "store")
    store.add(
        Document(
            doc_id="paper-1",
            source_path="paper-1.pdf",
            page_count=2,
            elements=[
                DocumentElement(
                    element_id="e1",
                    doc_id="paper-1",
                    kind="text",
                    page=1,
                    bbox=(72.0, 100.0, 523.0, 130.0),
                    reading_order=0,
                    text=QUOTE,
                )
            ],
        )
    )
    return store


def a_pdf(path: Path, pages: int = 2) -> Path:
    """A real multi-page PDF, written with the library the renderer will read it back with."""
    from PIL import Image

    sheets = [Image.new("RGB", (612, 792), "white") for _ in range(pages)]
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets[0].save(path, save_all=True, append_images=sheets[1:], resolution=72.0)
    return path


# ---------------------------------------------------------------------------
# The worksheet decides nothing
# ---------------------------------------------------------------------------


def test_the_index_ticks_no_boxes(tmp_path: Path) -> None:
    """A7: the verdict is the owner's, and nothing here records one on their behalf."""
    checks = [
        SpotCheck(citation=citation(), image=tmp_path / "1.png", hash_verified=True, label="c")
    ]
    text = write_index(checks, tmp_path / "index.md").read_text(encoding="utf-8")

    assert "- [ ]" in text
    assert "- [x]" not in text
    assert "PASSED" not in text


def test_the_index_warns_that_a_passing_hash_proves_nothing_visual(tmp_path: Path) -> None:
    """The whole reason the sheet renders images instead of printing check marks."""
    checks = [
        SpotCheck(citation=citation(), image=tmp_path / "1.png", hash_verified=True, label="c")
    ]
    text = write_index(checks, tmp_path / "index.md").read_text(encoding="utf-8")
    assert "mirrored" in text


def test_the_index_shows_the_claim_next_to_the_quote(tmp_path: Path) -> None:
    """Checking the box against the page is only half the question."""
    checks = [
        SpotCheck(
            citation=citation(),
            image=tmp_path / "1.png",
            hash_verified=True,
            label="Throughput improved substantially.",
        )
    ]
    text = write_index(checks, tmp_path / "index.md").read_text(encoding="utf-8")
    assert "Throughput improved substantially." in text
    assert QUOTE in text


def test_a_failed_hash_is_shouted(tmp_path: Path) -> None:
    checks = [
        SpotCheck(citation=citation(), image=tmp_path / "1.png", hash_verified=False, label="")
    ]
    text = write_index(checks, tmp_path / "index.md").read_text(encoding="utf-8")
    assert "**NO**" in text


def test_a_missing_pdf_is_reported_as_a_gate_failure(tmp_path: Path) -> None:
    """Not as an absence — a sheet that silently omits it looks complete when it is not."""
    store = stored(tmp_path)
    checks = build_spot_checks([(citation(), "claim")], store, {}, tmp_path / "out")

    assert len(checks) == 1
    assert checks[0].source_pdf is None
    text = write_index(checks, tmp_path / "index.md").read_text(encoding="utf-8")
    assert "cannot be checked" in text


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@needs_poppler
def test_a_citation_renders_to_an_image(tmp_path: Path) -> None:
    from PIL import Image

    pdf = a_pdf(tmp_path / "paper-1.pdf")
    out = render_citation(citation(), pdf, tmp_path / "out" / "check.png")

    assert out.exists()
    with Image.open(out) as image:
        assert image.size[0] > 612  # rendered above 72 dpi


@needs_poppler
def test_the_box_is_drawn_where_the_bbox_says(tmp_path: Path) -> None:
    """The assertion that would have caught the mirrored-bbox bug.

    The source page is blank white, so any non-white pixel is the drawn rectangle. Its
    top edge must land at the bbox's y0 scaled to the render dpi — not at
    `page_height - y1`, which is what a bottom-left/top-left mix-up produces and what a
    hash check cannot see.
    """
    from PIL import Image

    from autodeck.audit.spotcheck import RENDER_DPI

    pdf = a_pdf(tmp_path / "paper-1.pdf")
    out = render_citation(citation(), pdf, tmp_path / "out" / "check.png")

    with Image.open(out) as image:
        pixels = image.convert("RGB").load()
        width, height = image.size
        assert pixels is not None
        marked = [
            y
            for y in range(height)
            for x in range(0, width, 4)
            if pixels[x, y] != (255, 255, 255)
        ]

    scale = RENDER_DPI / 72.0
    assert marked, "nothing was drawn"
    assert min(marked) == pytest.approx(100.0 * scale, abs=6)  # bbox y0, not mirrored
    assert max(marked) == pytest.approx(130.0 * scale, abs=6)  # bbox y1


@needs_poppler
def test_a_page_beyond_the_document_fails_loudly(tmp_path: Path) -> None:
    """A citation pointing past the last page is wrong, and silence would hide it."""
    pdf = a_pdf(tmp_path / "paper-1.pdf", pages=2)
    with pytest.raises(SpotCheckError):
        render_citation(citation(page=9), pdf, tmp_path / "out" / "check.png")


@needs_poppler
def test_build_spot_checks_renders_and_verifies(tmp_path: Path) -> None:
    store = stored(tmp_path)
    pdf = a_pdf(tmp_path / "papers" / "paper-1.pdf")
    checks = build_spot_checks(
        [(citation(), "claim")], store, {"paper-1": pdf}, tmp_path / "out"
    )

    assert len(checks) == 1
    assert checks[0].hash_verified
    assert checks[0].image.exists()


def test_a_missing_pdftoppm_says_how_to_install_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(SpotCheckError, match="poppler-utils"):
        render_citation(citation(), tmp_path / "x.pdf", tmp_path / "out.png")
