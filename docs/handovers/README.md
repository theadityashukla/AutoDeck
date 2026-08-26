# Phase handovers

One document per completed phase, written at the end of that phase and carried in its
PR body. Newest first.

`README.md` (durable context) + the latest handover (current state) = the full picture.
That pairing is the design; if it stops being true, fix `TEMPLATE.md`.

| Phase | Branch | Handover | Gate | Status |
|---|---|---|---|---|
| 5 — Evals & hardening | `v2/phase-5-evals-hardening` | — | — | not started |
| 4 — Consulting workflow | `v2/phase-4-workflow` | — | GATE 4 | not started |
| 3b — Renderer & QA | `v2/phase-3b-render-qa` | — | GATE 3 | not started |
| 3a — Design system | `v2/phase-3a-design-system` | — | internal | not started |
| 2b — Content & validation | `v2/phase-2b-content-validate` | — | GATE 2 | not started |
| 2a — Planning & outline | `v2/phase-2a-plan-outline` | [PHASE-2A.md](PHASE-2A.md) | GATE 1 | **code complete — gate open** |
| 1 — Ingestion & knowledge | `v2/phase-1-ingest-knowledge` | [PHASE-1.md](PHASE-1.md) | GATE 1a | **merged — gate approved** |
| 0 — Foundations | `v2/phase-0-foundations` | [PHASE-0.md](PHASE-0.md) | GATE 0 | **code complete — gate open** |

Fill the **Handover** column with a link (`PHASE-0.md`) as each phase closes, and update
`STATUS.md` in the same commit.

## Writing a handover

1. Copy `TEMPLATE.md` to `PHASE-<N>.md`.
2. Fill every section — "none" beats a deleted heading.
3. Update the row above and `STATUS.md`.
4. Update the coverage tracker in `docs/INVARIANTS.md`.
5. Paste the whole thing into the PR body.

Section 6 (spike findings, **including negative results**) and section 11 (reading notes)
are the two that repay the effort. Tables can be reconstructed from the diff; those two
cannot.
