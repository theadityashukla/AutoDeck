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

import re
from collections.abc import Sequence

from autodeck.studio.conversation import CandidateSlide
from autodeck.studio.errors import EditError
from autodeck.studio.models import Brief, DeckArtifact, Marker, Slide
from autodeck.studio.tool_args import MARK_TARGET_PATTERN


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
    if title is None and audience is None and goal is None and notes is None:
        raise EditError("set_brief needs at least one of title, audience, goal or notes")
    data = deck.model_dump()
    if title is not None:
        data["title"] = title
    if audience is not None or goal is not None or notes is not None:
        brief = (deck.brief or Brief()).model_dump()
        if audience is not None:
            brief["audience"] = audience
        if goal is not None:
            brief["goal"] = goal
        if notes is not None:
            brief["notes"] = notes
        brief["marker"] = marker
        data["brief"] = brief
    return DeckArtifact.model_validate(data)


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
    given = [pid for pid, _ in points if pid is not None]
    for pid in given:
        if not pid.strip():
            raise EditError("a storyline point id may not be blank")
    duplicates = sorted({pid for pid in given if given.count(pid) > 1})
    if duplicates:
        raise EditError(f"duplicate storyline point ids: {', '.join(duplicates)}")

    numbers = [
        int(m.group(1))
        for pid in [*(p.id for p in deck.storyline.points), *given]
        if (m := re.fullmatch(rf"{STORYLINE_ID_PREFIX}([0-9]+)", pid)) is not None
    ]
    next_number = max(numbers, default=0) + 1

    new_points: list[dict[str, str]] = []
    for pid, text in points:
        if pid is None:
            pid = f"{STORYLINE_ID_PREFIX}{next_number}"
            next_number += 1
        new_points.append({"id": pid, "text": text})
    kept_ids = {p["id"] for p in new_points}

    data = deck.model_dump()
    data["storyline"] = {"points": new_points, "marker": marker}
    dropped: list[tuple[str, str]] = []
    for slide in data["slides"]:
        survivors: list[str] = []
        for point_id in slide["serves"]:
            if point_id in kept_ids:
                survivors.append(point_id)
            else:
                dropped.append((slide["id"], point_id))
        slide["serves"] = survivors
    return DeckArtifact.model_validate(data), dropped


def set_design_concept(
    deck: DeckArtifact, *, text: str, marker: Marker = "provisional"
) -> DeckArtifact:
    """The deck with `design_concept` set to `DesignConcept(text=text, marker=marker)`
    (text verbatim).

    Raises:
        pydantic.ValidationError: `text` is empty.
    """
    data = deck.model_dump()
    data["design_concept"] = {"text": text, "marker": marker}
    return DeckArtifact.model_validate(data)


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
    existing = next((i for i, s in enumerate(deck.slides) if s.id == slide.id), None)
    count = len(deck.slides)
    top = count if existing is not None else count + 1
    if position is not None and not 1 <= position <= top:
        raise EditError(f"position {position} is outside 1 .. {top} for deck {deck.id!r}")

    slides = [s.model_dump() for s in deck.slides]
    if existing is not None:
        del slides[existing]
        insert_index = existing if position is None else position - 1
    else:
        insert_index = count if position is None else position - 1
    slides.insert(insert_index, slide.model_dump())

    data = deck.model_dump()
    data["slides"] = slides
    return DeckArtifact.model_validate(data), existing is None, insert_index + 1


def remove_slide(deck: DeckArtifact, *, slide_id: str) -> DeckArtifact:
    """The deck without slide `slide_id`; the other slides keep their order.

    Raises:
        EditError: no slide `slide_id`.
    """
    slide_index = _slide_index(deck, slide_id)
    data = deck.model_dump()
    del data["slides"][slide_index]
    return DeckArtifact.model_validate(data)


def set_part_marker(deck: DeckArtifact, *, target: str, marker: Marker) -> DeckArtifact:
    """The deck with one part's marker set. `target` is `brief`, `storyline`,
    `design_concept` or `slide:<slide id>` (`tool_args.MARK_TARGET_PATTERN`). A slide
    target delegates to `set_slide_marker`.

    Raises:
        EditError: `brief` or `design_concept` when that part is None ("there is no brief
            yet"), no such slide, or a target outside the four forms.
    """
    if not re.fullmatch(MARK_TARGET_PATTERN, target):
        raise EditError(
            f"target {target!r} is not brief, storyline, design_concept or slide:<slide id>"
        )
    if target.startswith("slide:"):
        return set_slide_marker(deck, slide_id=target[len("slide:") :], marker=marker)

    data = deck.model_dump()
    if target == "brief":
        if deck.brief is None:
            raise EditError("there is no brief yet")
        data["brief"]["marker"] = marker
    elif target == "design_concept":
        if deck.design_concept is None:
            raise EditError("there is no design concept yet")
        data["design_concept"]["marker"] = marker
    else:
        data["storyline"]["marker"] = marker
    return DeckArtifact.model_validate(data)


def apply_candidate_slides(
    deck: DeckArtifact, candidates: Sequence[CandidateSlide]
) -> tuple[DeckArtifact, list[str]]:
    """The deck with a proposal option's candidate slides applied, and what was done.

    Each candidate says what applying it does (`CandidateSlide`). First every replacement:
    the candidate takes the place of the slide it `replaces` and gets **that slide's id**
    (ids stay stable); if its `serves` is empty it inherits the replaced slide's `serves`,
    so storyline links are not dropped. Then each insertion, in the given order, so that it
    ends at its `insert_at` (1 .. current length + 1) of the deck as it then stands; its id
    must be new to the deck. Candidates with neither placement (an old record) are refused.

    Returns `(new deck, lines)`, one past-tense line per candidate in the given order, for
    example `Replaced slide 1 (id s1 kept) with the new slide: <intent>` / `Inserted new slide 's2b': <intent> as slide 3`.

    Raises:
        EditError: no candidates; a candidate without a placement; a replaced slide that is
            not in the deck (the message says the deck changed since the proposal); an
            inserted id that is already in the deck; `insert_at` out of range.
        pydantic.ValidationError: the result is invalid (e.g. an unknown storyline point).
    """
    if not candidates:
        raise EditError("there are no candidate slides to apply")
    slides = deck.model_dump()["slides"]
    ids = {s["id"] for s in slides}
    lines: dict[str, str] = {}

    for c in candidates:
        if c.replaces is None and c.insert_at is None:
            raise EditError(
                f"candidate {c.slide.id} does not say whether it replaces a slide or is "
                "inserted"
            )
    for c in candidates:
        if c.replaces is None:
            continue
        index = next((i for i, s in enumerate(slides) if s["id"] == c.replaces), None)
        if index is None:
            raise EditError(
                f"the proposal replaces slide {c.replaces!r}, which is no longer in deck "
                f"{deck.id!r} (the deck changed after it was proposed); make the change with "
                "write_slide, or propose again"
            )
        new = c.slide.model_dump()
        new["id"] = c.replaces
        if not new["serves"]:
            new["serves"] = list(slides[index]["serves"])
        slides[index] = new
        lines[c.slide.id] = (
            f"Replaced slide {index + 1} (id {c.replaces} kept) with the new slide{_intent(c.slide)}"
        )
    for c in candidates:
        if c.insert_at is None:
            continue
        if c.slide.id in ids or any(s["id"] == c.slide.id for s in slides):
            raise EditError(
                f"candidate {c.slide.id!r} is to be inserted but the deck already has a slide "
                "with that id; it should replace it, or take a new id"
            )
        if not 1 <= c.insert_at <= len(slides) + 1:
            raise EditError(
                f"insert_at {c.insert_at} is outside 1 .. {len(slides) + 1} for deck {deck.id!r}"
            )
        slides.insert(c.insert_at - 1, c.slide.model_dump())
        lines[c.slide.id] = (
            f"Inserted new slide {c.slide.id!r}{_intent(c.slide)} as slide {c.insert_at}"
        )

    data = deck.model_dump()
    data["slides"] = slides
    return DeckArtifact.model_validate(data), [lines[c.slide.id] for c in candidates]


def _intent(slide: Slide) -> str:
    return f": {slide.intent[:60]}" if slide.intent else ""
