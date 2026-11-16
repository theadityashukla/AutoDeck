"""The six checkable GATE 2 criteria, shared by `autodeck gate2` and the review UI."""

from __future__ import annotations

from autodeck.audit.report import AuditReport
from autodeck.ir.models import DeckBrief
from autodeck.pipeline.orchestrator import RenderSafety


def gate2_checks(
    brief_doc: DeckBrief | None,
    safety: RenderSafety,
    report: AuditReport,
) -> list[tuple[str, bool, str]]:
    """The six checkable criteria `docs/phases/PHASE-2B.md` names for GATE 2.

    Every check reads an existing report field — nothing here re-derives a verdict, a
    numeral match or a demotion, and **this function is not given the deck**, so it cannot
    start. The first three criteria are `assess_render_safety`'s own four conditions,
    printed one per line: this used to call `blocking_blocks`, `unverified_claims` and read
    two reports of its own, which is three of the render guard's four conditions
    re-implemented at a second call site. The guard's docstring warns that three checks at
    three call sites is how one gets forgotten; it had already happened, and both copies
    shared the diagram blind spot. Phase 3b's render stage inherits one answer.

    The one deliberate broadening over "unsupported/contradicted": criterion 1 also fails
    on an `unverified` claim. A validation pass that never reached a claim leaves
    `blocking_blocks()` empty, which would otherwise let an unvalidated deck read as passing
    every GATE 2 criterion — the same trap `assess_render_safety` names.
    """
    checks: list[tuple[str, bool, str]] = []

    blocking, unverified = safety.blocking, safety.unverified
    overstated = safety.overstated_headlines
    checks.append(
        (
            "zero blocks verdict unsupported/contradicted, no overstated headline (and none "
            "left unverified)",
            not blocking and not unverified and not overstated,
            (
                f"{len(blocking)} blocking block(s), {len(unverified)} unverified claim(s), "
                f"{len(overstated)} overstated headline(s)"
                if blocking or unverified or overstated
                else ""
            ),
        )
    )

    numeric = safety.numeric
    checks.append(
        (
            "numeric linter: zero unmatched numerals, every derivation re-executes",
            numeric.passes,
            "" if numeric.passes else f"{len(numeric.blocking)} blocking A2 finding(s)",
        )
    )

    framing = safety.framing
    checks.append(
        (
            "framing linter clean, no unresolved demotions",
            not framing.blocks_build,
            (
                f"{len(framing.demotions)} block(s) demoted to claim"
                if framing.blocks_build
                else ""
            ),
        )
    )

    rows = report.claim_rows()
    fully_cited = all(
        row.citations
        and all(c.quote.strip() and c.page >= 1 and c.doc_id for c in row.citations)
        for row in rows
    )
    checks.append(
        (
            "every claim shows doc, page and a verbatim quote",
            fully_cited,
            "" if fully_cited else "a claim row is missing a citation with doc/page/quote",
        )
    )

    conflicts_ok = all(
        bool(row.contradicting_spans) for row in rows if row.verdict == "contradicted"
    )
    checks.append(
        (
            "conflicts section present where sources disagree (A8)",
            conflicts_ok,
            "" if conflicts_ok else "a contradicted claim has no contradicting span recorded",
        )
    )

    if brief_doc is None:
        checks.append(
            (
                "open_risks from the brief appear in the report",
                False,
                "no brief could be loaded for this run — risks cannot be resurfaced",
            )
        )
    else:
        risk_ids = {risk.message_id for risk in brief_doc.open_risks}
        reported_ids = {row.risk.message_id for row in report.risks}
        missing_ids = sorted(risk_ids - reported_ids)
        checks.append(
            (
                "open_risks from the brief appear in the report",
                risk_ids == reported_ids,
                "" if risk_ids == reported_ids else f"missing: {missing_ids}",
            )
        )

    return checks


__all__ = ["gate2_checks"]
