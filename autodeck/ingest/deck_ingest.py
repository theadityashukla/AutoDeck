"""Reference-deck ingestion (Phase 4, task 4.2): a past deck read for style, never for truth.

`deck_source.py` reads a client's *current* deck into a `Document` so a redesign can cite it
(B41). This module reads a client's *past* decks (`knowledge/clients/<client>/decks/*.pptx`)
into a `ReferenceDeck`, from which `autodeck.design.reference` derives four profiles: how the
client's decks are structured, titled, worded and laid out.

## The accuracy rule (A1) is structural here

> Reference decks teach style and structure, never truth.

A sentence that shipped in a past deck is not evidence that it was ever right, and it reads
authoritatively while carrying no provenance. So nothing in this module, or in
`autodeck.design.reference`, can turn deck text into something a citation resolves against:

* `ReferenceDeck` is a plain pydantic model. It is **not** a `Document`; there is no
  function here or in `autodeck.design.reference` that builds a `Document`,
  `DocumentElement`, `RetrievedSpan` or `CachedClaim`, or that adds anything to a
  `DocumentStore` or a retrieval index. This module does not import `Document` or the
  redesign ingest path (`deck_source.ingest_deck` / `document_from_presentation`); it reuses
  only that module's geometry helpers.
* Text that a prompt may later show lives in a profile under a field named for what it is
  (`exemplar_headers`, `titles`, `terms`) and nowhere else.
* Ingestion writes only `decks/<slug>.profile.json`, `decks/profile.json` and
  `decks/gaps.json` inside the client's own namespace. Never the corpus, never a run's
  `source/` folder.

## A4

Every read of a deck and every write of a profile goes through `ReferenceStore`, which wraps
the client's `ClientNamespace` guard and additionally insists the path is inside that
client's `decks/` folder. A deck from another client, or from anywhere else, is refused.

Coordinates follow `deck_source`: top-left origin, points (EMU / 12700).

Owning phase: 4 (tasks 4.2, 4.8).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.shapes.base import BaseShape
from pptx.shapes.group import GroupShape
from pydantic import BaseModel, ConfigDict, Field

from autodeck.ingest.deck_source import (
    _IDENTITY,
    EMU_PER_POINT,
    _child_transform,
    _figure_label,
    _Transform,
)
from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import KnowledgeError

PROFILE_SUFFIX = ".profile.json"
AGGREGATE_FILE = "profile.json"
GAPS_FILE = "gaps.json"

_TITLE_PLACEHOLDERS = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
_BODY_PLACEHOLDERS = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT}


class ReferenceDeckError(KnowledgeError):
    """A reference deck path or file is not usable (outside `decks/`, unreadable)."""


def deck_slug(name: str) -> str:
    """A filesystem-safe slug for a deck file name or stem (`Q3 Review.pptx` -> `q3-review`)."""
    stem = name[:-5] if name.casefold().endswith(".pptx") else name
    slug = re.sub(r"[^a-z0-9]+", "-", stem.casefold()).strip("-")
    if not slug:
        raise ReferenceDeckError(f"cannot derive a deck slug from {name!r}")
    return slug


# ---------------------------------------------------------------------------
# Models — deliberately not a Document
# ---------------------------------------------------------------------------

Box = tuple[float, float, float, float]
ShapeKind = Literal["title", "text", "picture", "chart", "table", "shape"]


class RefParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    bullet: bool = False
    level: int = 0


class RefShape(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ShapeKind
    box: Box
    paragraphs: list[RefParagraph] = Field(default_factory=list)
    font_names: list[str] = Field(default_factory=list)
    max_font_pt: float | None = None
    fill: str | None = None
    covers_slide: bool = False

    @property
    def words(self) -> int:
        return sum(len(p.text.split()) for p in self.paragraphs)


class RefSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int  # 1-based
    layout_name: str = ""
    title: str = ""
    notes: str = ""
    shapes: list[RefShape] = Field(default_factory=list)

    @property
    def body_paragraphs(self) -> list[RefParagraph]:
        return [p for s in self.shapes if s.kind == "text" for p in s.paragraphs]

    def count(self, kind: ShapeKind) -> int:
        return sum(1 for s in self.shapes if s.kind == kind)


class ReferenceDeck(BaseModel):
    """What was read from one past deck. Style and structure input only; see the module
    docstring — this is not a `Document` and nothing converts it into one."""

    model_config = ConfigDict(extra="forbid")

    name: str
    slide_width: float
    slide_height: float
    slides: list[RefSlide]


# ---------------------------------------------------------------------------
# The namespace-guarded file access
# ---------------------------------------------------------------------------


class ReferenceStore:
    """All reads of reference decks and writes of derived profiles for one client (A4)."""

    def __init__(self, namespace: ClientNamespace) -> None:
        self.namespace = namespace

    @property
    def decks_dir(self) -> Path:
        return self.namespace.own_root / "decks"

    def deck_paths(self) -> list[Path]:
        if not self.decks_dir.is_dir():
            return []
        return sorted(self.decks_dir.glob("*.pptx"))

    def _inside_decks(self, path: Path) -> Path:
        if ".." in Path(path).parts:
            raise ReferenceDeckError(f"{path}: '..' is not allowed in a reference deck path")
        guarded = self.namespace.guard(Path(path)).resolve()
        decks = self.decks_dir
        if decks != guarded and decks not in guarded.parents:
            raise ReferenceDeckError(
                f"{path} is outside client {self.namespace.client!r}'s decks/ folder ({decks})"
            )
        return guarded

    def resolve_deck(self, name_or_path: str | Path) -> Path:
        """A deck by bare file name (looked up in `decks/`) or by path; guarded either way."""
        candidate = Path(name_or_path)
        if len(candidate.parts) == 1:
            candidate = self.decks_dir / candidate
        resolved = self._inside_decks(candidate)
        if resolved.suffix.casefold() != ".pptx":
            raise ReferenceDeckError(f"{name_or_path}: a reference deck must be a .pptx")
        if not resolved.is_file():
            raise ReferenceDeckError(f"reference deck not found: {resolved}")
        return resolved

    def read_deck(self, name_or_path: str | Path) -> ReferenceDeck:
        path = self.resolve_deck(name_or_path)
        try:
            presentation = Presentation(str(path))
        except Exception as exc:  # python-pptx raises several unrelated types
            raise ReferenceDeckError(f"cannot read {path.name} as a .pptx: {exc}") from exc
        return reference_deck_from_presentation(presentation, name=path.stem)

    def write_json(self, path: Path, payload: object) -> Path:
        """Deterministic JSON (sorted keys, no timestamps), atomically, inside `decks/`."""
        target = self._inside_decks(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(dump_json(payload), encoding="utf-8")
        temporary.replace(target)
        return target

    def read_json(self, path: Path) -> object:
        target = self._inside_decks(path)
        return json.loads(self.namespace.read(target))

    def profile_path(self, slug: str) -> Path:
        return self.decks_dir / f"{slug}{PROFILE_SUFFIX}"

    @property
    def aggregate_path(self) -> Path:
        return self.decks_dir / AGGREGATE_FILE

    @property
    def gaps_path(self) -> Path:
        return self.decks_dir / GAPS_FILE


def dump_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Reading a presentation
# ---------------------------------------------------------------------------


def reference_deck_from_presentation(presentation, *, name: str) -> ReferenceDeck:  # type: ignore[no-untyped-def]
    """Build the `ReferenceDeck` without touching disk (the testable half)."""
    width = float(presentation.slide_width or 0) / EMU_PER_POINT
    height = float(presentation.slide_height or 0) / EMU_PER_POINT
    slides: list[RefSlide] = []
    for number, slide in enumerate(presentation.slides, start=1):
        walker = _Walker((0.0, 0.0, width, height))
        walker.walk(slide.shapes, _IDENTITY)
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text
        try:
            layout_name = slide.slide_layout.name or ""
        except Exception:
            layout_name = ""
        slides.append(
            RefSlide(
                index=number,
                layout_name=layout_name,
                title=walker.title,
                notes=notes,
                shapes=walker.shapes,
            )
        )
    return ReferenceDeck(name=name, slide_width=width, slide_height=height, slides=slides)


class _Walker:
    def __init__(self, slide_box: Box) -> None:
        self.slide_box = slide_box
        self.shapes: list[RefShape] = []
        self.title = ""

    def walk(self, shapes: Iterable[BaseShape], transform: _Transform) -> None:
        for shape in shapes:
            if isinstance(shape, GroupShape):
                self.walk(shape.shapes, _child_transform(shape, transform))
            else:
                self._shape(shape, transform)

    def _box(self, shape: BaseShape, transform: _Transform) -> Box | None:
        try:
            left, top, width, height = shape.left, shape.top, shape.width, shape.height
        except Exception:
            return None
        if None in (left, top, width, height):
            return None
        ox, oy, sx, sy = transform
        box = (
            (ox + left * sx) / EMU_PER_POINT,
            (oy + top * sy) / EMU_PER_POINT,
            (ox + (left + width) * sx) / EMU_PER_POINT,
            (oy + (top + height) * sy) / EMU_PER_POINT,
        )
        return (round(box[0], 1), round(box[1], 1), round(box[2], 1), round(box[3], 1))

    def _shape(self, shape: BaseShape, transform: _Transform) -> None:
        box = self._box(shape, transform)
        has_geometry = box is not None and box[2] > box[0] and box[3] > box[1]
        if box is None or not has_geometry:
            box = self.slide_box
        sw, sh = self.slide_box[2], self.slide_box[3]
        covers = (box[2] - box[0]) * (box[3] - box[1]) >= 0.95 * sw * sh
        fill = _fill_of(shape)

        kind: ShapeKind | None = None
        if getattr(shape, "has_table", False) and shape.has_table:
            kind = "table"
        else:
            label = _figure_label(shape, shape.shape_type)
            if label == "picture":
                kind = "picture"
            elif label == "chart":
                kind = "chart"
        if kind is not None:
            self.shapes.append(RefShape(kind=kind, box=box, fill=fill, covers_slide=covers))
            return

        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            frame = shape.text_frame
            paragraphs, fonts, biggest = _paragraphs(shape, frame)
            if paragraphs:
                is_title = (
                    shape.is_placeholder
                    and shape.placeholder_format.type in _TITLE_PLACEHOLDERS
                )
                if is_title and not self.title:
                    self.title = frame.text.strip()
                self.shapes.append(
                    RefShape(
                        kind="title" if is_title else "text",
                        box=box,
                        paragraphs=paragraphs,
                        font_names=fonts,
                        max_font_pt=biggest,
                        fill=fill,
                        covers_slide=covers,
                    )
                )
                return
        if fill is not None or shape.shape_type in (
            MSO_SHAPE_TYPE.AUTO_SHAPE,
            MSO_SHAPE_TYPE.FREEFORM,
        ):
            self.shapes.append(RefShape(kind="shape", box=box, fill=fill, covers_slide=covers))


def _paragraphs(shape: BaseShape, frame) -> tuple[list[RefParagraph], list[str], float | None]:  # type: ignore[no-untyped-def]
    in_body = shape.is_placeholder and shape.placeholder_format.type in _BODY_PLACEHOLDERS
    non_empty = [p for p in frame.paragraphs if p.text.strip()]
    paragraphs: list[RefParagraph] = []
    fonts: list[str] = []
    biggest: float | None = None
    for paragraph in non_empty:
        pPr = paragraph._p.pPr
        explicit = pPr is not None and any(
            child.tag.endswith(("}buChar", "}buAutoNum", "}buBlip")) for child in pPr
        )
        no_bullet = pPr is not None and any(child.tag.endswith("}buNone") for child in pPr)
        text = paragraph.text.strip()
        bullet = (
            explicit
            or text[:1] in "\u2022\u25aa\u25cf\u25e6-\u2013\u2014*"
            or (in_body and len(non_empty) >= 2 and not no_bullet)
        )
        paragraphs.append(
            RefParagraph(text=text, bullet=bool(bullet), level=int(paragraph.level or 0))
        )
        for run in paragraph.runs:
            if run.font.name:
                fonts.append(run.font.name)
            if run.font.size is not None:
                points = run.font.size.pt
                biggest = points if biggest is None else max(biggest, points)
    return paragraphs, fonts, biggest


def _fill_of(shape: BaseShape) -> str | None:
    """`#RRGGBB` or `theme:<NAME>` for an explicit solid fill; None otherwise."""
    try:
        fill = shape.fill
        if fill.type != 1:  # MSO_FILL.SOLID
            return None
        colour = fill.fore_color
        if colour.type == 1:  # RGB
            return f"#{colour.rgb}"
        if colour.type == 2:  # THEME
            return f"theme:{colour.theme_color.name if colour.theme_color else 'UNKNOWN'}"
    except Exception:
        return None
    return None
