# Phase 2b — Content, linters, validation — Handover

> The phase's reason for existing, in the plan's own words: *a deck whose every claim has
> been checked by something that did the work again rather than read the writer's answer.*

---

## 1. Identification

| | |
|---|---|
| **Phase** | 2b — content agent, A2/A5 linters, A3 validation, audit report, GATE 2 surface |
| **Branch** | `v2/phase-2b-content-validate` — cut from `v2/phase-2a-plan-outline`'s tip, **not** from `v2/integration` (B27) |
| **PR** | not opened. Nothing merges until the owner works the gate (B27) |
| **Started / completed** | 2026-09-18 → 2026-09-19 |
| **Gate** | GATE 2 |
| **Gate status** | **pending** — no claims table has been put to the owner |
| **Approved by / when** | — |
| **What the owner actually checked** | Nothing yet. **This handover does not claim the gate passed**, and no live Phase 2b milestone run exists — see §3, which explains why that is the invariant working rather than a shortfall. |

Seventeen commits, 30 files, +13,065 / −51. The suite goes **432 → 736 passing** (13
skipped for missing local tooling, 10 live-marked and deselected).

## 2. What shipped

| Path | What it does | Tests |
|---|---|---|
| `autodeck/design/budgets.py` | Text budgets in points. `LINE_HEIGHT_FACTOR = 1.20`, measured rather than derived — see §6.1 | `tests/test_design.py` |
| `autodeck/design/budget_check.py` | The LibreOffice cross-check, kept out of `budgets.py` so that module still imports in CI without LibreOffice | `tests/test_budget_check.py` |
| `autodeck/design/components/catalog.py` | Per-slot budgets for the components content is written into; `check_overflow` rejects over-budget text **before** render | `tests/test_catalog.py` |
| `prompts/content.md` | A1/A2/A5/A8 for the writer. Hedge in words, never in arithmetic | — |
| `prompts/validation.md` | The adversarial half of the pair. Being agreeable is named as the failure mode | — |
| `autodeck/audit/numeric_linter.py` | A2. Every numeral traces to a cited span or a re-executed derivation. Declarative normalisation tables, `Decimal` not `float`, formulas re-executed by AST walk rather than `eval` | `tests/test_numeric_linter.py` |
| `autodeck/audit/framing_linter.py` | A5. A framing block carrying a fact is **demoted** to `claim`, and the demotion's `materialise()` raises from `Claim.citations` — the IR's unconstructibility *is* the A1 failure | `tests/test_framing_linter.py` |
| `autodeck/audit/verdicts.py` | A3's rule: the four ordered bounds, the contradiction rule, `ValidatorEvidence` refusing at construction any citation not marked `retrieved_by="validator"` | `tests/test_verdicts.py` |
| `autodeck/pipeline/orchestrator.py` | `require_safe_to_render` — one place that knows what "safe to render" means, because a clean `Deck` is no longer the test (§6.4) | `tests/test_orchestrator.py` |
| `autodeck/agents/content.py` | One `content` call per slide. Citations resolved through the document store, never composed by the model | `tests/test_content.py` |
| `autodeck/agents/validation.py` | Independent re-retrieval, a separate contradiction pass, six claims per `validation` call | `tests/test_validation.py` |
| `autodeck/audit/report.py` | The working shown for every derivation, per-input traceability, conflicts recorded **without** averaging | `tests/test_report.py` |
| `autodeck/audit/manifest.py` | `canonical_pptx_digest`, `knowledge_commit`, `knowledge_dirty`, `Manifest.reproducible()`. Nothing named `bytes_match` (§6.6) | `tests/test_manifest.py` |
| `autodeck/pipeline/send_back.py` + `autodeck/cli.py` | `content`, `validate`, `gate2`, `send-back`. GATE 2's second half — rejecting named claims — existed nowhere before | `tests/test_cli_gate2.py` |

## 3. What did not ship

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|
| — | Every task 2b.1–2b.11 is complete | — |
| **The live Phase 2b milestone run** | Blocked at a human gate, correctly. See below | **Owner, at the review session** |

**The milestone is blocked by A7, not by missing code.** `autodeck content` refuses to run
without an approved outline (`Gate.OUTLINE`), and no flag anywhere approves a gate — a
property asserted by `test_none_of_the_new_commands_can_record_an_approval`. The GATE 1
approval recorded in DECISIONS.md **G1** was given against a real run whose artifacts lived
under `runs/`, which is derived data and not committed (B22); that working directory is gone
with the machine it was built on. Re-creating it means a fresh `autodeck plan` session
signed with `/sign <name>` — A7 approval 1 of 4, a human act — and a fresh GATE 1 judgement.
Neither is mine to perform, and forging either would make every downstream check decorative.

What this costs, stated plainly: the content agent, the validation agent and the audit
report have been exercised end to end **against fixtures**, including the full
content → send-back → content cycle, but not against the real seed corpus and a real model.
§10 is the recipe for closing that in one sitting.

A second consequence is worth its own line, because it is a design gap rather than an
accident: **an approved gate is recorded only in `runs/<id>/state.json`**, which is not
committed. The human act survives in `DECISIONS.md` because we write it down there by
convention; the machine-readable record does not survive a new machine. Recorded as
**B30**, with three options and no code changed on its strength — see §7.

## 4. Decisions made this phase

- **G1** — GATE 1 approved, recorded at G0/G1a precision: what the owner actually reviewed
  was the review sheet and `brief/v1.yaml`, not a blanket sign-off. Carries forward that all
  four key messages were signed `unprobed` because the classifier hit the daily quota.
- **B27** — Phases 2b–3b stack without merging. BRANCHING rule 1 (cut from the integration
  tip) collides with rule 3 (nothing merges without the owner's written gate approval) under
  the owner's instruction to build three phases in one pass. Rule 3 derives from A7; rule 1
  is a topology convention, so the convention yields.
- **B28** — Guardrail paths hold their tier. Opus-*tagged* work outside `autodeck/ir/`,
  `autodeck/audit/`, `prompts/`, `DECISIONS.md` and `docs/handovers/` drops to Sonnet under
  the budget, with each de-escalation named in §8. Two accuracy-critical modules were
  **split** so the invariant lives inside a guardrail path rather than being de-tiered.
- **B29** — *open, needs an owner decision.* A6's headline promises "byte-comparable"
  output. That is not achievable for PPTX, and A6's own "watch for" line contradicts its
  headline. `docs/INVARIANTS.md` is deliberately **unedited**: changing what an invariant
  says is the owner's call, not the implementer's (plan §0.4).
- **B30** — *open, needs an owner decision.* An approval is recorded only in
  `runs/<id>/state.json`, which is derived data and not committed. An approval is also the
  one thing in a run that cannot be reproduced. Three options are set out; no code was
  changed on the strength of the entry.

## 5. Invariant coverage delta

| Invariant | Before (P2a) | After (P2b) | Test that proves it |
|---|---|---|---|
| A1 citation | tested | **tested** | `test_content.py` — a quote that does not resolve drops the claim rather than producing an uncited block; `test_framing_linter.py` — a demotion's `materialise()` raises from `Claim.citations` |
| A2 numbers | partial | **tested** | `test_numeric_linter.py` — every numeral traces or blocks; derivations re-execute; `test_report.py` asserts an averaged conflict figure is *absent* |
| A3 validation | partial | **tested** | `test_verdicts.py` — a valid citation plus a contradicting span elsewhere returns `contradicted`, with every fake model returning `supported` by default |
| A4 isolation | tested | tested | unchanged. One build, one namespace; both new agents bind the run's index |
| A5 framing | partial | **tested** | `test_framing_linter.py` — a framing block carrying a fact is demoted, and the demotion blocks the build |
| A6 reproducibility | partial | **partial** | `test_manifest.py`. Deliberately not raised: A6's headline claim is unachievable as written (B29), and marking the cell `enforced` against a statement we know to be wrong would be the dishonest kind of green |
| A7 gates | tested | **tested** | `test_cli_gate2.py::test_none_of_the_new_commands_can_record_an_approval` — a banned-parameter check *and* a source scan for `.approve(`, because a parameter check alone misses a command that hard-codes one |
| A8 uncertainty | enforced | **tested** | `test_report.py` — `open_risks` resurface in the report; conflicts appear with both spans; `test_validation.py` — a provider failure returns `unverified` with a reason, never a guess |

Five invariants move to `tested` this phase; A6 deliberately does not, and A4 is untouched.

**A3's ceiling is the design to understand before changing anything here.** Borrowed from
`evidence_gap.py`: retrieval is deterministic and separate, the model returns a judgement,
and the bound is applied to that judgement **afterwards** rather than asked for in the
prompt. A model that ignores every instruction still cannot produce `supported` with zero
retrieved evidence, because the code will not let the value through. Prompts are advice;
only code is a constraint.

## 6. Spike and experiment findings

### 6.1 The line-height constant was under-predicting by ~7.4%, in the dangerous direction

`budgets.py` derived line pitch from the font's hhea `ascent + descent` — 1.1172 for
Liberation Sans. LibreOffice renders **1.20**, and the gap is proportional at every line
spacing, not only at 1.0 as first reported.

Under-prediction is the direction that hurts: the content agent is told "this much fits",
writes to that budget, and the text overflows at render — which is v1's defining failure.

The constant is now measured, not derived, and the check that established this is worth
keeping: five font families with metrics ranging 1.059–1.200 all rendered at exactly 1.20.
**It is an engine/OOXML convention, not a value read out of the font.** My own hypothesis —
that hhea `ascent + descent + lineGap` would reach 1.20 — was checked and is wrong; it
reaches 1.150, and OS/2 typo metrics give 1.088. Neither matches. The empirical constant was
the honest answer, and the agent that reported this rather than fitting the data was right.

### 6.2 The cross-check could not have caught it, and looked like agreement

The first LibreOffice cross-check compared rendered **ink height** against the predicted
**line box**. Those differ by design, so the comparison carried a tolerance wide enough to
swallow the bias — and the reported deltas (+1.1%, +5.5%, +0.3%) read as agreement while
actually being two errors in opposite directions cancelling. `budget_check.py` now measures
**line pitch**, which is the quantity the prediction is about. `RENDER_TOLERANCE` went
0.06 → 0.15 because the old value had been calibrated against the biased prediction.

The general lesson, worth carrying into Phase 3b's QA: *a cross-check that measures a
different quantity than the thing it is checking will report agreement it has not
established.*

### 6.3 Derivation laundering: a derivation could cite real spans and still invent its inputs

B13 gave `DerivationInput` both a value and a citation so re-execution would not have to
guess which numeral in a span was meant. Nothing required the value to actually **be** in
the quote. Reproduced directly: a derivation with two real citations, correct arithmetic,
and input values 900/300 against quotes reading 671/412 passed the IR, passed the citation
check, and re-executed cleanly. It traced to itself.

`check_derivation_inputs` closes it. This is the shape of hole to look for elsewhere: a
check that verifies the *relationship between two fields* while never verifying that either
field corresponds to anything outside the record.

### 6.4 A clean `Deck` is no longer sufficient evidence that A1 and A5 hold

The framing linter's demotion is correct and blocking — but the demoted block **stays in the
deck typed `framing`**, where it validates perfectly and `Deck.blocking_blocks()` returns
empty. Verified:

```
framing findings: 2 | blocks_build: True
demoted kind: claim | verdict: unsupported | blocks_render: True
Deck.blocking_blocks(): []          <- empty. The deck alone looks clean.
```

A render guard consulting only the deck ships the demoted block. The same shape turned up a
second time, found by the implementing agent unprompted: a validation pass that fails
outright *also* leaves `blocking_blocks()` empty, so an unvalidated deck reads as passing.

Both are closed by a single function, `require_safe_to_render`, whose docstring states the
trap explicitly — because the next person to add a check will otherwise add it at a call
site, and three checks at three call sites is how one gets forgotten. GATE 2's criterion 1
is deliberately broadened to fail on `unverified` for the same reason.

### 6.5 The validation prompt asked a model for something no model can produce

`prompts/validation.md` was written as though the model returns citation objects with
`doc_id`, page and bbox. A model cannot compute a bounding box or a SHA-256. The agent
implementing the wrapper reported this as an interface finding rather than working around
it — the right call — and the prompt now asks for **verbatim quotes**, which the system
resolves back onto real spans, with an unmatched quote being dropped.

### 6.6 "Byte-comparable" is not achievable for PPTX (B29, open)

Measured: two identical `Presentation().save()` calls two seconds apart produce different
bytes, from at least four causes outside our control, while the canonical digest matches.
A6's headline and A6's own "watch for" line contradict each other. The manifest implements
the achievable property and refuses to name anything `bytes_match`. **The invariant's
wording is the owner's to change**; a proposed correction is in B29.

### 6.7 The send-back mechanical check is half a defence, and says so

`autodeck content` drops a new claim whose text matches a rejected claim's snapshot. That
catches literal regeneration only. A model that rewords a rejected assertion produces text
the check cannot recognise; that half is advisory prompt context, the same posture as the A8
hedging instructions. `send_back.py`'s docstring states this rather than implying the check
is complete. Confirmed load-bearing by disabling the comparison: exactly one test goes red,
and it is `test_a_sent_back_claim_does_not_survive_verbatim`.

### 6.8 Two component slots had no budget coverage at all

`check_overflow` cannot protect content it has no slot for. `big_number.supporting_points`
had none — and worse, populating that field switches the renderer to a two-column layout, so
the *existing* slots' widths were wrong by half in that mode. `two_column_compare` modelled
one point per column where the real content model is a list. Both are covered now, with
geometry imported from the renderers rather than retyped. The catalog's stated reason for
capping `point` to one line was checked against the renderer and does not hold; the comment
is corrected.

## 7. Known gaps, risks, and debt carried forward

| Gap | Why it matters | Owner |
|---|---|---|
| **No live Phase 2b milestone** | Everything is fixture-verified; the real corpus and a real model have not met this code | **Owner, §10** |
| **A gate approval does not survive the machine (B30)** | `runs/<id>/state.json` is not committed, so who approved what and when is ephemeral. An approval is the one thing in a run that is *not* reproducible | **Owner decision at GATE 2** |
| **B29 open** | A6's headline is unachievable as written; the invariant is deliberately unedited | **Owner decision at GATE 2** |
| **Should A5 fence `section_header`?** | A section header is framing by nature, but nothing stops one carrying a fact | **Owner decision at GATE 2** |
| **The seed corpus is still synthetic** | Public papers, fictional clients. Fine for building; the first real deliverable needs real folders | Phase 4 |
| **All four key messages are `unprobed`** | The evidence-gap classifier hit the daily quota mid-run at GATE 1 and has never completed on a full brief. Phase 2b's validator is the next chance to catch what it would have found | Owner, at the milestone run |
| **Dev capacity is 20 requests/day/model** | A ten-slide deck costs roughly one `content` call per slide plus one `validation` call per six claims. Roles are spread across five models (B25), and it is still tight | Ongoing |
| **Nobody has typed into `autodeck plan`** | Carried from Phase 2a, and now on the critical path: the milestone run starts with that REPL | Owner, §10 |
| **Aptos is a hard prerequisite** | Budgets are wrong-by-default on a machine without it. `LINE_HEIGHT_FACTOR` is engine-level and holds, but per-glyph widths are not | Phase 3a |

## 8. Model routing: planned vs actual

`docs/MODEL_ROUTING.md`'s rule, and B28's application of it: **guardrail paths keep their
tier; everything else may be de-escalated under budget, and every de-escalation is named
here.** The cost of over-tiering is money; the cost of under-tiering is a defect in an
accuracy-critical path.

| Task | Brief says | Actually ran on | Why |
|---|---|---|---|
| 2b.1 budgets engine | Opus | **Sonnet** | Budget de-escalation. Outside every guardrail path. §6.1's bug was found on review, not by the tier |
| 2b.2 slot budgets | Sonnet | Sonnet | — |
| 2b.3 `prompts/content.md` | Opus | **Opus** | `prompts/` is a guardrail path |
| 2b.7 `prompts/validation.md` | Opus | **Opus** | `prompts/` is a guardrail path |
| 2b.5 numeric linter | Opus | **Opus** | `autodeck/audit/` is a guardrail path |
| 2b.6 framing linter | Opus | **Opus** | `autodeck/audit/` is a guardrail path |
| 2b.8a verdict core | Opus | **Opus** | **Split out of `agents/validation.py` on purpose** so A3's rule lives in `autodeck/audit/` rather than being de-tiered with the plumbing (B28) |
| 2b.8b validation agent | Sonnet | Sonnet | Plumbing only; it imports the rule and cannot soften a verdict |
| 2b.4 content agent | Sonnet | Sonnet | — |
| 2b.9 audit report + 2b.10 manifest | **Sonnet** | **Opus** | *Escalated.* `autodeck/audit/` is a guardrail path, and B28's rule is that the path wins over the tag |
| 2b.11 GATE 2 surface | Sonnet | Sonnet | `cli.py`, outside the guardrails. The A7 property it must not break is asserted by a test rather than trusted to the tier |
| This handover, `DECISIONS.md` | Opus | Opus | `docs/handovers/` and `DECISIONS.md` are guardrail paths |

**One de-escalation, two escalations, one split.** 2b.1 is the only Opus-tagged task that
dropped a tier — it touches no guardrail path, and §6.1's bug was caught on review rather
than by the tier. 2b.9 and 2b.10 went the other way: the brief tags them Sonnet, but they
land in `autodeck/audit/`, and under B28 the path wins over the tag. 2b.8 was split so that
A3's rule could sit in a guardrail path while its plumbing did not.

Spend across the phase: **$26.87** of the $50 ceiling, eight dispatches. Observed rates —
a substantial Sonnet dispatch is ~$1.40–2.10, an Opus one $3.43 (prose) to $6.08 (code).
The ledger lives in the session scratchpad.

## 9. Preconditions for the next phase

1. **GATE 2 judged** on a real claims table. Phase 3a can be *built* without it under B27's
   stacking, but a GATE 2 rejection invalidates whatever was built on top — an accepted cost
   the owner agreed to, stated again here so it is not a surprise.
2. **B29 answered.** Phase 3b's post-render lint and the final manifest both depend on what
   A6 actually promises.
3. **Aptos confirmed on the owner's machine**, carried from GATE 0. Phase 3a builds fifteen
   component renderers on top of the budgets this phase fixed.
4. **The icon and theme behaviour checks from GATE 0** — approved on the visual bar only,
   and Phase 3a is where they must be verified before more is built on them.

## 10. Verifying this phase from a cold start

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest -q -m "not live"        # 736 passed, 13 skipped, 10 deselected
```

Each linter ships a "disable the defence, confirm red" test, so the claims above can be
re-verified rather than taken on trust. The one for the send-back cycle: comment out the
text comparison in `cli.py`'s `matches_a_send_back` and re-run `tests/test_cli_gate2.py` —
exactly one test fails, and it is the one whose name says what it protects.

**The live milestone, which is what GATE 2 actually reviews:**

```bash
export GEMINI_API_KEY=...
uv run autodeck plan northwind-milestone --client northwind-retail --project llm-inference-efficiency
#   a conversation. `/brief` shows the draft; `/sign <your name>` ends it. There is no flag.
uv run autodeck outline northwind-milestone --client northwind-retail --project llm-inference-efficiency
uv run autodeck approve northwind-milestone outline      # GATE 1 — your judgement, not the report's
uv run autodeck content  northwind-milestone --client northwind-retail --project llm-inference-efficiency
uv run autodeck validate northwind-milestone --client northwind-retail --project llm-inference-efficiency
uv run autodeck gate2    northwind-milestone
```

`gate2` prints the audit report, a stable `slide_id:block_id` per claim, and the brief's six
checkable criteria, exiting non-zero on a failure. **A clean run there is not the gate.** The
six criteria are what a machine can check; whether the deck's argument is honest is what you
are being asked. To reject specific claims:

```bash
uv run autodeck send-back northwind-milestone --claim s3:b2 --reason "throughput figure is the authors' own benchmark, stated bare"
```

Budget the quota: 20 requests per model per day, roughly one `content` call per slide and
one `validation` call per six claims, spread across five models by B25.

## 11. Reading notes for the next implementer

**Read `autodeck/agents/evidence_gap.py` first, then `autodeck/audit/verdicts.py`.** The
second is the first's sibling and shares its shape deliberately. Once the ceiling pattern is
in your hands — deterministic retrieval, model judgement, bound applied afterwards — most of
this phase reads as one idea applied five times.

**The linters' normalisation tables are declarative on purpose.** Every row in
`SCALE_TABLE`, `UNIT_TABLE` and friends carries a `why`, and `_check_table_collisions()`
raises at **import** if two rules claim the same surface form. Add a row, do not add a
branch. `Decimal`, never `float`: `3.2 * 1e6 == 3200000.0000000005` is exactly the kind of
mismatch A2 exists to catch, and it would be ours.

**Formulas are re-executed by AST walk, not `eval`.** They are model-generated text. This is
a security property, not a style preference.

**`require_safe_to_render` is the only place that knows what safe means.** If you find
yourself adding a fourth condition at a call site, add it there instead.

**Nothing in `cli.py` may approve a gate**, and a test enforces it by scanning each command's
own source for `.approve(`. If you add a command that touches a run, expect that test to
have an opinion about it.

**The prompts are advice; only the code is a constraint.** Both `prompts/content.md` and
`prompts/validation.md` are written to a model that might ignore them, and every promise
either makes that *matters* is also enforced in code. When you change a prompt, ask which
half you are changing.
