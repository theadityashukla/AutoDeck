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

from autodeck.studio.models import ChangeEntry, ChangeLog


def new_changelog(artifact_id: str, initial_digest: str) -> ChangeLog:
    """An empty log for a freshly created artifact: no entries, `head=None`.

    Raises:
        pydantic.ValidationError: `artifact_id` is not a safe segment or the digest is not
            64 lower-case hex characters.
    """
    raise NotImplementedError


def next_entry_id(log: ChangeLog) -> str:
    """`c` + the 1-based ordinal of the next entry, zero-padded to 4 digits:
    `c0001` for an empty log, `c0013` after twelve entries, `c10000` after 9999.
    Undone entries count (ids are never reused)."""
    raise NotImplementedError


def head_entry(log: ChangeLog) -> ChangeEntry | None:
    """The entry whose after-state is current, or None at the initial state."""
    raise NotImplementedError


def head_digest(log: ChangeLog) -> str:
    """The digest the artifact's current state must have: the head entry's
    `after_digest`, or `log.initial_digest` when head is None."""
    raise NotImplementedError


def live_entries(log: ChangeLog) -> list[ChangeEntry]:
    """The entries on the live chain (root to head, in application order). These are
    exactly the entries with `undone == False`. `[]` at the initial state."""
    raise NotImplementedError


def append_entry(log: ChangeLog, entry: ChangeEntry) -> ChangeLog:
    """`log` with `entry` appended and `head` moved to it.

    Raises:
        ValueError: `entry.parent_id != log.head`, `entry.undone` is True, or `entry.id`
            is not `next_entry_id(log)`. (A digest that does not continue the chain is
            caught by `ChangeLog` validation and surfaces as `pydantic.ValidationError`,
            itself a `ValueError`.)
    """
    raise NotImplementedError


def undo_target(log: ChangeLog) -> ChangeEntry | None:
    """The entry an undo would reverse: `head_entry(log)`. None when nothing to undo."""
    raise NotImplementedError


def redo_target(log: ChangeLog) -> ChangeEntry | None:
    """The entry a redo would re-apply: the last-appended entry with `undone == True` and
    `parent_id == log.head`. None when there is none (including when a newer change was
    made on top of an undone one; see the module docstring)."""
    raise NotImplementedError


def mark_undone(log: ChangeLog) -> tuple[ChangeLog, ChangeEntry]:
    """Undo the head entry: return the new log (that entry `undone=True`, `head` = its
    `parent_id`) and the updated entry.

    Raises:
        NothingToUndoError: head is None.
    """
    raise NotImplementedError


def mark_redone(log: ChangeLog) -> tuple[ChangeLog, ChangeEntry]:
    """Redo `redo_target(log)`: return the new log (that entry `undone=False`, `head` = its
    id) and the updated entry.

    Raises:
        NothingToRedoError: `redo_target(log)` is None.
    """
    raise NotImplementedError


def listing(log: ChangeLog) -> list[str]:
    """One line per entry, in append order, exactly:

        f"{e.id} {'undone' if e.undone else 'live'} {e.layer} {e.model_id} {e.thread_id} "
        f"{e.created_at.isoformat(timespec='seconds')} {e.instruction}"

    and nothing else (head is implied by which entries are live). `[]` for an empty log."""
    raise NotImplementedError
