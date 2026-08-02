"""VLM figure descriptions via the `ingest_vlm` role (task 1.3, §6.3).

A figure carries information that exists nowhere in the text — a trend line, an
architecture diagram, an ablation grid. Docling extracts the *pixels* and the caption; it
does not tell you what the picture shows. This module fills that gap by sending each
figure crop to a vision model and storing the answer as **metadata**.

## The one rule everything here is arranged around

A description is generated text. It is not in the document. It can be wrong in ways that
are fluent and specific — a VLM will happily read "412" off an axis label that says "4.12"
— and it arrives in the same store as verbatim prose. So:

- descriptions are written to `DocumentElement.description`, **never** to `.text`;
- `.text` for a figure stays empty, which is what makes `is_citable` return False;
- `DocumentStore.resolve_quote` searches `.text` only and never sees descriptions;
- the retrieval index deliberately *does* include them (§6.3 wants figures findable), and
  `RetrievedSpan.to_citation()` raises `UncitableSourceError` for them.

That chain is already enforced in `document_store` and `retrieval.hybrid`. What this module
adds is the generation, and `attach_descriptions` re-asserts the invariant afterwards
rather than assuming it survived — because the failure being guarded against is a future
edit here quietly writing into the wrong field.

## Why descriptions are worth having at all, if they cannot be cited

They route the writer to the right page. A search for "throughput scaling with batch size"
should surface the figure that shows it, so the writer opens the paper, reads the prose
that discusses the figure, and cites *that*. The description is a signpost, not a source.

Owning phase: 1 (task 1.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from autodeck.ingest.document_store import Document, DocumentElement, IngestError
from autodeck.providers.base import ImageInput, ProviderError

if TYPE_CHECKING:  # pragma: no cover — import costs seconds and pulls in torch
    from docling_core.types.doc import DoclingDocument

logger = logging.getLogger(__name__)

#: Upscale factor for figure crops. Docling's default page raster is too coarse for a VLM
#: to read axis labels; 2x is enough to make tick text legible without inflating the
#: request past what the vision endpoints accept comfortably.
FIGURE_IMAGE_SCALE = 2.0

DESCRIBE_SYSTEM_PROMPT = """\
You describe figures from research papers so they can be FOUND by a search engine later.

Your output is metadata. It will never be quoted as evidence, and no claim will ever cite
it — a separate system rejects that structurally. So the goal is recall, not authority:
describe what a reader searching for this figure would type.

Rules:
- Describe only what is visibly in the image. Do not infer the paper's conclusions.
- Transcribe axis labels, legend entries and units when they are legible, because those
  are the terms people search for.
- If a value is not clearly legible, say so instead of guessing it. A confidently wrong
  number is worse than an absent one, even in metadata.
- No preamble. No "This figure shows". Start with the noun.
"""


class FigureDescription(BaseModel):
    """Structured VLM output for one figure.

    Structured rather than free text so the searchable summary and the transcribed labels
    stay separable — and so `legible` is an explicit field the model must fill in rather
    than a hedge it may or may not remember to write into prose (A8).
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        min_length=1,
        description="What the figure shows, in one or two sentences. Search-oriented.",
    )
    figure_type: str = Field(
        default="",
        description="e.g. line chart, bar chart, architecture diagram, screenshot.",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Axis labels, legend entries, units and series names, read off the image.",
    )
    legible: bool = Field(
        default=True,
        description="False when the crop is too low-resolution or cropped to read reliably.",
    )

    def as_metadata(self) -> str:
        """Flatten to the string stored in `DocumentElement.description`.

        Prefixed so that anything printing element content — a debug dump, a prompt, a
        search result — shows what this is without needing to know which field it came
        from. Someone reading a wall of retrieved text should not have to remember that one
        of those paragraphs was written by a model.
        """
        parts = [f"[VLM figure description — metadata, not citable] {self.summary.strip()}"]
        if self.figure_type.strip():
            parts.append(f"Type: {self.figure_type.strip()}.")
        if self.labels:
            joined = "; ".join(label.strip() for label in self.labels if label)
            parts.append(f"Labels: {joined}")
        if not self.legible:
            parts.append("The model reported this crop as not reliably legible.")
        return " ".join(parts)


@dataclass(frozen=True)
class FigureImage:
    """One rendered figure crop, bound to the element it belongs to."""

    element_id: str
    data: bytes
    media_type: str = "image/png"

    def to_input(self) -> ImageInput:
        return ImageInput(data=self.data, media_type=self.media_type)


class VisionProvider(Protocol):
    """Structural type for what this module needs from a provider.

    Only `vision` is used. A `Protocol` rather than a base class so a real `BaseProvider`
    satisfies it without importing anything from here, and so a test fake is one method
    wide instead of the whole provider surface.
    """

    def vision(
        self,
        images: list[ImageInput],
        prompt: str,
        response_model: type[FigureDescription],
        *,
        system: str | None = None,
    ) -> FigureDescription: ...  # pragma: no cover — protocol shape only


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_figure_images(
    doc: DoclingDocument, *, doc_id: str, image_format: str = "PNG"
) -> list[FigureImage]:
    """Pull the rendered crop for each picture in a `DoclingDocument`.

    Requires the document to have been converted with `generate_picture_images=True`
    (`run_docling(..., generate_picture_images=True)`). Without it Docling keeps no pixels
    and this returns an empty list rather than failing — an un-described corpus is a
    smaller problem than an ingestion that refuses to finish.

    `element_id` is derived the same way `document_from_docling` derives it, so the two
    line up without either having to pass identifiers to the other.
    """
    import io

    images: list[FigureImage] = []
    for order, (item, _level) in enumerate(doc.iterate_items()):
        # Duck-typed rather than `isinstance(item, PictureItem)`: importing Docling's item
        # classes at module scope pulls in the heavy dependency chain this module is
        # careful to keep behind TYPE_CHECKING.
        render = (
            getattr(item, "get_image", None) if type(item).__name__ == "PictureItem" else None
        )
        if render is None:
            continue
        try:
            image = render(doc)
        except Exception as exc:  # pragma: no cover — Docling internals
            logger.warning("could not render figure %s: %s", order, exc)
            continue
        if image is None:
            continue
        buffer = io.BytesIO()
        image.save(buffer, format=image_format)
        images.append(
            FigureImage(
                element_id=_element_id_for(item, doc_id=doc_id, reading_order=order),
                data=buffer.getvalue(),
                media_type=f"image/{image_format.lower()}",
            )
        )
    return images


def _element_id_for(item: Any, *, doc_id: str, reading_order: int) -> str:
    """Mirror of `docling_runner._element_from_item`'s id scheme.

    Duplicated deliberately rather than imported: `docling_runner` imports torch-heavy
    modules lazily and this keeps that boundary intact. If the scheme changes in one place
    and not the other, `describe_figures` silently matches nothing — which is why
    `test_figure_ids_match_the_runner` exists.
    """
    self_ref = getattr(item, "self_ref", None) or f"#/items/{reading_order}"
    return f"{doc_id}:{str(self_ref).lstrip('#/').replace('/', '-')}"


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


def describe_figure(
    provider: VisionProvider, image: FigureImage, *, caption: str | None = None
) -> FigureDescription:
    """Describe one figure crop.

    Args:
        caption: the figure's caption, if the document has one. Passed as context because
            it disambiguates axes and series names the crop alone renders illegibly — and
            because a description that contradicts its own caption is a useful signal that
            the crop is wrong.

    Raises:
        ProviderError: the vision call failed or produced nothing schema-valid.
    """
    prompt = "Describe this figure for retrieval."
    if caption and caption.strip():
        prompt += (
            f"\n\nThe figure's caption in the paper reads:\n{caption.strip()}\n\n"
            "Use it to resolve ambiguous labels, but describe what is in the image — if "
            "the image disagrees with the caption, describe the image and say so."
        )
    return provider.vision(
        [image.to_input()], prompt, FigureDescription, system=DESCRIBE_SYSTEM_PROMPT
    )


def attach_descriptions(
    document: Document,
    images: list[FigureImage],
    provider: VisionProvider,
    *,
    strict: bool = False,
) -> int:
    """Describe every supplied figure and store the result as metadata.

    Writes to `element.description` only. `element.text` is left exactly as ingestion
    produced it, which for a figure means empty — and empty text is what makes
    `is_citable` False. The invariant is re-asserted after every write rather than
    trusted, because the thing being guarded against is a later edit in this file, and a
    guard that lives somewhere else would not catch it.

    Args:
        strict: raise on the first failed description instead of logging and continuing.
            Off by default: a corpus that ingests with some figures undescribed is usable,
            and an ingestion that aborts three hours in because one vision call 500'd is
            not. Turn it on when a complete corpus matters more than a finished run.

    Returns:
        How many descriptions were attached.

    Raises:
        IngestError: `strict` and a description failed; or — always, regardless of
            `strict` — a described element came out citable, which would be an A1 hole.
    """
    by_id = {element.element_id: element for element in document.elements}
    attached = 0

    for image in images:
        element = by_id.get(image.element_id)
        if element is None:
            logger.warning(
                "figure %s has no matching element in %s; the id schemes have drifted",
                image.element_id,
                document.doc_id,
            )
            continue

        caption = _caption_text(document, element)
        try:
            description = describe_figure(provider, image, caption=caption)
        except (ProviderError, ValueError) as exc:
            if strict:
                raise IngestError(
                    f"could not describe figure {image.element_id}: {exc}"
                ) from exc
            logger.warning("could not describe figure %s: %s", image.element_id, exc)
            continue

        element.description = description.as_metadata()
        attached += 1

        # The whole point of the module, checked rather than assumed. If this ever fires,
        # a description has been written somewhere that makes a generated sentence look
        # like a source — stop the ingestion rather than store it.
        if element.is_citable:
            raise IngestError(
                f"element {element.element_id} became citable after a VLM description was "
                "attached. A description is generated text and must never back a claim "
                "(A1, §6.3) — it belongs in `description`, and `text` must stay verbatim."
            )

    return attached


def _caption_text(document: Document, element: DocumentElement) -> str | None:
    """The caption linked to this figure by `_link_captions`, if any."""
    if not element.caption_ref:
        return None
    caption = document.element(element.caption_ref)
    return caption.text if caption is not None else None
