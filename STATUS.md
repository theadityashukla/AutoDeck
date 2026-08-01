# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Phase 1 — ingestion & knowledge |
| **Integration branch** | `v2/integration` |
| **Active phase branch** | `v2/phase-1-ingest-knowledge` |
| **Last gate passed** | **GATE 0** — approved with conditions (DECISIONS.md G0) |
| **Next gate** | GATE 1a — owner spot-checks 10 citations against source PDFs |
| **Latest handover** | `docs/handovers/PHASE-0.md` |
| **Updated** | 2026-08-01 |

## Next action

Phase 1 — build the provenance chain (`docs/phases/PHASE-1.md`). Every citation the system
will ever produce resolves through what is built here; if provenance breaks, A1 is
unenforceable no matter how good the agents are.

**Q2 answered (2026-08-01):** seed with a **synthetic corpus** — public papers plus a
fictional client — so the chain is exercised end to end now. The real project and client
swap in later; GATE 1a's citation spot-check works against public PDFs just as well.

### Carried from GATE 0 — verification debt, not blockers

- **Icon and theme behaviour in PowerPoint is unconfirmed.** Approved on the visual bar
  (D5) only. **Phase 3a must check both before building on them** — see DECISIONS.md G0.
- **Aptos is a hard prerequisite.** Spike 0.4 verified rather than assumed B11 check #4:
  there is no metric-compatible open clone. Phase 2b's budgets are wrong-by-default on a
  machine without it. Checks #1–#3 still need the owner's machine.
- **The Claude adapter has never been called live.** The first `sit` run will be its first
  real request.

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
| 0 — Foundations | `v2/phase-0-foundations` | GATE 0 | **merged — gate approved** |
| 1 — Ingestion & knowledge | `v2/phase-1-ingest-knowledge` | GATE 1a | **in progress** |
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
