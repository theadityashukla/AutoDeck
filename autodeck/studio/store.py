"""One artifact on disk: current state, change log and version snapshots (plan §4, V4).

v2's `IRStore` kept immutable numbered versions per run; here the change log is the
history (plan §11: "diff kept; storage becomes the change log"). Layout, from `paths`:

* `current.json`: the current state, canonical text (`serialise.dump_artifact`);
* `versions/initial.json`: the state the artifact was created with;
* `versions/<entry-id>.json`: the state after each entry, written once, never changed;
* `changelog.json`: the `ChangeLog`, rewritten atomically on each transition.

**Undo restores a snapshot; it does not invert the diff.** Undoing entry E copies the
bytes of E's parent snapshot (or `initial.json`) over `current.json`. Redo copies E's own
snapshot. Both check digests first (current against the head's `after_digest`, the
snapshot against what the entry recorded) and raise `ChangeLogIntegrityError` rather than
guess. That is what makes "after undo the artifact equals its previous state byte for
byte" true by construction rather than by careful diff arithmetic.

**Write order** for every transition: (1) any new snapshot, (2) `changelog.json`,
(3) `current.json`, each with `serialise.atomic_write_text`. A crash between (2) and (3)
leaves `current.json` disagreeing with the log's head, which `load` reports as
`ChangeLogIntegrityError`; Phase 0 does not auto-repair.

Single writer only: Phase 0 has no locking. Several threads on one artifact (plan §5.4) is
Phase 4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio import changelog as cl
from autodeck.studio import diff as diffmod
from autodeck.studio import serialise as ser
from autodeck.studio.errors import (
    ArtifactExistsError,
    ArtifactMismatchError,
    ArtifactNotFoundError,
    ChangeLogIntegrityError,
    NoChangeError,
)
from autodeck.studio.models import ChangeEntry, ChangeLog, DeckArtifact, Layer
from autodeck.studio.paths import ArtifactPaths


def _read(path: Path, what: str) -> str:
    try:
        return ser.read_text(path)
    except FileNotFoundError as exc:
        raise ArtifactNotFoundError(f"{what} not found: {path}") from exc


class ArtifactStore:
    """Read and change one deck artifact. Bound to one client and project at construction.

    Construct through `Engagement.artifact_store` / `Engagement.create_artifact`, which
    supply the engagement's client and project and guarded paths. The constructor only
    stores its arguments; it touches no file.
    """

    def __init__(self, paths: ArtifactPaths, *, client: str, project: str) -> None:
        self.paths = paths
        self.client = client
        self.project = project

    @property
    def artifact_id(self) -> str:
        return self.paths.artifact_id

    # -- lifecycle ---------------------------------------------------------

    def exists(self) -> bool:
        """True when `current.json` exists (whether or not it is valid)."""
        return self.paths.current.is_file()

    def create(self, deck: DeckArtifact) -> ChangeLog:
        """Create the artifact with `deck` as its initial state; return the empty log.

        Checks, in this order: `deck.client == self.client` (else `ClientIsolationError`,
        v2's), `deck.project == self.project` and `deck.id == self.artifact_id` (else
        `ArtifactMismatchError`), not `exists()` (else `ArtifactExistsError`). Then
        `paths.ensure()`, write `versions/initial.json`, then `changelog.json`
        (`changelog.new_changelog(id, artifact_digest(deck))`), then `current.json`; the
        snapshot and current files hold identical bytes (`dump_artifact(deck)`). No entry is
        recorded for creation: the initial state is the root, not a change.
        """
        self._check_deck(deck)
        if self.exists():
            raise ArtifactExistsError(f"artifact {self.artifact_id!r} already exists")
        text = ser.dump_artifact(deck)
        log = cl.new_changelog(self.artifact_id, ser.text_digest(text))
        self.paths.ensure()
        ser.atomic_write_text(self.paths.initial_version, text)
        ser.atomic_write_text(self.paths.changelog, ser.dump_model(log))
        ser.atomic_write_text(self.paths.current, text)
        return log

    # -- reading -----------------------------------------------------------

    def current_text(self) -> str:
        """The exact text of `current.json` (`serialise.read_text`).

        Raises:
            ArtifactNotFoundError: the artifact does not exist.
        """
        return _read(self.paths.current, "current state")

    def changelog(self) -> ChangeLog:
        """The validated change log.

        Raises:
            ArtifactNotFoundError: `changelog.json` is missing.
            pydantic.ValidationError: it is malformed or violates the log's invariants.
        """
        return ser.load_changelog(_read(self.paths.changelog, "change log"))

    def load(self) -> DeckArtifact:
        """The current state, validated and checked.

        Raises:
            ArtifactNotFoundError: the artifact does not exist.
            ChangeLogIntegrityError: `text_digest(current_text())` is not
                `changelog.head_digest(log)`.
            ClientIsolationError: the stored deck's `client` is not `self.client` (a file
                copied in from another client's engagement).
            ArtifactMismatchError: the stored deck's `project` or `id` does not match.
        """
        text = self.current_text()
        log = self.changelog()
        if ser.text_digest(text) != cl.head_digest(log):
            raise ChangeLogIntegrityError(
                f"{self.paths.current} does not match the change log's head digest"
            )
        deck = ser.load_artifact(text)
        self._check_deck(deck)
        return deck

    def snapshot(self, entry_id: str | None) -> DeckArtifact:
        """The state after `entry_id` (or the initial state for None), whether or not that
        entry is currently undone.

        Raises:
            KeyError: no such entry in the log.
            ArtifactNotFoundError: the snapshot file is missing.
            ChangeLogIntegrityError: the snapshot's digest is not the entry's
                `after_digest` (or the log's `initial_digest`).
        """
        log = self.changelog()
        if entry_id is None:
            expected, path = log.initial_digest, self.paths.initial_version
        else:
            expected, path = log.entry(entry_id).after_digest, self.paths.version(entry_id)
        text = _read(path, "snapshot")
        if ser.text_digest(text) != expected:
            raise ChangeLogIntegrityError(f"snapshot {path} does not match its recorded digest")
        return ser.load_artifact(text)

    # -- changing ----------------------------------------------------------

    def apply(
        self,
        new_state: DeckArtifact,
        *,
        instruction: str,
        thread_id: str,
        layer: Layer,
        model_id: str,
        now: datetime | None = None,
    ) -> ChangeEntry:
        """Make `new_state` the current state and record the change. Returns the new entry.

        Steps: `before = load()` (so integrity and isolation are checked first);
        `new_state.client` must equal `self.client` (`ClientIsolationError`) and its
        `project`/`id` must match (`ArtifactMismatchError`); if
        `dump_artifact(new_state) == current_text()` raise `NoChangeError`. Build a
        `ChangeEntry` with `id=changelog.next_entry_id(log)`, `parent_id=log.head`,
        `diff=diff.diff_artifacts(before, new_state)`, the given instruction, thread, layer
        and model, `created_at = now or datetime.now(UTC)` (`now` must be timezone-aware;
        a naive datetime fails `ChangeEntry` validation),
        `before_digest = text_digest(current_text())` (the stored bytes, which `load` has
        just checked equal the head's digest) and `after_digest = artifact_digest(new_state)`.
        Compute the new log with `changelog.append_entry` *before* writing anything (so an
        invalid entry or log raises with the disk untouched). Then write the snapshot
        `versions/<id>.json`, the new `changelog.json`, and `current.json`, in that order;
        the snapshot and `current.json` hold identical bytes (`dump_artifact(new_state)`).

        A new change on top of undone entries leaves them in the log, undone and no longer
        redoable (`changelog` module docstring).

        Raises:
            NoChangeError, ClientIsolationError, ArtifactMismatchError,
            ChangeLogIntegrityError, ArtifactNotFoundError as above;
            pydantic.ValidationError: the instruction is blank or multi-line, or another
                entry field is invalid. Nothing is written in any error case.
        """
        before = self.load()
        self._check_deck(new_state)
        current = self.current_text()
        new_text = ser.dump_artifact(new_state)
        if new_text == current:
            raise NoChangeError("the new state is identical to the current state")
        log = self.changelog()
        entry = ChangeEntry(
            id=cl.next_entry_id(log),
            parent_id=log.head,
            diff=diffmod.diff_artifacts(before, new_state),
            instruction=instruction,
            thread_id=thread_id,
            layer=layer,
            model_id=model_id,
            created_at=now or datetime.now(UTC),
            before_digest=ser.text_digest(current),
            after_digest=ser.text_digest(new_text),
        )
        new_log = cl.append_entry(log, entry)
        new_log_text = ser.dump_model(new_log)
        snapshot_path = self.paths.version(entry.id)
        ser.atomic_write_text(snapshot_path, new_text)
        ser.atomic_write_text(self.paths.changelog, new_log_text)
        ser.atomic_write_text(self.paths.current, new_text)
        return entry

    def undo(self) -> ChangeEntry:
        """Reverse the head entry; return it as now stored (`undone=True`).

        Check `text_digest(current_text())` equals the head's `after_digest`; read the
        parent snapshot (`versions/<parent>.json`, or `versions/initial.json`) and check its
        digest equals the entry's `before_digest`; then write the log
        (`changelog.mark_undone`) and copy the snapshot text over `current.json` unchanged.
        Afterwards `current_text()` is byte-identical to what it was before the entry was
        applied.

        Raises:
            NothingToUndoError: the artifact is at its initial state.
            ChangeLogIntegrityError: a digest check fails (nothing is written).
        """
        log = self.changelog()
        new_log, entry = cl.mark_undone(log)
        self._check_current(log)
        parent_path = (
            self.paths.initial_version
            if entry.parent_id is None
            else self.paths.version(entry.parent_id)
        )
        text = _read(parent_path, "snapshot")
        if ser.text_digest(text) != entry.before_digest:
            raise ChangeLogIntegrityError(
                f"snapshot {parent_path} does not match entry {entry.id}'s before digest"
            )
        new_log_text = ser.dump_model(new_log)
        ser.atomic_write_text(self.paths.changelog, new_log_text)
        ser.atomic_write_text(self.paths.current, text)
        return entry

    def redo(self) -> ChangeEntry:
        """Re-apply `changelog.redo_target(log)`; return it as now stored (`undone=False`).

        Check the current digest equals `head_digest(log)` and the target snapshot
        (`versions/<target>.json`) digest equals the target's `after_digest`; then write
        the log (`changelog.mark_redone`) and copy the snapshot text over `current.json`.

        Raises:
            NothingToRedoError: there is no redo target.
            ChangeLogIntegrityError: a digest check fails (nothing is written).
        """
        log = self.changelog()
        new_log, entry = cl.mark_redone(log)
        self._check_current(log)
        path = self.paths.version(entry.id)
        text = _read(path, "snapshot")
        if ser.text_digest(text) != entry.after_digest:
            raise ChangeLogIntegrityError(
                f"snapshot {path} does not match entry {entry.id}'s after digest"
            )
        new_log_text = ser.dump_model(new_log)
        ser.atomic_write_text(self.paths.changelog, new_log_text)
        ser.atomic_write_text(self.paths.current, text)
        return entry

    # -- helpers -----------------------------------------------------------

    def _check_deck(self, deck: DeckArtifact) -> None:
        if deck.client != self.client:
            raise ClientIsolationError(
                f"client {self.client!r} may not hold a deck of client {deck.client!r}"
            )
        if deck.project != self.project or deck.id != self.artifact_id:
            raise ArtifactMismatchError(
                f"deck {deck.client}/{deck.project}/{deck.id} does not belong to "
                f"{self.client}/{self.project}/{self.artifact_id}"
            )

    def _check_current(self, log: ChangeLog) -> None:
        if ser.text_digest(self.current_text()) != cl.head_digest(log):
            raise ChangeLogIntegrityError(
                f"{self.paths.current} does not match the change log's head digest"
            )
