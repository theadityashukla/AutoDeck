"""A client's finished deck as a source document (Phase 3d, B41).

In a redesign run the uploaded `.pptx` is ingested into the same `Document` model Docling
fills for a PDF, so everything downstream — the A1 resolver, the A2 linter, the A3
validator, the audit report — treats it like any other source. A slide plays the role of a
page (1-based) and a shape's position the role of a bbox. A citation into this document
proves the redesigned wording is *faithful to the client's deck*, not that it is true; the
audit report labels such citations "client-supplied deck" (B41).

Elements, in the order python-pptx yields shapes (z-order, which is also how the deck was
built; we do not re-sort by position because a guess at reading order is exactly what a
verbatim-provenance layer should not invent):

* a title placeholder is one `title` element (`text_frame.text`, paragraphs joined by
  newlines). Any other text frame gives one `text` element **per non-empty paragraph** —
  a bullet is the unit a slide states a fact in, so it is the unit a citation should name;
  one element per frame fused a slide's bullets into one run-on "sentence" that invited
  quotes spanning two bullets. Every element carries the frame's box (python-pptx knows
  no per-paragraph position). Text is exactly what python-pptx returns — never tidied,
  because the quote hash is taken over these characters. Empty paragraphs are skipped.
* one `table` element per table. Its `text` is the cells' text, tab-separated within a
  row and newline-separated between rows, so a quote of a cell resolves through
  `resolve_quote`; `table` carries the cell structure (with per-cell boxes computed from the
  column widths and row heights) so `resolve_cell` works too. Merged-away cells are skipped.
* one `text` element per slide's speaker notes, id `s{n}-notes`. Notes have no position on
  the slide, so the box is the whole slide; the id suffix lets a citation say "notes".
* group shapes are recursed, with the group's child coordinate space mapped back to slide
  coordinates.
* pictures, charts, media and other graphic frames become a **non-citable `figure`
  element** with no text and a `description` naming the shape kind (e.g. "picture"). We
  record them rather than omit them so the evidence pack can tell the writer "slide 4 has a
  chart whose data we cannot read" instead of silently dropping it, and `figure` is not in
  `CITABLE_KINDS`, so nothing can cite an image. Plain decorative shapes (lines, empty
  boxes) are omitted.

Coordinates follow the PDF elements: top-left origin, **points** (EMU / 12700), so a 16:9
slide is 960 x 540. Shapes with no usable geometry (a placeholder that inherits a position
python-pptx cannot resolve, or a zero-area box) get the whole slide as their box, which is
honest provenance for "somewhere on this slide" and keeps the element citable.

Determinism: ids are `s{slide}-e{n}` with `n` counting that slide's elements in order, and
nothing else (no clock, no hashing of paths) enters the Document, so the same file always
yields an identical Document.

A4: the deck is a source for **one run only**. Callers store it under
`run_source_root(runs_root, run_id)` = `runs/<run>/source/`, inside the client's namespace;
this module never writes into the project corpus or into another run, and `ingest_deck`
takes the store root explicitly so there is no default location to get wrong.
`DocumentStore.add` replaces an existing document with the same id, so re-ingesting the
same deck name into the same run overwrites it cleanly.

Owning phase: 3d (tasks 3d.1, 3d.2).
"""

from __future__ import annotations

import re
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.presentation import Presentation as PresentationType
from pptx.shapes.base import BaseShape
from pptx.shapes.group import GroupShape

from autodeck.ingest.document_store import (
    Document,
    DocumentElement,
    DocumentStore,
    ElementKind,
    IngestError,
    TableCell,
    TableData,
)
from autodeck.ir.models import BBox
from autodeck.ir.store import run_paths

EMU_PER_POINT = 12700

DOC_ID_PREFIX = "client-deck--"

_TITLE_PLACEHOLDERS = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}

#: A shape-tree transform: child EMU -> slide EMU, as (offset_x, offset_y, scale_x, scale_y).
_Transform = tuple[float, float, float, float]
_IDENTITY: _Transform = (0.0, 0.0, 1.0, 1.0)


def run_source_root(runs_root: Path, run_id: str) -> Path:
    """Where a run's own source documents live: `runs/<run_id>/source/` (B41, A4)."""
    return run_paths(runs_root, run_id).root / "source"


def deck_doc_id(name: str) -> str:
    """`client-deck--<slug>` for a deck name or file stem."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not slug:
        raise IngestError(f"cannot derive a deck id from {name!r}")
    return f"{DOC_ID_PREFIX}{slug}"


def ingest_deck(pptx_path: Path, *, store_root: Path, name: str | None = None) -> Document:
    """Read `pptx_path` into a `Document`, store it under `store_root`, and return it.

    Args:
        pptx_path: the client's deck.
        store_root: the run-local source store, `run_source_root(runs_root, run_id)`.
            Never the project corpus (A4).
        name: used for the doc id; defaults to the file stem.

    Raises:
        IngestError: the file is missing or is not a readable .pptx.
    """
    pptx_path = Path(pptx_path)
    if not pptx_path.is_file():
        raise IngestError(f"deck not found: {pptx_path}")
    try:
        presentation = Presentation(str(pptx_path))
    except Exception as exc:  # python-pptx raises several unrelated types on bad packages
        raise IngestError(f"cannot read {pptx_path.name} as a .pptx: {exc}") from exc

    doc_id = deck_doc_id(name or pptx_path.stem)
    document = document_from_presentation(
        presentation, doc_id=doc_id, source_path=str(pptx_path)
    )
    DocumentStore(Path(store_root)).add(document)
    return document


def document_from_presentation(
    presentation: PresentationType, *, doc_id: str, source_path: str
) -> Document:
    """Build the `Document` without touching disk (the testable half of `ingest_deck`)."""
    slide_w = float(presentation.slide_width or 0) / EMU_PER_POINT
    slide_h = float(presentation.slide_height or 0) / EMU_PER_POINT
    slide_box: BBox = (0.0, 0.0, slide_w, slide_h)

    elements: list[DocumentElement] = []
    title: str | None = None
    slides = list(presentation.slides)

    for slide_number, slide in enumerate(slides, start=1):
        counter = 0

        def add(
            kind: ElementKind,
            bbox: BBox,
            *,
            text: str = "",
            description: str | None = None,
            table: TableData | None = None,
            element_id: str | None = None,
            _slide_number: int = slide_number,
        ) -> None:
            nonlocal counter
            counter += 1
            elements.append(
                DocumentElement(
                    element_id=element_id or f"s{_slide_number}-e{counter}",
                    doc_id=doc_id,
                    kind=kind,
                    page=_slide_number,
                    bbox=bbox,
                    reading_order=len(elements),
                    text=text,
                    description=description,
                    table=table,
                )
            )

        walker = _SlideWalker(add, slide_box)
        walker.walk(slide.shapes, _IDENTITY)
        if title is None:
            title = walker.first_title

        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                add("text", slide_box, text=notes.text, element_id=f"s{slide_number}-notes")

    return Document(
        doc_id=doc_id,
        source_path=source_path,
        title=title,
        page_count=len(slides),
        elements=elements,
    )


class _SlideWalker:
    def __init__(self, add, slide_box: BBox) -> None:
        self._add = add
        self._slide_box = slide_box
        self.first_title: str | None = None

    def walk(self, shapes, transform: _Transform) -> None:
        for shape in shapes:
            if isinstance(shape, GroupShape):
                self.walk(shape.shapes, _child_transform(shape, transform))
                continue
            self._shape(shape, transform)

    def _shape(self, shape: BaseShape, transform: _Transform) -> None:
        bbox = self._bbox(shape, transform)
        kind = shape.shape_type

        if getattr(shape, "has_table", False) and shape.has_table:
            self._table(shape, bbox, transform)
            return

        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            text = shape.text_frame.text
            if text.strip():
                is_title = (
                    shape.is_placeholder
                    and shape.placeholder_format.type in _TITLE_PLACEHOLDERS
                )
                if is_title:
                    if self.first_title is None:
                        self.first_title = text
                    self._add("title", bbox, text=text)
                else:
                    for paragraph in shape.text_frame.paragraphs:
                        if paragraph.text.strip():
                            self._add("text", bbox, text=paragraph.text)
            return

        label = _figure_label(shape, kind)
        if label is not None:
            self._add("figure", bbox, description=label)

    def _table(self, shape: BaseShape, bbox: BBox, transform: _Transform) -> None:
        table = shape.table
        left, top = self._origin(shape, transform)
        sx, sy = transform[2], transform[3]
        col_x = [left]
        for column in table.columns:
            col_x.append(col_x[-1] + column.width * sx / EMU_PER_POINT)
        row_y = [top]
        for row in table.rows:
            row_y.append(row_y[-1] + row.height * sy / EMU_PER_POINT)

        cells: list[TableCell] = []
        lines: list[str] = []
        for r in range(len(table.rows)):
            texts: list[str] = []
            for c in range(len(table.columns)):
                cell = table.cell(r, c)
                texts.append(cell.text)
                if cell.is_spanned or not cell.text.strip():
                    continue
                r1 = min(r + cell.span_height, len(table.rows))
                c1 = min(c + cell.span_width, len(table.columns))
                cell_box: BBox = (col_x[c], row_y[r], col_x[c1], row_y[r1])
                cells.append(
                    TableCell(
                        row=r,
                        column=c,
                        row_span=cell.span_height,
                        column_span=cell.span_width,
                        text=cell.text,
                        bbox=cell_box,
                        is_header=r == 0 and table.first_row,
                    )
                )
            lines.append("\t".join(texts))
        text = "\n".join(lines)
        if not text.strip():
            return
        self._add(
            "table",
            bbox,
            text=text,
            table=TableData(rows=len(table.rows), columns=len(table.columns), cells=cells),
        )

    def _origin(self, shape: BaseShape, transform: _Transform) -> tuple[float, float]:
        ox, oy, sx, sy = transform
        try:
            left, top = shape.left, shape.top
        except Exception:
            left = top = None
        if left is None or top is None:
            return self._slide_box[0], self._slide_box[1]
        return (ox + left * sx) / EMU_PER_POINT, (oy + top * sy) / EMU_PER_POINT

    def _bbox(self, shape: BaseShape, transform: _Transform) -> BBox:
        try:
            left, top, width, height = shape.left, shape.top, shape.width, shape.height
        except Exception:
            return self._slide_box
        if None in (left, top, width, height):
            return self._slide_box
        ox, oy, sx, sy = transform
        x0 = (ox + left * sx) / EMU_PER_POINT
        y0 = (oy + top * sy) / EMU_PER_POINT
        x1 = (ox + (left + width) * sx) / EMU_PER_POINT
        y1 = (oy + (top + height) * sy) / EMU_PER_POINT
        if x1 <= x0 or y1 <= y0 or x0 < 0 or y0 < 0:
            return self._slide_box
        return (x0, y0, x1, y1)


def _child_transform(group: GroupShape, parent: _Transform) -> _Transform:
    """Map a group's child coordinate space to slide EMU, composed with `parent`."""
    xfrm = group._element.grpSpPr.xfrm
    if xfrm is None or xfrm.chExt is None or not xfrm.chExt.cx or not xfrm.chExt.cy:
        return parent
    gx, gy = xfrm.off.x, xfrm.off.y
    scale_x = xfrm.ext.cx / xfrm.chExt.cx
    scale_y = xfrm.ext.cy / xfrm.chExt.cy
    # child -> group space: gx + (c - chOff) * scale; then through the parent.
    px, py, psx, psy = parent
    ox = px + (gx - xfrm.chOff.x * scale_x) * psx
    oy = py + (gy - xfrm.chOff.y * scale_y) * psy
    return (ox, oy, scale_x * psx, scale_y * psy)


def _figure_label(shape: BaseShape, kind: MSO_SHAPE_TYPE | None) -> str | None:
    if kind == MSO_SHAPE_TYPE.PICTURE:
        return "picture"
    if getattr(shape, "has_chart", False) and shape.has_chart:
        return "chart"
    if kind == MSO_SHAPE_TYPE.MEDIA:
        return "media"
    if kind in (MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT, MSO_SHAPE_TYPE.LINKED_OLE_OBJECT):
        return "embedded object"
    if kind == MSO_SHAPE_TYPE.IGX_GRAPHIC:
        return "SmartArt graphic"
    return None
