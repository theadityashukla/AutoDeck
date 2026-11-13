"""Errors raised by the studio package.

Client isolation is not redefined here: a cross-client reach raises v2's own
`autodeck.knowledge.loader.ClientIsolationError` (A4 holds in every mode, V9), so one
`except ClientIsolationError` catches it whichever package detected it. A missing or
malformed knowledge folder likewise surfaces as v2's `KnowledgeError`.
"""

from __future__ import annotations


class StudioError(RuntimeError):
    """Base for every studio error that is not an isolation or knowledge error."""


class InvalidSegmentError(StudioError, ValueError):
    """A client, project, artifact or entry id is not a safe single path segment."""


class WorkspaceLocationError(StudioError):
    """The workspace root is inside the knowledge tree (or the knowledge tree inside it).

    Working state must never be written into curated knowledge folders: those are tracked,
    reviewed and shared across clients at the project tier.
    """


class EngagementExistsError(StudioError):
    """`create_engagement` was asked for an engagement that already has a record."""


class EngagementNotFoundError(StudioError):
    """`open_engagement` found no `engagement.json` for that client and project."""


class EngagementMismatchError(StudioError):
    """An engagement record names a different project than the directory it sits in."""


class ArtifactExistsError(StudioError):
    """`ArtifactStore.create` was called for an artifact that already exists."""


class ArtifactNotFoundError(StudioError):
    """The artifact directory, its current state or its change log is missing."""


class ArtifactMismatchError(StudioError):
    """A deck's `id` or `project` does not match the store or engagement it is given to.

    A mismatched `client` is not this error: it is a `ClientIsolationError`.
    """


class NoChangeError(StudioError):
    """`ArtifactStore.apply` was given a state identical to the current one."""


class NothingToUndoError(StudioError):
    """Undo was requested with the artifact at its initial state."""


class NothingToRedoError(StudioError):
    """Redo was requested with no undone entry whose parent is the current head."""


class ChangeLogIntegrityError(StudioError):
    """Stored state disagrees with the change log: the current file's digest is not the
    head's `after_digest`, or a snapshot's digest is not what its entry recorded. Raised
    instead of guessing, because a guessed undo is not an exact one."""


class EditError(StudioError, LookupError):
    """An edit named a slide or block that does not exist, or asked a block to hold
    something its kind cannot (for example new text on a chart block)."""


class MissingLayoutError(StudioError):
    """A slide with no `FreeLayout` was handed to a function that needs one."""
