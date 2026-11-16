"""The base IR contracts. These pass already: the models are written in full."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from autodeck.studio.models import (
    Block,
    ChangeEntry,
    ChangeLog,
    ChartData,
    DeckArtifact,
    DiffItem,
    EngagementRecord,
    Slide,
)
from tests.studio.helpers import CLIENT, PROJECT, T0, load_fixture_deck

A, B, C, D = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def _entry(
    entry_id: str, parent: str | None, before: str, after: str, **kw: Any
) -> ChangeEntry:
    return ChangeEntry(
        id=entry_id,
        parent_id=parent,
        diff=[DiffItem(path="title", kind="changed", before="x", after="y")],
        instruction=kw.pop("instruction", "Retitle the deck."),
        thread_id="t1",
        layer="composition",
        model_id="test-model",
        created_at=T0,
        before_digest=before,
        after_digest=after,
        **kw,
    )


# -- the fixture and the deck ------------------------------------------------


def test_fixture_is_a_valid_base_deck_with_every_part() -> None:
    deck = load_fixture_deck()
    assert (deck.client, deck.project) == (CLIENT, PROJECT)
    assert deck.brief is not None and deck.design_concept is not None
    assert len(deck.slides) == 4
    assert all(s.layout is not None for s in deck.slides)
    assert {s.marker for s in deck.slides} == {"decided", "provisional"}
    assert any(b.kind == "chart" for s in deck.slides for b in s.blocks)
    assert any(b.source_note is not None for s in deck.slides for b in s.blocks)
    assert deck.slide("s3").serves == ["p2"]


def test_a_base_block_has_no_assurance_fields() -> None:
    for name in ("claim", "citation", "citations", "verdict", "approved"):
        assert name not in Block.model_fields
    with pytest.raises(ValidationError):
        Block.model_validate({"id": "b", "kind": "text", "text": "x", "claim": {}})


def test_slide_links_must_name_real_storyline_points() -> None:
    data = load_fixture_deck().model_dump()
    data["slides"][0]["serves"] = ["p9"]
    with pytest.raises(ValidationError, match="unknown storyline point 'p9'"):
        DeckArtifact.model_validate(data)


def test_duplicate_slide_ids_are_rejected() -> None:
    data = load_fixture_deck().model_dump()
    data["slides"][1]["id"] = "s1"
    with pytest.raises(ValidationError, match="duplicate slide ids"):
        DeckArtifact.model_validate(data)


@pytest.mark.parametrize("bad", ["../x", "a/b", ".hidden", "", "has space"])
def test_ids_used_as_path_segments_are_safe(bad: str) -> None:
    data = load_fixture_deck().model_dump()
    data["id"] = bad
    with pytest.raises(ValidationError):
        DeckArtifact.model_validate(data)
    with pytest.raises(ValidationError):
        EngagementRecord(client=bad, project=PROJECT, created_at=T0)


def test_an_empty_deck_is_valid() -> None:
    deck = DeckArtifact(id="empty", client=CLIENT, project=PROJECT)
    assert deck.slides == [] and deck.brief is None and deck.storyline.points == []


# -- blocks --------------------------------------------------------------------


def test_text_block_needs_non_blank_text() -> None:
    with pytest.raises(ValidationError, match="empty text"):
        Block(id="b", kind="text", text="   ")


def test_block_carries_exactly_its_own_payload() -> None:
    chart = ChartData.model_validate(
        {"chart_type": "bar", "categories": ["a"], "series": [{"name": "s", "values": [1]}]}
    )
    with pytest.raises(ValidationError, match="exactly one payload"):
        Block(id="b", kind="text", text="x", chart=chart)
    with pytest.raises(ValidationError, match="needs a chart"):
        Block(id="b", kind="chart")


def test_chart_series_align_with_categories() -> None:
    with pytest.raises(ValidationError, match="one value per category"):
        ChartData.model_validate(
            {
                "chart_type": "bar",
                "categories": ["a", "b"],
                "series": [{"name": "s", "values": [1]}],
            }
        )


# -- slide layout ----------------------------------------------------------------


def _slide_data(slide_id: str = "s2") -> dict[str, Any]:
    return load_fixture_deck().slide(slide_id).model_dump()


def test_layout_must_place_every_block() -> None:
    data = _slide_data()
    data["layout"]["elements"] = [
        e for e in data["layout"]["elements"] if e.get("block_id") != "meaning"
    ]
    with pytest.raises(ValidationError, match="'meaning' is not placed"):
        Slide.model_validate(data)


def test_layout_places_blocks_as_what_they_are() -> None:
    data = _slide_data("s3")
    for element in data["layout"]["elements"]:
        if element.get("block_id") == "chart":
            element["type"] = "figure"
    with pytest.raises(ValidationError, match="is a chart, placed as figure"):
        Slide.model_validate(data)


def test_a_diagram_element_has_no_base_block_to_place() -> None:
    data = _slide_data("s3")
    for element in data["layout"]["elements"]:
        if element.get("block_id") == "chart":
            element["type"] = "diagram"
            element["emphasis"] = []
    with pytest.raises(ValidationError, match="placed as diagram"):
        Slide.model_validate(data)


def test_emphasis_names_real_categories() -> None:
    data = _slide_data("s3")
    for element in data["layout"]["elements"]:
        if element.get("block_id") == "chart":
            element["emphasis"] = ["Wk 9"]
    with pytest.raises(ValidationError, match="not in the chart"):
        Slide.model_validate(data)


def test_a_slide_may_have_no_layout_yet() -> None:
    data = _slide_data()
    data["layout"] = None
    assert Slide.model_validate(data).layout is None


# -- change log ----------------------------------------------------------------------


@pytest.mark.parametrize("instruction", ["", "   ", "two\nlines"])
def test_instruction_is_one_non_blank_line(instruction: str) -> None:
    with pytest.raises(ValidationError):
        _entry("c0001", None, A, B, instruction=instruction)


def test_an_entry_must_change_the_state() -> None:
    with pytest.raises(ValidationError, match="identical"):
        _entry("c0001", None, A, A)


def test_entry_timestamps_are_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        ChangeEntry.model_validate(
            {**_entry("c0001", None, A, B).model_dump(), "created_at": datetime(2026, 1, 1)}
        )


def test_a_consistent_log_validates() -> None:
    log = ChangeLog(
        artifact_id="d",
        initial_digest=A,
        head="c0003",
        entries=[
            _entry("c0001", None, A, B),
            _entry("c0002", "c0001", B, C, undone=True),
            _entry("c0003", "c0001", B, D),
        ],
    )
    assert log.entry("c0002").undone


def test_live_chain_and_undone_flags_must_agree() -> None:
    with pytest.raises(ValidationError, match="inconsistent"):
        ChangeLog(
            artifact_id="d",
            initial_digest=A,
            head="c0001",
            entries=[_entry("c0001", None, A, B), _entry("c0002", "c0001", B, C)],
        )
    with pytest.raises(ValidationError, match="inconsistent"):
        ChangeLog(
            artifact_id="d",
            initial_digest=A,
            head="c0001",
            entries=[_entry("c0001", None, A, B, undone=True)],
        )


def test_parents_come_first_and_digests_chain() -> None:
    with pytest.raises(ValidationError, match="not an earlier entry"):
        ChangeLog(
            artifact_id="d",
            initial_digest=A,
            head=None,
            entries=[_entry("c0001", "c0002", A, B, undone=True)],
        )
    with pytest.raises(ValidationError, match="did not produce"):
        ChangeLog(
            artifact_id="d",
            initial_digest=A,
            head="c0002",
            entries=[_entry("c0001", None, A, B), _entry("c0002", "c0001", C, D)],
        )
