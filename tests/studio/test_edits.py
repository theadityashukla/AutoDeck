"""Pure deck edits: a new validated deck, the input untouched, ids never changed."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodeck.studio.edits import move_slide, set_block_text, set_slide_marker
from autodeck.studio.errors import EditError
from autodeck.studio.models import DeckArtifact


def test_set_block_text_replaces_only_that_text(base_deck: DeckArtifact) -> None:
    before = base_deck.model_dump()
    after = set_block_text(base_deck, slide_id="s2", block_id="number", text=" 42% ")
    assert isinstance(after, DeckArtifact) and after is not base_deck
    assert after.slide("s2").block("number").text == " 42% "  # verbatim, not stripped
    assert base_deck.model_dump() == before  # input untouched
    expected = base_deck.model_dump()
    expected["slides"][1]["blocks"][1]["text"] = " 42% "
    assert after.model_dump() == expected
    # The source note and the layout survive the edit.
    assert (
        after.slide("s2").block("number").source_note
        == base_deck.slide("s2").block("number").source_note
    )
    assert after.slide("s2").layout == base_deck.slide("s2").layout


@pytest.mark.parametrize(
    "slide_id,block_id,needle",
    [("s9", "number", "s9"), ("s2", "nope", "nope"), ("s3", "chart", "chart")],
)
def test_set_block_text_refuses_what_is_not_a_text_block(
    base_deck: DeckArtifact, slide_id: str, block_id: str, needle: str
) -> None:
    with pytest.raises(EditError, match=needle):
        set_block_text(base_deck, slide_id=slide_id, block_id=block_id, text="x")


def test_set_block_text_refuses_blank_text(base_deck: DeckArtifact) -> None:
    with pytest.raises(ValidationError):
        set_block_text(base_deck, slide_id="s2", block_id="number", text="   ")


def test_edit_error_is_a_lookup_error(base_deck: DeckArtifact) -> None:
    with pytest.raises(LookupError):
        set_slide_marker(base_deck, slide_id="s9", marker="decided")


def test_set_slide_marker(base_deck: DeckArtifact) -> None:
    before = base_deck.model_dump()
    after = set_slide_marker(base_deck, slide_id="s3", marker="stale")
    assert after.slide("s3").marker == "stale"
    assert base_deck.model_dump() == before
    assert [s.marker for s in after.slides] == ["decided", "decided", "stale", "provisional"]


def test_setting_the_same_marker_gives_an_equal_deck(base_deck: DeckArtifact) -> None:
    assert set_slide_marker(base_deck, slide_id="s1", marker="decided") == base_deck


@pytest.mark.parametrize(
    "to_index,order",
    [
        (0, ["s3", "s1", "s2", "s4"]),
        (1, ["s1", "s3", "s2", "s4"]),
        (2, ["s1", "s2", "s3", "s4"]),
        (3, ["s1", "s2", "s4", "s3"]),
    ],
)
def test_move_slide(base_deck: DeckArtifact, to_index: int, order: list[str]) -> None:
    before = base_deck.model_dump()
    after = move_slide(base_deck, slide_id="s3", to_index=to_index)
    assert after.slide_ids() == order
    assert after.slide("s3") == base_deck.slide("s3")
    assert base_deck.model_dump() == before


@pytest.mark.parametrize("to_index", [-1, 4, 10])
def test_move_slide_refuses_an_index_off_the_end(
    base_deck: DeckArtifact, to_index: int
) -> None:
    with pytest.raises(EditError):
        move_slide(base_deck, slide_id="s3", to_index=to_index)


def test_move_slide_refuses_an_unknown_slide(base_deck: DeckArtifact) -> None:
    with pytest.raises(EditError, match="s9"):
        move_slide(base_deck, slide_id="s9", to_index=0)
