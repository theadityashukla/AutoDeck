"""Undo and redo as pure transitions over a ChangeLog."""

from __future__ import annotations

import pytest

from autodeck.studio import changelog as cl
from autodeck.studio.errors import NothingToRedoError, NothingToUndoError
from autodeck.studio.models import ChangeEntry, ChangeLog, DiffItem
from tests.studio.helpers import T0

S0, S1, S2, S3 = ("0" * 64, "1" * 64, "2" * 64, "3" * 64)


def _entry(log: ChangeLog, after: str, instruction: str = "Retitle the deck.") -> ChangeEntry:
    return ChangeEntry(
        id=cl.next_entry_id(log),
        parent_id=log.head,
        diff=[DiffItem(path="title", kind="changed", before="x", after="y")],
        instruction=instruction,
        thread_id="t1",
        layer="composition",
        model_id="m",
        created_at=T0,
        before_digest=cl.head_digest(log),
        after_digest=after,
    )


def _apply(log: ChangeLog, after: str) -> ChangeLog:
    return cl.append_entry(log, _entry(log, after))


def test_new_log_is_at_the_initial_state() -> None:
    log = cl.new_changelog("deck", S0)
    assert log.head is None and log.entries == []
    assert cl.head_entry(log) is None and cl.head_digest(log) == S0
    assert cl.undo_target(log) is None and cl.redo_target(log) is None
    assert cl.next_entry_id(log) == "c0001"
    assert cl.listing(log) == []


def test_append_moves_head_and_returns_a_new_log() -> None:
    log0 = cl.new_changelog("deck", S0)
    log1 = _apply(log0, S1)
    assert log0.entries == [] and log0.head is None
    assert log1.head == "c0001" and cl.head_digest(log1) == S1
    assert cl.next_entry_id(log1) == "c0002"


def test_append_refuses_a_wrong_parent_or_id() -> None:
    log1 = _apply(cl.new_changelog("deck", S0), S1)
    stale = _entry(cl.new_changelog("deck", S0), S2)  # parent None, id c0001
    with pytest.raises(ValueError):
        cl.append_entry(log1, stale)


def test_undo_then_redo() -> None:
    log = _apply(_apply(cl.new_changelog("deck", S0), S1), S2)
    log, undone = cl.mark_undone(log)
    assert undone.id == "c0002" and undone.undone
    assert log.head == "c0001" and cl.head_digest(log) == S1
    target = cl.redo_target(log)
    assert target is not None and target.id == "c0002"
    log, redone = cl.mark_redone(log)
    assert redone.id == "c0002" and not redone.undone and log.head == "c0002"
    assert [e.id for e in cl.live_entries(log)] == ["c0001", "c0002"]


def test_undo_all_the_way_and_no_further() -> None:
    log = _apply(cl.new_changelog("deck", S0), S1)
    log, _ = cl.mark_undone(log)
    assert log.head is None and cl.head_digest(log) == S0
    with pytest.raises(NothingToUndoError):
        cl.mark_undone(log)


def test_nothing_to_redo() -> None:
    log = _apply(cl.new_changelog("deck", S0), S1)
    with pytest.raises(NothingToRedoError):
        cl.mark_redone(log)


def test_a_new_change_after_undo_branches() -> None:
    log = _apply(_apply(cl.new_changelog("deck", S0), S1), S2)  # A, B
    log, _ = cl.mark_undone(log)  # undo B
    log = _apply(log, S3)  # C on top of A
    assert [(e.id, e.undone) for e in log.entries] == [
        ("c0001", False), ("c0002", True), ("c0003", False)
    ]
    assert cl.redo_target(log) is None  # B is no longer redoable
    log, _ = cl.mark_undone(log)  # undo C
    target = cl.redo_target(log)
    assert target is not None and target.id == "c0003"  # most recent child of A, not B


def test_listing_format() -> None:
    log = _apply(cl.new_changelog("deck", S0), S1)
    log = cl.append_entry(log, _entry(log, S2, "Shorten the slide two heading."))
    log, _ = cl.mark_undone(log)
    assert cl.listing(log) == [
        "c0001 live composition m t1 2026-11-13T09:00:00+00:00 Retitle the deck.",
        "c0002 undone composition m t1 2026-11-13T09:00:00+00:00 Shorten the slide two heading.",
    ]
