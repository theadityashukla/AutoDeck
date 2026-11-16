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

from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio import serialise
from autodeck.studio.conversation import ProposalOption, ProposalRecord, ResolvedBy
from autodeck.studio.engagement import Engagement
from autodeck.studio.errors import ProposalNotFoundError, ProposalStateError, StudioError
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
        paths = self.engagement.paths.proposal(proposal_id)
        self.engagement.guard(paths.root)
        return paths

    def next_id(self) -> str:
        """`p` + 4-digit ordinal: `p0001` when there is none, else one more than the highest
        existing id's number (`engagement.paths.proposal_ids()`)."""
        existing = self.engagement.paths.proposal_ids()
        if not existing:
            return "p0001"
        highest = max(int(proposal_id[1:]) for proposal_id in existing)
        return f"p{highest + 1:04d}"

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
        proposal_id = self.next_id()
        record = ProposalRecord(
            id=proposal_id,
            thread_id=thread_id,
            turn_id=turn_id,
            artifact_id=artifact_id,
            summary=summary,
            options=options,
            created_at=now,
        )
        paths = self.paths(proposal_id).ensure()
        serialise.atomic_write_text(paths.record, serialise.dump_model(record))
        return record

    def load(self, proposal_id: str) -> ProposalRecord:
        """The validated record.

        Raises:
            ProposalNotFoundError: no `proposal.json` for this id (message names it).
            InvalidSegmentError, ClientIsolationError: as `paths`.
            pydantic.ValidationError: malformed.
        """
        paths = self.paths(proposal_id)
        if not paths.record.is_file():
            raise ProposalNotFoundError(f"no proposal {proposal_id!r} in this engagement")
        return ProposalRecord.model_validate_json(serialise.read_text(paths.record))

    def list(self) -> list[ProposalRecord]:
        """Every proposal, sorted by id. A directory whose record is missing, invalid or
        refused by `load` for any reason (isolation included) is skipped."""
        records: list[ProposalRecord] = []
        for proposal_id in self.engagement.paths.proposal_ids():
            try:
                records.append(self.load(proposal_id))
            except (StudioError, ClientIsolationError, ValueError, OSError):
                continue
        return records

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
        old = self.load(proposal_id)
        if old.status != "open":
            detail = f" (option {old.chosen})" if old.status == "accepted" else ""
            raise ProposalStateError(
                f"proposal {proposal_id} is already {old.status}{detail}; it cannot be resolved"
            )
        if status not in ("accepted", "dismissed"):
            raise ProposalStateError(f"proposal {proposal_id}: unknown status {status!r}")
        if status == "accepted":
            if chosen is None:
                raise ProposalStateError(f"proposal {proposal_id}: accepting needs an option")
            if chosen not in [option.id for option in old.options]:
                raise ProposalStateError(
                    f"proposal {proposal_id} has no option {chosen!r} to accept"
                )
        elif chosen is not None:
            raise ProposalStateError(f"proposal {proposal_id}: dismissing chooses no option")
        new = ProposalRecord.model_validate(
            {
                **old.model_dump(),
                "status": status,
                "chosen": chosen,
                "resolved_by": by,
                "resolved_at": now,
            }
        )
        serialise.atomic_write_text(self.paths(proposal_id).record, serialise.dump_model(new))
        return new
