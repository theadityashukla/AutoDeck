# Phase 2b — Content, linters & validation

**Branch:** `v2/phase-2b-content-validate` · **Gate:** GATE 2 · **Estimate:** ~3 weeks
**Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 2 tasks 4–8, §6.10

> **This is the accuracy core of the entire system.** Plan §7: *"This is the heart of the
> consulting use case. Spend the time here."* The whole invariant set A1–A8 goes live in
> this phase.
>
> The milestone is a **correct, fully-audited, deliberately ugly deck.** Ugly is fine;
> wrong is not. Resist every temptation to make it look good — that is Phase 3.

## Preconditions

- GATE 1 approved; `docs/handovers/PHASE-2A.md` read.
- IR v0 skeleton generation working; brief sign-off enforced.
- **Text budgets available.** The content agent writes *inside* budgets (§6.7), so
  `design/budgets.py` must exist. See the sequencing note below.

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 2b.1 | `design/budgets.py` — real glyph metrics (fonttools/Pillow), not character counts: given TTF + box + font size + line spacing, measure wrapped text height | **Opus** | `autodeck/design/budgets.py` | — | Measured height matches LibreOffice-rendered height within tolerance; **v1's `chars_per_line` heuristic is not reproduced** |
| 2b.2 | Per-slot budget declarations consumed by the content prompt as hard constraints | **Sonnet** | `autodeck/design/components/catalog.py` | — | Budgets reach the prompt as explicit limits; post-write deterministic check rejects overflow **before** render |
| 2b.3 | `prompts/content.md` — writing within budgets, citation per claim, derivations, **honest-uncertainty behaviour (A8)** | **Opus** | `prompts/content.md` | A1, A2, A8 | Own commit with rationale |
| 2b.4 | Content agent — per slide, writes `claim`/`framing`/`chart` blocks; each claim cited from `claims.md` or retrieval; derived numbers declared as `Derivation` | **Sonnet** | `autodeck/agents/content.py` | **A1, A2, A8** | Blocks validate against the IR schema; **speaker notes are blocks too and carry citations** |
| 2b.5 | **Numeric linter (A2)** — extract numerals, normalise (`3.2M`↔`3,200,000`, `%`↔`percent`, locale separators), match to cited spans or derivations, **re-execute every derivation formula** | **Opus** | `autodeck/audit/numeric_linter.py` | **A2** | Zero unmatched numerals to pass; blocking. Adversarial tests: uncited numeral, miscomputed derivation, format variant |
| 2b.6 | **Framing linter (A5)** — no numerals, no named studies, no factual superlatives in `framing` blocks; violators **demoted to `claim`** | **Opus** | `autodeck/audit/framing_linter.py` | **A5** | Demotion is a real state change that re-triggers A1/A3, not a logged warning |
| 2b.7 | `prompts/validation.md` | **Opus** | `prompts/validation.md` | A3 | Own commit with rationale |
| 2b.8 | **Validation agent (A3)** — independent re-retrieval per claim, four-verdict assignment, contradiction search across the corpus, claims table | **Opus** | `autodeck/agents/validation.py` | **A3** | A claim with a *valid* citation but a contradicting span elsewhere returns `contradicted`. Blocks final render on `unsupported`/`contradicted` |
| 2b.9 | Audit report (A6) — per-slide claims table, conflicts section (A8), `open_risks` from the brief resurfaced. Markdown first | **Sonnet** | `autodeck/audit/report.py` | **A6, A8** | Report shows the working for every derived figure |
| 2b.10 | Build manifest (A6) — model IDs, prompt hashes, knowledge git commit, component lib version, IR hash | **Sonnet** | `autodeck/audit/manifest.py` | **A6** | Same manifest + IR re-renders byte-comparable output (normalise zip order and timestamps first) |
| 2b.11 | GATE 2 review surface — claims table with send-back for specific claims | **Sonnet** | `autodeck/cli.py` | A7 | Owner can approve, or return named claims for correction |

## Sequencing note — budgets before content

Task 2b.1 is design-system work living in a content phase, and that is deliberate. Plan
§6.7 makes the content agent write *inside* budgets, so budgets must precede content or
the agent writes blind and Phase 3 becomes overflow whack-a-mole — exactly v1's failure.
Only the **measurement engine** is needed here; per-component budget *values* firm up in
Phase 3a as components are designed.

## Accuracy focus

> The entire invariant set (A1–A8) is live and enforced here.

## Milestone

**A correct, fully-audited, deliberately ugly deck** — every claim verified, every number
traced, audit report clean.

## GATE 2 — exit criteria

The owner reviews the audit claims table and approves, or sends specific claims back.

Checkable before requesting the gate:
- Zero blocks with verdict `unsupported` or `contradicted`.
- Numeric linter: zero unmatched numerals; every derivation re-executes to its stated result.
- Framing linter: clean, with any demotions resolved.
- Every claim in the table shows doc, page, and verbatim quote.
- Conflicts section present where sources disagree (A8) — not silently averaged.
- `open_risks` from the brief appear in the report.

## Escalation triggers

- **An invariant blocks a deck that seems obviously fine.** Per plan §0.4: do not weaken
  the invariant. Surface the conflict with options.
- **The validator cannot re-retrieve independently** because retrieval is too weak —
  a Phase 1 gap; fix it there.
- **A2 normalisation ambiguity** (a number that could match two different cited spans) —
  decide, record in `DECISIONS.md`, flag at the gate.

## Notes for the implementer

- **Read `legacy/v1/LEGACY.md` on the validation agent before starting 2b.8.** Plan §8
  lists v1's validator as salvage, but inspection shows it is mostly *image quality*
  (`validate_image`, OpenCV blur/brightness). Only `validate_content` and
  `validate_coherence` are content validation, and both trust the writer's retrieval.
  **A3's defining behaviours — independent re-retrieval and contradiction search — have
  no v1 ancestor.** Scope 2b.8 as new construction.
- The numeric linter runs **twice** in the finished system: here on IR text, and again
  post-render in Phase 3b. Build it so it can take either input.
- Derivations are first-class, not an exception (A2). The content agent is *free* to
  compute percentages and deltas — it just has to show the working.
