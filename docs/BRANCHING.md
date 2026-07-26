# Branching, gates, and PR protocol

## Topology

```
main                                  ← frozen at v1, never receives v2 work
 └── v2/integration                    ← v2 integration branch (long-lived)
      ├── v2/phase-0-foundations        → PR → GATE 0   go/no-go on render strategy
      ├── v2/phase-1-ingest-knowledge   → PR → GATE 1a  citation spot-check
      ├── v2/phase-2a-plan-outline      → PR → GATE 1   outline vs brief
      ├── v2/phase-2b-content-validate  → PR → GATE 2   claims table
      ├── v2/phase-3a-design-system     → PR → (internal review, no owner gate)
      ├── v2/phase-3b-render-qa         → PR → GATE 3   final render
      ├── v2/phase-4-workflow           → PR → GATE 4   real consulting deck
      └── v2/phase-5-evals-hardening    → PR
```

The branch advances only when a phase branch merges after a human gate — nothing builds
from it on a schedule, and B10 (local dev only) means there is no CI that could.

## Rules

1. A phase branch is cut from **the current tip of the integration branch** — never from
   `main`, never from a sibling phase branch.
2. Merge via PR with `--no-ff`, so each phase is one revertible merge commit.
3. **Nothing merges until its gate is approved by the owner in writing.** Per plan §0.3,
   the implementing agent does not self-approve. Gate approval is recorded in the phase
   handover and appended to `DECISIONS.md`.
4. Push authorisation covers the integration branch and `v2/*` only. Anything else needs
   explicit permission.
5. `legacy/v1/` is frozen. No commit on any phase branch may modify it except to correct
   `LEGACY.md`.

## The two kinds of gate — do not conflate

| | Build-time GATEs | Runtime approvals (A7) |
|---|---|---|
| **What** | GATE 0, 1a, 1, 2, 3, 4 | Four per deck: planning brief, outline, claims table, final render |
| **Who** | Owner reviews a phase PR | Owner reviews a deck being built |
| **Gates what** | Whether the *build* proceeds to the next phase | Whether a *deck* proceeds to the next stage |
| **Lives in** | This file, `docs/phases/*` | `autodeck/pipeline/orchestrator.py`, `docs/INVARIANTS.md` A7 |

GATE 1 and GATE 2 exist in both columns with the same names because the phase that builds
a runtime approval is gated on demonstrating it. That is intentional, and it is the only
overlap.

## GATE 0 is the important one

Plan §7 marks GATE 0 *"the go/no-go for the whole rendering strategy."* Three Phase 0
spikes must land before it, and if the native design spike fails, D5 is in question and
**the whole architecture needs re-planning before Phase 3** — not a workaround. Escalate
rather than improvise. The same is true, more narrowly, for the icon spike and D11.

## PR conventions

**Title:** `Phase <N> — <name>` (e.g. `Phase 2b — content, linters, validation`).

**Body:** the phase handover document, inline. It is the review surface; the owner should
not need to open another file to review a gate.

**Merge:** merge commit, never squash — phase branch commit granularity is part of the
audit trail.

**Before opening a PR:**
- Every task in the phase brief is done or explicitly listed as deferred with its new home.
- `docs/handovers/PHASE-<N>.md` is written and `docs/handovers/README.md` indexes it.
- `STATUS.md` is updated in the same commit as the handover.
- The invariant coverage table in `docs/INVARIANTS.md` is updated.
- Any decision made under plan §0.6 is in `DECISIONS.md`.
- Lint, types, and tests pass.

## Commit conventions

Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`),
matching v1's existing history. Two additional rules:

- A commit that touches an accuracy invariant names it: `feat(A2): re-execute derivation
  formulas in numeric linter`.
- Per plan §0.5, a prompt change under `prompts/` is **its own commit with rationale in
  the body** — never bundled with code.

## Resuming after a context reset

Read in this order:

1. `README.md` — durable context: what this is, D1–D13, A1–A8, architecture.
2. `STATUS.md` — where the build actually is right now.
3. `docs/handovers/PHASE-<latest>.md` — what the last phase left behind.
4. `docs/phases/PHASE-<current>.md` — the task list to execute.

If those four do not let you start work, the handover was inadequate — fix the template
rather than working around it.
