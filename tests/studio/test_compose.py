"""Task 23.11: composition orchestration (`compose.py`): what to compose, the result text,
sample slides, draft systems. The end-to-end behaviour (through the tools) is pinned in
`test_tools_phase23.py`."""

from __future__ import annotations

import pytest

from autodeck.studio import edits
from autodeck.studio.compose import (
    DRAFT_SYSTEM_ID,
    NOTHING_TO_COMPOSE,
    compose_text,
    deck_briefs,
    draft_system,
    sample_slides,
    select_slides,
)
from autodeck.studio.errors import CompositionError, EditError
from autodeck.studio.models import ComposedFrom, DeckArtifact, Slide, brief_digest
from autodeck.studio.tools import ComposedSlide
from tests.studio.helpers import flow_brief, flow_designed, flow_draft, load_fixture_deck


def deck_of_three() -> DeckArtifact:
    """s1 fresh, s2 not designed, s3 fresh; then s3's brief changes (stale)."""
    deck = DeckArtifact(id="d", client="c", project="p")
    for sid in ("s1", "s2", "s3"):
        deck, _, _ = edits.set_slide_brief(deck, sid, flow_brief(sid))
    for sid in ("s1", "s3"):
        data = flow_designed(sid)["slide"]
        b = flow_brief(sid)
        slide = Slide(
            id=sid, intent=b.intent, brief=b, blocks=data["blocks"], layout=data["layout"]
        )
        deck = edits.apply_composition(
            deck,
            sid,
            slide,
            ComposedFrom(
                brief_digest=brief_digest(b),
                system_id="default",
                system_version=1,
                model_id="m",
            ),
        )
    changed = flow_brief("s3").model_copy(update={"notes": "The return matters most."})
    deck, _, _ = edits.set_slide_brief(deck, "s3", changed)
    return deck


def test_select_stale_and_undesigned_by_default_and_named_in_deck_order() -> None:
    deck = deck_of_three()
    assert select_slides(deck, None) == ["s2", "s3"]
    assert select_slides(deck, ["s3", "s1", "s3"]) == ["s1", "s3"]
    with pytest.raises(EditError, match="s9"):
        select_slides(deck, ["s9"])
    legacy = edits.upsert_slide(
        deck, load_fixture_deck().slide("s1").model_copy(update={"id": "x", "serves": []})
    )[0]
    with pytest.raises(CompositionError, match="no brief"):
        select_slides(legacy, ["x"])
    assert select_slides(load_fixture_deck(), None) == []


def test_compose_text() -> None:
    results = [
        ComposedSlide("s1", True, 1, (), "m", 1.0, "c0004"),
        ComposedSlide("s2", True, 3, (), "m", 1.0, "c0005"),
        ComposedSlide(
            "s3",
            False,
            4,
            ("[text_fit] f2: a", "[overlap] b", "[contrast] c", "[x] d"),
            "m",
            1.0,
            "c0006",
        ),
    ]
    assert compose_text(results) == (
        "Composed 2 of 3 slides.\n"
        "- s1: clean in 1 attempt\n"
        "- s2: clean in 3 attempts\n"
        "- s3: failed after 4 attempts: [text_fit] f2: a; [overlap] b; [contrast] c\n"
        "The previous design is kept for slides that failed; shorten their briefs or ask again."
    )
    assert compose_text([]) == NOTHING_TO_COMPOSE


def test_sample_slides() -> None:
    deck = deck_of_three()
    assert sample_slides(deck, None) == ["s1", "s2", "s3"]
    assert sample_slides(deck, ["s2"]) == ["s2"]
    with pytest.raises(CompositionError, match="s9"):
        sample_slides(deck, ["s9"])
    with pytest.raises(CompositionError, match="write slide briefs first"):
        sample_slides(load_fixture_deck(), None)


def test_draft_system_and_deck_briefs() -> None:
    system = draft_system(flow_draft("Demand curve"))
    assert (system.id, system.version, system.marker, system.created_at) == (
        DRAFT_SYSTEM_ID,
        1,
        "provisional",
        None,
    )
    assert system.palette == flow_draft("Demand curve").palette
    assert [b.header for b in deck_briefs(deck_of_three())][:2] == [
        flow_brief("s1").header,
        flow_brief("s2").header,
    ]
