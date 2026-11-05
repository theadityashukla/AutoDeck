# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Phase 4 — consulting workflow: **code complete, GATE 4 open** (`docs/handovers/PHASE-4.md`) |
| **Integration branch** | `v2/integration` — carries Phases 2a–3d, 4a/4b/4c, agent memory and meeting steps 1–12 (`AGENT-MEETING-1.md`) |
| **Active phase branch** | `v2/phase-4-workflow` (cut from `v2/integration` at `1b5e38c`) |
| **Last gate passed** | **GATE 1** — approved 2026-09-18 (DECISIONS.md G1) |
| **Gates pending** | **GATE 3c** (draft-first; replaces GATE 2/3, B46) — never approved in writing. **GATE 4** — the owner runs a real consulting deck. Phase 4 was built before GATE 3c at the owner's instruction (B84); nothing merges until both are approved |
| **Latest handovers** | `docs/handovers/PHASE-4.md`, `docs/handovers/AGENT-MEETING-1.md` |
| **Suite** | 2434 passed, 4 skipped, 52 deselected (`uv run pytest -q -m 'not live and not render'`); one font test fails only in containers without Inter Display bold |
| **Updated** | 2026-11-05 |

## What exists now

- **Draft-first decks** from one prompt (clarify → draft → validate → preview → revise), one-shot
  by default on dev-mistral, an agent session with `--agent` (B71–B77), and `autodeck build`
  for the whole flow with the four approvals typed by a person (task 4.4).
- **Two provenance modes.** Strict (MLR): exact quotes and figures, the audit report reviewed
  and written as a PDF. Normal (everyday): grounded but not copied — quotes point, figures may
  be rounded, the writer uses its own words, the audit report is a log (B84, B86).
- **Meetings**: local transcription, the transcript as a citable source, meeting-only runs,
  notes written by an agent, a deck from the same session, and the meeting UI (B78–B83).
- **Clients**: `autodeck onboard` from a brand folder, the client's own theme in builds,
  reference-deck profiles, `--like` a past deck, catalog gaps, knowledge updates proposed as
  a diff (tasks 4.1–4.3, 4.7, 4.8).
- **A4 proven across full two-client builds**; its first run found and closed eight leaks (B85).

## Next action

1. **Owner:** approve GATE 3c, or say what blocks it.
2. **A session with `MISTRAL_API_KEY`:** the pending live checks — meeting steps 9–11 on the
   test clip (`AGENT-MEETING-1.md` §9) and B86's normal-mode behaviour on a real draft.
3. **Owner, on their Mac:** meeting step 13 with the real recording, through the UI.
4. **Owner:** GATE 4 — onboard a real client, `autodeck build` a real deck for actual use,
   `autodeck knowledge propose` after it.

Earlier status history (Phases 2b–3d) is in `git log -- STATUS.md` and the phase handovers.
