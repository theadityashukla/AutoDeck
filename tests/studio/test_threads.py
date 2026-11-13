"""Threads on disk: record, opening context, append-only log, isolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio.conversation import AssistantLine, ThreadRecord, UserLine
from autodeck.studio.engagement import Engagement, create_engagement
from autodeck.studio.errors import InvalidSegmentError, ThreadLogError, ThreadNotFoundError
from autodeck.studio.serialise import text_digest
from autodeck.studio.threads import ThreadStore
from tests.studio.helpers import CLIENT, OTHER_CLIENT, PROJECT, T0, T1, T2


def _engagement(knowledge_root: Path, workspace_root: Path, client: str = CLIENT) -> Engagement:
    return create_engagement(
        client, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )


def _create(store: ThreadStore, text: str = "# Engagement\n\ncontext\n") -> ThreadRecord:
    return store.create(context_text=text, opening="fresh", model_id="scripted", now=T1)


def _user(turn: str = "u0001", text: str = "Hello", origin: str = "owner") -> dict:
    return {"kind": "user", "turn_id": turn, "origin": origin, "text": text}


def test_create_writes_record_and_context(knowledge_root: Path, workspace_root: Path) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    store = ThreadStore(engagement)
    record = _create(store, "the context\n")
    assert record.id == "t0001" and record.client == CLIENT and record.project == PROJECT
    assert record.context_digest == text_digest("the context\n")
    paths = store.paths("t0001")
    assert paths.context.read_bytes() == b"the context\n"
    assert ThreadRecord.model_validate_json(paths.record.read_text()) == record
    assert not paths.messages.exists()
    assert store.load("t0001") == record
    assert store.context_text("t0001") == "the context\n"
    assert _create(store).id == "t0002"
    assert [r.id for r in store.list()] == ["t0001", "t0002"]


def test_ids_are_never_reused(knowledge_root: Path, workspace_root: Path) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    (engagement.paths.threads / "t0007").mkdir(parents=True)
    store = ThreadStore(engagement)
    assert store.next_thread_id() == "t0008"


def test_invalid_create_writes_nothing(knowledge_root: Path, workspace_root: Path) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    store = ThreadStore(engagement)
    with pytest.raises(ValidationError):
        store.create(context_text="x", opening="sometimes", model_id="m", now=T1)
    with pytest.raises(ValidationError):
        store.create(
            context_text="x", opening="fresh", model_id="m", now=T1.replace(tzinfo=None)
        )
    assert engagement.paths.thread_ids() == []


def test_missing_thread_and_bad_ids(knowledge_root: Path, workspace_root: Path) -> None:
    store = ThreadStore(_engagement(knowledge_root, workspace_root))
    with pytest.raises(ThreadNotFoundError, match="t0003"):
        store.load("t0003")
    with pytest.raises(ThreadNotFoundError):
        store.read_lines("t0003")
    with pytest.raises(InvalidSegmentError):
        store.load("../t0001")


def test_append_assigns_seq_and_time_and_reads_back(
    knowledge_root: Path, workspace_root: Path
) -> None:
    store = ThreadStore(_engagement(knowledge_root, workspace_root))
    _create(store)
    assert store.read_lines("t0001") == []
    assert store.next_turn_id("t0001") == "u0001"
    first = store.append("t0001", _user(), now=T1)
    assert isinstance(first, UserLine) and first.seq == 1 and first.created_at == T1
    second = store.append(
        "t0001",
        {
            "kind": "assistant",
            "turn_id": "u0001",
            "step": 1,
            "text": "Hi.",
            "model_id": "scripted",
        },
        now=T2,
    )
    assert isinstance(second, AssistantLine) and second.seq == 2
    assert store.read_lines("t0001") == [first, second]
    raw = store.paths("t0001").messages.read_text(encoding="utf-8")
    assert raw.count("\n") == 2 and raw.endswith("\n")
    store.append("t0001", _user("u0002", "Again"), now=T2)
    assert store.next_turn_id("t0001") == "u0003"


def test_several_user_lines_in_one_turn_count_once(
    knowledge_root: Path, workspace_root: Path
) -> None:
    store = ThreadStore(_engagement(knowledge_root, workspace_root))
    _create(store)
    store.append("t0001", _user(origin="context", text="ctx"), now=T1)
    store.append("t0001", _user(), now=T1)
    assert store.next_turn_id("t0001") == "u0002"


def test_invalid_appends_write_nothing(knowledge_root: Path, workspace_root: Path) -> None:
    store = ThreadStore(_engagement(knowledge_root, workspace_root))
    _create(store)
    with pytest.raises(ValidationError):
        store.append("t0001", {"kind": "user", "turn_id": "u0001", "origin": "owner"}, now=T1)
    with pytest.raises(ValueError):
        store.append("t0001", {**_user(), "seq": 5}, now=T1)
    assert not store.paths("t0001").messages.exists()


def test_corrupt_logs_are_reported(knowledge_root: Path, workspace_root: Path) -> None:
    store = ThreadStore(_engagement(knowledge_root, workspace_root))
    _create(store)
    store.append("t0001", _user(), now=T1)
    messages = store.paths("t0001").messages
    text = messages.read_text(encoding="utf-8")
    messages.write_text(text + text, encoding="utf-8")  # seq 1 twice
    with pytest.raises(ThreadLogError, match="2"):
        store.read_lines("t0001")
    messages.write_text(text + "\n", encoding="utf-8")
    with pytest.raises(ThreadLogError):
        store.read_lines("t0001")
    messages.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ThreadLogError):
        store.read_lines("t0001")


def test_a_changed_context_file_is_detected(knowledge_root: Path, workspace_root: Path) -> None:
    store = ThreadStore(_engagement(knowledge_root, workspace_root))
    _create(store, "original\n")
    store.paths("t0001").context.write_text("edited\n", encoding="utf-8")
    with pytest.raises(ThreadLogError):
        store.context_text("t0001")


def test_a_symlinked_thread_into_another_client_is_refused(
    knowledge_root: Path, workspace_root: Path
) -> None:
    mine = _engagement(knowledge_root, workspace_root)
    theirs = _engagement(knowledge_root, workspace_root, OTHER_CLIENT)
    _create(ThreadStore(theirs), "their secret context\n")
    mine.paths.threads.mkdir(parents=True, exist_ok=True)
    os.symlink(theirs.paths.thread("t0001").root, mine.paths.threads / "t0001")
    store = ThreadStore(mine)
    with pytest.raises(ClientIsolationError):
        store.load("t0001")
    with pytest.raises(ClientIsolationError):
        store.context_text("t0001")
    assert store.list() == []


def test_a_record_copied_from_another_engagement_is_refused(
    knowledge_root: Path, workspace_root: Path
) -> None:
    mine = _engagement(knowledge_root, workspace_root)
    theirs = _engagement(knowledge_root, workspace_root, OTHER_CLIENT)
    _create(ThreadStore(theirs))
    target = mine.paths.thread("t0001").ensure()
    source = theirs.paths.thread("t0001")
    target.record.write_bytes(source.record.read_bytes())
    target.context.write_bytes(source.context.read_bytes())
    with pytest.raises(ClientIsolationError):
        ThreadStore(mine).load("t0001")
