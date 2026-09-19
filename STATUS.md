# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Phase 2b — content, linters, validation |
| **Integration branch** | `v2/integration` — **unchanged since Phase 1.** 2a and 2b are stacked and unmerged (B27) |
| **Active phase branch** | `v2/phase-2b-content-validate`, cut from `v2/phase-2a-plan-outline`'s tip |
| **Last gate passed** | **GATE 1** — approved 2026-09-18 (DECISIONS.md G1), at the precision that entry records |
| **Next gate** | **GATE 2 — open, waiting on the owner** |
| **Latest handover** | `docs/handovers/PHASE-2B.md` |
| **Updated** | 2026-09-19 |

## Next action

**Judge GATE 2 on a real deck.** Phase 2b is code complete — all eleven tasks, 736 tests —
but **no live milestone run exists**, and that is the invariant working rather than a
shortfall. `autodeck content` refuses to run without an approved outline, and no flag
anywhere approves a gate. GATE 1's approval was given against a run whose `runs/` directory
was derived data on a machine that no longer exists, so the milestone starts from the
planning session again:

```bash
export GEMINI_API_KEY=...
uv run autodeck plan northwind-milestone --client northwind-retail --project llm-inference-efficiency
#   a conversation. `/brief` shows the draft; `/sign <your name>` ends it. There is no flag.
uv run autodeck outline  northwind-milestone --client northwind-retail --project llm-inference-efficiency
uv run autodeck approve  northwind-milestone outline
uv run autodeck content  northwind-milestone --client northwind-retail --project llm-inference-efficiency
uv run autodeck validate northwind-milestone --client northwind-retail --project llm-inference-efficiency
uv run autodeck gate2    northwind-milestone
```

`gate2` prints the audit report, a stable `slide_id:block_id` per claim and six checkable
criteria, exiting non-zero on a failure. **A clean run there is not the gate.** The six are
what a machine can check; whether the deck's argument is honest is what you are being asked.
Reject named claims with `autodeck send-back <run> --claim s3:b2 --reason "..."` — the next
content pass sees the rejection and drops a verbatim repeat of it.

Budget the quota: 20 requests per model per day, roughly one `content` call per slide and
one `validation` call per six claims, spread across five models (B25).

### Three owner decisions waiting at GATE 2

- **B29 — A6 promises "byte-comparable" PPTX output, which is measurably impossible.** The
  manifest implements the achievable property; `docs/INVARIANTS.md` is deliberately unedited
  because changing what an invariant *says* is yours, not the implementer's.
- **B30 — a gate approval does not survive the machine.** Approvals live in
  `runs/<id>/state.json`, which is derived data and not committed (B22). The human act
  survives in `DECISIONS.md` only because we write it there by convention, and an approval
  is the one thing in a run that cannot be reproduced. Three options are set out in B30.
- **Should A5 fence `section_header`?** A section header is framing by nature, and nothing
  currently stops one carrying a fact.

### Carried from GATE 0 — verification debt, not blockers

- **Icon and theme behaviour in PowerPoint is unconfirmed.** Approved on the visual bar
  (D5) only. **Phase 3a must check both before building on them** — see DECISIONS.md G0.
- **Aptos is a hard prerequisite.** Spike 0.4 verified rather than assumed B11 check #4:
  there is no metric-compatible open clone. Phase 2b's budgets are wrong-by-default on a
  machine without it. Checks #1–#3 still need the owner's machine.
- **The Claude adapter has never been called live.** The first `sit` run will be its first
  real request.

### New debt from Phase 2b

- **Nothing in this phase has met a real model or the real corpus.** Everything is
  fixture-verified, including the full content → send-back → content cycle. The milestone
  run above is what closes that.
- **All four key messages in the GATE 1 brief were `unprobed`** — the evidence-gap
  classifier hit the daily quota mid-run and has never completed on a full brief. The
  validator is the next chance to catch what it would have found.
- **The send-back check catches literal regeneration only.** A reworded rejected claim is
  not recognised; that half of the defence is advisory prompt context, and `send_back.py`
  says so rather than implying the check is complete.

### New debt from Phase 2a

- **Nobody has typed into `autodeck plan`.** The session is exercised end to end against
  live models programmatically, but the REPL's ergonomics are unknown.
- **Dev capacity is ~20 planner turns a day.** The free tier allows 20 requests per model
  per day; roles are spread across five models (B25) but a long session will still hit it.
- **Model IDs go stale fast.** `gemini-2.5-pro` was retired inside a week (B23). Re-resolve
  before any phase that calls a provider.

### Debt from Phase 1

- **The seed is synthetic.** Public papers, fictional clients — per the Q2 answer. Fine for
  building; the first real deliverable needs real folders. The structure does not change.
- **VLM figure descriptions have never run live.** The path is built and unit-tested against
  a fake; the prompt has not met a real model.
- **A5 is structured but not enforced.** `value_prop.md` is typed as framing, but nothing
  yet stops a claim tracing to it. Phase 2b's validator owns that.

## Invariant coverage

**Five cells move to `tested` in Phase 2b** — A1, A2, A3, A5 and A8 — leaving A4 and A7
where they were and A6 deliberately at `partial`.

A2 and A5 gain linters that block rather than warn. A3 gains the behaviour that has no v1
ancestor: independent re-retrieval with a separate contradiction pass, and a rule ordered so
that a contradicting span elsewhere in the corpus outranks a perfectly valid citation. A8
becomes `tested` — `open_risks` resurface in the report, conflicting sources appear with
both spans rather than an average, and a provider failure returns `unverified` with a
reason instead of a guess.

**Read A1 and A5's cells with their trap attached:** a clean `Deck` is no longer sufficient
evidence that either holds, because a demoted framing block and a failed validation pass
both leave `Deck.blocking_blocks()` empty. The cells are `tested` on
`require_safe_to_render`, the one function that knows what "safe" means.

**A6 stays `partial` on purpose.** Its headline is unachievable as written (B29), and
marking it `enforced` against a statement we know to be wrong would be the dishonest kind of
green.

See the tracker in `docs/INVARIANTS.md`.

## Phase progress

| Phase | Branch | Gate | Status |
|---|---|---|---|
| 0 — Foundations | `v2/phase-0-foundations` | GATE 0 | **merged — gate approved** |
| 1 — Ingestion & knowledge | `v2/phase-1-ingest-knowledge` | GATE 1a | **merged — gate approved** |
| 2a — Planning & outline | `v2/phase-2a-plan-outline` | GATE 1 | **gate approved (G1) — unmerged, stacked under 2b** |
| 2b — Content & validation | `v2/phase-2b-content-validate` | GATE 2 | **code complete — gate open** |
| 3a — Design system | `v2/phase-3a-design-system` | internal | not started |
| 3b — Renderer & QA | `v2/phase-3b-render-qa` | GATE 3 | not started |
| 4 — Consulting workflow | `v2/phase-4-workflow` | GATE 4 | not started |
| 5 — Evals & hardening | `v2/phase-5-evals-hardening` | — | not started |

## What exists today

Phases 0 through 2b, on `v2/phase-2b-content-validate`. **736 tests pass** (13 skipped for
missing local tooling, 10 live-marked and deselected); ruff and pyright are clean.

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

### Added in Phase 2a

- **Planning** (`autodeck/agents/planner.py`, `prompts/planner.md`) — a conversation that
  ends only on human sign-off, A7 approval 1 of 4. No flag approves a brief.
- **Evidence gaps** (`autodeck/agents/evidence_gap.py`) — deterministic retrieval, model
  judgement, and a ceiling applied to the judgement afterwards. The pattern the rest of the
  system copies.
- **Outline** (`autodeck/agents/outline.py`, `autodeck/audit/gate1.py`) — signed brief to IR
  skeleton, no prose, pins honoured or flagged; GATE 1's mechanical half.

### Added in Phase 2b

- **Budgets** (`autodeck/design/budgets.py`, `budget_check.py`,
  `design/components/catalog.py`) — per-slot budgets in points, `LINE_HEIGHT_FACTOR = 1.20`
  measured rather than derived, over-budget text rejected before render.
- **Prompts** (`prompts/content.md`, `prompts/validation.md`) — the writer and its
  adversary. Both written to a model that might ignore them; every promise that matters is
  also enforced in code.
- **Linters** (`autodeck/audit/numeric_linter.py`, `framing_linter.py`) — A2 and A5. Every
  numeral traces to a cited span or a re-executed derivation; a `framing` block carrying a
  fact is demoted to `claim`, where the IR refuses to construct it.
- **Validation** (`autodeck/audit/verdicts.py`, `autodeck/agents/validation.py`) — A3's rule
  in a guardrail path, its plumbing outside one.
- **The render guard** (`autodeck/pipeline/orchestrator.py`) — `require_safe_to_render`, the
  single place that knows what safe means.
- **Audit surface** (`autodeck/audit/report.py`, `manifest.py`) — the working shown for every
  derivation, conflicts recorded without averaging, a canonical PPTX digest.
- **GATE 2** (`autodeck/cli.py`, `autodeck/pipeline/send_back.py`) — `content`, `validate`,
  `gate2`, `send-back`. Rejecting a named claim existed nowhere before this phase.
