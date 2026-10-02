# UI 1 — Review UI, first slice — Handover

> Written at the end of the first UI session (cloud container, 2026-10-02) so the work can
> continue on the owner's Windows PC. `README.md` + `STATUS.md` + this file are the full
> picture for the UI; the pipeline's own state is in `PHASE-3B.md` and `STATUS.md`.

---

## 1. Identification

| | |
|---|---|
| **Phase** | UI 1 — review UI over the pipeline (not a numbered plan phase; D7's deferred "thin review UI", pulled forward by B39/B40) |
| **Branch** | `v2/integration` (worked directly on it, per B39) |
| **PR** | none — commits pushed straight to `v2/integration` |
| **Commits** | `e331a42` feat(ui): review UI … (B40) · `2673fef` test(ui), docs … · this handover |
| **Started / completed** | 2026-10-02 → 2026-10-02 (first slice) |
| **Gate** | none of its own. It must not change how any gate is approved (A7, B39) |
| **Gate status** | n/a — GATE 2 and GATE 3 are still open, as `STATUS.md` says |
| **Approved by / when** | not reviewed by the owner yet |
| **What the owner actually checked** | The design mockups on the canvas (start screen, new client, redesign). The owner has **not** yet run `autodeck ui` on a real machine. |

## 2. What shipped

| Path | What it does | Tests |
|---|---|---|
| `autodeck/ui/server.py` | Stdlib `ThreadingHTTPServer` on 127.0.0.1: JSON API + static files. Refuses non-localhost `Host` (403) and non-JSON POSTs (415). Holds open planning sessions in memory (`App.sessions`). | `tests/test_ui.py` |
| `autodeck/ui/api.py` | HTTP-free functions each screen calls: clients/projects, A5 lint, create client, readiness checks, settings (model tier), run list and per-run summary (from `Orchestrator.approval_state`, the same source `status` uses). | `tests/test_ui.py` |
| `autodeck/ui/launch.py` | Opens a pywebview window; falls back to the default browser if pywebview is missing or fails. | none (needs a desktop) |
| `autodeck/ui/static/` | `index.html`, `app.css`, `app.js` — plain JS, hash routing, no build step, no downloads. Light/dark follow the OS. | screenshots only |
| `autodeck/pipeline/planning.py` | `prepare_planning()` / `PlanningContext.open_session()` — the planner setup moved out of `cli.plan` so the CLI and UI share one path (A4 index check included). | existing planner/owner-run tests |
| `autodeck/cli.py` | New `ui` command; `plan` now calls `prepare_planning`. | `test_cli_gate2.py` (ui added to the no-approval list) |
| `pyproject.toml`, `uv.lock` | Optional extra `ui = ["pywebview>=5.0"]`. | — |

API routes (all under `/api/`): `GET home`, `GET runs`, `GET runs/<id>`, `GET|POST clients`,
`POST lint/framing`, `GET|POST settings`, `POST plan/start`, `GET plan/<id>`,
`POST plan/<id>/say`, `POST plan/<id>/sign`.

Screens: Home (start planning · readiness checklist · recent runs), Runs, Run detail,
Planning (chat + live draft brief + sign), New client, Settings, Redesign (placeholder).

## 3. What did not ship

| Task | Why deferred | Now owned by |
|---|---|---|
| Outline / content / validate / render from the UI | First slice covered setup + planning only | UI 2 (next session) |
| Outline, claims and final-render approval screens | Needs a design that keeps the single approval path (see §7, first row) | UI 2 |
| Claims review screen (GATE 2) | Depends on the above | UI 2 |
| Brand / template / past-deck upload on New client | Drop zones are visual only; files go in the folder by hand | UI 2 |
| Redesign an existing deck | Pipeline cannot read a deck yet; rule recorded as B41 | a pipeline task first, then UI |
| Evidence-probe results in the planning chat | The CLI prints probe verdicts per turn; the UI shows only the reply text and draft | UI 2 |
| Native-window test on macOS / Windows | No desktop in the cloud container | owner, on the PC (§9) |

## 4. Decisions made this phase

- **B40** — Review UI: local web front end in a native window over the existing pipeline; stdlib server, pywebview optional, browser fallback; adds no approval path.
- **B41** — Redesigning an existing deck: the uploaded deck is the source document; citations labelled "client-supplied deck". Not implemented.

Owner choices from the conversation that are not separate entries: glass look but clean
and "Apple-like" (light, frosted panels, system fonts, one blue accent); dev/sit/prod lives
in Settings, not on the start screen; the UI is a full front end for everything the CLI
does, built incrementally.

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | unchanged | unchanged | — |
| A2 numbers | unchanged | unchanged | — |
| A3 validation | unchanged | unchanged | — |
| A4 isolation | tested | tested; UI adds a name check on new-client text | `tests/test_ui.py` (create_client refuses another client's name) |
| A5 framing | enforced | enforced; UI lints positioning text as typed (advisory, not blocking) | `tests/test_ui.py` (lint_framing) |
| A6 reproducibility | unchanged | unchanged | — |
| A7 gates | tested | tested, extended to the UI | `test_orchestrator.py::test_no_command_can_bypass_a_gate` (unchanged allow-list: `cli.py` 1, `agents/planner.py` 1); `test_cli_gate2.py` (`ui` added); `test_ui.py` (no `.approve(` under `autodeck/ui/`; `.sign_off(` only in `plan_sign`) |
| A8 uncertainty | unchanged | unchanged | — |

## 6. Spike and experiment findings

- **Dark glass was rejected** by the owner as "a little indie"; the light, macOS-settings-like direction was accepted. Canvas: https://claude.ai/artifact/3R4thkrRUEsTeLXJRqjXJ7 (private to the owner).
- **pywebview pulls platform packages, not runtimes**: the lock adds `pythonnet` (Windows) and `qtpy` (Linux backend); WebView2 itself ships with Windows 10/11. On Linux without a GUI the launcher falls back to the browser — confirmed by design, not run.
- **The test suite needs the Inter fonts**: on a fresh container 60 tests fail with `FontNotFoundError` until `scripts/install-dev-fonts.sh` runs. Not a UI problem; worth knowing before reading a red suite.
- **`uv sync` is heavy** (docling brings torch, ~3 GB of CUDA wheels on Linux). The UI adds only pywebview; "minimal downloads" applies to the UI, not to the pipeline's existing dependencies.

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| **Approving outline/claims/final from the UI.** The bypass test allows `.approve(` only in `cli.approve` and the planner. Calling `Orchestrator.approve` from `autodeck/ui/` would fail that test — correctly. The fix is to move the body of `cli.approve` into one shared function (e.g. `pipeline/approvals.py`) that both the CLI and UI call, and update the test's allow-list to that one place. Do not add a second call site. | A second approval path, which B39 forbids | UI 2 |
| Planning sessions live in server memory; a restart drops them. The draft and transcript are on disk, so reopening the run rebuilds the session (`App._live`), but the index rebuild is slow. | Slow first message after restart | UI 2 |
| `runs/<id>/ui.json` is the only record of a run's client/project. Runs started with `autodeck plan` in a terminal have none, so the UI cannot resume their planning (it says so and shows the CLI command). | Terminal-started runs are read-only in the UI | UI 2 (consider recording client/project in `RunState`, which is a pipeline change → needs a decision) |
| `_provider_message` imports the private `cli._provider_failure_message`. | Coupling to a private helper | UI 2 (move it to `providers/guard.py`) |
| A5 lint on New client warns but does not block. Deliberate: the build demotes such lines anyway. | none if the build-time fence holds | — |
| No auth on the local server. Mitigated by localhost binding, Host check, JSON-only POSTs and a strict CSP. | Another local user on a shared machine could use it | accepted for a single-user tool (B40) |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| UI design (canvas) and implementation | Opus (owner's instruction) | Opus | — |
| Mapping existing APIs for the UI | Haiku | Haiku | Accurate; one miscount (reported 71 tests, actual 41 cases) |
| DECISIONS B40/B41 prose | Sonnet | Sonnet | — |
| `tests/test_ui.py` + bypass-test extension | Sonnet | Sonnet | — |
| README / STATUS / CHANGELOG / OWNER-GUIDE | Haiku | Haiku, then Opus fixed placement and wrapping | Haiku put the guide subsection mid-section and left out two facts |

## 9. Preconditions for the next phase (moving to the Windows PC)

1. Install **Git**, **uv** (`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`) and Python 3.11+ (uv can install it: `uv python install 3.11`).
2. `git clone` the repo, `git checkout v2/integration`, `git pull`.
3. `uv sync --extra ui` (installs pywebview + pythonnet; WebView2 is already in Windows 10/11).
4. **Fonts.** `scripts/install-dev-fonts.sh` is bash and Linux-oriented. On Windows either run it from Git Bash, or download Inter 4.1 (OFL) and put the `.ttf` files in the repo's `fonts/` folder (the resolver searches `fonts/` first, then `C:/Windows/Fonts`). Also install them into Windows (right-click → Install for all users) so LibreOffice renders the same face. Check: `uv run autodeck fonts check --tokens config/tokens/dev.json` — every line `OK`.
5. **LibreOffice** for rendering: install it and make sure `soffice` is on `PATH` (usually `C:\Program Files\LibreOffice\program`). `scripts/setup-dev-env.sh` uses apt and will not work on Windows.
6. **Keys** (PowerShell, per session): `$env:GEMINI_API_KEY="…"; $env:GROQ_API_KEY="…"`, then `uv run autodeck models` shows no "missing credentials" line.
7. **Papers**: `uv run autodeck knowledge ingest llm-inference-efficiency` (slow the first time; downloads a layout model).
8. Run every command from the repository root (`runs/` and `corpus/` are relative).

## 10. Verifying this phase from a cold start

```bash
uv sync --extra ui
uv run pytest -q
# expected (with fonts installed): 1409 passed, 54 deselected
uv run pytest tests/test_ui.py -q
# expected: 41 passed
uv run ruff check . && uv run ruff format --check . && uv run pyright
# expected: All checks passed! / files already formatted / 0 errors
uv run autodeck ui
# expected: a native window titled "AutoDeck" on the Home screen.
#   If it prints "Native window failed …; using the browser." and opens the browser,
#   the UI still works; note the error for UI 2.
uv run autodeck ui --browser
# expected: prints "AutoDeck is running at http://127.0.0.1:<port>/" and opens the browser
```

Manual checks in the window, in order:
1. Home → "Ready to build" lists API keys, Fonts, LibreOffice, Papers; anything red shows its fix command.
2. Clients → New client → type "Proven to cut costs by 40%" in Positioning → two warnings appear (a numeral, a factual superlative). Create a throwaway client; `knowledge/clients/<name>/` gains `client.md` and `value_prop.md`. Delete the folder afterwards.
3. Home → pick a client and project, name a run, Start planning → the Planning screen opens; send a message → planner reply appears and the draft brief updates. Signing records approval 1 of 4: `uv run autodeck status <run>` then shows `brief` approved.
4. Runs → the run shows the next step and the exact CLI command.

## 11. Reading notes for the next implementer

- **Read first:** `DECISIONS.md` B39–B41, then `autodeck/ui/server.py` (routes are one `match` statement at the bottom), then `autodeck/ui/api.py`.
- **The one rule that matters:** the UI never records an approval itself. The brief is signed via `PlannerSession.sign_off` (the same call `/sign` makes). For the other three gates, extract `cli.approve`'s body into a shared function and call that — see §7. The bypass tests will fail if anyone takes a shortcut, and that failure is the point.
- **Next work, suggested order:** (1) shared approval function + outline step and GATE 1 screen; (2) content + validate with progress, then the claims review (GATE 2) — the first-direction "Claims review" mockup on the canvas is the layout to restyle in the clean look; (3) render + GATE 3 with the five PowerPoint checks as a checklist the person ticks (nothing in code ticks them); (4) show evidence-probe verdicts in the planning chat.
- **Long-running stages** (content, validate, render) block for minutes and burn quota (20 requests/model/day on dev, B25). Run them in a background thread per run and poll a status endpoint; do not hold an HTTP request open for the whole stage.
- **Design language** is in `autodeck/ui/static/app.css` tokens (`--panel`, `--accent`, `--btn`, …). Keep system fonts and the single blue accent; dark mode comes free from the tokens.
- **What looks wrong but is deliberate:** the POST endpoints insist on `application/json` (CSRF defence, not fussiness); `log_message` is silenced; the Redesign screen is a placeholder that says so.
- **On the PC,** if pywebview fails, try `--browser` first to separate a window problem from an app problem.
