# Phase 3b — Renderer, QA & art direction — Handover

> The phase's defining constraint, in its brief's own words: "the aesthetic loop may never
> edit claim text or citations. This must be structural — enforced by the action space's
> type system — not a prompt instruction."

---

## 1. Identification

| | |
|---|---|
| **Phase** | 3b — Renderer, QA & art direction |
| **Branch** | `v2/phase-3b-render-qa` — stacked on 3a (B27); task work landed via sub-branches `v2/phase-3b-*`, each merged `--no-ff` |
| **PR** | not opened. Nothing merges to `v2/integration` until the owner works the gates (B27) |
| **Started / completed** | 2026-09-27 → 2026-10-01 |
| **Gate** | GATE 3 (and GATE 2, carried from 2b, which the owner has not yet run) |
| **Gate status** | **pending** — implementation complete; owner review not started |
| **Approved by / when** | — |
| **What the owner actually checked** | Nothing yet. The owner's GATE 2 run and GATE 3's five PowerPoint checks are both outstanding; `docs/OWNER-GUIDE.md` walks through both. |

Suite at tip `6678e90`: **1327 passed, 51 deselected** (live + render); **41 render tests
passed** with `-m render`. Requires the B34 environment (`scripts/setup-dev-env.sh`).

## 2. What shipped

| Path | What it does | Tests |
|---|---|---|
| `autodeck/ir/models.py` — `SlideStyle` | Per-slide presentation state (type scale, accent, column balance, emphasis) as closed vocabularies. B36: `text` only on text kinds | `test_ir_models.py` |
| `autodeck/ir/actions.py` | The closed action set; `apply_action` with address, pin and fact-fingerprint checks; `AssignIcons` and `ArtAction` (B36); `facts_digest` | `test_actions.py` |
| `autodeck/render/renderer.py` | IR → PPTX in the client theme; slide tagging; `adapt_slide` + `ADAPTERS`; `placeable_slots` (the single placement authority) | `test_renderer.py` |
| `autodeck/render/extract.py` | Reads rendered text back per slide (face, notes, chart text) | `test_post_render.py` |
| `autodeck/audit/post_render.py` | Detection half: claim survival, numeric re-lint on rendered text (3b.8), slide set, image parts, `buAutoNum startAt` | `test_post_render.py` |
| `autodeck/render/qa/deterministic.py` | Overlap, safe area, minimum size, WCAG contrast; remedies by token/slot/catalog gap | `test_deterministic_qa.py` |
| `autodeck/render/qa/libreoffice.py` | True renders to PNG (D5); refuses on font substitution (B11) | render-marked |
| `autodeck/render/trial.py` | One acceptance rule for every presentation action: applies, renders (touched slide only), no new blocking grammar finding | `test_trial.py` |
| `autodeck/render/qa/aesthetic.py` | Bounded vision critique loop; returns the best *scored* deck; reverts on QA regression or audit failure | `test_aesthetic.py` |
| `autodeck/agents/art_direction.py` | Modes by rule, pins override; model taste via `ArtAction` | `test_art_direction.py` |
| `autodeck/design/headers/flow.py` | + repeated-opening and storyline-order findings (3b.9) | `test_header_flow_3b9.py` |
| `autodeck/design/components/renderers/icon_pillars.py` | First component that places a face icon (B35); `Stack.icon` draws the exact glyph | `test_icon_pillars.py` |
| `autodeck/design/diagrams.py` | Diagram shapes named `diagram:<kind>:<placement>:<n>` | `test_diagram_renderers.py` |
| `autodeck/audit/gate3.py` | Final assessment from disk; four checkable criteria; five human checks printed unticked | `test_gate3.py` |
| `autodeck/cli.py` — `render`, `gate3` | GATE 3 surface: deck, final audit report and manifest together | `test_gate3.py` |
| `autodeck/pipeline/orchestrator.py` | Approvals bound to artifact fingerprints; claims approval bound to facts | `test_orchestrator.py`, `test_owner_run.py` |
| `prompts/aesthetic_critique.md`, `prompts/art_direction.md` | 3b.4, 3b.6 — each its own commit with rationale | example outputs validated against their schemas |
| `docs/OWNER-GUIDE.md` | Step-by-step for GATE 2 and GATE 3 | captured from the real CLI with scripted providers |

## 3. What did not ship

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|
| 3b.7 — automatic section dividers | A divider's title is slide copy with no fact-safe source; the model may not write text (B36) | Owner (manual) or a future, separately designed mechanism; Phase 4 to decide |
| GATE 3 sign-off | Needs the owner, a live run and PowerPoint | Owner |
| Live verification of the vision critique and art direction | No live API calls were made in this phase; behaviour is proven with scripted providers only | Owner's live run → Phase 4 (`sit` per A3/A8 model-sensitivity) |

## 4. Decisions made this phase

- **B29** — A6 "byte-comparable" corrected to normalised-comparable under a recorded normalisation (accepted by owner).
- **B30** — approvals do not survive the machine (open, owner decision).
- **B32** — Opus writes scaffolds, Sonnet fills.
- **B33** — registering a component is not a local change.
- **B34** — the environment is part of the project.
- **B35** — icon-anchored slides need a face-icon component first → `icon_pillars`.
- **B36** — art direction: modes by rule, taste by model; `AssignIcons`; IR `text` hole closed; icon blocks out of the fingerprint; no automatic dividers; `outline` role binding.

Not yet in the log, recorded here and in commit messages: claims approval bound to facts
(`facts_digest`), and pins rejecting only a move *away* from the pinned value. **Phase 4
should add these as B-entries** if the owner accepts them at GATE 3.

## 5. Invariant coverage delta

| Invariant | Before (P3a) | After (P3b) | Test that proves it |
|---|---|---|---|
| A1 citation | tested | **tested** | `test_post_render.py` (claim survival incl. diagram nodes); `test_renderer.py::test_claim_text_reaches_the_slide_character_for_character` |
| A2 numbers | tested | **tested** | `test_post_render.py` (rendered re-lint, `startAt`); `test_renderer.py::test_no_component_renders_a_word_or_number_its_content_did_not_hold` |
| A3 validation | tested | **tested** | `test_actions.py` (verdicts are inside the fingerprint); `test_aesthetic.py::test_fact_mutation_inside_apply_action_propagates_out_of_the_loop` |
| A4 isolation | tested | tested | unchanged |
| A5 framing | enforced | **tested** | `test_ir_models.py::test_only_text_kinds_may_carry_text`; `test_framing_linter.py` (defence in depth via `model_construct`) |
| A6 reproducibility | enforced | **tested** | `test_renderer.py::test_two_renders_are_normalised_comparable`; manifest written by `gate3` |
| A7 gates | tested | **tested** | `test_owner_run.py` (fingerprinted approvals), `test_gate3.py` (claims bound to facts; render/gate3 cannot approve), `test_orchestrator.py::test_no_command_can_bypass_a_gate` |
| A8 uncertainty | tested | tested | `test_aesthetic.py` / `test_art_direction.py` (model errors reported, never guessed) |

## 6. Spike and experiment findings

- **The first whole-deck render failed the post-render audit four ways** — a diagram node's
  claim not on the slide, a bare "Source:" caption, agenda ordinals the IR never held, and
  renderer-composed text (title separator, a default callout label). Each was fixed in the
  design, not by loosening the audit. Lesson: the detection half earns its keep immediately.
- **Deterministic QA found 13 real defects in golden previews the owner had already seen**
  (contrast, overlaps). Previews look right at a glance and fail arithmetic.
- **"Look at the PNG" was decisive for `icon_pillars`.** All automated checks passed on a
  first version that was visibly too sparse; two design rounds were driven entirely by
  looking at the image.
- **Two descriptions drift, again.** The catalog's text slots and the renderer's placement
  disagreed (charts/diagrams missing, computed `source` present) → `placeable_slots` as the
  single authority. The aesthetic loop's acceptance rule had to be shared with art
  direction → `trial.try_action`.
- **A file-bound approval is voided by fact-identical presentation passes.** Binding the
  claims approval to `facts_digest` was the fix; it is strictly stronger for facts and
  correct for presentation.
- Negative: `accent3` on the dev theme fails contrast on a bullets slide; the loop reverted
  it correctly (`qa_regression`).

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| Vision critique and art direction never run against a live model | Prompt/behaviour mismatch discovered at the owner's first real render | Owner's live run; Phase 4 |
| `icon_pillars` label budget ≈ 16 characters at four columns | Content writer labels may be rejected for length | Phase 4 (content prompt guidance, or a 3-column variant) |
| Only `icon_pillars` can place a face icon | `icon_anchored` reachable through one layout only | Phase 4 catalog work if the owner wants more |
| Section dividers not automated | Long decks lack section structure unless added by hand | Phase 4 decision (B36) |
| B30 — approvals live in `state.json`, not committed | An approval can be lost with the machine | Owner decision |
| Approvals recorded before this phase's fingerprint changes read CHANGED | Re-approval needed — no real approvals exist yet | n/a unless approvals predate tip |
| Dev theme `accent3` contrast | Critique proposals using it are reverted, wasting a round | Real client template (Q5) |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| 3b.1 renderer | Sonnet | Opus scaffold → Sonnet | B32 |
| 3b.2 deterministic QA | Sonnet | Opus scaffold → Sonnet; Haiku for `count_decor_exempt` | mechanical follow-up |
| 3b.3 LibreOffice | Sonnet | Sonnet | — |
| 3b.4 / 3b.6 prompts | Opus | Opus | — |
| 3b.5 aesthetic loop | Opus | Opus scaffold (+ amendment) → Sonnet | B32; the filler's review found two scaffold flaws, fixed by amendment |
| 3b.7 art direction | Sonnet | Opus scaffold → Sonnet | design was not mechanical (B36): modes-by-rule, IR text hole, fingerprint scope |
| 3b.8 post-render re-lint | Opus | Opus scaffold → Sonnet; Haiku for `startAt` | — |
| 3b.9 header flow | Sonnet | Opus scaffold → Sonnet | B32 |
| 3b.10 GATE 3 surface | Sonnet | Opus scaffold → Sonnet | B32; scaffold named a non-existent shape prefix — filler stopped correctly |
| B35 `icon_pillars` | — | Opus scaffold → Sonnet, three design rounds | design driven by inspecting the PNG |
| Owner guide | — | Sonnet, captured from the real CLI | — |

Systematic deviation: every "Sonnet" task gained an Opus scaffold (B32). The brief's tags
describe who writes the bodies, not who sets the contracts.

## 9. Preconditions for the next phase

- [ ] Owner runs GATE 2 on a live build and approves (or sends back) the claims.
- [ ] Owner runs `autodeck render` and `autodeck gate3` live, performs the five PowerPoint checks, and approves `final_render` — or records which check failed.
- [ ] Owner answers the open decisions: B30; the A5 `section_header` fence; chart verdicts; `split_rows` exception type (see `STATUS.md`).
- [ ] Owner accepts (or rejects) the two un-logged changes in §4 so they become B-entries.
- [ ] Real client template (Q5) and Aptos availability confirmed for Phase 4.

## 10. Verifying this phase from a cold start

```bash
git checkout v2/phase-3b-render-qa
bash scripts/setup-dev-env.sh      # Inter fonts, libreoffice-impress, poppler-utils (B34)
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
# expected: All checks passed! / 150 files already formatted / 0 errors
uv run pytest -q
# expected: 1327 passed, 51 deselected
uv run pytest -q -m render
# expected: 41 passed
uv run autodeck components preview
git status --short autodeck/design/components/previews
# expected: no output (all 16 golden previews regenerate byte-identical)
```

## 11. Reading notes for the next implementer

Read `autodeck/ir/actions.py`'s module docstring first. Everything that makes the
presentation passes safe is there: the action types cannot express text, addresses are only
looked up, pins are structural, and every applied action is fingerprint-checked. The
aesthetic loop and art direction add no safety of their own and must never need to — if one
ever seems to, the hole is in the types.

Then `render/trial.py` — the single acceptance rule — and `audit/post_render.py`, the
detection half. Prevention and detection were built independently on purpose; neither
alone was enough during this phase (the first render proved detection's worth; the IR
`text` hole showed prevention had a gap nobody had tested).

What looks wrong but is deliberate: communication mode is a rule, not a model output (B36);
the aesthetic critic is never shown the slide's words, while the art director is (its
output still cannot carry text); `render` has no options at all, because any option that
skipped a stage would look like a gate bypass.

What I would do differently: write the placement authority (`placeable_slots`) before the
first consumer of slot names, not after the second. Twice this phase a contract named
something that did not exist (a shape prefix, a catalog slot set); both times the Sonnet
filler stopped and said so rather than inventing it, which is the behaviour to keep
asking for.
