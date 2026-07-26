# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Phase 0 — code complete, **GATE 0 open** |
| **Integration branch** | `v2/integration` |
| **Active phase branch** | `v2/phase-0-foundations` |
| **Last gate passed** | none |
| **Next gate** | GATE 0 — go/no-go on the whole rendering strategy |
| **Latest handover** | `docs/handovers/PHASE-0.md` |
| **Updated** | 2026-07-26 |

## Next action

**The owner opens three PPTX files in PowerPoint.** All seven Phase 0 tasks are built and
every check that can be run headlessly is green — but GATE 0's criteria are all phrased as
*"the owner opens the file in PowerPoint"*, and Phase 0 was built in a Linux container with
neither PowerPoint nor Aptos.

Download from `spikes/gate0/` on `v2/phase-0-foundations` and check, in PowerPoint:

1. `theme.pptx` — palette appears under Design → Variants; a hand-added slide inherits it.
2. `components.pptx` — `big_number` and `two_column_compare` meet the visual bar.
3. `icon.pptx` — icons select as shapes, scale losslessly, recolour from the theme.

Full instructions in `docs/handovers/PHASE-0.md` §10. Then, on a machine with Aptos:
re-run the spike with `--tokens config/tokens/aptos.json`, and run
`pytest -m live -k claude` with an `ANTHROPIC_API_KEY` to close the last 0.3 criterion.

**Do not merge on the strength of the committed PNGs.** They were rendered by LibreOffice,
in Inter, on Linux. GATE 0 is the go/no-go for the entire rendering strategy.

**Also still open — the Aptos prerequisite.** Spike 0.4 verified rather than assumed
B11 check #4: **there is no metric-compatible open clone of Aptos.** "Aptos installed on
the build machine" is therefore a hard prerequisite for Phase 2b's budgets and Phase 3's
design loop, not a convenience. Checks #1–#3 need the owner's machine.

**Next question needed: Q2** — which project and client seed the build, real or
anonymised? Answer before Phase 1 is cut.

## Invariant coverage

**A1 is `tested`** — landed structurally in task 0.2, exactly as planned: `Claim.citations`
carries `min_length=1`, so a claim with no evidence cannot be constructed, and that applies
to speaker notes identically. **A7 is `enforced`** — gates raise rather than log, and a test
asserts no CLI flag can bypass one. A2, A3 and A6 are `partial`: the IR and manifest can
express what they need, but their linters and validators are Phase 2b.

See the tracker in `docs/INVARIANTS.md`.

## Phase progress

| Phase | Branch | Gate | Status |
|---|---|---|---|
| 0 — Foundations | `v2/phase-0-foundations` | GATE 0 | **code complete — gate open** |
| 1 — Ingestion & knowledge | `v2/phase-1-ingest-knowledge` | GATE 1a | not started |
| 2a — Planning & outline | `v2/phase-2a-plan-outline` | GATE 1 | not started |
| 2b — Content & validation | `v2/phase-2b-content-validate` | GATE 2 | not started |
| 3a — Design system | `v2/phase-3a-design-system` | internal | not started |
| 3b — Renderer & QA | `v2/phase-3b-render-qa` | GATE 3 | not started |
| 4 — Consulting workflow | `v2/phase-4-workflow` | GATE 4 | not started |
| 5 — Evals & hardening | `v2/phase-5-evals-hardening` | — | not started |

## What exists today

The Phase 0 foundation, on `v2/phase-0-foundations`. 192 tests pass; ruff and pyright are
clean.

- **Deck IR** (`autodeck/ir/`) — models, three-dialect JSON-Schema export, versioned store
  with an id-keyed diff.
- **Providers** (`autodeck/providers/`) — protocol, repair-retry, 429 backoff, resumable
  cache, Gemini/Groq/Claude adapters, `dev`/`sit`/`prod` registry.
- **Design system** (`autodeck/design/`) — font resolution, glyph-metric budgets, OOXML
  theme builder, `layout_kit`, two components, SVG→`custGeom` icon converter.
- **Pipeline** (`autodeck/pipeline/`, `autodeck/audit/`, `autodeck/cli.py`) — run dirs,
  resumable stages, blocking gates, A6 manifest, CLI.
- **Spike artifacts** (`spikes/gate0/`) — the three PPTX files GATE 0 turns on.
- Governance docs, the vendored spec, and frozen v1 under `legacy/v1/`.
