"""The Phase 1 contracts in `conversation.py`: thread lines, turn classification, proposals,
render manifests and events. Written in full by the lead, so these pass from the start."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from autodeck.studio.conversation import (
    THREAD_LINE,
    TURN_EVENT,
    AssistantLine,
    NoteLine,
    ProposalOption,
    ProposalRecord,
    RenderManifest,
    ThreadRecord,
    TurnEndLine,
    TurnFinished,
    UserLine,
    classify_turn,
)
from tests.studio.helpers import CLIENT, PROJECT, T0, T1, load_fixture_deck

DIGEST = "a" * 64


def _turn_end(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": "turn_end",
        "seq": 4,
        "created_at": T0,
        "turn_id": "u0001",
        "turn_kind": "talk",
        "stop_reason": "replied",
        "model_id": "scripted",
        "steps": 1,
    }
    data.update(changes)
    return data


# -- classification -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lists", "expected"),
    [
        ({}, "talk"),
        ({"proposal_ids": ["p0001"]}, "proposal"),
        ({"change_ids": ["c0001"]}, "change"),
        ({"undone_ids": ["c0001"]}, "change"),
        ({"redone_ids": ["c0001"]}, "change"),
        ({"created_artifacts": ["deck"]}, "change"),
        ({"change_ids": ["c0002"], "proposal_ids": ["p0001"]}, "change"),
    ],
)
def test_classify_turn(lists: dict[str, list[str]], expected: str) -> None:
    full = {
        "change_ids": [],
        "undone_ids": [],
        "redone_ids": [],
        "created_artifacts": [],
        "proposal_ids": [],
    }
    full.update(lists)
    assert classify_turn(**full) == expected


def test_a_turn_end_must_carry_the_kind_its_lists_imply() -> None:
    line = THREAD_LINE.validate_python(_turn_end(turn_kind="change", change_ids=["c0001"]))
    assert isinstance(line, TurnEndLine)
    with pytest.raises(ValidationError, match="kind"):
        THREAD_LINE.validate_python(_turn_end(turn_kind="talk", change_ids=["c0001"]))
    with pytest.raises(ValidationError, match="kind"):
        THREAD_LINE.validate_python(_turn_end(turn_kind="change"))


def test_error_text_is_set_exactly_when_the_turn_errored() -> None:
    THREAD_LINE.validate_python(_turn_end(stop_reason="error", error="ProviderError: 500"))
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python(_turn_end(stop_reason="error"))
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python(_turn_end(error="something"))


def test_turn_end_ids_are_checked() -> None:
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python(_turn_end(turn_kind="change", change_ids=["1"]))
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python(_turn_end(turn_kind="proposal", proposal_ids=["x1"]))


# -- lines ------------------------------------------------------------------------------


def test_lines_are_discriminated_by_kind() -> None:
    user = THREAD_LINE.validate_python(
        {
            "kind": "user",
            "seq": 1,
            "created_at": T0,
            "turn_id": "u0001",
            "origin": "owner",
            "text": "Hi",
        }
    )
    assert isinstance(user, UserLine)
    assistant = THREAD_LINE.validate_python(
        {
            "kind": "assistant",
            "seq": 2,
            "created_at": T0,
            "turn_id": "u0001",
            "step": 1,
            "tool_calls": [{"id": "c1", "name": "view_deck", "arguments": {}}],
            "model_id": "scripted",
        }
    )
    assert isinstance(assistant, AssistantLine)
    assert THREAD_LINE.validate_json(assistant.model_dump_json()) == assistant


def test_a_user_line_needs_non_blank_text_and_a_known_origin() -> None:
    base = {"kind": "user", "seq": 1, "created_at": T0, "turn_id": "u0001", "origin": "owner"}
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python({**base, "text": "   "})
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python({**base, "text": "x", "origin": "system"})


def test_a_tool_summary_is_one_short_line() -> None:
    base = {
        "kind": "tool",
        "seq": 3,
        "created_at": T0,
        "turn_id": "u0001",
        "step": 1,
        "tool_call_id": "c1",
        "tool_name": "view_deck",
        "text": "...",
    }
    THREAD_LINE.validate_python({**base, "summary": "viewed deck d (2 slides)"})
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python({**base, "summary": "two\nlines"})
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python({**base, "summary": "x" * 201})


def test_naive_times_and_bad_seq_are_refused() -> None:
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python(_turn_end(created_at=T0.replace(tzinfo=None)))
    with pytest.raises(ValidationError):
        THREAD_LINE.validate_python(_turn_end(seq=0))


def test_notes_reference_the_right_kind_of_id() -> None:
    note = THREAD_LINE.validate_python(
        {
            "kind": "note",
            "seq": 5,
            "created_at": T1,
            "note": "proposal_dismissed",
            "ref": "p0001",
            "text": "The owner dismissed proposal p0001: Two openings",
        }
    )
    assert isinstance(note, NoteLine)
    with pytest.raises(ValidationError):
        NoteLine(
            seq=1, created_at=T1, note="owner_undo", ref="p0001", text="x", artifact_id="d"
        )
    with pytest.raises(ValidationError, match="names the artifact"):
        NoteLine(seq=1, created_at=T1, note="owner_undo", ref="c0001", text="x")
    NoteLine(seq=1, created_at=T1, note="owner_undo", ref="c0001", text="x", artifact_id="d")


def test_thread_record_validates_ids_and_digest() -> None:
    record = ThreadRecord(
        id="t0001",
        client=CLIENT,
        project=PROJECT,
        created_at=T0,
        opening="fresh",
        context_digest=DIGEST,
        model_id="scripted",
    )
    assert record.title == ""
    with pytest.raises(ValidationError):
        ThreadRecord.model_validate({**record.model_dump(), "id": "thread-1"})
    with pytest.raises(ValidationError):
        ThreadRecord.model_validate({**record.model_dump(), "context_digest": "abc"})


# -- proposals --------------------------------------------------------------------------


def _proposal(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "p0001",
        "thread_id": "t0001",
        "turn_id": "u0002",
        "artifact_id": "deck",
        "summary": "Two ways to open the deck",
        "options": [
            {"id": "A", "label": "Lead with the number", "text": "Open on 41%."},
            {"id": "B", "label": "Lead with the question", "text": "Open on the question."},
        ],
        "created_at": T0,
    }
    data.update(changes)
    return data


def test_an_open_proposal_round_trips() -> None:
    record = ProposalRecord.model_validate(_proposal())
    assert record.status == "open" and record.option("B").label == "Lead with the question"
    with pytest.raises(KeyError, match="C"):
        record.option("C")


def test_option_ids_are_a_b_c_in_order() -> None:
    options = _proposal()["options"]
    options[1]["id"] = "C"
    with pytest.raises(ValidationError, match="option ids"):
        ProposalRecord.model_validate(_proposal(options=options))


def test_resolution_fields_follow_the_status() -> None:
    ProposalRecord.model_validate(
        _proposal(status="accepted", chosen="B", resolved_by="owner", resolved_at=T1)
    )
    ProposalRecord.model_validate(
        _proposal(status="dismissed", resolved_by="owner", resolved_at=T1)
    )
    with pytest.raises(ValidationError):
        ProposalRecord.model_validate(_proposal(chosen="A"))
    with pytest.raises(ValidationError):
        ProposalRecord.model_validate(
            _proposal(status="accepted", chosen="C", resolved_by="owner", resolved_at=T1)
        )
    with pytest.raises(ValidationError):
        ProposalRecord.model_validate(
            _proposal(status="dismissed", chosen="A", resolved_by="owner", resolved_at=T1)
        )
    with pytest.raises(ValidationError):
        ProposalRecord.model_validate(_proposal(status="dismissed"))


def test_candidate_slides_need_an_artifact_and_unique_ids() -> None:
    slide = load_fixture_deck().slides[1].model_dump(mode="json")
    candidate = {"slide": slide, "replaces": "s1"}
    options = [{"id": "A", "label": "Number", "text": "x", "candidates": [candidate]}]
    ProposalRecord.model_validate(_proposal(options=options))
    with pytest.raises(ValidationError, match="artifact_id"):
        ProposalRecord.model_validate(_proposal(options=options, artifact_id=None))
    with pytest.raises(ValidationError, match="repeat"):
        ProposalOption.model_validate(
            {"id": "A", "label": "x", "text": "x", "candidates": [candidate, candidate]}
        )


def test_every_candidate_replaces_or_inserts_exactly_one() -> None:
    slide = load_fixture_deck().slides[1].model_dump(mode="json")

    def option(*candidates: dict[str, object]) -> dict[str, object]:
        return {"id": "A", "label": "x", "text": "x", "candidates": list(candidates)}

    ProposalOption.model_validate(option({"slide": slide, "insert_at": 2}))
    for bad in ({"slide": slide}, {"slide": slide, "replaces": "s1", "insert_at": 2}):
        with pytest.raises(ValidationError, match="replace a slide or be inserted"):
            ProposalOption.model_validate(option(bad))
    other = {**slide, "id": "other"}
    with pytest.raises(ValidationError, match="same slide"):
        ProposalOption.model_validate(
            option({"slide": slide, "replaces": "s1"}, {"slide": other, "replaces": "s1"})
        )


def test_an_old_option_loads_marked_legacy() -> None:
    """Before replace-or-insert an option held `slides` and `insert_at`; such a record must
    still load (the engagement home lists it), flagged so it cannot be applied."""
    slide = load_fixture_deck().slides[1].model_dump(mode="json")
    old = {"id": "A", "label": "Number", "text": "x", "slides": [slide], "insert_at": 2}
    option = ProposalOption.model_validate(old)
    assert option.legacy and [s.id for s in option.slides] == [slide["id"]]
    assert option.candidates[0].replaces is None and option.candidates[0].insert_at is None
    record = ProposalRecord.model_validate(_proposal(options=[old]))
    assert record.options[0].legacy
    # And it survives being resolved (the record is rebuilt from its own dump).
    resolved = ProposalRecord.model_validate(
        {
            **record.model_dump(),
            "status": "dismissed",
            "resolved_by": "owner",
            "resolved_at": T1,
        }
    )
    assert resolved.options[0].legacy


def test_labels_and_summaries_are_one_line() -> None:
    with pytest.raises(ValidationError):
        ProposalRecord.model_validate(_proposal(summary="two\nlines"))
    with pytest.raises(ValidationError):
        ProposalOption.model_validate({"id": "A", "label": "x" * 81, "text": "x"})


# -- renders and events ---------------------------------------------------------------


def test_a_rendered_manifest_has_one_image_per_slide() -> None:
    RenderManifest(digest="0123456789ab", slide_ids=["s1"], rendered=True, images=["p/1.png"])
    with pytest.raises(ValidationError):
        RenderManifest(
            digest="0123456789ab", slide_ids=["s1", "s2"], rendered=True, images=["a"]
        )
    with pytest.raises(ValidationError):
        RenderManifest(digest="0123456789ab", rendered=False, images=["a"])
    with pytest.raises(ValidationError):
        RenderManifest(digest="XYZ", rendered=False)


def test_events_are_discriminated_by_type_and_turn_finished_checks_its_kind() -> None:
    event = TURN_EVENT.validate_python(
        {
            "type": "turn_finished",
            "thread_id": "t0001",
            "turn_id": "u0001",
            "turn_kind": "proposal",
            "stop_reason": "replied",
            "model_id": "scripted",
            "steps": 2,
            "proposal_ids": ["p0001"],
        }
    )
    assert isinstance(event, TurnFinished)
    assert event.model_dump(mode="json")["type"] == "turn_finished"
    with pytest.raises(ValidationError):
        TURN_EVENT.validate_python({**event.model_dump(), "turn_kind": "talk"})
