# Phase <N> — <name> — Handover

> Copy this file to `docs/handovers/PHASE-<N>.md` and fill every section. Sections are
> fixed so successive handovers diff cleanly. **Do not delete a section** — write
> "none" or "n/a" instead, because an empty section and a missing section mean
> different things to whoever reads this cold.
>
> This document plus `README.md` must be sufficient to pick the build up from nothing.
> That is the acceptance test for a handover. Written by Opus (see `docs/MODEL_ROUTING.md`).

---

## 1. Identification

| | |
|---|---|
| **Phase** | |
| **Branch** | `v2/phase-<n>-<name>` |
| **PR** | #<n> |
| **Started / completed** | YYYY-MM-DD → YYYY-MM-DD |
| **Gate** | GATE <n> |
| **Gate status** | pending / approved / approved with conditions |
| **Approved by / when** | |
| **What the owner actually checked** | Be specific. "Opened the spike deck in PowerPoint, confirmed the theme palette appears under Design → Variants, recoloured the icon" — not "reviewed and approved". |

## 2. What shipped

Modules, tests, CLI surface, with real paths. A reader should be able to open each one.

| Path | What it does | Tests |
|---|---|---|

## 3. What did not ship

Every task in the phase brief that is not done, and **where it went**. A deferred task
with no new home is how scope silently evaporates.

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|

## 4. Decisions made this phase

Pointers into `DECISIONS.md` — ids and one-line summaries only. Do not duplicate the prose;
the log is the record.

## 5. Invariant coverage delta

Status: `not-started` · `partial` · `enforced` (code exists) · `tested` (a test proves it).
Copy the result into the tracker in `docs/INVARIANTS.md`.

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | | | |
| A2 numbers | | | |
| A3 validation | | | |
| A4 isolation | | | |
| A5 framing | | | |
| A6 reproducibility | | | |
| A7 gates | | | |
| A8 uncertainty | | | |

## 6. Spike and experiment findings

**Including negative results — these are the most valuable thing a handover carries.**
A spike that failed, and precisely how, saves the next phase from repeating it. Record
what was tried, what happened, and what it implies for the locked decisions.

## 7. Known gaps, risks, and debt carried forward

Each item names the phase that owns it. "Someone should look at this" is not an entry.

| Item | Impact if ignored | Owned by |
|---|---|---|

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|

Note escalations (a task that needed a higher tier) and de-escalations (a pattern that
became mechanical). Systematic deviation means the phase brief's tags are wrong — say so.

## 9. Preconditions for the next phase

What must be true before the next branch is cut. Unanswered owner questions, environment
setup, credentials, data that has to exist. Be concrete enough to check off.

## 10. Verifying this phase from a cold start

Exact commands, in order, that a fresh checkout can run to confirm this phase's work.
Include expected output — a command with no expected result verifies nothing.

```bash
# e.g.
# uv sync && uv run pytest tests/phase_1 -q
# expected: 34 passed
```

## 11. Reading notes for the next implementer

Free text. The things that do not fit a table: where the surprises were, which file to
read first, what looks wrong but is deliberate, what you would do differently. This
section is usually the most-read part of the document — write it last, and write it honestly.
