"""The Phase 1 edits behind the lead's tools: new validated decks, input never mutated."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodeck.studio.conversation import CandidateSlide
from autodeck.studio.edits import (
    apply_candidate_slides,
    remove_slide,
    set_brief,
    set_design_concept,
    set_part_marker,
    set_storyline,
    upsert_slide,
)
from autodeck.studio.errors import EditError
from autodeck.studio.models import DeckArtifact, Slide
from autodeck.studio.serialise import dump_artifact


def _empty(base_deck: DeckArtifact) -> DeckArtifact:
    return DeckArtifact(id=base_deck.id, client=base_deck.client, project=base_deck.project)


def _slide(base_deck: DeckArtifact, source: str, new_id: str, serves: list[str]) -> Slide:
    data = base_deck.slide(source).model_dump()
    data.update(id=new_id, serves=serves)
    return Slide.model_validate(data)


def test_set_brief_starts_a_brief_and_keeps_unset_fields(base_deck: DeckArtifact) -> None:
    deck = _empty(base_deck)
    before = dump_artifact(deck)
    out = set_brief(deck, audience="Board", goal="Approve")
    assert dump_artifact(deck) == before
    assert out.brief is not None
    assert (out.brief.audience, out.brief.goal, out.brief.notes, out.brief.marker) == (
        "Board",
        "Approve",
        "",
        "provisional",
    )
    again = set_brief(out, notes="Short", marker="decided")
    assert again.brief is not None
    assert (again.brief.audience, again.brief.notes, again.brief.marker) == (
        "Board",
        "Short",
        "decided",
    )


def test_title_only_leaves_the_brief_alone(base_deck: DeckArtifact) -> None:
    deck = _empty(base_deck)
    out = set_brief(deck, title="Readout", marker="decided")
    assert out.title == "Readout" and out.brief is None
    with pytest.raises(EditError):
        set_brief(deck)


def test_set_storyline_assigns_ids_and_drops_dead_links(base_deck: DeckArtifact) -> None:
    out, dropped = set_storyline(
        base_deck, [("p1", "Reworded first point"), (None, "A new point"), ("p3", "Third")]
    )
    assert out.storyline.point_ids() == ["p1", "p4", "p3"]
    assert out.storyline.points[0].text == "Reworded first point"
    assert out.storyline.marker == "provisional"
    assert dropped == [("s2", "p2"), ("s3", "p2")]
    assert out.slide("s2").serves == [] and out.slide("s1").serves == ["p1"]


def test_set_storyline_on_an_empty_deck_numbers_from_one(base_deck: DeckArtifact) -> None:
    out, dropped = set_storyline(
        _empty(base_deck), [(None, "a"), (None, "b")], marker="decided"
    )
    assert out.storyline.point_ids() == ["p1", "p2"] and dropped == []
    assert out.storyline.marker == "decided"


def test_set_storyline_refuses_duplicate_or_blank_ids(base_deck: DeckArtifact) -> None:
    with pytest.raises(EditError):
        set_storyline(base_deck, [("p1", "a"), ("p1", "b")])
    with pytest.raises(EditError):
        set_storyline(base_deck, [(" ", "a")])
    with pytest.raises(ValidationError):
        set_storyline(base_deck, [(None, "")])


def test_set_design_concept(base_deck: DeckArtifact) -> None:
    out = set_design_concept(base_deck, text="Dark and quiet.", marker="decided")
    assert out.design_concept is not None
    assert (out.design_concept.text, out.design_concept.marker) == (
        "Dark and quiet.",
        "decided",
    )


def test_upsert_replaces_in_place_or_moves(base_deck: DeckArtifact) -> None:
    changed = _slide(base_deck, "s2", "s2", ["p2"])
    changed = changed.model_copy(update={"intent": "New intent"})
    out, created, position = upsert_slide(base_deck, changed)
    assert (created, position) == (False, 2) and out.slide("s2").intent == "New intent"
    out, created, position = upsert_slide(base_deck, changed, position=4)
    assert (created, position) == (False, 4) and out.slide_ids() == ["s1", "s3", "s4", "s2"]


def test_upsert_inserts_or_appends(base_deck: DeckArtifact) -> None:
    new = _slide(base_deck, "s2", "s9", ["p2"])
    out, created, position = upsert_slide(base_deck, new)
    assert (created, position) == (True, 5) and out.slide_ids()[-1] == "s9"
    out, created, position = upsert_slide(base_deck, new, position=1)
    assert (created, position) == (True, 1) and out.slide_ids()[0] == "s9"
    with pytest.raises(EditError):
        upsert_slide(base_deck, new, position=6)
    with pytest.raises(EditError):
        upsert_slide(base_deck, base_deck.slide("s1"), position=5)


def test_upsert_refuses_unknown_storyline_points(base_deck: DeckArtifact) -> None:
    with pytest.raises(ValidationError):
        upsert_slide(base_deck, _slide(base_deck, "s2", "s9", ["p9"]))


def test_remove_slide(base_deck: DeckArtifact) -> None:
    before = dump_artifact(base_deck)
    out = remove_slide(base_deck, slide_id="s2")
    assert out.slide_ids() == ["s1", "s3", "s4"] and dump_artifact(base_deck) == before
    with pytest.raises(EditError):
        remove_slide(base_deck, slide_id="s9")


def test_set_part_marker(base_deck: DeckArtifact) -> None:
    out = set_part_marker(base_deck, target="design_concept", marker="decided")
    assert out.design_concept is not None and out.design_concept.marker == "decided"
    out = set_part_marker(base_deck, target="slide:s3", marker="decided")
    assert out.slide("s3").marker == "decided"
    out = set_part_marker(base_deck, target="storyline", marker="provisional")
    assert out.storyline.marker == "provisional"
    with pytest.raises(EditError):
        set_part_marker(_empty(base_deck), target="brief", marker="decided")
    with pytest.raises(EditError):
        set_part_marker(base_deck, target="slide:s9", marker="decided")
    with pytest.raises(EditError):
        set_part_marker(base_deck, target="everything", marker="decided")


def _cand(
    slide: Slide, *, replaces: str | None = None, insert_at: int | None = None
) -> CandidateSlide:
    return CandidateSlide(slide=slide, replaces=replaces, insert_at=insert_at)


def test_apply_candidate_slides_replaces_in_place_and_keeps_the_replaced_id(
    base_deck: DeckArtifact,
) -> None:
    before = dump_artifact(base_deck)
    first = base_deck.slides[0]
    new_opening = _slide(base_deck, "s2", "s1b", [])
    out, lines = apply_candidate_slides(base_deck, [_cand(new_opening, replaces="s1")])
    assert dump_artifact(base_deck) == before
    # Same count, new content first, the replaced slide's id kept, its links inherited.
    assert len(out.slides) == len(base_deck.slides)
    assert out.slide_ids() == base_deck.slide_ids()
    assert out.slides[0].intent == base_deck.slide("s2").intent != first.intent
    assert out.slides[0].serves == first.serves
    assert lines == [
        f"Replaced slide 1 (id s1 kept) with the new slide: {base_deck.slide('s2').intent[:60]}"
    ]


def test_a_replacement_that_names_links_keeps_its_own(base_deck: DeckArtifact) -> None:
    new_opening = _slide(base_deck, "s2", "s1b", ["p2"])
    out, _ = apply_candidate_slides(base_deck, [_cand(new_opening, replaces="s1")])
    assert out.slides[0].serves == ["p2"]


def test_apply_candidate_slides_replaces_then_inserts(base_deck: DeckArtifact) -> None:
    replacement = _slide(base_deck, "s2", "r1", ["p1"])
    new_a = _slide(base_deck, "s2", "n1", ["p2"])
    new_b = _slide(base_deck, "s3", "n2", ["p2"])
    out, lines = apply_candidate_slides(
        base_deck,
        [
            _cand(new_a, insert_at=2),
            _cand(replacement, replaces="s1"),
            _cand(new_b, insert_at=3),
        ],
    )
    assert out.slide_ids() == ["s1", "n1", "n2", "s2", "s3", "s4"]
    assert out.slide("s1").intent == base_deck.slide("s2").intent
    assert [line.split(" ")[0] for line in lines] == ["Inserted", "Replaced", "Inserted"]
    assert lines[0].endswith("as slide 2") and lines[2].endswith("as slide 3")


def test_apply_candidate_slides_refusals(base_deck: DeckArtifact) -> None:
    new_a = _slide(base_deck, "s2", "n1", ["p2"])
    with pytest.raises(EditError, match="no candidate"):
        apply_candidate_slides(base_deck, [])
    with pytest.raises(EditError, match="outside 1"):
        apply_candidate_slides(base_deck, [_cand(new_a, insert_at=6)])
    # The slide to replace is gone: the message says the deck changed.
    with pytest.raises(EditError, match=r"no longer in deck.*changed after"):
        apply_candidate_slides(base_deck, [_cand(new_a, replaces="gone")])
    # An insertion may not reuse an id the deck has (it used to replace silently).
    clash = _slide(base_deck, "s2", "s3", ["p2"])
    with pytest.raises(EditError, match="already has a slide with that id"):
        apply_candidate_slides(base_deck, [_cand(clash, insert_at=1)])
    # A candidate with no placement (an old record) is refused.
    with pytest.raises(EditError, match="does not say"):
        apply_candidate_slides(base_deck, [_cand(new_a)])
