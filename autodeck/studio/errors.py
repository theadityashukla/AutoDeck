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


# ---------------------------------------------------------------------------
# Phase 1: threads, proposals, sources, turns, configuration
# ---------------------------------------------------------------------------


class ThreadNotFoundError(StudioError):
    """No `thread.json` for that thread id in this engagement."""


class ThreadLogError(StudioError):
    """A thread's files disagree with themselves: `messages.jsonl` has a line whose `seq`
    is not its 1-based position, a line that is not a valid `ThreadLine`, or `context.md`
    whose digest is not the record's `context_digest`. Raised instead of guessing."""


class ProposalNotFoundError(StudioError):
    """No `proposal.json` for that proposal id in this engagement."""


class ProposalStateError(StudioError):
    """A proposal was asked to change in a way its status does not allow: resolving one
    that is no longer open, accepting an option it does not have, or applying an option
    that was not the one chosen."""


class SourceNotFoundError(StudioError, LookupError):
    """A source id names nothing this engagement can read, or a page/offset is outside it."""


class TurnInProgressError(StudioError):
    """A turn (or an owner action that changes state) was started while another turn is
    running in the same engagement. Phase 1 runs one turn at a time per engagement."""


class StudioConfigError(StudioError):
    """`config/studio.yaml` is missing or malformed, or names an unknown environment, role
    or provider."""


# ---------------------------------------------------------------------------
# Phase 2-3: design systems, composition, routing
# ---------------------------------------------------------------------------


class DesignSystemNotFoundError(StudioError, LookupError):
    """No stored version of that design system in this engagement (the default system,
    `models.DEFAULT_SYSTEM_ID` version 1, is never missing: it is not stored)."""


class PaletteRefusedError(StudioError):
    """A palette failed the contrast rules. The message lists every measured ratio that
    failed (`design.findings_text`), so the system layer can correct it."""


class CompositionError(StudioError):
    """A composition request cannot be carried out as asked: a named slide has no brief,
    a sample slide is unknown, or no direction produced a usable design. Converted to a
    tool error by `tools.guarded`, so the lead can correct the call."""
