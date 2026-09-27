# Status

**One screen: where the v2 build actually is right now.** Updated in the same commit as
every phase handover. If this file disagrees with your memory, this file is right.

---

| | |
|---|---|
| **Current phase** | Phase 3a — design system |
| **Integration branch** | `v2/integration` — **unchanged since Phase 1.** 2a, 2b and 3a are stacked and unmerged (B27) |
| **Active phase branch** | `v2/phase-3a-design-system`, cut from `v2/phase-2b-content-validate`'s tip |
| **Last gate passed** | **GATE 1** — approved 2026-09-18 (DECISIONS.md G1), at the precision that entry records |
| **Next gate** | **GATE 2 — open**, then GATE 3 after Phase 3b |
| **Latest handovers** | `docs/handovers/PHASE-2B.md`, `docs/handovers/PHASE-3A.md` |
| **Updated** | 2026-09-27 |

## What the adversarial review found

Phase 2b's handover was written from a green suite of 736 tests. An independent adversarial
review then found holes those tests did not reach — 11 findings, 9 demonstrated by executing
against the code, with 6 of those reproduced independently by the orchestrator before
acting — and twelve commits fixed them. The review ran on Opus; the planned Fable 5.1
returned HTTP 429, "requires usage credits". The suite on the phase branch stood at
839 passed, 0 skipped, 10 live-marked and deselected at the time — the 13 font-dependent
skips are gone because fonts are installed, and CI now installs the OFL dev fonts too,
since `3cac30e` on the 3a branch. The suite at tip, including Phase 3a, is
**1098 passed, 0 skipped, 10 live-marked and deselected**. See `docs/handovers/PHASE-2B.md`
§6.9–§6.13 for what the review found and how it was closed.

**The corrected coverage: A2 and A3 stay `tested`, corrected in place; A5 is downgraded from
`tested` to `enforced`.** A5's fence is a closed list of factual phrasings — ordinary
factual language outside that list passes uncited, demonstrated with "Quantisation halves
serving cost" as an unfenced `section_header`. A2 and A3 keep their `tested` cells after the
fixes, each with a named residual gap: A2 cannot see numbers written as words ("forty
percent", "four times"); A3's `chart` blocks never receive a verdict.

## Next action

**Judge GATE 2 on a real deck.** Phase 2b is code complete — all eleven tasks, 1098 tests —
but **no live milestone run exists**, and that is the invariant working rather than a
shortfall. `autodeck content` refuses to run without an approved outline, and no flag
anywhere approves a gate. GATE 1's approval was given against a run whose `runs/` directory
was derived data on a machine that no longer exists, so the milestone starts from the
planning session again.

Before running anything, `./scripts/setup-dev-env.sh` (B34) — without it the render checks
cannot run.

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

- **B30 — a gate approval does not survive the machine.** Approvals live in
  `runs/<id>/state.json`, which is derived data and not committed (B22). The human act
  survives in `DECISIONS.md` only because we write it there by convention, and an approval
  is the one thing in a run that cannot be reproduced. Three options are set out in B30.
- **Should A5 fence `section_header`?** A section header is framing by nature, and nothing
  currently stops one carrying a fact. Input from the headers work: lean yes, narrowly — it
  is where A5's closed list is weakest.
- **Chart verdict / per-cell citations.** `chart` blocks never receive a verdict, and
  `ChartSpec.source_citations` is not linked per data point, so "the source table cell is
  the citation" is not literally satisfiable without an IR change.

### Carried from GATE 0 — verification debt, not blockers

- **Icon and theme behaviour in PowerPoint is unconfirmed.** Approved on the visual bar
  (D5) only. **Phase 3a must check both before building on them** — see DECISIONS.md G0.
- **Aptos is a hard prerequisite.** Spike 0.4 verified rather than assumed B11 check #4:
  there is no metric-compatible open clone. Phase 2b's budgets are wrong-by-default on a
  machine without it. Checks #1–#3 still need the owner's machine.
- **The Claude adapter has never been called live.** The first `sit` run will be its first
  real request.

### New debt from Phase 3a

- **The four PowerPoint-only GATE 3 checks** (no PowerPoint in this environment) — see
  `docs/handovers/PHASE-3A.md` §7.
- `check_overflow`'s sibling-floor gap: each slot's budget assumes siblings take one line;
  nothing checks both can hold at once.
- Diagram and chart labels are protected only at render, not by `check_overflow`.
- The icon-adjacency threshold is uncalibrated — no component places icons yet.
- Theme mode (a) is proven against a synthetic template only, not a real corporate one.

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
- **Numbers written as words are invisible to A2 and A5** ("forty percent", "four times",
  "quadrupled", "a third") — the extractor sees only digits, so both linters pass vacuously
  on them.
- **Two spellings of one claim id**: `s1:b1:n1` in validation vs. `s1:b1/n1` in the report
  and send-back — a send-back and a judgement about the same node cannot be joined across
  rounds.
- **No store re-verification of citations.** Nothing re-checks a stored citation against the
  document store after construction; a hand-edited IR or a re-ingested corpus is not caught.
- **`require_safe_to_render` must be called by Phase 3b's render stage.**
- **`autodeck content` under-reports `incomplete_slots`** (landed on the 3a branch).

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

## Invariant coverage — corrected after independent review

**Four cells move up in Phase 2b — A1 (unchanged at `tested`), A2, A3 and A8 move to or stay
`tested`; A5 moves to `enforced`, not `tested`** — leaving A4 and A7 where they were and A6
deliberately at `partial`. The independent review found that A2, A3 and A5 being marked
`tested` in the original handover was true of the tests and false of the code; A2 and A3
are corrected in place and remain `tested`, each with a named residual gap, and **A5 is
downgraded to `enforced`**.

A2 and A5 gain linters that block rather than warn. A3 gains the behaviour that has no v1
ancestor: independent re-retrieval with a separate contradiction pass, and a rule ordered so
that a contradicting span elsewhere in the corpus outranks a perfectly valid citation. A8
becomes `tested` — `open_risks` resurface in the report, conflicting sources appear with
both spans rather than an average, and a provider failure returns `unverified` with a
reason instead of a guess.

**Read A1 and A5's cells with their trap attached:** a clean `Deck` is no longer sufficient
evidence that either holds, because a demoted framing block and a failed validation pass
both leave `Deck.blocking_blocks()` empty. The cells are `tested`/`enforced` on
`require_safe_to_render`, the one function that knows what "safe" means.

**A5 is downgraded from `tested` to `enforced`.** The fence is a closed list of factual
phrasings, tested on what it lists; ordinary factual language outside the list passes.
Demonstrated: "Quantisation halves serving cost" passes as uncited `section_header` text (no
numeral, no superlative, "halves" not in the multiplier list) — headers are terse by
construction, which is exactly what strips the patterns A5 matches.

**A2 stays `tested`, with a named gap**: numbers written as words are invisible to the
extractor ("forty percent", "four times", "quadrupled", "a third"), so A2 passes vacuously
on them.

**A6 is `enforced`.** Its headline promised "byte-comparable" output, which is not achievable
for PPTX; the owner accepted the corrected wording on 2026-09-27 (B29) — normalised-comparable
under a recorded normalisation. The manifest half is tested; the render-twice proof needs
Phase 3b's renderer.

See the tracker in `docs/INVARIANTS.md`.

## Phase progress

| Phase | Branch | Gate | Status |
|---|---|---|---|
| 0 — Foundations | `v2/phase-0-foundations` | GATE 0 | **merged — gate approved** |
| 1 — Ingestion & knowledge | `v2/phase-1-ingest-knowledge` | GATE 1a | **merged — gate approved** |
| 2a — Planning & outline | `v2/phase-2a-plan-outline` | GATE 1 | **gate approved (G1) — unmerged, stacked under 2b** |
| 2b — Content & validation | `v2/phase-2b-content-validate` | GATE 2 | **code complete — gate open** |
| 3a — Design system | `v2/phase-3a-design-system` | internal | **code complete, internal review pending** |
| 3b — Renderer & QA | `v2/phase-3b-render-qa` | GATE 3 | not started |
| 4 — Consulting workflow | `v2/phase-4-workflow` | GATE 4 | not started |
| 5 — Evals & hardening | `v2/phase-5-evals-hardening` | — | not started |

## What exists today

Phases 0 through 3a, on `v2/phase-3a-design-system`. **1098 tests pass** (0 skipped, 10
live-marked and deselected — fonts are installed, and CI now installs the OFL dev fonts
too); ruff and pyright are clean.

- **Deck IR** (`autodeck/ir/`) — models, three-dialect JSON-Schema export, versioned store
  with an id-keyed diff.
- **Providers** (`autodeck/providers/`) — protocol, repair-retry, 429 backoff, resumable
  cache, Gemini/Groq/Claude adapters, `dev`/`sit`/`prod` registry.
- **Design system** (`autodeck/design/`) — font resolution, glyph-metric budgets, OOXML
  theme builder, `layout_kit`, 15 components, SVG→`custGeom` icon converter.
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

### Added in Phase 3a

- `layout_kit.py` — composition layer: `Frame`, `Stack`, `Box.reserve`, `measure_block`;
  nothing shrinks text, over-budget raises.
- `components/catalog.py` — component registry: `register()`, variants,
  `components_missing_previews()`.
- `ir/models.py` — `DiagramSpec` type system; a node must be exactly one of `claim`/`framing`.
- `components/preview.py` — golden-preview loop and `autodeck components preview`.
- 15 components, each with a committed golden PNG.
- Budgets resolve a real face per weight/style; exact integer prediction-vs-render line-count
  cross-check.
- `theme/` — mode (b) from tokens with inheritance proven; mode (a) against a synthetic
  template only.
- `icons/` — licence record, semantic library, deck consistency checker, `Frame.icon`.
- `headers/` — profile loader, profile in the content prompt, `--header-style` flag on
  `autodeck content`, horizontal-flow QA.
- `charts.py` — native charts, data in an embedded workbook referenced by formula, no image
  part ever.
- `diagrams.py` + `draw.py` — process_flow, two_by_two, layered_stack as ungrouped native
  shapes with theme colours.
- `grammar.py` — D13 lints: word budget, ≤1 diagram, icon+chart+diagram pileup (blocking);
  concept count (advisory); icon adjacency (blocking, uncalibrated).
