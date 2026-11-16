# Status

**One screen: where things are right now.** Written 2026-11-16. If this file disagrees with
your memory, this file is right; if it disagrees with the repository, say so and fix it.

| | |
|---|---|
| **State** | **Development is paused** (owner's instruction, end of the session of 2026-11-15). Nothing is in progress. |
| **Direction** | v3, the conversational studio in `autodeck/studio/`. v2 (the strict pipeline) is complete as far as it goes and is the only route to traceable decks. |
| **Branch** | `claude/autodeck-principles-review-zp7nsm`, built on `v2/integration` (merge base `1b5e38c`). The plan recommended `v3/integration`; that was not possible in the session that did the work, so the owner may want to rename or rebase. |
| **Last verified** | 2026-11-16 (tests below); the layered flow in one real-model run on 2026-11-15 |
| **Start reading** | `README.md`, `docs/handovers/V3-STUDIO.md`, `docs/AUTODECK_V3_PLAN.md` |

## v3 phases

| Phase | What | Status | Verified |
|---|---|---|---|
| Mock-up | Clickable, scripted, no engine (`mockups/v3/`) | Done, accepted as the direction | The owner used it |
| 0 Foundations | Engagement, plain deck model, change log with exact undo and redo, rendering through v2's renderer | **Done** (2026-11-13) | Scripted; Phase 0 exit test |
| 1 Conversation core | Threads from state, loop with tools, web interface, proposals | **Done** (2026-11-13), fixes after a real run (2026-11-14) | Scripted and browser walkthrough; one real-model run (`gpt-5.4-mini`) |
| Slide bench | One-slide design tests (added at the owner's suggestion) | **Done**, 2026-11-14 and 2026-11-15 | Real models; results in `bench/slides/results/README.md` |
| 2 and 3 (merged) | Layers, routing, design system, staleness, recomposition, cost record | **Done** (2026-11-15) | Scripted and browser walkthrough; one real-model run on `dev-openai` |
| After the run | Close-out fixes; studio layout rules; reviewer prompt and bench support | **Done** | Rules measured on 34 designed slides; reviewer tested twice on the bench |
| Reviewer as a layer | | **Not built** | |
| 4 State and refinement | Selection as scope, propose-first, export confirmation, several threads, undo from the middle | **Not built** (staleness and recomposition were pulled forward into Phases 2 and 3) | |
| 5 Notes and sources | Meeting notes on the new core, source notes, fact-check tool | **Not built** | |
| 6 Strict overlay | Annotations, audit, gates, manifest over the base | **Not built** | |
| 7 Routing benchmark | | **Not built** | |
| Vocabulary phase | Styled charts, curves and diagonals, emphasis in a line of text, more fonts, a proper fix for the base theme colours | **Not built** (not in the original plan) | |

## Test results observed on 2026-11-16

| Command | Result |
|---|---|
| `uv run pytest -q -p no:cacheprovider tests/studio` | 564 passed, 8 deselected |
| `... -m render tests/studio` | 8 passed |
| `... bench/slides/tests` | 70 passed, 1 deselected |
| `... ` (full default suite) | 2696 passed, 1 failed, 6 skipped, 60 deselected |

The one failure, `tests/test_design.py::test_a_missing_face_is_as_loud_as_a_missing_family`,
predates v3 and is an environment font issue. 2696 minus the 564 studio tests is v2's 2132,
unchanged since before v3 began: no v2 file was edited by the v3 work (stated in each phase
document and consistent with these counts; not re-checked file by file for this document).
Ruff and pyright were reported clean on the studio code in each phase's verification; not
re-run for this document.

## What was last verified, and how

- **On scripted models:** the whole flow, including a browser walkthrough on the real server
  (briefs, composition, design proposal with samples, pick, stale, recompose, a new thread's
  recap, a rule-routed retitle). Re-checked on 2026-11-16 over the HTTP API with
  `tests/studio/fixtures/scripts/design_flow.json`: each step behaved as `docs/STUDIO-GUIDE.md`
  says.
- **In one real-model run (2026-11-15, `dev-openai`):** the layered flow ran end to end with no
  API, adapter or schema error. Four slides designed, four of four clean (three to four
  attempts each); recomposition after picking a design, four of four clean; a rule-routed
  retitle and a model-routed swap both done by the mechanic. Estimated cost $8.69 over seven
  turns.
- **Not run:** any Anthropic model (`sit` and `prod` are untested against a live API);
  `dev-mistral` with the studio; any real client engagement; any deck over a larger knowledge
  folder than the seed pair.
- **All costs are estimates** from assumed, deliberately high prices that were never confirmed
  (`config/studio_prices.yaml`, `bench/slides/prices.yaml`). The session limit was 50 US
  dollars; the running estimate at the end was about 39.50.

## What is next

Nothing is scheduled. In the order I would take it (the plan and the phase documents have the
detail; the owner decides):

1. Use the studio on a real engagement, on `dev-openai`, and write down what feels wrong.
2. Trim the lead's per-call context (about 14k tokens resent on every call).
3. The reviewer as a product layer, as an optional extra pass.
4. A vocabulary phase, so designed slides stop being limited by the drawing primitives.
5. Phase 4, then 5 and 6 as the strict group needs them; Phase 7 once there is enough change log
   data to judge the bindings.

## Known open problems

| Problem | Where it is recorded |
|---|---|
| The reviewer's recall on composition flaws (uneven, scattered or crowded layouts) is weak, and it is not in the product | `bench/slides/results/README.md`, V19 |
| The lead resends about 14k tokens per call; a one-line question cost about $0.17 (estimated) | `V3-PHASE-2-3.md`, defect 4 |
| Design proposals are the most expensive action (about $3.63 estimated in the real run, before the two-direction default, which was not re-measured) | `V3-PHASE-2-3.md`, defect list and fixes |
| Layout rules cannot catch detached labels, crowding or tight clearance; the text half of the `straddle` rule rests on synthetic tests only | `V3-PHASE-2-3.md`, "Studio layout rules" |
| The studio depends on private v2 names (`ir.store._diff`, `render.renderer._BLANK_LAYOUT`, `SLIDE_TAG_PREFIX`) | `V3-PHASE-0.md`, risks |
| Several client-isolation symlink cases are untested (a workspace client folder that is a symlink; a project folder symlinked into another client; listings that follow symlinks); v2's own guard may share the gap, not verified | `V3-PHASE-0.md`, carried items |
| The store assumes a single process; there is no crash repair | `V3-PHASE-0.md`, `V3-PHASE-1.md` |
| Undo of one change from the middle of the history is not built | `V3-PHASE-0.md` |
| A turn that fails before it starts is only printed on the server; the interface is not told | `V3-PHASE-1.md`, carried forward |
| A failed preview (LibreOffice missing) is stored and not retried until the deck changes | `V3-PHASE-1.md`, carried forward |
| Two base theme colours (`dk1`, `lt1`) are emitted by v2's theme writer as system colours; the studio patches its own copy | `V3-PHASE-2-3.md`, V14 |
| A base v3 deck has no traceability, by decision | V8 |
| v2's one failing test, `test_a_missing_face_is_as_loud_as_a_missing_family` (fonts in this environment) | above |

## v2: the state it was left in

Taken from `DECISIONS.md`, `docs/handovers/AGENT-MEETING-1.md` (the latest v2 handover) and the
code. The last v2 commit is `1b5e38c` (2026-11-05, B83, the meeting UI).

- **Gates:** GATE 0, GATE 1a and GATE 1 are approved (`DECISIONS.md` G0, G1a, G1). GATE 2
  (claims table) and GATE 3 (finished deck, with five checks to make in PowerPoint) are open;
  the owner's decisions waiting at them are in `docs/handovers/STATUS-V2-2026-10-03.md`.
- **Built:** Phases 0 to 3b merged to `v2/integration` (B39); the review UI (B40, B42); the
  draft-first build and redesign of an existing deck (3c and 3d, B43 to B52); deck craft and
  skills, providers, free layout (B53 to B70); the deck agent session, advisor, transcript and
  resume (B71 to B76); memory (B77); local meeting transcription, the transcript as a citable
  source, notes written by an agent, the meeting deck, and the meeting UI (B78 to B83, meeting
  plan steps 1 to 12 of 13).
- **Not done, as far as the repository shows:** meeting plan step 13 (a live check on the real
  recording, which is on the owner's Mac); the live check of step 9 on the test clip; v2's
  roadmap Phases 4 and 5 (consulting workflow, evals and hardening); a Claude run of the deck
  agent. **I could not confirm whether any of these happened off the repository after
  2026-11-05**; no later v2 commit or document records them.
- **Never confirmed:** the PowerPoint-only GATE 3 checks and the behaviour of icons and theme in
  real PowerPoint (no PowerPoint in the build environment); the Claude adapter against a live
  API.
- **Known failure:** the one test above. The v2 suite is otherwise 2132 passed in the same run.
- **Old status document:** `docs/handovers/STATUS-V2-2026-10-03.md`.
