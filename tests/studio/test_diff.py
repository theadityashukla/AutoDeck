"""The id-keyed diff, reused from v2."""

from __future__ import annotations

from autodeck.ir.store import Change
from autodeck.studio.diff import describe, diff_artifacts
from autodeck.studio.models import DeckArtifact, DiffItem


def _with_text(deck: DeckArtifact, slide_id: str, block_id: str, text: str) -> DeckArtifact:
    data = deck.model_dump()
    for slide in data["slides"]:
        if slide["id"] == slide_id:
            for block in slide["blocks"]:
                if block["id"] == block_id:
                    block["text"] = text
    return DeckArtifact.model_validate(data)


def test_identical_states_have_no_diff(base_deck: DeckArtifact) -> None:
    assert diff_artifacts(base_deck, base_deck.model_copy(deep=True)) == []


def test_a_text_edit_is_one_id_keyed_change(base_deck: DeckArtifact) -> None:
    after = _with_text(base_deck, "s2", "number", "42%")
    assert diff_artifacts(base_deck, after) == [
        DiffItem(path="slides[s2].blocks[number].text", kind="changed", before="41%", after="42%")
    ]


def test_a_reorder_is_reported_once(base_deck: DeckArtifact) -> None:
    slides = list(base_deck.slides)
    slides[1], slides[2] = slides[2], slides[1]
    after = base_deck.model_copy(update={"slides": slides})
    diff = diff_artifacts(base_deck, after)
    assert [d.path for d in diff] == ["slides[order]"]
    assert diff[0].before == ["s1", "s2", "s3", "s4"]
    assert diff[0].after == ["s1", "s3", "s2", "s4"]


def test_removing_a_slide_is_one_removal(base_deck: DeckArtifact) -> None:
    after = base_deck.model_copy(update={"slides": base_deck.slides[:3]})
    diff = diff_artifacts(base_deck, after)
    assert [(d.path, d.kind) for d in diff] == [("slides[s4]", "removed")]
    assert diff[0].before["id"] == "s4" and diff[0].after is None


def test_inputs_are_not_modified(base_deck: DeckArtifact) -> None:
    after = _with_text(base_deck, "s2", "number", "42%")
    snapshot = (base_deck.model_dump(), after.model_dump())
    diff_artifacts(base_deck, after)
    assert (base_deck.model_dump(), after.model_dump()) == snapshot


def test_describe_uses_v2_format() -> None:
    items = [
        DiffItem(path="title", kind="changed", before="a", after="b"),
        DiffItem(path="slides[s9]", kind="added", after={"id": "s9"}),
        DiffItem(path="slides[s1]", kind="removed", before={"id": "s1"}),
    ]
    assert describe(items) == [
        str(Change("title", "changed", "a", "b")),
        str(Change("slides[s9]", "added", None, {"id": "s9"})),
        str(Change("slides[s1]", "removed", {"id": "s1"}, None)),
    ]
    assert describe(items)[0] == "~ title: 'a' -> 'b'"
