"""One artifact on disk: create, apply, undo, redo, and the integrity checks that make
undo exact. Built on `ArtifactStore` directly (no engagement), so these tests depend only on
`paths`, `serialise`, `diff` and `changelog`."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio import changelog as cl
from autodeck.studio.errors import (
    ArtifactExistsError,
    ArtifactMismatchError,
    ArtifactNotFoundError,
    ChangeLogIntegrityError,
    NoChangeError,
    NothingToRedoError,
    NothingToUndoError,
)
from autodeck.studio.models import DeckArtifact
from autodeck.studio.paths import workspace_paths
from autodeck.studio.serialise import artifact_digest, dump_artifact, text_digest
from autodeck.studio.store import ArtifactStore, artifact_lock
from tests.studio.helpers import ARTIFACT_ID, CLIENT, OTHER_CLIENT, PROJECT, T1, T2, with_text


def _store(
    workspace_root: Path, *, client: str = CLIENT, artifact_id: str = ARTIFACT_ID
) -> ArtifactStore:
    paths = workspace_paths(workspace_root).engagement(CLIENT, PROJECT).artifact(artifact_id)
    return ArtifactStore(paths, client=client, project=PROJECT)


def _files(store: ArtifactStore) -> dict[str, bytes]:
    """Every file under the artifact, relative path -> bytes."""
    root = store.paths.root
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _apply_number(store: ArtifactStore, deck: DeckArtifact, text: str, now: datetime = T1):
    return store.apply(
        with_text(deck, "s2", "number", text),
        instruction=f"Make the number {text}.",
        thread_id="t1",
        layer="composition",
        model_id="test-model",
        now=now,
    )


# -- create ------------------------------------------------------------------------


def test_create_writes_initial_current_and_empty_log(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    assert not store.exists()
    log = store.create(base_deck)
    assert store.exists()
    text = dump_artifact(base_deck)
    assert store.paths.current.read_bytes() == text.encode("utf-8")
    assert store.paths.initial_version.read_bytes() == text.encode("utf-8")
    assert log.entries == [] and log.head is None
    assert log.initial_digest == artifact_digest(base_deck)
    assert store.changelog() == log
    assert store.current_text() == text
    assert store.load() == base_deck


def test_create_refuses_another_clients_deck(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    foreign = base_deck.model_copy(update={"client": OTHER_CLIENT})
    with pytest.raises(ClientIsolationError):
        store.create(foreign)
    assert not store.paths.root.exists()


@pytest.mark.parametrize(
    "field,value", [("project", "another-project"), ("id", "another-deck")]
)
def test_create_refuses_a_mismatched_deck(
    workspace_root: Path, base_deck: DeckArtifact, field: str, value: str
) -> None:
    store = _store(workspace_root)
    with pytest.raises(ArtifactMismatchError):
        store.create(base_deck.model_copy(update={field: value}))
    assert not store.paths.root.exists()


def test_create_refuses_an_existing_artifact(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    before = _files(store)
    with pytest.raises(ArtifactExistsError):
        store.create(base_deck)
    assert _files(store) == before


def test_reading_a_missing_artifact_raises(workspace_root: Path) -> None:
    store = _store(workspace_root)
    with pytest.raises(ArtifactNotFoundError):
        store.current_text()
    with pytest.raises(ArtifactNotFoundError):
        store.changelog()
    with pytest.raises(ArtifactNotFoundError):
        store.load()


# -- apply ---------------------------------------------------------------------------


def test_apply_records_the_change(workspace_root: Path, base_deck: DeckArtifact) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    entry = _apply_number(store, base_deck, "42%")
    assert entry.id == "c0001" and entry.parent_id is None and not entry.undone
    assert entry.instruction == "Make the number 42%."
    assert (entry.thread_id, entry.layer, entry.model_id, entry.created_at) == (
        "t1",
        "composition",
        "test-model",
        T1,
    )
    assert [(d.path, d.kind, d.before, d.after) for d in entry.diff] == [
        ("slides[s2].blocks[number].text", "changed", "41%", "42%")
    ]
    after = with_text(base_deck, "s2", "number", "42%")
    assert entry.before_digest == artifact_digest(base_deck)
    assert entry.after_digest == artifact_digest(after)
    assert store.current_text() == dump_artifact(after)
    assert store.paths.version("c0001").read_text(encoding="utf-8") == dump_artifact(after)
    log = store.changelog()
    assert log.head == "c0001" and log.entries == [entry]
    assert store.load() == after


def test_apply_defaults_to_an_aware_now(workspace_root: Path, base_deck: DeckArtifact) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    entry = store.apply(
        with_text(base_deck, "s1", "kicker", "Readout"),
        instruction="Shorten the kicker.",
        thread_id="t1",
        layer="composition",
        model_id="human",
    )
    assert entry.created_at.tzinfo is not None


def test_an_identical_state_is_not_a_change(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    before = _files(store)
    with pytest.raises(NoChangeError):
        store.apply(
            base_deck.model_copy(deep=True),
            instruction="Do nothing.",
            thread_id="t1",
            layer="mechanics",
            model_id="m",
            now=T1,
        )
    assert _files(store) == before


@pytest.mark.parametrize("instruction", ["", "two\nlines"])
def test_a_bad_entry_writes_nothing(
    workspace_root: Path, base_deck: DeckArtifact, instruction: str
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    before = _files(store)
    with pytest.raises(ValidationError):
        store.apply(
            with_text(base_deck, "s2", "number", "42%"),
            instruction=instruction,
            thread_id="t1",
            layer="composition",
            model_id="m",
            now=T1,
        )
    assert _files(store) == before


def test_a_naive_timestamp_writes_nothing(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    before = _files(store)
    with pytest.raises(ValidationError):
        _apply_number(store, base_deck, "42%", now=datetime(2026, 11, 13, 9, 0))
    assert _files(store) == before


def test_apply_refuses_another_clients_or_a_mismatched_state(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    before = _files(store)
    changed = with_text(base_deck, "s2", "number", "42%")
    for state, error in (
        (changed.model_copy(update={"client": OTHER_CLIENT}), ClientIsolationError),
        (changed.model_copy(update={"project": "another-project"}), ArtifactMismatchError),
        (changed.model_copy(update={"id": "another-deck"}), ArtifactMismatchError),
    ):
        with pytest.raises(error):
            store.apply(
                state,
                instruction="Edit.",
                thread_id="t1",
                layer="composition",
                model_id="m",
                now=T1,
            )
    assert _files(store) == before


# -- undo and redo -------------------------------------------------------------------


def test_undo_restores_the_previous_bytes_exactly(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    initial = store.paths.current.read_bytes()
    _apply_number(store, base_deck, "42%", T1)
    middle = store.paths.current.read_bytes()
    _apply_number(store, store.load(), "43%", T2)

    undone = store.undo()
    assert undone.id == "c0002" and undone.undone
    assert store.paths.current.read_bytes() == middle
    assert store.changelog().head == "c0001"

    store.undo()
    assert store.paths.current.read_bytes() == initial
    assert store.load() == base_deck
    with pytest.raises(NothingToUndoError):
        store.undo()


def test_redo_restores_the_undone_bytes_exactly(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    _apply_number(store, base_deck, "42%")
    after = store.paths.current.read_bytes()
    store.undo()
    redone = store.redo()
    assert redone.id == "c0001" and not redone.undone
    assert store.paths.current.read_bytes() == after
    with pytest.raises(NothingToRedoError):
        store.redo()


def test_a_change_after_undo_keeps_the_undone_entry(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    _apply_number(store, base_deck, "42%", T1)
    store.undo()
    entry = _apply_number(store, store.load(), "40%", T2)
    assert entry.id == "c0002" and entry.parent_id is None
    log = store.changelog()
    assert [(e.id, e.undone) for e in log.entries] == [("c0001", True), ("c0002", False)]
    assert cl.listing(log)[0].startswith("c0001 undone ")
    with pytest.raises(NothingToRedoError):
        store.redo()


def test_snapshots_stay_readable_after_undo(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    _apply_number(store, base_deck, "42%")
    store.undo()
    assert store.snapshot(None) == base_deck
    assert store.snapshot("c0001") == with_text(base_deck, "s2", "number", "42%")
    with pytest.raises(KeyError):
        store.snapshot("c0099")


# -- integrity and isolation on load -------------------------------------------------


def test_a_hand_edited_current_file_is_refused(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    _apply_number(store, base_deck, "42%")
    tampered = dump_artifact(with_text(base_deck, "s2", "number", "99%"))
    store.paths.current.write_text(tampered, encoding="utf-8")
    with pytest.raises(ChangeLogIntegrityError):
        store.load()
    before = _files(store)
    with pytest.raises(ChangeLogIntegrityError):
        store.undo()
    assert _files(store) == before


def test_a_corrupted_snapshot_blocks_undo(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    _apply_number(store, base_deck, "42%")
    store.paths.initial_version.write_text(dump_artifact(base_deck) + " ", encoding="utf-8")
    before = _files(store)
    with pytest.raises(ChangeLogIntegrityError):
        store.undo()
    assert _files(store) == before
    with pytest.raises(ChangeLogIntegrityError):
        store.snapshot(None)


def test_a_deck_read_by_another_client_is_an_isolation_error(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    _store(workspace_root).create(base_deck)
    wrong_owner = _store(workspace_root, client=OTHER_CLIENT)
    with pytest.raises(ClientIsolationError):
        wrong_owner.load()


def test_current_digest_matches_the_log_head(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    _apply_number(store, base_deck, "42%")
    assert text_digest(store.current_text()) == cl.head_digest(store.changelog())


# -- concurrency: readers never see a half-applied change ---------------------------

_JOIN_SECONDS = 60.0


def _join_all(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join(timeout=_JOIN_SECONDS)
    hung = [t.name for t in threads if t.is_alive()]
    assert not hung, f"threads did not finish within {_JOIN_SECONDS}s: {hung}"


def test_readers_never_see_a_half_applied_change(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    """One writer applies, undoes and redoes many changes while readers `load` in a tight
    loop. Without the per-artifact lock a reader lands between the change-log write and
    the `current.json` write and gets `ChangeLogIntegrityError`."""
    store = _store(workspace_root)
    store.create(base_deck)
    changes = 40
    valid = {dump_artifact(base_deck)} | {
        dump_artifact(with_text(base_deck, "s2", "number", f"{i}%")) for i in range(changes)
    }
    stop = threading.Event()
    failures: list[BaseException] = []
    seen: list[int] = []

    def writer() -> None:
        try:
            for i in range(changes):
                _apply_number(store, base_deck, f"{i}%")
                if i % 3 == 2:
                    store.undo()
                    store.redo()
                    store.undo()
                    store.redo()
        except BaseException as exc:
            failures.append(exc)
        finally:
            stop.set()

    def reader() -> None:
        count = 0
        try:
            while not stop.is_set():
                deck = store.load()
                if dump_artifact(deck) not in valid:
                    raise AssertionError("a reader saw a state that was never current")
                count += 1
        except BaseException as exc:
            failures.append(exc)
        finally:
            seen.append(count)

    threads = [threading.Thread(target=writer, name="writer")] + [
        threading.Thread(target=reader, name=f"reader-{n}") for n in range(3)
    ]
    for thread in threads:
        thread.start()
    _join_all(threads)

    assert not failures, failures
    assert all(count > 0 for count in seen)
    assert store.load() == with_text(base_deck, "s2", "number", f"{changes - 1}%")


def test_snapshot_readers_see_consistent_state_during_writes(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    """`snapshot` reads the log and then a version file; it must not fail while a writer
    is mid-change."""
    store = _store(workspace_root)
    store.create(base_deck)
    stop = threading.Event()
    failures: list[BaseException] = []

    def writer() -> None:
        try:
            for i in range(25):
                _apply_number(store, base_deck, f"{i}%")
        except BaseException as exc:
            failures.append(exc)
        finally:
            stop.set()

    def reader() -> None:
        try:
            while not stop.is_set():
                store.snapshot(None)
                log = store.changelog()
                if log.head is not None:
                    store.snapshot(log.head)
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    _join_all(threads)
    assert not failures, failures


def test_two_store_objects_on_one_artifact_share_a_lock(workspace_root: Path) -> None:
    assert artifact_lock(_store(workspace_root).paths.root) is artifact_lock(
        _store(workspace_root).paths.root
    )
    assert artifact_lock(_store(workspace_root).paths.root) is not artifact_lock(
        _store(workspace_root, artifact_id="other-deck").paths.root
    )


def test_the_lock_is_reentrant_and_per_artifact(
    workspace_root: Path, base_deck: DeckArtifact
) -> None:
    store = _store(workspace_root)
    store.create(base_deck)
    other = _store(workspace_root, artifact_id="other-deck")
    other.create(base_deck.model_copy(update={"id": "other-deck"}))
    results: dict[str, object] = {}

    def read(name: str, target: ArtifactStore) -> None:
        results[name] = target.load()

    with artifact_lock(store.paths.root):
        # Re-entrant: the holding thread may take the lock again through the store.
        assert store.load() == base_deck
        _apply_number(store, base_deck, "1%")
        # Independent: another artifact's reader is not blocked by this lock...
        free = threading.Thread(target=read, args=("other", other))
        free.start()
        free.join(timeout=_JOIN_SECONDS)
        assert not free.is_alive() and "other" in results
        # ...but a reader of this artifact on another thread waits for it.
        blocked = threading.Thread(target=read, args=("same", store))
        blocked.start()
        blocked.join(timeout=0.3)
        assert blocked.is_alive() and "same" not in results
    blocked.join(timeout=_JOIN_SECONDS)
    assert not blocked.is_alive() and "same" in results
