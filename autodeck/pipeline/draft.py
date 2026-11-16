"""A draft-first run's draft brief, and how a person turns it into a recorded one (B43, B48).

On a draft-first run the compose call writes the brief together with everything else, and it
is saved as a **draft** — the same `draft_brief.json` the planner conversation keeps, in the
same `Draft` shape — because a brief under construction is legitimately invalid: a `thin`
key message has no accepted risk yet, and nobody has approved anything. `DeckBrief`'s
`_gaps_are_accounted_for` rule only applies at approval, which is when it means something.

`finalise_draft_brief` is the draft-first counterpart of `PlannerSession.sign_off`'s first
half: it builds the `DeckBrief` from the draft, with every weak message's risk accepted **by
name** by the person approving, and saves it. It records no approval itself — the caller
(`autodeck approve`, or the UI's one approval route) calls `Orchestrator.approve` on the
result, so the sanctioned approval callers stay the only ones (A7, B42).

A weak message the person did not accept is not quietly carried: the brief is refused and the
refusal names it. Accepting is a decision, and B48's "keep what the person agreed to" does
not extend to accepting a gap on their behalf.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from autodeck.agents.planner import Draft
from autodeck.ir.models import DeckBrief, OpenRisk
from autodeck.pipeline.orchestrator import Orchestrator


class DraftBriefError(RuntimeError):
    """The draft brief cannot become a recorded brief as things stand; the message says why."""


def save_draft_brief(orchestrator: Orchestrator, draft: Draft) -> None:
    """Save the compose call's brief as the run's draft brief, atomically."""
    path = orchestrator.paths.draft_brief
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(draft.to_dict(), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_draft_brief(orchestrator: Orchestrator) -> Draft:
    path = orchestrator.paths.draft_brief
    if not path.exists():
        raise DraftBriefError(
            f"run {orchestrator.run_id!r} has no draft brief. Draft the deck first."
        )
    try:
        return Draft.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise DraftBriefError(f"the draft brief at {path} cannot be read: {exc}") from exc


def weak_messages(draft: Draft) -> list[tuple[str, str, str]]:
    """`(message_id, evidence_status, what is missing)` for every message that needs a risk."""
    excused = {risk.message_id for risk in draft.open_risks}
    return [
        (m.id, m.evidence_status, m.probe_notes or f"evidence is {m.evidence_status}")
        for m in draft.key_messages
        if m.needs_a_risk() and m.id not in excused
    ]


def finalise_draft_brief(
    orchestrator: Orchestrator,
    *,
    approver: str,
    accepted_risks: Mapping[str, str] | None = None,
) -> DeckBrief:
    """Build and save the recorded brief from the draft, ready for `Orchestrator.approve`.

    Args:
        approver: who is approving; recorded on the brief and on every risk they accept.
        accepted_risks: message id → what the person accepts is missing. Only weak messages
            (`thin`, `unsupported`) need one; the description defaults to the evidence
            check's own note when the person accepts without rewording it (pass `""`).

    Raises:
        DraftBriefError: no draft brief; no approver; a weak message the person did not
            accept; or a draft that is not a valid brief for another reason (the message
            is `DeckBrief`'s own).
    """
    approver = approver.strip()
    if not approver:
        raise DraftBriefError("an approval needs the name of the person giving it (A7).")
    draft = load_draft_brief(orchestrator)
    accepted = dict(accepted_risks or {})

    unaccepted = []
    for message_id, _status, missing in weak_messages(draft):
        if message_id not in accepted:
            unaccepted.append(message_id)
            continue
        draft.open_risks.append(
            OpenRisk(
                message_id=message_id,
                description=accepted[message_id].strip() or missing,
                accepted_by=approver,
            )
        )
    if unaccepted:
        raise DraftBriefError(
            f"key message(s) {', '.join(unaccepted)} have weak or no evidence. Accept each "
            "as a named risk, reword it, or remove it before approving the brief (A8, B48)."
        )

    version = orchestrator.ir.next_brief_version()
    try:
        brief = draft.to_brief(orchestrator.run_id, version=version)
    except Exception as exc:
        raise DraftBriefError(f"this brief cannot be approved yet: {exc}") from exc
    recorded = brief.model_copy(update={"approved_by": approver})
    orchestrator.ir.save_brief(recorded)
    return recorded
