"""VLM figure descriptions, and the rule that they can never become evidence.

The load-bearing tests are `test_a_described_figure_is_still_not_citable` and
`test_a_description_never_lands_in_text`. Task 1.3's exit criterion is that descriptions
are retrievable *and structurally cannot be cited as fact* — enforced in the resolver, not
by convention — so both halves are asserted here against the real generation path rather
than only against hand-built elements.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.ingest.document_store import (
    Document,
    DocumentElement,
    DocumentStore,
    IngestError,
    UncitableSourceError,
)
from autodeck.ingest.figure_describer import (
    FigureDescription,
    FigureImage,
    attach_descriptions,
    describe_figure,
    extract_figure_images,
)
from autodeck.providers.base import ImageInput, ProviderError
from autodeck.retrieval.hybrid import build_index, search

PNG = b"\x89PNG\r\n\x1a\n fake pixels"


class FakeVision:
    """Returns a canned description and records what it was asked.

    D2 forbids local models, so the real `ingest_vlm` binding is a cloud call; injecting
    the provider keeps this path testable without a network or an API key.
    """

    def __init__(self, description: FigureDescription | None = None) -> None:
        self.description = description or FigureDescription(
            summary="Throughput against batch size for three quantization schemes.",
            figure_type="line chart",
            labels=["batch size", "tokens/s", "fp16", "int8"],
        )
        self.calls: list[tuple[list[ImageInput], str, str | None]] = []

    def vision(
        self,
        images: list[ImageInput],
        prompt: str,
        response_model: type[FigureDescription],
        *,
        system: str | None = None,
    ) -> FigureDescription:
        self.calls.append((images, prompt, system))
        return self.description


class BrokenVision:
    def vision(self, images: object, prompt: object, response_model: object, **_: object):
        raise ProviderError("vision endpoint returned 500")


def figure(element_id: str = "paper-1:pictures-0", page: int = 3) -> DocumentElement:
    """A figure as ingestion produces one: pixels on the page, no text."""
    return DocumentElement(
        element_id=element_id,
        doc_id="paper-1",
        kind="figure",
        page=page,
        bbox=(100.0, 200.0, 400.0, 450.0),
        reading_order=1,
        text="",
    )


def caption(text: str, *, element_id: str = "paper-1:texts-9") -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id="paper-1",
        kind="caption",
        page=3,
        bbox=(100.0, 455.0, 400.0, 470.0),
        reading_order=2,
        text=text,
    )


def document(*elements: DocumentElement) -> Document:
    return Document(
        doc_id="paper-1", source_path="paper-1.pdf", page_count=8, elements=list(elements)
    )


# ---------------------------------------------------------------------------
# A1 — a description is metadata, permanently
# ---------------------------------------------------------------------------


def test_a_described_figure_is_still_not_citable() -> None:
    """Task 1.3's exit criterion, on the real generation path."""
    doc = document(figure())
    attached = attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], FakeVision())

    element = doc.element("paper-1:pictures-0")
    assert attached == 1
    assert element is not None
    assert element.description  # it was described...
    assert not element.is_citable  # ...and is still not evidence


def test_a_description_never_lands_in_text() -> None:
    """`text` is the field the citation resolver reads. It must stay verbatim."""
    doc = document(figure())
    attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], FakeVision())

    element = doc.element("paper-1:pictures-0")
    assert element is not None
    assert element.text == ""
    assert "Throughput" in (element.description or "")


def test_citing_a_described_figure_raises(tmp_path: Path) -> None:
    """End to end: describe, store, then try to cite the description's own words.

    The error is `QuoteNotFoundError`, not `UncitableSourceError`, and the difference
    matters. `UncitableSourceError` would mean the resolver *found* the sentence and then
    refused it on grounds of element kind — one rule away from citable. `QuoteNotFoundError`
    means the resolver never saw it: descriptions live in a field it does not read, so a
    generated sentence is not a rejected candidate, it is not a candidate. That is the
    stronger guarantee, and it is the one to notice breaking.
    """
    from autodeck.ingest.document_store import QuoteNotFoundError

    doc = document(figure())
    attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], FakeVision())
    store = DocumentStore(tmp_path)
    store.add(doc)

    assert "Throughput against batch size" in (
        doc.element("paper-1:pictures-0").description or ""  # type: ignore[union-attr]
    )
    with pytest.raises(QuoteNotFoundError):
        store.resolve_quote("paper-1", "Throughput against batch size", retrieved_by="writer")


def test_a_figure_with_transcribed_text_is_refused_at_both_doors(tmp_path: Path) -> None:
    """Belt and braces: even if a figure somehow acquired text, its kind still refuses it.

    The description path cannot produce this — `attach_descriptions` raises if an element
    turns citable. This covers the other door: a future extractor that decides to OCR
    figure contents into `text` would have to get past `CITABLE_KINDS` as well.

    Both of the resolver's entry points are checked, because they fail differently and a
    reader of one error should not conclude the other path is open:

    - the broad search never puts a figure in the candidate set, so the quote is simply
      not found;
    - naming the element directly gets an explicit refusal that says why.
    """
    from autodeck.ingest.document_store import QuoteNotFoundError

    fig = figure()
    fig.text = "Throughput rose from 412 to 671 sequences per second."
    store = DocumentStore(tmp_path)
    store.add(document(fig))

    with pytest.raises(QuoteNotFoundError):
        store.resolve_quote("paper-1", "rose from 412 to 671", retrieved_by="writer")

    with pytest.raises(UncitableSourceError, match="cannot back a claim"):
        store.resolve_quote(
            "paper-1",
            "rose from 412 to 671",
            retrieved_by="writer",
            element_id="paper-1:pictures-0",
        )


def test_a_described_figure_is_findable() -> None:
    """§6.3: descriptions exist to be retrieved. Only citing them is forbidden."""
    doc = document(figure())
    attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], FakeVision())

    hits = search(build_index([doc], project="p"), "throughput batch size quantization")
    assert any(hit.element_id == "paper-1:pictures-0" for hit in hits)
    assert all(not hit.citable for hit in hits if hit.element_id == "paper-1:pictures-0")


def test_a_description_is_labelled_as_generated() -> None:
    """Anything dumping element content should show what wrote it, without extra context."""
    doc = document(figure())
    attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], FakeVision())
    element = doc.element("paper-1:pictures-0")
    assert element is not None
    assert element.description is not None
    assert element.description.startswith("[VLM figure description")


def test_attaching_to_a_text_element_is_refused() -> None:
    """The guard that catches a future edit writing into the wrong field.

    A text element with real prose is citable. If a description were ever attached to one,
    generated text would be sitting on a citable element — so the ingestion stops.
    """
    prose = DocumentElement(
        element_id="paper-1:texts-1",
        doc_id="paper-1",
        kind="text",
        page=1,
        bbox=(72.0, 100.0, 523.0, 130.0),
        reading_order=0,
        text="Quantization reduces memory use.",
    )
    doc = document(prose)
    with pytest.raises(IngestError, match="became citable"):
        attach_descriptions(doc, [FigureImage("paper-1:texts-1", PNG)], FakeVision())


# ---------------------------------------------------------------------------
# Generation behaviour
# ---------------------------------------------------------------------------


def test_the_caption_is_passed_as_context() -> None:
    """Captions disambiguate axis labels a crop renders illegibly."""
    fig = figure()
    fig.caption_ref = "paper-1:texts-9"
    doc = document(fig, caption("Figure 3: throughput on an A100-80GB node."))

    vision = FakeVision()
    attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], vision)

    _, prompt, system = vision.calls[0]
    assert "A100-80GB" in prompt
    assert system is not None
    assert "never be quoted as evidence" in system


def test_a_figure_without_a_caption_still_gets_described() -> None:
    vision = FakeVision()
    doc = document(figure())
    assert attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], vision) == 1
    assert "caption" not in vision.calls[0][1].lower()


def test_a_failed_description_does_not_abort_the_ingestion() -> None:
    """Aborting a three-hour corpus ingest because one vision call 500'd is worse."""
    doc = document(figure())
    attached = attach_descriptions(
        doc, [FigureImage("paper-1:pictures-0", PNG)], BrokenVision()
    )
    assert attached == 0
    element = doc.element("paper-1:pictures-0")
    assert element is not None
    assert element.description is None


def test_strict_mode_raises_on_a_failed_description() -> None:
    doc = document(figure())
    with pytest.raises(IngestError, match="could not describe figure"):
        attach_descriptions(
            doc, [FigureImage("paper-1:pictures-0", PNG)], BrokenVision(), strict=True
        )


def test_an_unmatched_figure_id_is_skipped() -> None:
    """Id-scheme drift must not crash ingestion — but it must not silently succeed either."""
    doc = document(figure())
    assert attach_descriptions(doc, [FigureImage("paper-1:ghost", PNG)], FakeVision()) == 0


def test_an_illegible_crop_says_so(tmp_path: Path) -> None:
    """A8: the model reporting it cannot read the figure is information worth keeping."""
    vision = FakeVision(FigureDescription(summary="A dense scatter plot.", legible=False))
    doc = document(figure())
    attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], vision)
    element = doc.element("paper-1:pictures-0")
    assert element is not None
    assert "not reliably legible" in (element.description or "")


def test_describe_figure_returns_the_structured_model() -> None:
    result = describe_figure(FakeVision(), FigureImage("paper-1:pictures-0", PNG))
    assert isinstance(result, FigureDescription)
    assert result.figure_type == "line chart"


def test_labels_are_carried_into_the_metadata() -> None:
    """Axis labels are what people actually search for."""
    doc = document(figure())
    attach_descriptions(doc, [FigureImage("paper-1:pictures-0", PNG)], FakeVision())
    element = doc.element("paper-1:pictures-0")
    assert element is not None
    assert "tokens/s" in (element.description or "")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extraction_returns_nothing_when_docling_kept_no_pixels() -> None:
    """`generate_picture_images=False` is the default; an empty list beats an exception."""

    class NoPictures:
        def iterate_items(self):
            return iter(())

    assert extract_figure_images(NoPictures(), doc_id="paper-1") == []  # type: ignore[arg-type]


def test_figure_ids_match_the_runner() -> None:
    """The id schemes are duplicated across two modules; this is what catches drift.

    If they diverge, `attach_descriptions` matches nothing and every figure silently ends
    up undescribed — a failure with no error message anywhere.
    """
    from autodeck.ingest.docling_runner import _element_from_item
    from autodeck.ingest.figure_describer import _element_id_for

    class Item:
        label = "picture"
        self_ref = "#/pictures/0"
        text = ""
        prov = ()

    element = _element_from_item(Item(), doc_id="paper-1", reading_order=7, page_heights={})
    assert element is not None
    assert element.element_id == _element_id_for(Item(), doc_id="paper-1", reading_order=7)
