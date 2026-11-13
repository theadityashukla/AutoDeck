"""Proposals on disk (plan §5.2 "Propose", P6, §5.1 "what was rejected").

One directory per proposal under `<engagement>/proposals/<proposal-id>/`, holding
`proposal.json` (`conversation.ProposalRecord`) and, derived, `renders/<option-id>/` (the
candidate-slide previews, written by `previews`). Proposal ids are per engagement, so
`apply_option(proposal_id, ...)` and the interface can name a proposal without a thread.

A proposal is created `open` by the `propose` tool and resolved exactly once: `accepted`
(with the chosen option) or `dismissed`, by the owner's buttons or, for acceptance, by the
model applying an option the owner chose in words. Resolution rewrites `proposal.json`
atomically; nothing is ever deleted, because the next thread's context lists what was
dismissed (`context`).

Bound to one `Engagement`; every path passes `engagement.guard` before use.
"""

from __future__ import annotations

from datetime import datetime

from autodeck.studio.conversation import ProposalOption, ProposalRecord, ResolvedBy
from autodeck.studio.engagement import Engagement
from autodeck.studio.models import OptionId
from autodeck.studio.paths import ProposalPaths


class ProposalStore:
    """Create, read and resolve the proposals of one engagement. The constructor stores
    the engagement and touches no file."""

    def __init__(self, engagement: Engagement) -> None:
        self.engagement = engagement

    def paths(self, proposal_id: str) -> ProposalPaths:
        """`engagement.paths.proposal(proposal_id)`, root passed through `engagement.guard`.

        Raises:
            InvalidSegmentError: not a proposal id (`p0001`, ...).
            ClientIsolationError: the directory resolves into another client's engagements.
        """
        raise NotImplementedError

    def next_id(self) -> str:
        """`p` + 4-digit ordinal: `p0001` when there is none, else one more than the highest
        existing id's number (`engagement.paths.proposal_ids()`)."""
        raise NotImplementedError

    def create(
        self,
        *,
        thread_id: str,
        turn_id: str,
        artifact_id: str | None,
        summary: str,
        options: list[ProposalOption],
        now: datetime,
    ) -> ProposalRecord:
        """Record a new open proposal and return it.

        id = `next_id()`; the record is validated (`ProposalRecord`) before anything is
        written; then `paths(id).ensure()` and `proposal.json` is written with
        `serialise.atomic_write_text(serialise.dump_model(record))`.

        Raises:
            pydantic.ValidationError: invalid record (for example option ids out of order,
                a multi-line summary, candidate slides with no `artifact_id`); nothing
                written.
        """
        raise NotImplementedError

    def load(self, proposal_id: str) -> ProposalRecord:
        """The validated record.

        Raises:
            ProposalNotFoundError: no `proposal.json` for this id (message names it).
            InvalidSegmentError, ClientIsolationError: as `paths`.
            pydantic.ValidationError: malformed.
        """
        raise NotImplementedError

    def list(self) -> list[ProposalRecord]:
        """Every proposal, sorted by id. A directory whose record is missing, invalid or
        refused by `load` for any reason (isolation included) is skipped."""
        raise NotImplementedError

    def resolve(
        self,
        proposal_id: str,
        *,
        status: str,
        chosen: OptionId | None,
        by: ResolvedBy,
        now: datetime,
    ) -> ProposalRecord:
        """Accept or dismiss an open proposal; return the record as now stored.

        `status` is `"accepted"` (then `chosen` must be one of the proposal's option ids)
        or `"dismissed"` (then `chosen` must be None). The new record is built with
        `ProposalRecord.model_validate({**old.model_dump(), "status": ..., "chosen": ...,
        "resolved_by": by, "resolved_at": now})` and written atomically.

        Raises:
            ProposalNotFoundError: no such proposal.
            ProposalStateError: the proposal is not open (the message says its status and,
                if accepted, which option); `status` is neither value; `chosen` names an
                option the proposal does not have, or is given for a dismissal, or missing
                for an acceptance. Nothing is written.
        """
        raise NotImplementedError
