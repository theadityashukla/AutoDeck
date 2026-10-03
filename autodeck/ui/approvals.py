"""The UI's one way to approve a gate: a person clicking "Approve & proceed" (A7, B42).

This is the only module in `autodeck/ui/` that calls `Orchestrator.approve`, and it is
reachable only from `POST /api/runs/<id>/approve` (tests pin both). It calls the same method
`autodeck approve <run> <gate> --by <name>` calls, so every refusal the CLI gives — no
artifact yet, claims no longer current, a final audit that did not run or did not pass —
applies here unchanged. The name comes from Settings > Profile instead of `--by`.

On a gate-first run the brief is not approvable here: it is signed through the planner
(`plan_sign`), as `/sign` is in `autodeck plan`. On a draft-first run (B43) it is: the draft
brief is first made into a recorded brief by `pipeline.draft.finalise_draft_brief`, with every
weak key message accepted by name as a risk the person chose to carry (B48), and then
approved here like any other gate.
"""

from __future__ import annotations

from typing import Any

from autodeck.pipeline.orchestrator import ApprovalRefused, ArtifactMissing, Gate
from autodeck.ui import api
from autodeck.ui.api import Roots, UIError

APPROVABLE = {
    "brief": Gate.BRIEF,
    "outline": Gate.OUTLINE,
    "claims": Gate.CLAIMS,
    "final_render": Gate.FINAL_RENDER,
}


def approve_gate(
    roots: Roots,
    run_id: str,
    gate_name: str,
    *,
    approver: str,
    accepted_risks: dict[str, str] | None = None,
) -> dict[str, Any]:
    gate = APPROVABLE.get(gate_name)
    if gate is None:
        raise UIError("Approve the brief, the outline, the claims or the final deck.")
    orch = api._open(roots, run_id)
    if gate is Gate.BRIEF:
        if not orch.is_draft_first:
            raise UIError(
                "This run was planned in conversation; approve its brief from the planning "
                "screen."
            )
        from autodeck.pipeline.draft import DraftBriefError, finalise_draft_brief

        try:
            finalise_draft_brief(orch, approver=approver, accepted_risks=accepted_risks)
        except DraftBriefError as exc:
            raise UIError(str(exc), status=409) from None
    try:
        orch.approve(gate, approver=approver)
    except (ArtifactMissing, ApprovalRefused) as exc:
        raise UIError(str(exc), status=409) from None
    at, _, by = orch.state.approvals[gate.value].partition(" by ")
    return {"gate": gate.value, "by": by, "at": at[:16].replace("T", " ")}
