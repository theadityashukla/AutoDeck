# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Scaffold complete — Phase 0 not started |
| **Integration branch** | `v2/integration` |
| **Active phase branch** | none yet |
| **Last gate passed** | none |
| **Next gate** | GATE 0 — go/no-go on the whole rendering strategy |
| **Latest handover** | none — `docs/handovers/` is empty by design |
| **Updated** | 2026-07-26 |

## Next action

Cut `v2/phase-0-foundations` from the integration branch tip and work
`docs/phases/PHASE-0.md`.

**Not blocked** — both Phase 0 questions are answered:

- **Q1 — deployment target:** local dev only; containers deferred to v3 (B10). Task 0.1
  ships no Dockerfile, and CI does not run the LibreOffice render path.
- **Q3 — brand fonts:** Aptos Display / Aptos (B11). Spike 0.4 must settle four things
  before Phase 2b's budgets can be trusted — see the Aptos checks in the Phase 0 brief.
  The one most likely to be skipped: **headless LibreOffice needs Aptos installed**, or
  preview renders come back in a substituted face and the design loop is judging a lie.

**Next question needed: Q2** — which project and client seed the build, real or
anonymised? Answer before Phase 1 is cut.

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
