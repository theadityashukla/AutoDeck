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

from datetime import datetime

from autodeck.studio.models import ChangeEntry, ChangeLog, DeckArtifact, Layer
from autodeck.studio.paths import ArtifactPaths


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
        raise NotImplementedError

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
        raise NotImplementedError

    # -- reading -----------------------------------------------------------

    def current_text(self) -> str:
        """The exact text of `current.json` (`serialise.read_text`).

        Raises:
            ArtifactNotFoundError: the artifact does not exist.
        """
        raise NotImplementedError

    def changelog(self) -> ChangeLog:
        """The validated change log.

        Raises:
            ArtifactNotFoundError: `changelog.json` is missing.
            pydantic.ValidationError: it is malformed or violates the log's invariants.
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def snapshot(self, entry_id: str | None) -> DeckArtifact:
        """The state after `entry_id` (or the initial state for None), whether or not that
        entry is currently undone.

        Raises:
            KeyError: no such entry in the log.
            ArtifactNotFoundError: the snapshot file is missing.
            ChangeLogIntegrityError: the snapshot's digest is not the entry's
                `after_digest` (or the log's `initial_digest`).
        """
        raise NotImplementedError

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
        a naive datetime fails `ChangeEntry` validation), and the before/after digests.
        Then write the snapshot `versions/<id>.json`, the log via
        `changelog.append_entry`, and `current.json`, in that order.

        A new change on top of undone entries leaves them in the log, undone and no longer
        redoable (`changelog` module docstring).

        Raises:
            NoChangeError, ClientIsolationError, ArtifactMismatchError,
            ChangeLogIntegrityError, ArtifactNotFoundError as above;
            pydantic.ValidationError: the instruction is blank or multi-line, or another
                entry field is invalid. Nothing is written in any error case.
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def redo(self) -> ChangeEntry:
        """Re-apply `changelog.redo_target(log)`; return it as now stored (`undone=False`).

        Check the current digest equals `head_digest(log)` and the target snapshot
        (`versions/<target>.json`) digest equals the target's `after_digest`; then write
        the log (`changelog.mark_redone`) and copy the snapshot text over `current.json`.

        Raises:
            NothingToRedoError: there is no redo target.
            ChangeLogIntegrityError: a digest check fails (nothing is written).
        """
        raise NotImplementedError
