# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Scaffold complete — Phase 0 not started |
| **Integration branch** | `claude/phased-feature-branch-plan-atygas` |
| **Active phase branch** | none yet |
| **Last gate passed** | none |
| **Next gate** | GATE 0 — go/no-go on the whole rendering strategy |
| **Latest handover** | none — `docs/handovers/` is empty by design |
| **Updated** | 2026-07-26 |

## Next action

Cut `v2/phase-0-foundations` from the integration branch tip and work
`docs/phases/PHASE-0.md`.

**Blocked on two owner answers** (from plan §11, tracked in the Phase 0 brief):

- **Q1 — deployment target.** Local dev only, or containerised for a small team?
  Determines CI and packaging in task 0.1.
- **Q3 — brand fonts.** Available and licensed for the seed client, or design against a
  safe default and swap later? Determines what the font spike (0.4) measures.

Phase 0 can start without them; it cannot close GATE 0 without them.

## Invariant coverage

All of A1–A8 are `not-started`. See the tracker in `docs/INVARIANTS.md`.

The first to land is **A1**, structurally, in Phase 0 task 0.2 — the IR schema makes a
`claim` block with zero citations fail validation.

## Phase progress

| Phase | Branch | Gate | Status |
|---|---|---|---|
| 0 — Foundations | `v2/phase-0-foundations` | GATE 0 | not started |
| 1 — Ingestion & knowledge | `v2/phase-1-ingest-knowledge` | GATE 1a | not started |
| 2a — Planning & outline | `v2/phase-2a-plan-outline` | GATE 1 | not started |
| 2b — Content & validation | `v2/phase-2b-content-validate` | GATE 2 | not started |
| 3a — Design system | `v2/phase-3a-design-system` | internal | not started |
| 3b — Renderer & QA | `v2/phase-3b-render-qa` | GATE 3 | not started |
| 4 — Consulting workflow | `v2/phase-4-workflow` | GATE 4 | not started |
| 5 — Evals & hardening | `v2/phase-5-evals-hardening` | — | not started |

## What exists today

Planning scaffold only — **no v2 package code yet.** The repo currently holds:

- Governance docs (`README.md`, this file, `DECISIONS.md`, `docs/`).
- The vendored spec (`docs/AUTODECK_V2_PLAN.md`) and slide-geometry reference.
- Frozen v1 under `legacy/v1/` with a salvage map.
