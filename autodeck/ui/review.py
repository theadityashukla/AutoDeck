"""The review screens' read models: outline, claims and final deck (B42).

Each function builds the same report the matching CLI command prints (`autodeck outline`,
`gate2`, `gate3`) from the same code, and returns plain JSON. Nothing here approves a gate:
approval is `autodeck/ui/approvals.py`'s job alone (A7). The only writes are `audit_report.md`
(as `gate2` writes it, so the file on disk is always the report for the latest IR, A6) and
the send-back log (as `autodeck send-back` writes it). No model is called.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autodeck.ir.models import Deck, DeckBrief
from autodeck.ir.store import IRStoreError
from autodeck.pipeline.orchestrator import ApprovalState, Gate, Orchestrator
from autodeck.ui.api import Roots, UIError, _open

PREVIEW_DIR = ("previews", "final")
PREVIEW_NAME = re.compile(r"^.+-(\d+)\.png$")

#: How to do each of PHASE-3B.md's five PowerPoint checks. Titles come from
#: `audit.gate3.HUMAN_CHECKS`; nothing here, or anywhere in the code, ticks them.
HUMAN_CHECK_STEPS: tuple[str, ...] = (
    "Open the deck in PowerPoint. On the diagram slide, click one node, then change its fill "
    "from the Shape Format tab. It must recolour on its own, not as part of a picture.",
    "On the icon slide, click one icon and recolour it from the theme palette (Shape Fill, "
    "theme colours). It must be a shape, not an image.",
    "On the chart slide, right-click the chart, choose Edit Data, and change a value. The "
    "chart must redraw from the embedded workbook.",
    "Open the Design tab, then Variants, Colors and Fonts. The deck's theme colours and "
    "fonts must be the ones listed there.",
    "Insert a new slide from the Home tab. It must come in with the master's look "
    "(background, fonts, placeholders) without any manual fixing.",
)


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------


def _approval(orch: Orchestrator, gate: Gate) -> dict[str, Any]:
    """The same approval fields `api.run_summary` shows for a gate."""
    approval, detail = orch.approval_state(gate)
    ok = approval is ApprovalState.CURRENT
    by, at = "", ""
    if gate.value in orch.state.approvals:
        at, _, by = orch.state.approvals[gate.value].partition(" by ")
    return {
        "approved": ok,
        "state": approval.value,
        "by": by,
        "at": at[:16].replace("T", " "),
        "detail": "" if ok else detail,
    }


def _load_deck(orch: Orchestrator, version: int | None = None) -> Deck:
    try:
        return orch.ir.load(version)
    except IRStoreError as exc:
        raise UIError(str(exc), status=409) from None


def _load_brief(orch: Orchestrator) -> DeckBrief | None:
    try:
        return orch.ir.load_brief()
    except IRStoreError:
        return None


# ---------------------------------------------------------------------------
# Outline
# ---------------------------------------------------------------------------


def outline_view(roots: Roots, run_id: str) -> dict[str, Any]:
    """GATE 1 as data: the outline, the brief's messages, and `review_outline`'s findings."""
    from autodeck.audit.gate1 import review_outline

    orch = _open(roots, run_id)
    record = orch.state.stages.get("outline")
    recorded = record.ir_version if record is not None else None
    if recorded is not None and not orch.ir.version_path(recorded).exists():
        recorded = None
    if recorded is None and orch.ir.latest_version() is None:
        raise UIError("This run has no outline yet.", status=409)
    deck = _load_deck(orch, recorded)

    brief = _load_brief(orch)
    if brief is None:
        raise UIError("This run has no brief to review the outline against.", status=409)
    try:
        report = review_outline(deck, brief)
    except ValueError as exc:
        raise UIError(str(exc), status=409) from None

    return {
        "version": deck.version,
        "approval": _approval(orch, Gate.OUTLINE),
        "slides": [
            {
                "id": slide.id,
                "n": n,
                "role": slide.narrative_role,
                "component": slide.component,
                "message_ids": list(slide.message_ids),
                "intent": slide.intent or "",
            }
            for n, slide in enumerate(deck.slides, start=1)
        ],
        "messages": {message.id: message.text for message in brief.key_messages},
        "checks_pass": report.mechanical_checks_pass,
        "findings": [
            {"severity": f.severity, "label": f.check, "text": f.detail}
            for f in [*report.blocking, *report.advisory]
        ],
        # The outline agent's notes and corrections are printed by `autodeck outline` and
        # never saved, so there is nothing to read back for an outline built earlier.
        "notes": "",
        "corrections": [],
    }


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def claims_view(roots: Roots, run_id: str) -> dict[str, Any]:
    """GATE 2 as data: every claim with its citations, the six criteria, risks, send-backs."""
    from autodeck.audit.gate2 import gate2_checks
    from autodeck.audit.report import build_audit_report, render
    from autodeck.pipeline.orchestrator import assess_render_safety
    from autodeck.pipeline.send_back import SendBackError, load_send_backs

    orch = _open(roots, run_id)
    if not orch.state.is_complete("validate"):
        raise UIError("The claims have not been validated yet.", status=409)
    deck = _load_deck(orch)
    brief = _load_brief(orch)

    safety = assess_render_safety(deck)
    report = build_audit_report(
        deck, brief=brief, numeric=safety.numeric, framing=safety.framing
    )
    # A6, as `gate2` does it: the file on disk is the report for the latest IR.
    orch.paths.audit_report.write_text(render(report) + "\n", encoding="utf-8")

    slides = {slide.id: (n, slide) for n, slide in enumerate(deck.slides, start=1)}
    claims = []
    for row in report.claim_rows():
        n, slide = slides.get(row.slide_id, (0, None))
        claims.append(
            {
                "id": f"{row.slide_id}:{row.block_id}",
                "slide_id": row.slide_id,
                "block_id": row.block_id,
                "slide_n": n,
                "role": slide.narrative_role if slide else "",
                "component": slide.component if slide else "",
                "intent": (slide.intent or "") if slide else "",
                "text": row.claim_text,
                "verdict": row.verdict,
                "blocking": row.blocks_render,
                "citations": [
                    {
                        "doc_id": c.doc_id,
                        "page": c.page,
                        "quote": c.quote,
                        "sha256": c.quote_sha256,
                        "retrieved_by": c.retrieved_by,
                    }
                    for c in row.citations
                ],
                "notes": row.notes,
                "contradicting": [
                    {"doc_id": c.doc_id, "page": c.page, "quote": c.quote}
                    for c in row.contradicting_spans
                ],
            }
        )

    try:
        recorded = load_send_backs(orch.paths.root)
    except SendBackError as exc:
        raise UIError(str(exc), status=409) from None

    return {
        "version": deck.version,
        "approval": _approval(orch, Gate.CLAIMS),
        "claims": claims,
        "checks": [
            {"label": label, "passed": passed, "detail": detail}
            for label, passed, detail in gate2_checks(brief, safety, report)
        ],
        "risks": [
            {
                "message_id": row.risk.message_id,
                "text": row.risk.description,
                "accepted_by": row.risk.accepted_by,
                "slide_ids": list(row.slides),
            }
            for row in report.risks
        ],
        "send_backs": [
            {
                "claim_id": r.claim_id,
                "ir_version": r.ir_version,
                "reason": r.reason,
                "by": r.by,
                "at": r.at,
            }
            for r in recorded
        ],
    }


def send_back(
    roots: Roots, run_id: str, items: list[dict[str, Any]], by: str
) -> dict[str, Any]:
    """Reject named claims of the latest IR, exactly as `autodeck send-back` does.

    A rejection, never an approval. The caller offers "Rewrite" (the content stage) after.
    """
    from autodeck.pipeline.send_back import (
        EmptyReasonError,
        UnknownClaimError,
        append_send_backs,
        build_send_backs,
    )

    if not isinstance(items, list) or not items:
        raise UIError("Pick at least one claim to send back.")
    pairs: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            raise UIError("Each item needs a claim_id and a reason.")
        claim_id, reason = item.get("claim_id"), item.get("reason")
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise UIError("Each item needs a claim_id.")
        if not isinstance(reason, str):
            raise UIError(f"Say why claim {claim_id!r} is sent back.")
        pairs.append((claim_id.strip(), reason))
    by = by.strip() if isinstance(by, str) else ""
    if not by:
        raise UIError("Who is sending these back? Set your name in Settings.")

    orch = _open(roots, run_id)
    deck = _load_deck(orch)
    at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        records = build_send_backs(deck, pairs, by=by, at=at)
    except EmptyReasonError as exc:
        raise UIError(
            f"Say why claim {exc.claim_id!r} is sent back; a blank reason teaches the writer "
            "nothing."
        ) from None
    except UnknownClaimError as exc:
        raise UIError(
            f"Unknown claim id(s): {', '.join(exc.claim_ids)}. Claim ids change across "
            "content passes; reload the claims.",
            status=409,
        ) from None

    path = append_send_backs(orch.paths.root, records)
    return {"sent": [r.claim_id for r in records], "path": str(path)}


# ---------------------------------------------------------------------------
# Final deck
# ---------------------------------------------------------------------------


def _preview_images(orch: Orchestrator) -> dict[int, Path]:
    folder = orch.paths.root.joinpath(*PREVIEW_DIR)
    found: dict[int, Path] = {}
    if not folder.is_dir():
        return found
    for path in folder.iterdir():
        match = PREVIEW_NAME.fullmatch(path.name)
        if match and path.is_file() and not path.is_symlink():
            found[int(match.group(1))] = path
    return found


def _final_assessment(roots: Roots, orch: Orchestrator, deck: Deck, brief: DeckBrief | None):  # type: ignore[no-untyped-def]
    """`gate3`'s assessment, recomputed from the files on disk (pure reads, no model)."""
    from autodeck.audit.gate3 import assess_final
    from autodeck.design.headers.prompt import resolve_profile
    from autodeck.design.theme.tokens import DesignTokens
    from autodeck.knowledge.context_assembler import ContextAssembler

    theme = Path(deck.theme_ref)
    tokens = DesignTokens.load(theme if theme.is_file() else roots.tokens)
    try:
        context = ContextAssembler(
            roots.knowledge, client=deck.client, project=deck.project
        ).assemble()
        header_profile = context.header_profile
    except Exception:
        header_profile = None
    profile = resolve_profile(header_profile, brief.header_style if brief else None)
    return assess_final(deck, orch.paths.deck_pptx, tokens=tokens, brief=brief, profile=profile)


def final_view(roots: Roots, run_id: str) -> dict[str, Any]:
    """GATE 3 as data: the rendered deck, the final audit, the five human checks, previews."""
    from autodeck.audit.gate3 import (
        HUMAN_CHECKS,
        _post_render_lines,
        _qa_line,
    )
    from autodeck.audit.manifest import canonical_pptx_digest

    orch = _open(roots, run_id)
    paths = orch.paths
    if not orch.state.is_complete("render") or not paths.deck_pptx.exists():
        raise UIError("This run has no rendered deck yet.", status=409)
    deck = _load_deck(orch)
    brief = _load_brief(orch)
    recorded = orch.state.final_assessment

    digest = canonical_pptx_digest(paths.deck_pptx)
    passes = False
    criteria: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    header_flow: list[dict[str, Any]] = []
    header_notes: list[str] = []

    if not recorded:
        criteria.append(
            {
                "label": "Final audit",
                "passed": False,
                "detail": "Final audit not run yet. Run the final audit (gate3) on this deck.",
            }
        )
    else:
        try:
            assessment = _final_assessment(roots, orch, deck, brief)
        except Exception as exc:
            failed = recorded.get("failed") or []
            passes = bool(recorded.get("passes"))
            criteria.append(
                {
                    "label": "Final audit",
                    "passed": passes,
                    "detail": (
                        f"Could not recompute the audit ({exc}). Last recorded result: "
                        + (
                            "passed."
                            if passes
                            else f"failed: {', '.join(failed) or 'unknown'}."
                        )
                    ),
                }
            )
        else:
            digest = assessment.deck_digest
            passes = assessment.passes
            criteria = [
                {"label": label, "passed": ok, "detail": detail}
                for label, ok, detail in assessment.checkable()
            ]
            for line in _post_render_lines(assessment.post_render, advisory=True):
                findings.append({"section": "Post-render audit", "text": line})
            for qa in assessment.qa:
                findings.append({"section": "Deterministic QA", "text": _qa_line(qa)})
            for grammar_finding in assessment.grammar:
                findings.append({"section": "Grammar", "text": str(grammar_finding)})
            header_flow = [
                {"slide_id": line.slide_id, "n": n, "text": line.text, "kind": line.kind}
                for n, line in enumerate(assessment.flow.lines, start=1)
            ]
            header_notes = [f"{f.slide_id}: {f.detail}" for f in assessment.flow.findings]
            if recorded.get("digest") != digest:
                passes = False
                criteria.append(
                    {
                        "label": "Final audit is current",
                        "passed": False,
                        "detail": "The deck changed after the last final audit. Run it again.",
                    }
                )

    slide_ids = {n: slide.id for n, slide in enumerate(deck.slides, start=1)}
    previews = [
        {
            "n": n,
            "slide_id": slide_ids.get(n, ""),
            "url": f"/api/runs/{run_id}/preview/{n}",
        }
        for n in sorted(_preview_images(orch))
    ]

    return {
        "deck_path": str(paths.deck_pptx),
        "digest": digest,
        "passes": passes,
        "approval": _approval(orch, Gate.FINAL_RENDER),
        "criteria": criteria,
        "findings": findings,
        "header_flow": header_flow,
        "header_notes": header_notes,
        "human_checks": [
            {"n": n, "title": title, "steps": steps}
            for n, (title, steps) in enumerate(
                zip(HUMAN_CHECKS, HUMAN_CHECK_STEPS, strict=True), start=1
            )
        ],
        "previews": previews,
        # The aesthetic critic's score is printed by `autodeck render` and never saved.
        "critique": {"score": None, "looks": None},
    }


def preview_file(roots: Roots, run_id: str, n: int) -> tuple[bytes, str]:
    """One slide's PNG from `runs/<id>/previews/final/`. Only an int picks the file."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise UIError("Slide number must be a whole number from 1.", status=404)
    orch = _open(roots, run_id)
    path = _preview_images(orch).get(n)
    if path is None:
        raise UIError(f"No preview for slide {n}.", status=404)
    try:
        return path.read_bytes(), "image/png"
    except OSError:
        raise UIError(f"No preview for slide {n}.", status=404) from None


# ---------------------------------------------------------------------------
# Open a copy in PowerPoint
# ---------------------------------------------------------------------------


def _open_with_os(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined,unused-ignore]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_deck_copy(roots: Roots, run_id: str) -> dict[str, str]:
    """Copy `deck.pptx` to the Desktop (or home) and open the copy with the OS default app.

    A copy, so the file the final approval fingerprints is never the one PowerPoint holds
    open and may re-save while the owner does the five checks.
    """
    orch = _open(roots, run_id)
    if not orch.paths.deck_pptx.exists():
        raise UIError("This run has no rendered deck yet.", status=409)
    home = Path.home()
    target_dir = home / "Desktop" if (home / "Desktop").is_dir() else home
    target = target_dir / f"{run_id}-check.pptx"
    try:
        shutil.copyfile(orch.paths.deck_pptx, target)
        _open_with_os(target)
    except OSError as exc:
        raise UIError(f"Could not open a copy of the deck: {exc}", status=500) from None
    return {"path": str(target)}
