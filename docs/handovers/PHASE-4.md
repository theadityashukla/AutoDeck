# Phase 4 — Consulting workflow — Handover

> Written 2026-11-05 in the remote session. Read `README.md`, `docs/phases/PHASE-4.md`, then
> this, then `DECISIONS.md` B84–B86.

---

## 1. Identification

| | |
|---|---|
| **Phase** | 4 — Consulting workflow |
| **Branch** | `v2/phase-4-workflow`, cut from `v2/integration` at `1b5e38c` (meeting steps 9–12 included) |
| **PR** | none yet |
| **Started / completed** | 2026-11-05 → 2026-11-05 (code complete; gate open) |
| **Gate** | GATE 4 — the owner runs a real consulting deck through the system for actual use |
| **Gate status** | pending. Its precondition, GATE 3c, is also unapproved (B84) |
| **Approved by / when** | — |
| **What the owner actually checked** | Nothing in this phase yet. The owner answered three questions in it: proceed on the branch before GATE 3c; all eight tasks; Q4 — the audit report is internal and reviewed only for strict decks. During the phase they also asked for normal mode to be "grounded, but not a copy-paste job" (B86) and chose "any reasonable rounding" and normal-style meeting notes. |

## 2. What shipped

| Task | Path | What it does | Tests |
|---|---|---|---|
| 4.5 Multi-client regression (Opus design) | `tests/test_multi_client_regression.py`, `tests/two_clients.py` | Canaries on every client surface; recording providers on every model role; one-shot, agent and meeting builds for two clients; scans of every request, written file, pptx text and stdout; crafted names, caches, UI memory routes, assembler errors. **Found eight leaks, fixed in B85** | 162 |
| (B85 fixes) | `autodeck/pipeline/planning.py` (`require_run_binding`), `autodeck/knowledge/loader.py` (`_contained`), `autodeck/cli.py` | A run is bound to the client and project its own files record; knowledge files may not resolve outside their folder | in the 162 |
| 4.2 Reference decks | `autodeck/ingest/deck_ingest.py`, `autodeck/design/reference/` (`profiles.py`, `service.py`), loader `reference_profile`, `autodeck reference ingest\|show` | `ReferenceDeck` (not a `Document`; no path makes it one), Storyline / derived HeaderStyle / Voice / Design profiles, client aggregate, deterministic, behind the namespace guard | `tests/test_reference_decks.py`, `tests/test_reference_cli.py` (29) |
| 4.8 Catalog gaps | `autodeck/design/reference/gaps.py`, `autodeck reference gaps` | Layouts the catalog matches below 0.5 confidence, clustered by signature, ranked | in the 29 |
| 4.1 Onboarding | `autodeck/design/onboard.py`, `autodeck onboard`, `autodeck/design/theme/resolve.py` | Brand folder → client namespace: theme (mode a with fallback to supplied tokens), fonts and fsType licence flag, icons, past decks ingested, stubs marked TODO, `headers.proposed.yaml`; **builds now use the client's own `theme/tokens.json`** (a gap the regression found) | `tests/test_onboard.py` (42) |
| 4.3 `--like` | `autodeck/design/reference/like.py`, `prompts/reference_like.md`, compose/agent/cli | A past deck's profile snapshotted to `runs/<run>/like.json` (hashed, A6) and shown to clarify, compose, revise and the agent as shape and voice only; never in a pack or citable set (A1) | `tests/test_like.py` (14) |
| 4.4 `build` | `autodeck build` in `cli.py` | Clarify → typed answers → draft → validate → preview → four approvals (brief, outline, claims after gate2, final after render and gate3), each typed `approve`, recorded through `ui.approvals.approve_gate` (the single route). No skip flag, no environment override; without a terminal it stops at the first approval with the `autodeck approve` command. Resumable | `tests/test_build.py` (18) |
| 4.7 Update proposer | `autodeck/knowledge/update_proposer.py`, `autodeck knowledge propose\|apply` | A run's durable learnings as a git-style diff (claims.md additions from supported single-source corpus claims only; engagement note; kept headlines as `headers.proposed.yaml`; Terms/People without figures in client.md). Never writes `knowledge/`; `apply --yes-i-reviewed-this` only into the run's own client and project | `tests/test_update_proposer.py` (19) |
| 4.6 Audit PDF | `autodeck/audit/report_pdf.py`, `_strict_report_pdf` in `cli.py` | Strict decks only (B84): gate2 and gate3 write a PDF beside the Markdown report, via a minimal escaping Markdown→HTML converter and LibreOffice. Normal decks keep the Markdown log | `tests/test_report_pdf.py` (7), `tests/test_cli_gate2.py` (+1) |
| Normal mode balance (B86) | `autodeck/ingest/provenance.py`, `autodeck/agents/content.py`, `autodeck/audit/numeric_linter.py`, `framing_linter.py`, `draft_checks.py`, `validation.py`, prompts | Normal decks and meeting notes: quotes point (≥60% match resolves to the passage's exact words); figures may be rounded (same unit, ≤10%, reported); the writer is told to use its own words; the validator judges meaning and is told the mode. Strict unchanged | `tests/test_normal_mode_balance.py` (8) |

Full suite at the end of the phase: **2434 passed, 4 skipped, 52 deselected, 1 failed**
(`tests/test_design.py::test_a_missing_face_is_as_loud_as_a_missing_family`: the remote
container's Inter Display has no bold face; it fails identically on the base commit). At the
start of the phase: 2134 passed. 300 new tests.

## 3. What did not ship

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|
| GATE 4 itself | Needs the owner to run a real consulting deck for actual use | Owner |
| Two **real** client decks (milestone) | Only synthetic clients exist in the repo; the real ones are the owner's | Owner, with GATE 4 |
| Mode (a) theme extraction proven on a real corporate template (Q5) | No real template in the environment | Owner supplies one; `autodeck onboard` reports what it could not extract |
| `like.json` as a surface in the two-client harness | Did not fit the harness cheaply; equivalent A4 tests are in `tests/test_like.py` | Any regression pass |
| Diffing approved vs final IR in the update proposer | "Kept headlines" means the latest IR | Small follow-up |
| fontTools as a declared dependency | Licence check runs only when it is importable; otherwise "license not checked" | Owner decision |

## 4. Decisions made this phase

- **B84**: Phase 4 built on its branch before GATE 3c; Q4 answered (audit report reviewed only
  for strict decks; 4.6 is strict-only).
- **B85**: a run belongs to one client; knowledge files may not link out of their folder (the
  eight leaks).
- **B86**: normal mode is grounded, not copied (pointing quotes, readable rounding, natural
  words, meaning-not-wording validation, normal-style meeting notes).
- Smaller choices recorded here rather than as decisions:
  - `build` takes `--by` (not `--approver`) because the gate-bypass test bans names containing
    "approve"; the approver defaults to the profile name.
  - Without a terminal, `build` accepts the suggested clarify answers (recorded as accepted,
    never as typed, B55) and stops at the first approval. Answers are not approvals.
  - `onboard`'s `--force` is the Python parameter `merge`, for the same test.
  - Derived header profiles and kept headlines are written as `style/headers.proposed.yaml`,
    never `headers.yaml`: `HeaderStyleProfile` forbids extra fields, and a person curates it.
- **Next free id: B87.**

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | tested | tested; reference decks are structurally uncitable; normal-mode pointing still stores exact words | `test_reference_decks.py` (A1 cases), `test_like.py`, `test_normal_mode_balance.py` |
| A2 numbers | tested | tested; normal-mode rounding bounded (same unit, ≤10%, reported), strict exact | `test_normal_mode_balance.py` |
| A3 validation | tested | tested; validator told the mode, judges meaning in normal decks | `test_normal_mode_balance.py::test_the_validator_is_told_the_decks_mode` |
| A4 isolation | tested | **tested across full two-client builds**; run binding and symlink containment (B85) | `test_multi_client_regression.py` (162) |
| A5 framing | tested | unchanged (per-client framing checked non-vacuously in the regression) | `test_multi_client_regression.py` (framing reaches only its own client) |
| A6 reproducibility | tested | tested; `like.json` hashed with run sources | `test_like.py` |
| A7 gates | tested | tested; `build` cannot approve without a typed `approve`; `knowledge apply` needs an explicit review flag | `test_build.py`, `test_update_proposer.py`, `test_orchestrator.py::test_no_command_can_bypass_a_gate` |
| A8 uncertainty | tested | unchanged | — |

## 6. Spike and experiment findings

- **The regression found real leaks on its first run**, both of the kind INVARIANTS warned
  about ("not just the obvious markdown load path"): a run re-bound to another client by a
  command-line option, and symlinks read outside the namespace guard. Neither had a test
  before; both had plausible user paths (a mistyped `--client`, a client folder assembled with
  links). Coverage-first design paid for itself.
- **The existing quote "snap" was already lenient** (85% character-run coverage resolves most
  near-copies), so the copy-paste feel came mainly from the prompts, which told the writer in
  every mode to copy exactly and keep numbers exact. B86 changed both the prompts and the
  bars; the prompt change is likely the bigger effect. Not yet measured live.
- No live model call was made in this phase (no key in the environment; the budget rule).

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| B86 not measured live | Normal-mode accuracy on dev-mistral with looser pointing is unknown; the validator carries more weight | First session with `MISTRAL_API_KEY` |
| Live check of meeting steps 9–11 still pending | See `AGENT-MEETING-1.md` §9 | Same |
| GATE 3c and GATE 4 unapproved | Nothing on this branch can merge | Owner |
| Owner-memory checks are heuristics (B77) | A client fact phrased without names or figures can pass | Accepted backstop |
| `cli.py` keeps growing (~4,500 lines) and carries pre-existing E501 lines | Review and merge friction | Any cleanup pass |
| Supplied fonts are copied to `theme/fonts/` but builds read fonts from `fonts/` / `AUTODECK_FONT_DIRS` | A brand font is not used until installed or the path is set; onboarding warns | Small follow-up |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| 4.5 coverage design, B85 fixes (A4), B84–B86, all prompt edits, the numeric-linter and validation changes (A2/A3), `audit/report_pdf.py`, this handover | Opus | Opus | — |
| 4.5 implementation, 4.2 + 4.8, 4.1, 4.7, 4.3 + 4.4 | Sonnet | Sonnet (five subagents, two pairs in parallel) | — |
| 4.6 (planned Haiku) | Haiku | Opus | `audit/` is Opus-only by the owner's routing rule |
| 4.8 (planned Haiku) | Haiku | Sonnet | Folded into 4.2, same module |

## 9. Preconditions for the next phase

- The owner approves GATE 3c, then runs a real consulting deck (GATE 4): `autodeck onboard`
  the real client from its brand folder, `autodeck build` the deck, `autodeck knowledge
  propose` after it.
- `MISTRAL_API_KEY` for the pending live checks (meeting steps 9–11 and B86).
- Phase 5 (evals) should take B86's normal-mode bars as a measured target: pointing coverage
  and rounding bound are constants (`NORMAL_SNAP_MIN_COVERAGE`, `NORMAL_ROUNDING_REL_LIMIT`).

## 10. Verifying this phase from a cold start

```bash
uv sync --extra meeting --extra ui
uv run pytest -q -m 'not live and not render'
# expected: 2434 passed, 4 skipped (1 font failure only in containers without Inter Display bold)
uv run pytest -q tests/test_multi_client_regression.py
# expected: 162 passed — the A4 proof
uv run autodeck build --help        # no option named yes/approve/skip/force
uv run autodeck onboard --help
uv run autodeck reference --help
uv run autodeck knowledge propose --help
```

## 11. Reading notes for the next implementer

- **Read the regression's module docstring first**: its table is the A4 proof, surface by
  build by assertion. Any new client-scoped file needs a `Surface(...)` in
  `tests/two_clients.py` `CLIENT_SURFACES`.
- **A run's client is whatever its files say** (`planning.run_binding`). Never let an option
  override it; start a new run instead.
- **Reference decks teach style, never truth.** Nothing in `design/reference/` may produce a
  `Document`, a span or a claim; a test scans the imports.
- **Strict vs normal is now three bars** (pointing coverage, rounding, validator framing),
  all keyed on the deck's `provenance`. Strict must stay exact: it is the MLR path.
- **`build` has no flag that approves**, by design (A7). If someone asks for one, the answer
  is `autodeck approve` per gate, typed by a person.
