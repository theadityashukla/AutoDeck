# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Phase 2a — planning agent & outline |
| **Integration branch** | `v2/integration` |
| **Active phase branch** | `v2/phase-2a-plan-outline` |
| **Last gate passed** | **GATE 1a** — approved 2026-08-02 (DECISIONS.md G1a) |
| **Next gate** | GATE 1 — owner approves the outline skeleton *against the brief* |
| **Latest handover** | `docs/handovers/PHASE-1.md` |
| **Updated** | 2026-08-02 |

## Next action

**Phase 2a — planning agent & outline** (`docs/phases/PHASE-2A.md`). The point of the phase,
in its own words: *evidence gaps surface in conversation, before a single slide is written.*

Task 2a.4 is why it exists. Each key message the planner proposes is probed against
`claims.md` and the corpus during the session, so an unsupported message triggers an
in-conversation challenge — *"no source currently supports X: soften it, add a source, or
drop it?"* — and an accepted gap lands in `open_risks` rather than disappearing. A gap
caught here costs one conversational turn; the same gap caught at GATE 2 costs a rewrite of
every slide built on it.

GATE 1 then asks a deliberately objective question: not "is this a good outline" but "does
this outline deliver the brief's key messages, in the brief's order, honouring its pins?"

### Carried from GATE 0 — verification debt, not blockers

- **Icon and theme behaviour in PowerPoint is unconfirmed.** Approved on the visual bar
  (D5) only. **Phase 3a must check both before building on them** — see DECISIONS.md G0.
- **Aptos is a hard prerequisite.** Spike 0.4 verified rather than assumed B11 check #4:
  there is no metric-compatible open clone. Phase 2b's budgets are wrong-by-default on a
  machine without it. Checks #1–#3 still need the owner's machine.
- **The Claude adapter has never been called live.** The first `sit` run will be its first
  real request.

### New debt from Phase 1

- **The seed is synthetic.** Public papers, fictional clients — per the Q2 answer. Fine for
  building; the first real deliverable needs real folders. The structure does not change.
- **VLM figure descriptions have never run live.** The path is built and unit-tested against
  a fake; the prompt has not met a real model.
- **A5 is structured but not enforced.** `value_prop.md` is typed as framing, but nothing
  yet stops a claim tracing to it. Phase 2b's validator owns that.

## Invariant coverage

**A1 is `tested` end to end** — the schema constraint from task 0.2 (`Claim.citations` has
`min_length=1`) now sits on top of a real provenance chain: a PDF produces elements whose
quotes hash-verify, and every path that could yield a citable fact without provenance fails
closed and is asserted — figure descriptions, low-provenance documents, retrieval hits.
Mechanism only, though: **GATE 1a has not been judged**, and no test can confirm a box
points at the right part of a page.

**A4 is `tested`** — against the real seed folders, not only a fixture, which is why the
seed ships two clients. **A7 is `enforced`** — gates raise rather than log, and a test
asserts no CLI flag bypasses one. A2, A3, A5, A6 and A8 are `partial`: the structures exist,
the validators are Phase 2b.

See the tracker in `docs/INVARIANTS.md`.

## Phase progress

| Phase | Branch | Gate | Status |
|---|---|---|---|
| 0 — Foundations | `v2/phase-0-foundations` | GATE 0 | **merged — gate approved** |
| 1 — Ingestion & knowledge | `v2/phase-1-ingest-knowledge` | GATE 1a | **merged — gate approved** |
| 2a — Planning & outline | `v2/phase-2a-plan-outline` | GATE 1 | **in progress** |
| 2b — Content & validation | `v2/phase-2b-content-validate` | GATE 2 | not started |
| 3a — Design system | `v2/phase-3a-design-system` | internal | not started |
| 3b — Renderer & QA | `v2/phase-3b-render-qa` | GATE 3 | not started |
| 4 — Consulting workflow | `v2/phase-4-workflow` | GATE 4 | not started |
| 5 — Evals & hardening | `v2/phase-5-evals-hardening` | — | not started |

## What exists today

Phases 0 and 1, on `v2/phase-1-ingest-knowledge`. **342 tests pass**; ruff and pyright are
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

### Added in Phase 1

- **Ingestion** (`autodeck/ingest/`) — Docling runner split at the ML seam, document store
  as the A1 chokepoint, tolerant-not-approximate quote matching, table cells with their own
  bboxes, VLM figure descriptions that are retrievable but structurally uncitable, and a
  Grobid stub that raises on purpose.
- **Knowledge** (`autodeck/knowledge/`) — two-tier folders (D8) and A4 isolation, with the
  non-obvious leak paths covered: reference decks and cached retrieval indices.
- **Retrieval** (`autodeck/retrieval/hybrid.py`) — BM25 + optional embeddings, RRF fusion.
  No chunker: elements are the chunks, so a hit cannot lack provenance.
- **Spot-check** (`autodeck/audit/spotcheck.py`) — GATE 1a evidence. Renders the box, emits
  no verdict.
- **CLI** — `autodeck knowledge validate | ingest | ask | spotcheck`.
- **Seed corpus** (`knowledge/`) — five CC BY 4.0 papers, 16 hash-verified claims, two
  fictional clients. Real evidence, not fixtures: prefer citing from it in tests.
