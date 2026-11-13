"""A few pure edits on a deck state, enough for Phase 0's "an edit can be made".

Phase 1's edit tools grow from here. Every function takes a deck and returns a **new**,
fully validated `DeckArtifact`: build the updated data from `deck.model_dump()` (or nested
`model_copy` calls) and finish with `DeckArtifact.model_validate(...)` so every model
validator runs on the result. The input deck is never mutated (tests compare its
serialisation before and after). Ids are never changed: the strict overlay will key on
`slide_id:block_id` (plan §8.2), so an edit changes content, never identity.

These functions do not record anything; pass the result to `ArtifactStore.apply`.
"""

from __future__ import annotations

from autodeck.studio.errors import EditError
from autodeck.studio.models import DeckArtifact, Marker, Slide


def _slide_index(deck: DeckArtifact, slide_id: str) -> int:
    for index, slide in enumerate(deck.slides):
        if slide.id == slide_id:
            return index
    raise EditError(f"deck {deck.id!r} has no slide {slide_id!r}")


def set_block_text(
    deck: DeckArtifact, *, slide_id: str, block_id: str, text: str
) -> DeckArtifact:
    """The deck with the text of one text block replaced by `text` (verbatim, not stripped).

    Raises:
        EditError: no slide `slide_id`, no block `block_id` on it, or the block's kind is
            not `text` (the message names the kind).
        pydantic.ValidationError: `text` is empty or whitespace (a text block's own rule).
    """
    slide_index = _slide_index(deck, slide_id)
    slide = deck.slides[slide_index]
    block_index = next(
        (i for i, block in enumerate(slide.blocks) if block.id == block_id), None
    )
    if block_index is None:
        raise EditError(f"slide {slide_id!r} has no block {block_id!r}")
    block = slide.blocks[block_index]
    if block.kind != "text":
        raise EditError(
            f"block {block_id!r} on slide {slide_id!r} is a {block.kind}, not a text block; "
            "only a text block holds text"
        )
    data = deck.model_dump()
    data["slides"][slide_index]["blocks"][block_index]["text"] = text
    return DeckArtifact.model_validate(data)


def set_slide_marker(deck: DeckArtifact, *, slide_id: str, marker: Marker) -> DeckArtifact:
    """The deck with one slide's `marker` set. Setting the marker it already has returns an
    equal deck (the store will then refuse it as `NoChangeError`; that is the caller's
    concern).

    Raises:
        EditError: no slide `slide_id`.
    """
    slide_index = _slide_index(deck, slide_id)
    data = deck.model_dump()
    data["slides"][slide_index]["marker"] = marker
    return DeckArtifact.model_validate(data)


def move_slide(deck: DeckArtifact, *, slide_id: str, to_index: int) -> DeckArtifact:
    """The deck with slide `slide_id` moved to position `to_index` of the result (0-based;
    `list.insert` semantics after removal, so `to_index` may be 0 .. len(slides) - 1).

    Raises:
        EditError: no slide `slide_id`, or `to_index` outside 0 .. len(slides) - 1
            (negative indices are not accepted).
    """
    slide_index = _slide_index(deck, slide_id)
    if not 0 <= to_index <= len(deck.slides) - 1:
        raise EditError(
            f"to_index {to_index} is outside 0 .. {len(deck.slides) - 1} for deck {deck.id!r}"
        )
    data = deck.model_dump()
    slides = data["slides"]
    moved = slides.pop(slide_index)
    slides.insert(to_index, moved)
    return DeckArtifact.model_validate(data)


# ---------------------------------------------------------------------------
# Phase 1: the edits behind the lead's tools. Same rules as above: a new, fully validated
# deck (finish with `DeckArtifact.model_validate`), the input never mutated, ids never
# changed. None of these records anything.
# ---------------------------------------------------------------------------

STORYLINE_ID_PREFIX = "p"
"""New storyline points get ids `p1`, `p2`, ... (see `set_storyline`)."""


def set_brief(
    deck: DeckArtifact,
    *,
    title: str | None = None,
    audience: str | None = None,
    goal: str | None = None,
    notes: str | None = None,
    marker: Marker = "provisional",
) -> DeckArtifact:
    """The deck with its title and/or brief updated. `None` means "keep".

    `title` sets `deck.title`. If any of `audience`, `goal`, `notes` is given, the brief is
    updated: when `deck.brief` is None a new `Brief` is started from defaults; the given
    fields replace the old ones verbatim; the brief's `marker` becomes `marker`. When only
    `title` is given the brief (or its absence) is left exactly as it was and `marker` is
    ignored.

    Raises:
        EditError: every one of title, audience, goal and notes is None.
    """
    raise NotImplementedError


def set_storyline(
    deck: DeckArtifact,
    points: list[tuple[str | None, str]],
    *,
    marker: Marker = "provisional",
) -> tuple[DeckArtifact, list[tuple[str, str]]]:
    """The deck with its storyline replaced by `points` (in order), and the slide links
    that had to be dropped.

    Each point is `(id, text)`. A given id is kept as is (so a reworded point keeps its
    links). A point with id None gets a new id `p<n>`: n starts at one more than the
    largest number among ids of the form `p<digits>` in the *current* storyline and in the
    given ids (1 when there are none) and counts up in point order. The storyline's marker
    becomes `marker`. Then, for every slide in deck order, each id in `serves` that no
    longer names a point is removed (order of the rest kept), and `(slide_id, point_id)`
    is reported in the second return value, in deck order then `serves` order.

    Raises:
        EditError: two points have the same given id, or a given id is blank.
        pydantic.ValidationError: a point's text is empty.
    """
    raise NotImplementedError


def set_design_concept(
    deck: DeckArtifact, *, text: str, marker: Marker = "provisional"
) -> DeckArtifact:
    """The deck with `design_concept` set to `DesignConcept(text=text, marker=marker)`
    (text verbatim).

    Raises:
        pydantic.ValidationError: `text` is empty.
    """
    raise NotImplementedError


def upsert_slide(
    deck: DeckArtifact, slide: Slide, *, position: int | None = None
) -> tuple[DeckArtifact, bool, int]:
    """The deck with `slide` written into it, whether it was new, and its 1-based position.

    If a slide with `slide.id` exists it is replaced: in place when `position` is None,
    otherwise moved so that it ends at `position` (1 .. len(slides)). If it is new it is
    inserted so that it ends at `position` (1 .. len(slides) + 1), or appended when
    `position` is None. The slide is stored exactly as given (no field changed).

    Raises:
        EditError: `position` is outside the allowed range (the message gives the range).
        pydantic.ValidationError: the resulting deck is invalid, e.g. the slide serves a
            storyline point the deck does not have.
    """
    raise NotImplementedError


def remove_slide(deck: DeckArtifact, *, slide_id: str) -> DeckArtifact:
    """The deck without slide `slide_id`; the other slides keep their order.

    Raises:
        EditError: no slide `slide_id`.
    """
    raise NotImplementedError


def set_part_marker(deck: DeckArtifact, *, target: str, marker: Marker) -> DeckArtifact:
    """The deck with one part's marker set. `target` is `brief`, `storyline`,
    `design_concept` or `slide:<slide id>` (`tool_args.MARK_TARGET_PATTERN`). A slide
    target delegates to `set_slide_marker`.

    Raises:
        EditError: `brief` or `design_concept` when that part is None ("there is no brief
            yet"), no such slide, or a target outside the four forms.
    """
    raise NotImplementedError


def apply_candidate_slides(
    deck: DeckArtifact, slides: list[Slide], *, insert_at: int | None = None
) -> DeckArtifact:
    """The deck with a proposal option's candidate slides applied.

    First every candidate whose id is already in the deck replaces that slide in place.
    Then the remaining (new) candidates, in their given order, are inserted as one run so
    that the first of them ends at 1-based position `insert_at` of the result, or appended
    when `insert_at` is None. `insert_at` may be 1 .. (number of slides after the
    replacements) + 1.

    Raises:
        EditError: `slides` is empty, or `insert_at` is out of range.
        pydantic.ValidationError: the result is invalid (e.g. an unknown storyline point).
    """
    raise NotImplementedError
