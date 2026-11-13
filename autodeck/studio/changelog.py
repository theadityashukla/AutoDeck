"""Undo and redo as pure functions over a `ChangeLog` (plan §4, V4).

No file is touched here; `store.ArtifactStore` does the I/O and calls these. Every function
returns a **new** `ChangeLog` built with `ChangeLog.model_validate(...)` (never
`model_copy`, which skips validation), so the log's invariants are re-checked on every
transition and an invalid log cannot be produced by this module. Inputs are never mutated.

The model (see `ChangeLog`'s docstring) is a tree of states with a `head` pointer:

* **apply** appends an entry whose parent is the current head, and moves head to it;
* **undo** marks head undone and moves head to its parent;
* **redo** picks, among undone entries whose parent is head, the most recently appended,
  marks it not undone and moves head to it.

So after `A, B`, undo B, then a new change C: the log is `A, B(undone), C` with head C;
B is no longer redoable (its parent A is not head), and undoing C makes head A, at which
point redo re-applies C (the most recent child of A), not B. Undone entries stay in the log
because the next thread is told what was rejected (plan §5.1).

Phase 0 has linear undo/redo only. Undoing one change from the middle of the history while
keeping later ones (plan §5.3 "per change") is not offered; see docs/phases/V3-PHASE-0.md.
"""

from __future__ import annotations

from autodeck.studio.errors import NothingToRedoError, NothingToUndoError
from autodeck.studio.models import ChangeEntry, ChangeLog


def _rebuild(log: ChangeLog, entries: list[ChangeEntry], head: str | None) -> ChangeLog:
    """A new, fully validated log; `log` is not mutated."""
    return ChangeLog.model_validate(
        {
            "schema_version": log.schema_version,
            "artifact_id": log.artifact_id,
            "initial_digest": log.initial_digest,
            "head": head,
            "entries": [e.model_dump() for e in entries],
        }
    )


def _with_undone(entry: ChangeEntry, undone: bool) -> ChangeEntry:
    return ChangeEntry.model_validate({**entry.model_dump(), "undone": undone})


def new_changelog(artifact_id: str, initial_digest: str) -> ChangeLog:
    """An empty log for a freshly created artifact: no entries, `head=None`.

    Raises:
        pydantic.ValidationError: `artifact_id` is not a safe segment or the digest is not
            64 lower-case hex characters.
    """
    return ChangeLog.model_validate(
        {
            "artifact_id": artifact_id,
            "initial_digest": initial_digest,
            "head": None,
            "entries": [],
        }
    )


def next_entry_id(log: ChangeLog) -> str:
    """`c` + the 1-based ordinal of the next entry, zero-padded to 4 digits:
    `c0001` for an empty log, `c0013` after twelve entries, `c10000` after 9999.
    Undone entries count (ids are never reused)."""
    return f"c{len(log.entries) + 1:04d}"


def head_entry(log: ChangeLog) -> ChangeEntry | None:
    """The entry whose after-state is current, or None at the initial state."""
    return None if log.head is None else log.entry(log.head)


def head_digest(log: ChangeLog) -> str:
    """The digest the artifact's current state must have: the head entry's
    `after_digest`, or `log.initial_digest` when head is None."""
    head = head_entry(log)
    return log.initial_digest if head is None else head.after_digest


def live_entries(log: ChangeLog) -> list[ChangeEntry]:
    """The entries on the live chain (root to head, in application order). These are
    exactly the entries with `undone == False`. `[]` at the initial state."""
    chain: list[ChangeEntry] = []
    entry = head_entry(log)
    while entry is not None:
        chain.append(entry)
        entry = None if entry.parent_id is None else log.entry(entry.parent_id)
    chain.reverse()
    return chain


def append_entry(log: ChangeLog, entry: ChangeEntry) -> ChangeLog:
    """`log` with `entry` appended and `head` moved to it.

    Raises:
        ValueError: `entry.parent_id != log.head`, `entry.undone` is True, or `entry.id`
            is not `next_entry_id(log)`. (A digest that does not continue the chain is
            caught by `ChangeLog` validation and surfaces as `pydantic.ValidationError`,
            itself a `ValueError`.)
    """
    if entry.parent_id != log.head:
        raise ValueError(
            f"entry {entry.id!r} has parent {entry.parent_id!r}, head is {log.head!r}"
        )
    if entry.undone:
        raise ValueError(f"entry {entry.id!r} is appended already undone")
    expected = next_entry_id(log)
    if entry.id != expected:
        raise ValueError(f"entry id {entry.id!r} is not the next id {expected!r}")
    return _rebuild(log, [*log.entries, entry], entry.id)


def undo_target(log: ChangeLog) -> ChangeEntry | None:
    """The entry an undo would reverse: `head_entry(log)`. None when nothing to undo."""
    return head_entry(log)


def redo_target(log: ChangeLog) -> ChangeEntry | None:
    """The entry a redo would re-apply: the last-appended entry with `undone == True` and
    `parent_id == log.head`. None when there is none (including when a newer change was
    made on top of an undone one; see the module docstring)."""
    for entry in reversed(log.entries):
        if entry.undone and entry.parent_id == log.head:
            return entry
    return None


def mark_undone(log: ChangeLog) -> tuple[ChangeLog, ChangeEntry]:
    """Undo the head entry: return the new log (that entry `undone=True`, `head` = its
    `parent_id`) and the updated entry.

    Raises:
        NothingToUndoError: head is None.
    """
    target = head_entry(log)
    if target is None:
        raise NothingToUndoError("nothing to undo: the artifact is at its initial state")
    updated = _with_undone(target, True)
    entries = [updated if e.id == target.id else e for e in log.entries]
    return _rebuild(log, entries, target.parent_id), updated


def mark_redone(log: ChangeLog) -> tuple[ChangeLog, ChangeEntry]:
    """Redo `redo_target(log)`: return the new log (that entry `undone=False`, `head` = its
    id) and the updated entry.

    Raises:
        NothingToRedoError: `redo_target(log)` is None.
    """
    target = redo_target(log)
    if target is None:
        raise NothingToRedoError("nothing to redo")
    updated = _with_undone(target, False)
    entries = [updated if e.id == target.id else e for e in log.entries]
    return _rebuild(log, entries, target.id), updated


def listing(log: ChangeLog) -> list[str]:
    """One line per entry, in append order, exactly:

        f"{e.id} {'undone' if e.undone else 'live'} {e.layer} {e.model_id} {e.thread_id} "
        f"{e.created_at.isoformat(timespec='seconds')} {e.instruction}"

    and nothing else (head is implied by which entries are live). `[]` for an empty log."""
    return [
        f"{e.id} {'undone' if e.undone else 'live'} {e.layer} {e.model_id} {e.thread_id} "
        f"{e.created_at.isoformat(timespec='seconds')} {e.instruction}"
        for e in log.entries
    ]
