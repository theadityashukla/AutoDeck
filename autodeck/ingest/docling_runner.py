"""Docling ingestion: PDF → `Document` with page and bbox provenance (D3).

The module is split deliberately at the seam where the machine learning stops:

- `run_docling()` calls Docling's converter. It needs model weights, a lot of memory, and
  a network connection the first time.
- `document_from_docling()` maps Docling's `DoclingDocument` onto our `Document`. It is
  pure, takes no models, and is where **every provenance decision lives** — coordinate
  origin, bbox conversion, reading order, which elements are citable.

That split is not tidiness. All the A1-relevant logic sits in the pure half, so it is
fully testable against hand-built documents, on any machine, in milliseconds — including
CI, which will never have the model weights.

**Coordinate origins matter.** Docling reports bounding boxes with a `BOTTOMLEFT` origin
by default (PDF convention), while the rest of AutoDeck uses top-left `(x0, y0, x1, y1)`.
Getting this wrong produces citations that are vertically mirrored — plausible-looking,
consistently wrong, and invisible until someone checks a box against the page. GATE 1a is
exactly that check, so the conversion is explicit and tested.

v1's ingestion is fully retired (`legacy/v1/LEGACY.md`): PyMuPDF parsing, agentic chunking
and ChromaDB. Do not consult it — its chunks structurally cannot carry `(doc_id, page,
bbox)`, which is why it is being replaced.

Owning phase: 1 (tasks 1.1, 1.3, 1.4).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autodeck.ingest.document_store import (
    Document,
    DocumentElement,
    ElementKind,
    IngestError,
    TableCell,
    TableData,
)
from autodeck.ingest.provenance import bbox_is_sane

if TYPE_CHECKING:  # pragma: no cover — import costs seconds and pulls in torch
    from docling_core.types.doc import DoclingDocument

logger = logging.getLogger(__name__)

#: Docling label -> our element kind. Labels with no useful provenance or no citable
#: content are dropped rather than mapped to something approximate.
_LABEL_MAP: dict[str, ElementKind] = {
    "title": "title",
    "section_header": "section_header",
    "text": "text",
    "paragraph": "text",
    "list_item": "list_item",
    "caption": "caption",
    "footnote": "footnote",
    "formula": "formula",
    "table": "table",
    "picture": "figure",
    "chart": "figure",
    "code": "code",
    "reference": "reference",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "document_index": "text",
}

#: Below this share of elements carrying a usable box, the document is flagged for human
#: review (plan §9). Two thirds is deliberately generous — the flag should fire on genuinely
#: broken extraction, not on a paper with a few decorative elements.
PROVENANCE_COVERAGE_THRESHOLD = 0.67


class ModelsUnavailableError(IngestError):
    """Docling's model weights could not be obtained.

    Its own message is a bare download failure, which reads as a transient network blip
    rather than what it usually is: an environment with no route to the model host. Since
    ingestion cannot proceed at all without these, the error says so plainly and names the
    hosts that must be reachable.
    """


def run_docling(
    pdf: Path,
    *,
    do_ocr: bool = False,
    do_table_structure: bool = True,
    generate_picture_images: bool = False,
) -> DoclingDocument:
    """Convert a PDF with Docling.

    Args:
        pdf: path to the source PDF.
        do_ocr: OCR the page images. Off by default — research PDFs are digital-native, and
            OCR costs a large model download plus minutes per document. Turn it on for
            scanned sources.
        do_table_structure: recover table cell structure. Required for cell-level citations
            (task 1.4, D10).
        generate_picture_images: keep a rendered crop of each figure, which
            `figure_describer.extract_figure_images` needs to send to the VLM. Off by
            default because it holds every figure's pixels in memory for the duration of
            the conversion, and a corpus being ingested without descriptions has no use
            for them.

    Raises:
        ModelsUnavailableError: model weights could not be fetched.
        IngestError: conversion failed for another reason.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from autodeck.ingest.figure_describer import FIGURE_IMAGE_SCALE

    pdf = Path(pdf)
    if not pdf.exists():
        raise IngestError(f"PDF not found: {pdf}")

    options = PdfPipelineOptions()
    options.do_ocr = do_ocr
    options.do_table_structure = do_table_structure
    options.generate_picture_images = generate_picture_images
    if generate_picture_images:
        # Docling's default raster is too coarse for a VLM to read tick labels, and an
        # illegible crop produces a confidently wrong transcription rather than a missing
        # one — the failure mode the `legible` field exists to surface.
        options.images_scale = FIGURE_IMAGE_SCALE

    try:
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        return converter.convert(pdf).document
    except Exception as exc:
        if _looks_like_a_download_failure(exc):
            raise ModelsUnavailableError(
                "Docling could not download its model weights. Ingestion needs the layout "
                "model and, with table structure enabled, TableFormer.\n\n"
                "Allowing huggingface.co alone is NOT enough: that host serves metadata "
                "and redirects the actual weights to a CDN. The full set is\n"
                "  huggingface.co        - repo metadata and small files\n"
                "  *.cdn.hf.co           - weight bytes (e.g. us.aws.cdn.hf.co)\n"
                "  *.xethub.hf.co        - Xet backend; avoidable with HF_HUB_DISABLE_XET=1\n"
                "  modelscope.cn         - RapidOCR, only when do_ocr=True\n\n"
                "If the network policy denies those, no amount of retrying will help — "
                "allow them, or pre-populate ~/.cache/docling and ~/.cache/huggingface "
                "from a machine that can reach them.\n\n"
                f"Underlying error: {type(exc).__name__}: {exc}"
            ) from exc
        raise IngestError(f"Docling failed on {pdf.name}: {type(exc).__name__}: {exc}") from exc


def _looks_like_a_download_failure(exc: Exception) -> bool:
    """Whether an exception is really "the weights could not be fetched"."""
    text = f"{type(exc).__name__}: {exc}".lower()
    # Weight *bytes* do not come from huggingface.co itself. It serves metadata and
    # redirects to a CDN (`*.cdn.hf.co`) or to the Xet content-addressed store
    # (`*.xethub.hf.co`), so an environment that allows only huggingface.co gets a 403 from
    # a host whose name never mentions HuggingFace. Matching on the API host alone would
    # misreport that as a generic failure.
    hosts = (
        "huggingface",
        "hf.co",
        "xethub",
        "cas-server",
        "cas client",
        "modelscope",
        "hf-mirror",
    )
    return (
        any(host in text for host in hosts)
        or "downloadfileexception" in text
        or ("proxyerror" in text and "403" in text)
    )


# ---------------------------------------------------------------------------
# The pure half: Docling document -> our Document
# ---------------------------------------------------------------------------


def document_from_docling(
    doc: DoclingDocument,
    *,
    doc_id: str,
    source_path: str,
) -> Document:
    """Map a `DoclingDocument` onto our `Document`, preserving provenance.

    Elements without usable provenance are **kept but left uncitable** rather than dropped:
    a reader may still want them, and silently discarding content makes a corpus look
    complete when it is not. What must never happen is inventing a plausible box for them.
    """
    elements: list[DocumentElement] = []
    page_heights = _page_heights(doc)

    for order, (item, _level) in enumerate(doc.iterate_items()):
        element = _element_from_item(
            item, doc_id=doc_id, reading_order=order, page_heights=page_heights
        )
        if element is not None:
            elements.append(element)

    document = Document(
        doc_id=doc_id,
        source_path=source_path,
        title=_document_title(doc),
        page_count=len(getattr(doc, "pages", {}) or {}),
        elements=elements,
    )

    coverage = document.provenance_coverage()
    if coverage < PROVENANCE_COVERAGE_THRESHOLD:
        document.low_provenance = True
        logger.warning(
            "%s: only %.0f%% of elements carry a usable bounding box; flagged for human "
            "review. Content from this document must not back claims until checked "
            "(plan §9).",
            doc_id,
            coverage * 100,
        )

    _link_captions(document)
    return document


def _document_title(doc: DoclingDocument) -> str | None:
    for item, _level in doc.iterate_items():
        if _label_of(item) == "title":
            text = getattr(item, "text", "")
            if text.strip():
                return text.strip()
    return None


def _label_of(item: Any) -> str:
    label = getattr(item, "label", None)
    return getattr(label, "value", label) if label is not None else ""


def _element_from_item(
    item: Any, *, doc_id: str, reading_order: int, page_heights: dict[int, float]
) -> DocumentElement | None:
    """Convert one Docling item. Returns None for items that carry nothing citable."""
    kind = _LABEL_MAP.get(_label_of(item))
    if kind is None:
        return None

    provenance = getattr(item, "prov", None) or []
    if not provenance:
        # No provenance at all. Kept with a degenerate box so it is visible in the store
        # and counted against coverage, but `is_citable` will refuse it.
        page, bbox = 1, (0.0, 0.0, 0.0, 0.0)
    else:
        first = provenance[0]
        page = int(getattr(first, "page_no", 1) or 1)
        bbox = _bbox_from_docling(getattr(first, "bbox", None), page_heights.get(page))

    self_ref = getattr(item, "self_ref", None) or f"#/items/{reading_order}"
    element_id = f"{doc_id}:{str(self_ref).lstrip('#/').replace('/', '-')}"

    table = _table_from_item(item, page_heights.get(page)) if kind == "table" else None
    text = getattr(item, "text", "") or ""
    if kind == "table" and not text.strip() and table is not None:
        # Docling gives tables no flat text; a searchable rendering keeps them findable
        # without pretending any single cell said it.
        text = _table_as_text(table)

    return DocumentElement(
        element_id=element_id,
        doc_id=doc_id,
        kind=kind,
        page=page,
        bbox=bbox,
        reading_order=reading_order,
        text=text,
        table=table,
    )


def _bbox_from_docling(
    bbox: Any, page_height: float | None = None
) -> tuple[float, float, float, float]:
    """Convert a Docling bounding box to top-left `(x0, y0, x1, y1)`.

    Docling reports a `BOTTOMLEFT` origin by default — PDF convention, where y grows
    *upward* from the bottom of the page. AutoDeck uses top-left throughout.

    Converting between them needs the **page height**: `y_top = page_height - y_bottomleft`.
    Merely swapping `t` and `b` produces a well-formed rectangle that is still in
    bottom-left space, so a heading at the top of an A4 page reads as y≈690 instead of
    y≈137 — every citation box mirrored about the page centre. It looks entirely reasonable
    in a report and fails the moment anyone checks it against the source, which is exactly
    what GATE 1a does. (This is not hypothetical: the first real-PDF run produced precisely
    that, which is why the page height is now threaded through.)

    When the origin is bottom-left and the page height is unknown, the conversion is
    impossible and this returns a degenerate box. That makes the element uncitable, which
    is the honest outcome — a wrong box is worse than no box.
    """
    if bbox is None:
        return (0.0, 0.0, 0.0, 0.0)

    left = float(getattr(bbox, "l", 0.0))
    top = float(getattr(bbox, "t", 0.0))
    right = float(getattr(bbox, "r", 0.0))
    bottom = float(getattr(bbox, "b", 0.0))

    origin = getattr(bbox, "coord_origin", None)
    origin_name = str(getattr(origin, "value", origin) or "").upper()
    is_bottom_left = origin_name == "BOTTOMLEFT" or (not origin_name and top > bottom)

    if is_bottom_left:
        if page_height is None or page_height <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        # Larger y is nearer the top of the page, so the box's top edge is max(t, b).
        return (left, page_height - max(top, bottom), right, page_height - min(top, bottom))

    return (left, min(top, bottom), right, max(top, bottom))


def _page_heights(doc: DoclingDocument) -> dict[int, float]:
    """Page number -> height in points, for the bottom-left conversion."""
    heights: dict[int, float] = {}
    for number, page in (getattr(doc, "pages", None) or {}).items():
        size = getattr(page, "size", None)
        height = getattr(size, "height", None) if size is not None else None
        if height:
            heights[int(number)] = float(height)
    return heights


def _table_from_item(item: Any, page_height: float | None) -> TableData | None:
    """Extract cell structure so individual cells stay citable (task 1.4)."""
    data = getattr(item, "data", None)
    if data is None:
        return None

    cells: list[TableCell] = []
    for cell in getattr(data, "table_cells", None) or []:
        text = getattr(cell, "text", "") or ""
        start_row = getattr(cell, "start_row_offset_idx", None)
        start_col = getattr(cell, "start_col_offset_idx", None)
        if start_row is None or start_col is None:
            continue
        end_row = getattr(cell, "end_row_offset_idx", start_row + 1) or start_row + 1
        end_col = getattr(cell, "end_col_offset_idx", start_col + 1) or start_col + 1

        cell_bbox = getattr(cell, "bbox", None)
        converted = (
            _bbox_from_docling(cell_bbox, page_height) if cell_bbox is not None else None
        )

        cells.append(
            TableCell(
                row=int(start_row),
                column=int(start_col),
                row_span=max(int(end_row) - int(start_row), 1),
                column_span=max(int(end_col) - int(start_col), 1),
                text=text,
                bbox=converted if converted and bbox_is_sane(converted) else None,
                is_header=bool(getattr(cell, "column_header", False))
                or bool(getattr(cell, "row_header", False)),
            )
        )

    return TableData(
        rows=int(getattr(data, "num_rows", 0) or 0),
        columns=int(getattr(data, "num_cols", 0) or 0),
        cells=cells,
    )


def _table_as_text(table: TableData) -> str:
    """A flat rendering of a table, for search only.

    Cell-level citations go through `DocumentStore.resolve_cell`; this exists so a table is
    findable by retrieval, not so it can be quoted as prose.
    """
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell in table.cells:
        rows.setdefault(cell.row, []).append((cell.column, cell.text))
    return "\n".join(
        " | ".join(text for _column, text in sorted(columns))
        for _row, columns in sorted(rows.items())
    )


def _link_captions(document: Document) -> None:
    """Attach each figure and table to the caption nearest below it on the same page.

    Captions are the citable text about a figure — the figure itself is not citable and its
    VLM description never will be — so the link is what lets a writer cite the right thing.
    """
    captions = [e for e in document.elements if e.kind == "caption"]
    if not captions:
        return

    for element in document.elements:
        if element.kind not in ("figure", "table"):
            continue
        following = [
            caption
            for caption in captions
            if caption.page == element.page and caption.reading_order > element.reading_order
        ]
        if following:
            element.caption_ref = min(following, key=lambda c: c.reading_order).element_id


def ingest_pdf(
    pdf: Path,
    *,
    doc_id: str,
    do_ocr: bool = False,
    vision_provider: object | None = None,
    strict_descriptions: bool = False,
) -> Document:
    """Convenience wrapper: convert a PDF and map it in one call.

    Needs model weights. The pure mapping is `document_from_docling`, which does not.

    Args:
        vision_provider: when supplied, each figure is rendered and described through the
            `ingest_vlm` role (task 1.3). Descriptions land in `element.description` and
            never in `element.text`, so a described figure stays uncitable — see
            `figure_describer` for why that separation is the whole point.
        strict_descriptions: abort the ingestion if a figure cannot be described, rather
            than logging and carrying on with that figure undescribed.
    """
    from autodeck.ingest.figure_describer import attach_descriptions, extract_figure_images

    pdf = Path(pdf)
    describe = vision_provider is not None
    docling_document = run_docling(pdf, do_ocr=do_ocr, generate_picture_images=describe)
    document = document_from_docling(docling_document, doc_id=doc_id, source_path=str(pdf))

    if describe:
        images = extract_figure_images(docling_document, doc_id=doc_id)
        attached = attach_descriptions(
            document,
            images,
            vision_provider,  # type: ignore[arg-type]
            strict=strict_descriptions,
        )
        logger.info("%s: described %d of %d figure(s)", doc_id, attached, len(images))

    return document
