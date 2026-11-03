# Phase 4a/4b + design pass: deck craft, providers, design — Handover

> Written 2026-10-14 by Opus, mid-stream: the owner asked for a handover while the next
> piece of work (consulting-grade components) was being scoped. Section 9 says exactly where
> to pick up.

---

## 1. Identification

| | |
|---|---|
| **Phase** | 4a (deck-craft skills), 4b (providers + tool calling), plus a design pass. Plan: `~/.claude/plans/sequential-swinging-quokka.md` (owner-approved 2026-10-05) |
| **Branch** | `v2/integration` |
| **PR** | none. **Nothing is committed.** About 114 changed or untracked paths are on the working tree, on top of the uncommitted Phase 3c/3d and B53–B58 work. |
| **Started / completed** | 2026-10-04 → in progress (2026-10-14) |
| **Gate** | none (no A7 gate changes) |
| **Gate status** | n/a |
| **Approved by / when** | The plan was approved 2026-10-05. Individual decisions are recorded in DECISIONS B59–B68, with the owner's words where they gave them. |
| **What the owner actually checked** | <ul><li>Ran the UI on `dev-mistral` (run XLP).</li><li>Reviewed the gold-deck contact sheets.</li><li>Judged the gold decks "plain, not what consulting decks look like" (2026-10-14). That is the open item.</li><li>Asked for one last Gemini run, then its removal.</li><li>Added an OpenAI key; it is rejected as invalid (§9).</li></ul> |

## 2. What shipped

| Path | What it does | Tests |
|---|---|---|
| `prompts/skills/*.md` (13 files) | Deck craft as modular skills. Each has front matter (`name`, `summary`, `use_when`) and a body. `deck-thinking` is the core; `exemplars` holds the gold decks, tagged per project; `visual-review` is for the future agent. All examples use invented subjects (drug A, ALPHA trials, model M). | `tests/test_skills.py` |
| `autodeck/agents/skills.py` | Loader. `SKILL_SETS` fixes each writer role's skills, in order. `skills_text(role, project=)` withholds the run's own gold exemplar (B65). | `tests/test_skills.py` |
| `prompts/compose.md`, `content.md`, `components.md`, `redesign.md`, `revise.md`, `repair.md`, `validation.md` | Role files trimmed to what is role-specific. `validation.md` gained the talking-headers rubric (B62) and a rule that same-strength synonyms are carried (B64). `repair.md` gained split and single-slot rules. | prompt tests in `test_compose.py`, `test_content_diagrams.py` |
| `autodeck/agents/compose.py` | `_writer_system(role=, project=)`. `_drop_still_failing` removes draft-check failures after repair (B62). `revise_deck` runs the draft checks on the slides it rewrote. | `test_compose.py`, `test_repair.py` |
| `autodeck/agents/draft_checks.py` | `drop_failed_blocks` (B62) | `test_repair.py`, `test_compose.py` |
| `autodeck/agents/validation.py` + `ir/models.py` (`HeadlineCheck`, `Slide.headline_check`) | The validator judges every talking headline against its slide's claims. `overstates` blocks render and fails GATE 2. The UI shows it (B62). | `tests/test_validation.py` (4 new) |
| `autodeck/pipeline/orchestrator.py`, `audit/gate2.py`, `render/draft.py`, `ui/api.py`, `ui/static/app.js` | Overstated headlines in the render guard, GATE 2, draft flags and the UI inspector | as above |
| `autodeck/agents/evidence_pack.py` | The person's clarify answers become queries (`extra_queries`). The opening paragraphs of each corpus section are added (`section_lead_spans`) (B64). | `tests/test_evidence_pack.py` (3 new) |
| `autodeck/agents/content.py` | `check_budgets` gained two checks. A second block in a single-block slot is rejected (B64). A **trial layout** draws the real component renderer on a throwaway slide and drops optional parts until the slide fits (B67). | `tests/test_content.py` |
| `autodeck/providers/openai_compat.py`, `openai.py`, `nebius.py`; `mistral.py` rebased; `claude.py`, `base.py`, `guard.py`, `registry.py` | OpenAI-compatible base and tool calling: `converse()`, `Message`, `ToolSpec`, `AssistantTurn`, with conversations cached in full. Gemini and Groq are removed; `default_env: dev-mistral` (B66). | `tests/test_tool_calling.py` (20), updated `test_providers.py`, `test_registry.py` |
| `autodeck/design/charts.py` | Bar, column and area charts start at zero (B63). Horizontal bars read top to bottom. Tick labels use the data's own precision (B67). | `tests/test_charts.py` |
| `autodeck/design/components/renderers/closing_cta.py` | CTA text sits inside its panel (B67) | `tests/test_render_draft.py` |
| `autodeck/render/draft.py` | A `LayoutOverflowError` or `ChartConstructionError` becomes a placeholder, not an aborted preview. Explicit placeholder colours. Draft marker at 5.4:1 contrast (B67). | `tests/test_render_draft.py` |
| `config/tokens/dev.json`, `aptos.json`; `design/components/renderers/bullets_supporting.py`; `design/layout_kit.py` (`Stack.placed_boxes`); `catalog.TARGET_LINES["body"]=4` | Type scale is 18/24/32/54. Bullets use `dk1` text, an accent "•", row gaps that grow with the free space, and tinted hairlines (B68). | full suite |
| `scripts/check_gold.py` | Runs a gold deck through `compose._build` against the whole corpus. Any snap, drop or A2 finding counts as a failure. | manual: all three decks CLEAN |
| `knowledge/projects/transformer-attention/`, `lejepa-ssl/` + `corpus/` | Two new single-paper projects. Git-excluded via `.git/info/exclude`. | — |
| `knowledge/projects/*/gold/*.json` | Three hand-written gold decks: oral semaglutide for a P&T committee, Transformer for a CTO, LeJEPA for a CTO (question-led). Git-excluded (B63). | `check_gold.py` |

**Suite:** 1,807 passed, 52 deselected, with `AUTODECK_FONT_DIRS=$HOME/.local/share/fonts`.

## 3. What did not ship

| Task | Why deferred | Now owned by |
|---|---|---|
| **Consulting-grade components** (owner asked for all of them) | Scoping had just begun when the handover was requested. | **Next session: start here (§9).** |
| Phase 4c: deck agent session (skills on demand, advisor, check/render tools, corpus index, resume for revise) | The owner prioritised design | after the components |
| Phase 4d: validator strength layer and round-trip check; align gate-first prompts with the skills | not started | after 4c |
| Joint budgets in the catalog | Each slot's published ceiling still assumes it owns the region. The trial layout (B67) is the safety net, not the fix. | design work, with the components |
| `icon_pillars` in drafts | Only gate-first art direction assigns icons, so a draft always shows a placeholder. | design work |
| `evidence_with_figure` | Draws no figure; its "figure" slot is italic text. | design work |
| Weak composition | `two_column_compare` with only titles; one data card filling the body; oversized two-step chevrons; series within a bar cluster stacked bottom-up | design work |
| Seven deferred test layers | The owner deferred them (2026-10-05) | memory `deferred-test-layers.md` |
| Commits | Never requested. Repo rule: each prompt file is its own commit with its rationale. | owner's call |

## 4. Decisions made this phase

- **B59** Deck craft lives in skill files.
- **B60** Labelled "Implication:" inferences are allowed on body slides.
- **B61** The writer chooses answer-first or question-led.
- **B62** Talking headlines get a verdict; failing draft blocks are dropped.
- **B63** Gold exemplar decks are the bar; charts are zero-based; number traps added to `citations`.
- **B64** The evidence pack reads section openings and the person's answers; examples are fictional; skill sets per role; one block per single slot.
- **B65** A draft never sees its own project's gold exemplar.
- **B66** Gemini and Groq removed; OpenAI-compatible base with Nebius and OpenAI; tool calling.
- **B67** A slide must fit as a whole before render; gallery fixes.
- **B68** 1.33 type scale; bullets that fill the slide.

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | tested | tested (unchanged) | `test_content.py`, `test_snap.py` |
| A2 numbers | tested | tested. Failing blocks are now dropped before the IR; revise checks too. | `test_repair.py::test_a_block_still_failing…`, `test_compose.py::test_revise_runs_the_draft_checks…` |
| A3 validation | tested | tested, extended to headlines (B62) | `test_validation.py::test_an_overstated_headline…` |
| A4 isolation | tested | tested; exemplars withheld per project (B65) | `test_skills.py::test_a_projects_own_gold_exemplar_is_withheld` |
| A5 framing | tested | tested | — |
| A6 reproducibility | tested | tested; skills hashed; `converse` cache key covers messages and tools | `test_skills.py`, `test_tool_calling.py` |
| A7 gates | tested | unchanged | — |
| A8 uncertainty | partial | partial; prompt-level only (`fidelity` skill) | — |

## 6. Spike and experiment findings

All live runs used `dev-mistral` (writer `ministral-14b-2512`, validator `ministral-8b-2512`). Runs live in `runs/XLP*`.

- **XLP** (first run on the skills): every slide got a body, but only about 100 body words in total. The overclaiming headline got through. Failed draft blocks reached the IR (fixed in B62).
- **XLP2**: the evidence pack used 8.5k of its 24k-token budget and lacked the paper's key results. The model quoted a skill example's invented "−1.3% vs −0.9%" as evidence (fixed in B64).
- **XLP3**: a repair split a point into meaningless halves, and two blocks in one slot produced a placeholder (fixed in B64).
- **XLP4**: the writer stated the PIONEER 2 result correctly. The **validator is the weak link**: `ministral-8b` marked that correct claim unsupported and raised headline false positives. It needs a stronger model (B44 forbids the writer's model).
- **Clarify isn't deterministic** on Mistral even at temperature 0, so scripted `--answer q1=…` can land on different questions. Read the questions before answering.
- **Gemini, 2026-10-13**: compose returned HTTP 503 twice. Removed.
- **Design stress gallery** (scratchpad harness, not committed; recipe in §10). Every component was rendered at minimal fill, at target, at 60% of the ceiling and at the full ceiling. Findings:
  - **Deterministic QA catches geometry, not composition.** It returned 0 findings on the gold decks, which looked plain.
  - **Per-slot ceilings are not jointly achievable**, though targets mostly are (B67, B68).
  - **Only the dev (Carlito) theme is testable on this Mac.** `aptos` and Northwind need Aptos Display Bold, which PowerPoint's bundled `DFonts` doesn't include.
- **Writing the gold decks by hand hit the same A2 traps as the model.** Writing "points" for "%", adding "%" to a bare table number, a quote that lacks the week the sentence states, and hyphenated number-words. All are now in `citations.md`.

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| Decks look plain; component library is generic | Owner rejects the visual quality | next session (§9) |
| `ministral-8b` validator: false "unsupported" and false "overstates" | Correct slides blocked; noise in review | needs a working OpenAI (GPT 6 Luna) or Nebius key, then a validation-model choice |
| ~114 uncommitted paths | Loss or confusion | owner decides on commits |
| `.env` holds unused Gemini/Groq keys | Credential hygiene | owner: revoke |
| Runs saved with `env: dev` no longer load (env removed) | Old runs unusable | accept, or migrate `state.json` |
| Gate-first prompts (planner, outline, art_direction, aesthetic_critique) not aligned with the skills | Two crafts in one product | 4d |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| Skill and prompt writing, DECISIONS, IR (`HeadlineCheck`) | Opus | Opus | — |
| Skills loader and wiring | Sonnet | Sonnet | — |
| Phase 4b adapters and provider removal | Sonnet | Sonnet (reviewed by Opus) | — |
| Gold decks, design fixes, trial layout | Opus / Sonnet | Opus | Needed visual judgement and fast iteration |

## 9. Preconditions for the next phase

1. **OpenAI key.** `.env` `OPENAI_API_KEY` returns 401 `invalid_api_key`. It is 106 characters and probably truncated. The owner should re-paste it.
   - **Use only GPT 6 Luna** (owner's instruction, 2026-10-13). Get its exact id from `GET /v1/models` (match "luna"). Never call another OpenAI model.
   - Then: one live `complete_structured` and one `converse` round trip, then consider Luna as the `validation` model in a new environment.
2. **Next work, which the owner asked for: consulting-grade, "visually appealing" decks.** There are no reference decks. Owner: "claude generates beautiful decks". Priority is everything, in this order:
   - **Visual language and chrome.** Section tracker top-left, page numbers, stickers ("Preliminary", "Illustrative"), numbered footnotes, applied to every content slide.
   - **Structured text and executive summary.** Numbered rows with a bold lead-in and detail. This should replace most `bullets_supporting` slides.
   - **Chart with takeaway panel.** Chart on the left two-thirds, numbered so-whats on the right. Focal categories highlighted in the accent, the rest grey. That needs an optional highlight field on the IR `ChartSpec` (Opus path).
   - **Column grid** of 2–4 headed columns.
   - **Table** with highlighted cells, ticks and Harvey balls. Needs a new IR payload with citations per row (Opus path).
   - **Frameworks.** Expose the existing `two_by_two` diagram renderer to the writer (`ProposedDiagram.relationship` is "sequence"-only); add a waterfall and an issue tree.
   - **Then** rewrite the three gold decks with these components, and update `components.md`, the `slide-bodies` recipes and `exemplars.md`.
3. **How a component is wired.** Read these in order:
   - `catalog.register(...)`, which takes name, narrative roles, renderer, content dataclass, preview, and slots or variants;
   - the slot builder (`_data_card_grid_slots` is a good model for 2-D grids);
   - the renderer (`renderers/data_card_grid.py`);
   - `render.renderer.adapt_slide`, which maps dataclass fields to block slots by name; paired lists like `card_value`/`card_label` are matched by order;
   - golden previews (`autodeck components preview`);
   - `tests/test_components_*.py`;
   - the writer-facing budget text (`catalog.render_budgets`, `_describe_slot`, `target_chars`).

   Every new component must pass the stress gallery at its targets and must be added to the `content.check_budgets` trial layout (automatic, through the renderer).

## 10. Verifying this phase from a cold start

```bash
cd "/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck"
AUTODECK_FONT_DIRS="$HOME/.local/share/fonts" .venv/bin/pytest -q
# expected: 1807 passed, 52 deselected

for pair in oral-semaglutide:pt-committee transformer-attention:cto-architecture lejepa-ssl:cto-in-domain-pretraining; do
  p=${pair%%:*}; g=${pair##*:}
  AUTODECK_FONT_DIRS="$HOME/.local/share/fonts" .venv/bin/python scripts/check_gold.py $p knowledge/projects/$p/gold/$g.json | tail -1
done
# expected: CLEAN, three times

.venv/bin/autodeck models
# expected: environment: dev-mistral; ministral-14b-2512 / ministral-8b-2512 bindings
```

Live draft, which costs cents on the owner's Mistral allowance:

```bash
.venv/bin/autodeck clarify RUNID --client pharma-demo --project oral-semaglutide --prompt "Evidence summary for a hospital P&T committee on oral semaglutide for type 2 diabetes. Five slides. Clinicians who will ask which trial a number came from."
# read the questions, then: autodeck answer RUNID --answer q1="…" …
.venv/bin/autodeck draft RUNID && .venv/bin/autodeck validate RUNID && .venv/bin/autodeck preview RUNID
```

**Stress gallery.** The harness lived in the session scratchpad and is gone. To rebuild it:
1. Build a `ComposeDraft` with one slide per component and fill level. Find each slot's limit by binary-searching text length against `catalog.check_overflow`. Parse targets from `catalog.render_budgets`.
2. Resolve it with `compose._build` against `scripts/check_gold.whole_corpus_pack`.
3. Render each slide alone with `render.draft.render_draft`, catching errors and placeholders. Run `render.qa.deterministic.run_deterministic_qa`, then make contact sheets with PIL.

Worth committing as `scripts/design_gallery.py`.

## 11. Reading notes for the next implementer

- **Read first:**
  - `prompts/skills/deck-thinking.md`, then `slide-bodies.md`, then `exemplars.md`;
  - `DECISIONS.md` B59–B68;
  - memory files `deck-craft-skills-agent-plan.md`, `gold-exemplar-decks.md`, `deferred-test-layers.md`.
- **The owner's stance:** quality must come from prompts and model-independent checks, not model choice. They prefer to be told plainly what failed. "Don't wait for me" means act and report.
- **Deliberate, though it may look wrong:**
  - `exemplars.md` contains real facts and quotes. They are checked against the corpora and withheld from drafts on the same project (B65).
  - Every other skill example is invented on purpose.
- **Surprises:**
  - The biggest quality lever was the evidence pack, not the prompt (XLP2).
  - The biggest design defect was in the budget engine, not the renderer.
  - My own zero-axis chart fix caused a float-noise tick (fixed in B67). Re-render after every design change; don't trust unit tests alone.
- **What I'd do differently:**
  - Build a reusable design gallery script in the repo from day one.
  - Design the gold decks around a richer component set. Using plain components produced plain decks, which is exactly the owner's latest complaint.
