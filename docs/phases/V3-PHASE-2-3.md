# v3 Phase 2-3 — Layers, routing and the design layer

**Branch:** `claude/autodeck-principles-review-zp7nsm` · **Source:** `docs/AUTODECK_V3_PLAN.md`
P4, P5, P7, V5, §4, §6, §7, §8.3, §12 Phases 2 and 3; the slide bench (`bench/slides/`,
results in `bench/slides/results/README.md`).

> **Done when:** the studio stops asking one model to do everything. The lead decides
> direction in words; a design system is decided once; each slide is designed in its own
> focused call; small edits skip the lead; and every turn records which layers ran and what
> they cost.
>
> The exit test is `tests/studio/test_phase23_done.py`, on the real knowledge pair
> `northwind-retail` / `llm-inference-efficiency` with scripted models per role
> (`tests/studio/fixtures/scripts/design_flow.json`). Thread one: the lead writes three
> slide briefs and composes them (the designer, in the provisional default design); the
> owner says the deck looks generic; the lead proposes two design directions (the system
> layer makes each palette, the designer renders each on slide 2); the owner picks B with the
> button; the three slides are stale; the owner asks and they are recomposed. Thread two
> opens from state, and "Retitle slide 2 to ..." goes by rule to the mechanic. The test pins
> that the lead's model is never asked for a layout (no lead call is offered `write_slide`,
> no lead tool call carries a layout); that design tokens reach both layout QA (a spy on
> `render_adapter.check_slide` sees the night palette during recomposition) and the render
> (the renderer receives the deck with the palette, and `deck_tokens` gives it); that picking
> the design marks every composed slide stale and recomposing makes them fresh; that the
> retitle turn records the mechanic only (no lead call, no lead layer); and that every turn's
> layer and cost record is correct against assumed prices. The `render` version draws the
> recomposed deck with LibreOffice and checks the night-blue ground.

## Why this phase is shaped as it is

Phases 2 (layers and routing) and 3 (the design layer) of the plan are merged, because the
slide bench showed they are one piece of work:

- In the first real-model run, one model doing everything through the tool loop produced
  slides that passed layout QA and were generic (a title, a rule, paragraphs on white).
- At slide level the same models do well when given one slide's brief, a design concept with
  a palette and roles, and a prompt that teaches composition and the real layout arithmetic:
  `gpt-5.6-sol` clean on every slide it completed in one or two attempts, `gpt-5.6-luna` on
  14 of 16 in two to four, at about a fifth of Sol's cost. `gpt-5.4-mini` could not pass
  layout QA with the same brief.
- With a concept, separately designed slides read as one deck; without one they do not
  match. So the design is decided once, before slides are composed.
- A model shown its own render changed little. A separate reviewer is untested and out of
  scope here.
- A palette could not use `dk1`/`lt1` for its ground or ink, because v2's theme writer emits
  them as system colours; the bench patched its own PPTX. The studio does the same.
- The 5.6 models need the Responses endpoint for tools with reasoning; the bench's adapter
  proved it.

## How to use this document

The scaffold is written: the Phase 2-3 models in full (`models.py` additions, the top of
`design.py` and `usage.py`, `conversation.py`, `tool_args.py`, the bindings), the scripted
model per role (`scripted.py`), the prompts (`prompts/studio/lead.md` rewritten,
`designer.md`, `system.md`, `mechanic.md`, `router.md`), the small glue that needed no
judgement (the session constructor, the API's route field and health bindings, preview of
design options, `views.composition_view`, the Phase 1 handlers kept in `tools.py`), every
other function as a signature, type hints and a docstring with a `NotImplementedError` body,
the acceptance tests, the prepared script, and the front-end contract below. Each task fills
in the bodies of the files it owns until its tests pass. Tasks own disjoint files.

**Every test was checked against a prototype before it was written down.** The scaffolder
implemented every skeleton body in a throwaway prototype, ran the whole suite (all 483
default tests, `test_responses.py`'s five against their own prototype, plus the eight
`render` tests), and then restored the skeletons. Implementers write their own
bodies from the docstrings; the prototype is not part of the repository.

Rules for every implementer (Phase 1's, plus these lead files):

- Implement only the files your task owns. The docstrings are the spec; if one is wrong or
  ambiguous, stop and report it rather than guessing.
- Lead-owned, do not edit: `models.py`, `errors.py`, `paths.py`, `conversation.py`,
  `tool_args.py`, `scripted.py`, `prompt.py`, `bindings.py`, `responses.py`'s constants and
  `ImageMessage`/`StudioUsage`, everything above the marker line in `design.py` and
  `usage.py`, the constants, `ComposedSlide`, `TurnLedger`, `ToolContext` and the Phase 1
  handlers in `tools.py`, the prompts under `prompts/studio/`, `config/studio.yaml`,
  `config/studio_prices.yaml`, `tests/studio/helpers.py`, `tests/studio/conftest.py`,
  `tests/studio/fixtures/`. Do not change a signature.
- Do not modify any v2 file (`autodeck/` outside `studio/`, `config/models.yaml`, v2
  prompts, v2 tests), and do not import from `bench/`. Import from v2; move what is needed
  from the bench into the studio (the docstrings say what).
- Do not edit your tests to make them pass. If a test is demonstrably wrong, report it.
- No paid API calls. Every test runs on scripted models.
- Checks before handing back: `uv run ruff check` and `uv run ruff format --check` on your
  files, `uv run pyright autodeck/studio`, and your task's tests. A test that still fails
  must fail only with `NotImplementedError` from *another* task's file (or, for a test that
  starts a background turn, because the session's turn is not yet implemented).

Running the tests: `uv run pytest -q -p no:cacheprovider tests/studio` (default) and
`uv run pytest -q -p no:cacheprovider -m render tests/studio` (LibreOffice). Tests that run
the designer or the layout check need the Carlito font and skip without it.

## Tasks

| id | Wave | Model | Files owned | What to implement | Proven by | Depends on |
|---|---|---|---|---|---|---|
| 23.1 | 1 | sonnet | `autodeck/studio/design.py` (below the marker) | `default_design_system`, `design_tokens`, `deck_tokens`, `check_palette` (exact ratios and order), `findings_text`, `check_draft`, `slugify`, `DesignSystemStore` (immutable versions behind the engagement guard, the virtual default) | `tests/studio/test_design_system.py` | none |
| 23.2 | 2 | haiku | `autodeck/studio/design_render.py` | `patch_theme_colours` (the bench's, returning whether it patched), `build_designed_pptx`, `render_designed`, `render_with_design` (Phase 1's manifest mapping), `renderable` | `tests/studio/test_design_render.py` (and its `render` test) | 23.1 |
| 23.3 | 1 | sonnet | `autodeck/studio/responses.py` (the four functions) | `uses_responses`, `build_request_body`, `parse_response`, `make_responses_model`: the bench's `_BenchResponsesMixin` moved into the studio | `tests/studio/test_responses.py` | none |
| 23.4 | 1 | haiku | `autodeck/studio/usage.py` (below the marker) | `Prices.cost`, `load_prices`, `UsageMeter` (thread-safe, ordered snapshot), `MeteredModel`, `metered` | `tests/studio/test_usage.py` | none |
| 23.5 | 1 | haiku | `autodeck/studio/edits.py` (the Phase 2-3 functions at the end) | `set_slide_brief`, `apply_composition`, `record_compose_failure`, `set_design_system`, `swap_slides`, `retitle_slide`, `set_designed_text` | `tests/studio/test_edits_phase23.py` | none |
| 23.6 | 1 | haiku | `autodeck/studio/designer_prompt.py` | `master_text`, `palette_text`, `vocabulary_text` (moved from `bench/slides/run.py`), `designer_system_prompt`, `brief_user_text` (byte-exact) | `tests/studio/test_designer_prompt.py` | none |
| 23.7 | 2 | sonnet | `autodeck/studio/designer.py` | `designed_slide`, `conformance_findings`, `qa_findings`, `evaluate`, `answer_calls`, `design_slide` (the bench's loop), `design_slides` (thread pool, job order) | `tests/studio/test_designer.py` | 23.1, 23.2, 23.6 |
| 23.8 | 2 | sonnet | `autodeck/studio/system_layer.py` | `system_user_text`, `draft_from_args`, `make_design` (refusals with measured ratios), `make_designs` | `tests/studio/test_system_layer.py` | 23.1 |
| 23.9 | 1 | sonnet | `autodeck/studio/routing.py` | `rule_route`, `router_user_text`, `ask_router`, `decide_route` (never raises) | `tests/studio/test_routing.py` | none |
| 23.10 | 2 | sonnet | `autodeck/studio/views.py` (`slide_brief_line`, `design_system_text`, `design_system_view`, `design_draft_view`), `autodeck/studio/context.py` (`load_deck_system`, `slide_composition_item`, `design_system_item`) | Outline, context and JSON views of briefs, staleness and the design system; Phase 1 decks render byte-identically | `tests/studio/test_views_phase23.py` (and `test_views.py`, `test_context.py` still green) | 23.1 |
| 23.11 | 3 | sonnet | `autodeck/studio/compose.py` | `select_slides`, `draft_system`, `jobs_for`, `compose_slides` (one entry per slide, designer's model id), `compose_text`, `sample_slides`, `propose_design`, `apply_design`, `propose_briefs`, `deck_briefs`, `result_line` | `tests/studio/test_compose.py`, `tests/studio/test_tools_phase23.py` | 23.1, 23.5, 23.7, 23.8 |
| 23.12 | 3 | sonnet | `autodeck/studio/tools.py` (the `run_*` functions and `qa_gate`) | The new lead and mechanic tools' handlers, as their docstrings specify | `tests/studio/test_tools_phase23.py`, `tests/studio/test_tools.py` | 23.5, 23.11 |
| 23.13 | 2 | haiku | `autodeck/studio/loop.py` (`fold_mechanic_lines`), `autodeck/studio/mechanic.py` | The mechanic's run folded into one line for the lead; the mechanic's one message | `tests/studio/test_loop_phase23.py` | none |
| 23.14 | 4 | sonnet | `autodeck/studio/session.py` (`_run_turn_locked`) | The turn: route, the mechanic and its handoff, the lead, metered bindings, the usage record, in the fixed order of the docstring | `tests/studio/test_session_phase23.py`, `tests/studio/test_session.py`, `tests/studio/test_phase23_done.py` | 23.1–23.13 |
| 23.15 | 5 | haiku | `autodeck/studio/api.py` (`system_for`), `autodeck/studio/__main__.py` (`build`) | The artifact view's design system; the entry point with every role bound and the design renderer | `tests/studio/test_api_phase23.py`, `tests/studio/test_api.py`, `tests/studio/test_server.py` | 23.14 |
| 23.16 | 1–5 | sonnet | `autodeck/studio/static/index.html`, `app.css`, `app.js` | The front-end additions, from the contract below only | the lead, in a browser (23.17) | the contract; 23.15 to run it |
| 23.17 | 6 | lead | none (verification) | Both test modes, the full v2 suite, a browser walk-through on the scripted server, viewing the PNGs, the real-model run on `dev-openai` | `tests/studio/test_phase23_done.py` | 23.1–23.16 |

Waves: **wave 1** (23.1, 23.3, 23.4, 23.5, 23.6, 23.9) needs no other task's body. **Wave 2**
(23.2, 23.7, 23.8, 23.10, 23.13) once 23.1 (and 23.2, 23.6 for the designer) are merged.
**Wave 3** is composition (23.11) and the tool handlers (23.12), which call it. **Wave 4** is
the session, which wires everything. **Wave 5** is the API and the entry point. The front end
(23.16) works only from the contract and can start at once. **Wave 6** is the lead's
verification.

Why the tags: 23.2, 23.4, 23.5, 23.6, 23.13 and 23.15 are short, mechanical and pinned line
by line by their docstrings and tests (23.2 and 23.6 move proven bench code). 23.1 holds the
contrast rule and the client guard on a new tree. 23.3 is the wire format of a paid endpoint.
23.7 and 23.8 are model loops whose feedback texts matter. 23.9 decides what the lead never
sees. 23.10 produces text tested byte for byte. 23.11, 23.12 and 23.14 are where the
behaviour of the phase lives. 23.16 is product surface.

## Design choices

**A slide carries its brief; its designed form is derived from it.** `Slide.brief` is a
`SlideBrief`: a one-line talking `header`, the `intent`, and `content` (short `points`,
`figures` with labels, optional `chart` data in the bench's case shape, `notes` for the
designer). The lead writes and edits briefs (`set_slide_brief`), never blocks or layouts. The
designer produces the blocks and the free layout. `Slide.intent` must equal the brief's
intent when a brief is set, so the two cannot drift. Slides made before this phase (no brief)
are `unbriefed` and behave exactly as in Phase 1.

**Staleness is a pure function of fingerprints (plan §8.3, P7).** A composed slide records
`ComposedFrom`: the SHA-256 of its brief (`brief_digest`), the design system id and version
it was composed in, and the designer's model id. `models.composition_status(slide, system)`
compares them with the current brief and `effective_system(deck)`: `unbriefed`,
`undesigned`, `fresh`, `stale` (with the reasons `brief changed` / `design system changed`)
or `failed` (a `CompositionFailure` recorded for the current brief and system; the previous
designed form is kept). Nothing is stored as "stale" and nothing rebuilds by itself: adopting
a design only changes the deck's reference, and an undo of that change makes the slides fresh
again. The `stale` marker value is still never set by code; markers stay the owner's
`decided` / `provisional`.

**The design system is a versioned artifact; the deck carries a copy of the palette.**
`<engagement>/design_systems/<id>/v0001.json`, one immutable `DesignSystem` per version: name,
concept, rules, palette (hex per slot), roles, background slot, declared text pairs, marker,
the model that made it. A deck refers to one version by `DesignSystemRef(id, version,
marker, palette)`. Copying the palette onto the reference (versions are immutable, so it
cannot drift) makes rendering and layout QA a pure function of the deck and the base tokens
(`design.deck_tokens`): the preview service renders any deck state, including undone ones,
without reading the store, and the render digest still names exactly one image. A new
engagement is in the default system (`default` v1: the base tokens' palette, no concept,
provisional), built in memory and never stored; a deck with no reference is in it.

**Every palette is checked by code before it is accepted.** The system layer declares, with
its palette, the background slot and every text pair its roles allow (`TextPair(text,
ground, large_only)`). `design.check_palette` measures each with v2's `contrast_ratio`:
4.5:1, or 3:1 for a pair declared large-text only, plus `dk2` on the background, because v2
draws every chart's labels in `dk2`. A failing palette is refused with the measured ratios
(`- accent1 on lt2: 2.31:1, needs 4.5:1 (text pair)`), the model corrects it, and the store
refuses to write a failing draft at all. Layout QA still checks every slide; the palette
check only stops a palette that would make every slide fail.

**Tokens reach both QA and the render, and the base slots render as the palette says.**
`deck_tokens` replaces the ten colour slots of the base tokens (fonts, sizes, spacing and
the hyperlink slots unchanged). `design_render.render_with_design` is the production
renderer: it builds the PPTX with the deck's tokens and rewrites `dk1`/`lt1` in the theme
from `sysClr` to `srgbClr` in the studio's own copy (`patch_theme_colours`, the bench's
method), so LibreOffice draws a dark ground dark. v2 is unchanged; a test asserts the v2
output still has `sysClr` and the patched file does not.

**The designer is the bench's loop, in the product.** `designer.design_slide`: one brief,
one tool (`write_slide`, taking a `DesignedSlideInput`: id, blocks, layout; intent and notes
accepted and ignored), the prompt moved from `bench/slides/prompts/slide.md` with the same
`{{MASTER}}`, `{{PALETTE}}` and `{{VOCABULARY}}` texts. Each attempt validates the call,
then checks the brief by code (the header word for word in one text block, line breaks
aside; chart data exactly the brief's), then layout QA in the system's tokens, then a dry
build (a placeholder from the renderer is a finding, as on the bench). Everything is fed
back as the tool result; prose is nudged once. Four attempts by default. `design_slides` runs
slides on a thread pool, results in job order. A model error fails only that slide.

**Results land through the artifact store, one entry per slide.** `compose.compose_slides`
designs the selected slides in parallel and then applies each result in deck order as its
own change-log entry with layer `composition` and the **designer's** model id. A failure is
recorded on the slide (its own entry), keeping the previous design. So the change log shows
who composed each slide and one slide can be undone alone.

**The lead's vocabulary (22 tools).** Kept from Phase 1: `view_deck`, `view_slide`,
`list_sources`, `read_source`, `search_sources`, `create_deck`, `set_brief`,
`set_storyline`, `remove_slide`, `move_slide`, `set_marker`, `apply_option`, `undo`,
`redo`, `load_skill`. New: `set_slide_brief`, `compose_slides` (named slides, or every stale
and undesigned one), `propose_design` (two or three directions in words; each is made
concrete by the system layer and rendered by the designer on up to three real slides, all in
parallel; recorded as a proposal whose options carry the design and the sample slides),
`apply_design` (a proposal option, or a direction in words; stored as a decided version; the
deck's reference changes), `retitle_slide` and `set_block_text` (small direct text changes
that keep the brief in step and are refused when the text no longer fits). `propose` now
takes candidate slides as **briefs**, composed by the designer before the proposal is
recorded, so the owner still sees renders and the lead still writes no layout. Retired:
`write_slide` and `set_design_concept` (the concept now lives in the design system). No lead
tool's schema has a `layout` or `palette` field (a test checks the schemas).

**Picking a design works like any other proposal.** The pick route resolves the proposal and
sends `I pick option B of p0001: Demand curve.`; the lead then calls `apply_design` (or
`apply_option`, which on a design option does exactly the same). The sample slides are
previews and are never committed: adopting a design marks the designed slides stale, and the
lead recomposes them (or says they are stale and asks). Committing the samples would save
calls but would skip the owner's view of the whole deck; it is listed as a later
optimisation.

**Layers and bindings.** `config/studio.yaml` binds `lead`, `system`, `designer`,
`mechanic` and `router` per environment, each with an optional `reasoning` effort, an output
cap (`max_output_tokens`) and an endpoint choice (`api`: auto, chat, responses); `reviewer`
is reserved and may be left out. `dev-openai` binds, provisionally from the bench, lead and
system `gpt-5.6-terra`, designer `gpt-5.6-luna`, mechanic and router `gpt-5.4-mini`. The
other environments bind their one model to every role. No model id appears in code; every id
is one already in `config/models.yaml` or `bench/slides/prices.yaml`.

**The studio's own Responses path.** `responses.py` holds the bench's adapter moved into the
product: a subclass of v2's OpenAI provider whose request builder and response parser speak
`/v1/responses` (tools with reasoning, `store: false`, image input), with HTTP, retries and
the cache still v2's. `api: auto` sends `gpt-5.6*` there; everything else stays on v2's
provider. v2's provider code is not edited.

**Routing: rules where certain, a cheap model otherwise, the lead when unsure.**
`routing.decide_route` runs before every turn: a recap or pick goes to the lead; the owner's
override (`route: "lead"`) pins the lead; a narrow set of full-match patterns ("retitle slide
2 to ...", "swap slides 1 and 3", "move slide 3 to 1", "mark slide 2 decided") goes to the
mechanic; a long, multi-line or questioning message goes to the lead; otherwise the router
model answers with one `route` call, and anything unreadable falls back to the lead. In the
Phase 1 construction form (`Studio(lead=...)`, one model for every role) the router model is
never asked, so a single script is not consumed by routing.

**The mechanic is stateless and can hand back.** It gets only the decks' compact outlines and
the owner's one message (cheap calls), and eight tools: `view_deck`, `view_slide`,
`retitle_slide`, `set_block_text`, `swap_slides`, `move_slide`, `set_marker`,
`hand_to_lead`. Its edits
record layer `mechanics` and its model id. `hand_to_lead` stops its steps; the lead then runs
the same turn with the mechanic's part folded into one assistant line
(`[mechanic] handed to the lead: ...`), so the lead never sees tool calls it does not have.

**Every turn records its layers and an estimated cost.** Every role's binding is wrapped in a
`usage.MeteredModel` for the turn (the router, mechanic and lead in the session; the system
layer and designer through `ToolContext.bindings`). `TurnUsage` lists the roles that ran in
flow order with their layer, model, calls, tokens and cost from `config/studio_prices.yaml`
(the bench's assumed prices, labelled as assumptions), and is stored on the `TurnEndLine` and
the `TurnFinished` with the `RouteRecord`. A model missing from the price file is unpriced and
makes the total unknown rather than wrong.

**The scripted model per role.** A script step may name its `role` and a `match` substring;
each role has its own queue, and a call is answered with the first unplayed step of its role
whose match occurs in what it was sent (system prompt and messages). Parallel designer calls
are thus answered deterministically by matching on `Slide id: s2` or `Name: Demand curve`.
`scripted_bindings` binds every role to one script. `design_flow.json` (25 steps) is the
walk-through, built from slides prototyped to pass real layout QA in the default, Itemised and
Demand curve palettes.

**What the lead reads.** The outline gains one line per briefed slide (header, content counts,
state); the context gains a `### Design system` block (name, concept, rules, never colours)
for a deck with a stored system, and open items for stale, failed and undesigned slides and a
provisional design system. Phase 1 decks render byte-identically (the golden context test is
unchanged). `slide-design` is no longer an allowed skill: it teaches layouts, which are now
the designer's.

## Phase 1 behaviour replaced, and the tests that followed it

- **`write_slide` and `set_design_concept` left the lead's toolbox.** Retired from
  `tests/studio/test_tools.py`: `test_write_slide_reports_the_layout_check`,
  `test_write_slide_without_layout`, `test_write_slide_names_its_fields_and_still_refuses_unknown_ones`;
  the `set_design_concept` lines and the `write_slide` refusal were removed from
  `test_edits_record_instruction_thread_layer_and_model` and
  `test_refusals_come_back_as_errors`; `test_undo_and_redo` now undoes a `move_slide`.
- **`propose` takes candidate briefs, not whole slides.** Retired from `test_tools.py`:
  `test_propose_records_options_without_changing_the_deck`,
  `test_propose_requires_replace_or_insert_for_every_candidate`,
  `test_propose_refuses_unplaced_candidates`, `test_apply_option`,
  `test_an_option_meant_to_replace_the_opening_replaces_it`,
  `test_apply_option_inserts_at_the_stated_position`,
  `test_apply_option_refuses_when_the_deck_no_longer_fits_and_stays_open`,
  `test_apply_option_refuses_an_old_record_that_never_said_replace_or_insert`. The
  replace-or-insert rules themselves are unchanged (`edits.apply_candidate_slides`, its tests
  in `test_edits_phase1.py`); `test_tools_phase23.py` covers propose with briefs and
  applying the result.
- **The Phase 1 walk-through** (`tests/studio/test_phase1_done.py` and
  `fixtures/scripts/two_threads.json`) was built on `write_slide` and is retired. Its
  guarantee, that a second thread opens from state with no transcript, is carried by the new
  exit test's thread two (its context equals `build_context` and contains none of thread one's
  replies) and by `test_context.py`.
- **The scripted-script tests** in `test_scripted.py` now check `design_flow.json` (each
  role's tools, valid arguments, no layout or hex in any lead call, the palettes well formed,
  every designer slide passing layout QA in its palette) instead of `two_threads.json`.
- **`StudioEnvironment` binds five roles.** `test_bindings.py`'s malformed-config case now
  binds all five.
- **The lead prompt** test asserts the new division of labour instead of "A slide has only
  these fields".
- Every other Phase 1 test is unchanged and passes against the prototype; those that run a
  turn fail until 23.14 is merged.

## Skills the base allows

`prompt.ALLOWED_SKILLS = ("storyline", "writing-style")`. `slide-design` is now refused:
it teaches designing a slide with a free layout, which the lead must not do; the designer's
own prompt carries the composition craft the bench proved. The rest of Phase 1's table holds.

## Front-end contract (additions)

Everything the front end (task 23.16) needs beyond Phase 1's contract
(`docs/phases/V3-PHASE-1.md`), which still holds. The server's code is not required reading.

### Changed shapes

- **`GET /api/health`** also returns `bindings: {lead, system, designer, mechanic, router}`
  (model id per role).
- **ArtifactView** also has:
  - `composition: {slide id: {state, reasons, failure, composed_by}}` for every slide, where
    `state` is `"unbriefed" | "undesigned" | "fresh" | "stale" | "failed"`, `reasons` is a
    list of `"brief changed"` / `"design system changed"` (stale only), `failure` is
    `{attempts, findings: [str], model_id}` for `failed` and null otherwise, `composed_by` is
    the designer's model id or null;
  - `design_system`: **DesignSystemView** or null (null only when the deck's reference cannot
    be read).
- **DesignSystemView** `{id, version, name, concept, rules: [str], marker: "provisional" |
  "decided", is_default: bool, background: slot, made_by, created_at: time | null, palette:
  [{slot, hex: "#RRGGBB", role}] (ten, in the order dk1, lt1, dk2, lt2, accent1..accent6),
  text_pairs: [{text: slot, ground: slot, large_only: bool}]}`.
- **The deck JSON** (`ArtifactView.deck`) slides also carry `brief` (`{header, intent,
  content: {points, figures: [{value, label}], chart: {kind, categories, series: [{name,
  values}], emphasis} | null}, notes}` or null), `composed` and `compose_failure` (show
  `composition` instead of reading these).
- **MessageView, assistant** also has `roles: ["lead"] | ["mechanic"] | ["mechanic",
  "lead"]` (who answered, in order; a handoff shows both), `route: RouteRecord | null` and
  `usage: TurnUsage | null` (null while running and on Phase 1 lines).
  - **RouteRecord** `{requested: "auto" | "lead", route: "lead" | "mechanic", by: "rule" |
    "model" | "override" | "origin" | "fallback", reason: str, handed_off: bool}`.
  - **TurnUsage** `{layers: [{role, layer, model_id, calls, input_tokens, output_tokens,
    cost_usd: number | null}], total_cost_usd: number | null, prices_assumed: true,
    price_note: str}`; `layers` lists only roles that ran, in the order router, mechanic,
    lead, system, designer.
- **ProposalView options** also have `design`: null, or `{name, concept, rules, background,
  made_by, palette: [...], text_pairs: [...]}` (as DesignSystemView, without id, version,
  marker and created_at). A design option's `applies` reads `Adopts the design "<name>";
  designed slides become stale`, and its `previews` are the sample slides rendered in its own
  palette.

### Changed routes

| Method and path | Body | Change |
|---|---|---|
| `POST E/threads/<t>/messages` | `{text, route?}` | `route` is `"auto"` (default) or `"lead"`; anything else is `400 bad_request` |

There is no "recompose" route. The Recompose action sends a message pinned to the lead:
`POST E/threads/<t>/messages` with `{text: "Recompose the stale slides: s1, s2.", route:
"lead"}` (the ids of the stale slides, in deck order).

### New events

| Type | Fields | Meaning |
|---|---|---|
| `slide_composed` | `turn_id, artifact_id, slide_id, clean, attempts, findings, model_id, seconds` | the designer finished one slide (after that slide's `change_recorded`); `clean: false` means it failed and its previous design is kept |

`turn_finished` also carries `route` and `usage` (as above). `turn_started.model_id` is the
model that answers: the mechanic's for a mechanic turn.

### Screens and behaviour

- **Design tab** (a fourth tab of the artifact panel, after Changes): the design system's
  name and version, a `Decided` or `Provisional` tag (and `Default` when `is_default`), the
  concept as a paragraph ("No concept stated" for the default), the rules as a list, and the
  palette as swatches: one row per slot, a swatch (a filled square with a visible border so
  light colours show), the slot name, the hex, and the role text. The background slot is
  marked "Background". Below the swatches, the declared text pairs as small samples ("Aa" in
  the text colour on the ground colour) with their slot names. Swatches are drawn with
  `element.style.backgroundColor` from script (no inline style attributes).
- **Slide markers** (thumbnail strip and the large preview), from `composition`, alongside
  Phase 1's decided/provisional markers: `stale` shows a desaturated slide and a "Stale" tag
  with the reasons as its tooltip and in a quiet line under the large preview; `failed` shows
  a "Failed to compose" tag in the warning colour with the first finding under the large
  preview; `undesigned` shows Phase 1's calm placeholder with "Not designed yet"; tag text is
  always present (never colour alone). When any slide is stale, a "Recompose" button appears
  above the strip ("Recompose 3 stale slides"), sending the message described above; it is
  disabled while a turn runs.
- **Routing line under each assistant message**: one quiet line, for example `Mechanic ·
  gpt-5.4-mini · 2 calls · $0.003 est.` or `Router → Lead · 3 layers · 41.2k tokens · $0.86
  est.`; after a handoff `Mechanic → Lead`. Clicking it expands a small table: one row per
  layer (role, layer, model id, calls, input and output tokens, cost or "unpriced"), the
  route's `by` and `reason`, and the `price_note` in small print. A cost is always shown with
  "est."; an unknown total shows "cost unknown". Hidden while the turn runs; shown from the
  refetched thread after `turn_finished`.
- **Routing control on the composer**: a two-way segmented control, "Auto" (default) and
  "Lead", next to the send button; its value is sent as `route` with each message and
  persists per thread in `localStorage` (wrapped in try/catch). A tooltip says what each does
  ("Auto: small edits go to a cheaper model", "Lead: always the lead").
- **Design proposals**: a Proposal message whose options have `design` shows each option as a
  card with its name, concept, its swatches (a compact row of ten), its rules collapsed, and
  its sample slides (`previews`; placeholders until `proposal_previews_ready`), with "Use this"
  and "Dismiss" as for other proposals.
- **Live composition**: while a turn runs, each `slide_composed` event adds one line to the
  live activity ("Designed slide s2 (2 attempts)", or "Slide s3 failed to compose") and, as
  for `change_recorded`, triggers a refetch of the artifact.
- **Top bar**: unchanged; the model id shown is the lead's.
- **Look**: as Phase 1 (tokens on `:root`, dark mode, no emoji, no gradients, no external
  resources, CSP rules); the warning colour is a token.

## Deliberately left out of Phase 2-3

- **The reviewer** (plan §6.1 Review): reserved in the bindings, unused. A model reviewing its
  own render added little on the bench; a separate reviewer is untested.
- **The model seeing renders.** The Responses path carries images, but no studio caller sends
  any.
- **Taste notes to owner memory.** Memory stays read-only.
- **Propose-first editing; selection as scope; the export confirmation; several threads on
  one artifact; middle-of-history undo** (Phase 4).
- **Diagrams, notes artifacts, fact-check, strict mode** (Phases 5 and 6).
- **Token streaming.** Events stream at step granularity, as in Phase 1.
- **New layout vocabulary**: styled charts, diagonal or curved lines, emphasis inside a line of
  text, more fonts. The gaps the bench found are listed below for a later vocabulary phase.
- **Committing a design proposal's sample slides** when the design is adopted (they are
  recomposed instead).
- **Per-slide render caching and parallel rendering** (whole-deck renders, as in Phase 1).
- **Routing by the mechanic's own judgement of "small"** beyond `hand_to_lead`; no learned
  routing.

## Layout vocabulary gaps found by the bench (for a later vocabulary phase)

From `bench/slides/results/` and the hand-made reference (`opus-reference.png`), the places
where the free-layout vocabulary limited the designs:

1. **Charts cannot be styled.** No control over gridlines, axis visibility, bar thickness,
   value-label format (412, not $412k), label colour (always `dk2`) or a chart background;
   the reserved empty band under every chart (about 45pt) costs space.
2. **Lines are horizontal or vertical only.** No diagonal or curved line, so a "demand
   curve" or a step chart drawn with shapes must be faked with right angles.
3. **No emphasis inside a line of text.** A number inside a sentence cannot be bold or
   coloured; designers split text into several frames to emphasise one figure, which then
   fails overlap checks when sizes change.
4. **One font family.** Only the token fonts (Carlito) can be measured, so a display face,
   a monospaced figure face or a condensed face for labels is impossible.
5. **No strike-through or highlight on text.** The "old price struck through" idea needs a
   line shape laid over text, positioned by arithmetic.
6. **Few shape kinds, no rotation or transparency.** `rect`, `rounded_rect`, `ellipse`,
   `line` with a tint toward the background; no triangle or chevron (timelines, steps), no
   rotation, no opacity independent of tint.
7. **Charts have one accent and one neutral.** Emphasised categories in the element's accent,
   all others in `accent6`; no per-series colours, no "before" colour for a comparison.
8. **No images or full-bleed figures.** `figure` draws an empty captioned frame.
9. **Text frames are measured, not fitted.** A frame too small by a few points fails; the
   designer spends attempts on arithmetic rather than design (most of the bench's second and
   third attempts were text-fit fixes).

## Risks found while scaffolding

1. **Designer cost and time per deck.** Luna took 2-4 attempts per slide at roughly $0.08-0.40
   (assumed prices); a design proposal with three directions and three samples is nine
   designer calls plus three system calls. Measure in the real run; `sample_slide_ids` and
   `designer_attempts` are the levers.
2. **`gpt-5.6-terra` as the lead is untested.** The bench tested Sol and Luna as designers,
   never Terra as a lead driving 22 tools. The binding is provisional.
3. **The Responses path is new product code against a paid endpoint.** It is a move of the
   bench's proven adapter and tested on request bodies and payloads, but its first real call
   is the lead's run.
4. **Routing rules are English-only and narrow.** A retitle phrased differently goes to the
   router model; a misroute costs one mechanic call and a handoff. Watch the routing line.
5. **The mechanic gets no history.** "Undo that" or "change it back" cannot be done by the
   mechanic (it does not know what "that" is); such messages contain no rule match and go to
   the router, which should send them to the lead. If the router sends them to the mechanic it
   must hand off.
6. **Briefs are free text.** A long header or many points will fail composition repeatedly;
   the failure is recorded and the lead is told to shorten. Measure failure rates.
7. **The scripted designer is matched by text.** `design_flow.json` relies on `Slide id: s2`
   and `Name: Demand curve` appearing in the designer's input; `brief_user_text` is pinned
   byte for byte, so a change there must update the script's matches.
8. **Prices are assumptions.** Every cost is an estimate from copied bench values, labelled as
   such; the real price list must replace `config/studio_prices.yaml` before any cost is read
   as fact.
9. **Background-turn tests fail indirectly until the session is implemented.** Tests that
   start a turn on a worker thread (`test_api.py`, `test_server.py`, one in
   `test_session.py`, one in `test_api_phase23.py`) see missing state rather than
   `NotImplementedError`, because the worker logs the error. They all passed against the
   prototype session.
10. **A WIP commit (`af010f0`) on the branch contains prototype bodies** for `design.py`,
    `design_render.py`, `designer.py`, `system_layer.py` and `usage.py`, captured while the
    scaffold was being checked. The working tree holds the skeletons; implementers start from
    the working tree (the skeletons), not from that commit.

## How the lead verifies the phase (task 23.17)

1. `uv run pytest -q -p no:cacheprovider tests/studio` and the same with `-m render`: all
   green, no `NotImplementedError` left. `uv run pytest -q -p no:cacheprovider
   bench/slides/tests` still green.
2. `uv run ruff check`, `uv run ruff format --check` on the studio files,
   `uv run pyright autodeck/studio`.
3. The full default suite: v2 unchanged (the one known failure is
   `tests/test_design.py::test_a_missing_face_is_as_loud_as_a_missing_family`).
4. A browser walk-through on the scripted server, with a fresh workspace:

   ```
   uv run python -m autodeck.studio \
       --script tests/studio/fixtures/scripts/design_flow.json \
       --workspace /tmp/studio-design-flow
   ```

   Open `http://127.0.0.1:8765/`. Create the engagement `northwind-retail` /
   `llm-inference-efficiency`. Start a thread. Send any message: three slides are written and
   designed (watch the `slide_composed` lines, then the previews; the routing line reads
   Router → Lead with the designer's calls). Send "It looks generic." (any words): a design
   proposal with two directions, each with swatches and a rendered slide 2. Pick B (Demand
   curve) with the button: the Design tab shows Demand curve, decided; the three slides are
   marked Stale and the Recompose button appears. Send any message (or press Recompose): the
   slides are redesigned on the night ground and the Stale tags clear. Go back and start a
   new thread: the recap appears. Send exactly `Retitle slide 2 to Quantisation cuts the bill
   by 38%`: the routing line reads Mechanic, and slide 2's header changes. Check the
   Changes tab (layers and models per entry), both themes, and widths 1280, 900 and 390px.
5. Look at the rendered PNGs under `/tmp/studio-design-flow/engagements/.../renders/` (the
   night ground must be dark, not white).
6. **The real-model run on `dev-openai`** (needs `OPENAI_API_KEY`; the lead's job, not an
   implementer's):

   ```
   uv run python -m autodeck.studio --env dev-openai --workspace /tmp/studio-live
   ```

   One session on the fixture pair: ask for a short readout deck (four to six slides), then
   say it looks generic, pick a direction, recompose, and make two small edits (one retitle
   by rule, one phrased loosely to exercise the router). Record, from the routing lines and
   `messages.jsonl`: per turn the layers, calls, tokens and estimated cost; the designer's
   clean rate and attempts; whether any lead call carried a layout (none may); how the slides
   look against the bench's Luna sheet; and how often the mechanic handed off. Write the
   result below.

## Result (task 23.17)

Verified by the lead on 2026-11-15.

**On scripted models**

- Studio tests: 483 in the default selection, 8 `render`-marked, all passing. Bench tests:
  42 passing. Ruff and pyright clean on the studio code. No skeleton body remains.
- v2 unchanged: no v2 file edited; full default suite 2615 passed, 1 failed (the known
  `tests/test_design.py::test_a_missing_face_is_as_loud_as_a_missing_family`).
- Browser walk-through on the real server with `design_flow.json`, driven with Playwright
  and viewed: briefs written and composed; a design proposal with two directions, swatches
  and rendered samples; picking Demand curve marks slides stale and shows Recompose;
  recomposing redraws on the night ground; a new thread recaps from state; a retitle goes
  to the mechanic and the routing line says so. No console or server errors; no horizontal
  scroll at 390px.

**First real-model run** (`dev-openai`: lead and system `gpt-5.6-terra`, designer
`gpt-5.6-luna`, router and mechanic `gpt-5.4-mini`; driven over the HTTP API by a Sonnet
agent; sheets in `assets/v3-phase-2-3/`)

- The layered flow ran end to end with no API, adapter, schema or server error and no code
  change. The Responses path worked on its first real call.
- **The slides look designed.** Before any design was chosen the four slides already used
  colour panels, large figures and a timeline (`sheet-default.png`). After picking a
  direction they are one dark deck with mint and amber accents (`sheet-final.png`).
- **Lead:** wrote briefs in words with published figures from the sources, never a layout
  or colour; refused to combine figures the papers measured separately. It offered three
  directions, not two.
- **Designer:** 4 of 4 slides clean, 3-4 attempts each, after one slide failed on a brief
  that was too long and the lead shortened it. Recomposition after the pick: 4 of 4 clean.
- **System layer:** three palettes accepted, one on its second attempt.
- **Routing:** a retitle went to the mechanic by rule, a loosely phrased swap by the router
  model; both were done correctly without the lead, about $0.02 each.
- **Cost (assumed prices, unconfirmed):** $8.69 over seven turns. Build $3.24, design
  proposal $3.63, apply and recompose $1.43. The designer was about $5.5 of it.

**Defects found in the real run**

1. Layout QA passes slides with visible flaws: a rule running through the word UNMEASURED
   like a strike-through; a timeline line and its last item running into a colour band;
   labels detached from their figures. All four slides were reported clean.
2. Three of nine design-proposal samples failed to render with nothing recorded, and the
   lead presented those directions as complete.
3. The lead retried a failed compose and told the owner all slides composed cleanly,
   without mentioning the failure.
4. The lead resends about 14k tokens per call; a one-line question costs about $0.17 on
   the assumed prices, and the first build used 128k input tokens over nine calls.
5. Change descriptions in the interface are technical ("composed, system id: default →
   demand-curve").
6. A system-layer retry leaves no record of its findings.

## Studio layout rules (answer to defect 1)

`autodeck/studio/layout_rules.py` runs inside `render_adapter.check_slide`, after v2's checks,
so every caller (the designer's loop, previews, the dry build) gets it. v2 is unchanged. Each
rule returns a v2 `FreeLayoutFinding`, so the designer feeds it back as `[line_through_text]
unmeasured: ...` with no change to `designer.py`. Everything is geometry in points on the
master's canvas; nothing needs judgement.

**Measuring text.** A text element is judged by the extent of its ink, not by its frame. Each
wrapped line (v2's `measure_text`) is as wide as v2's font metrics say, placed by the element's
`align` and `anchor`, and `INK_HEIGHT_EM` = 0.68 of the type size tall, standing on a baseline
`BASELINE_EM` = 0.22 of the size above the bottom of its line box. Both constants were
measured on the LibreOffice renders of about 80 single-line text elements in the bench slides (capitals and
digits span 0.49 to 1.18 of the size on a 1.38 line, 0.60 to 1.25 on a 1.5 line: extra leading
goes above the line). A first guess with the ink centred in the line missed the strike-through
on a 112pt "21%" by 1.5pt, which is why this was measured. A *rule* is a `line` shape (drawn
as v2 draws it: through the frame's centre along its longer side, `line_pt` thick) or a
filled rect thinner than `RULE_MAX_PT` = 3pt.

| Rule | A finding when | Tolerances |
| --- | --- | --- |
| `line_through_text` | a rule crosses a line of ink, the ink band shrunk top and bottom | margin `LINE_CROSS_MARGIN_EM` = 0.10 of the size; crossing at least `MIN_CROSS_PT` = 2pt long. A line at or below the baseline (an underline), above the caps, or ending at the word is clean |
| `line_through_chart` | a rule crosses the inside of a `chart` or `diagram` frame | frame inset `CHART_EDGE_PT` = 6pt; crossing at least 2pt |
| `straddle` (text) | a text line block lies partly on a filled `rect` / `rounded_rect` / `ellipse` drawn *earlier* and partly off it | more than `STRADDLE_TOLERANCE_PT` = 3pt inside the shape and more than 3pt outside, on the extent of the ink lines |
| `straddle` (line) | a rule lies partly inside such a shape and partly outside it, along its own direction | more than 3pt inside and more than 3pt outside; a line wholly inside, wholly outside or ending at the edge is clean |

For `straddle`, the ground shapes exclude full-bleed backgrounds (90% of the slide in both
directions), shapes that are themselves rules, and shapes drawn after the element (those hide
it, which v2's `hidden_text` reports). Nested shapes are each judged on their own: text wholly
inside a card on a panel is clean, text crossing the card's edge is not. Ellipses use their
bounding box.

**Measured result on the 34 designed slides** (4 real-run slides, 30 bench slides). All 34
renders were looked at; each slide with a finding was opened.

| Slide | Rule | Finding | Verdict |
| --- | --- | --- | --- |
| real run 1 `serve-before-buy` | `line_through_text` | `unmeasured`, line at shape 6 | true: the strike-through |
| real run 4 `approve-benchmark` | `line_through_text` | `capacity_label`, the timeline line runs through "THEN REVISIT CAPACITY" | true |
| real run 4 `approve-benchmark` | `straddle` | the timeline line (shape 3) starts above and ends inside the amber band | true: the line into the band |
| bench sol s7-case, none | `line_through_text` | `cost-figure`, a rule through "$310k" | true (the same strike-through, not seen before) |
| bench luna s5-caching, demand-curve | `line_through_text` | `hero21`, the curve through "21%" | true |
| bench sol s2-inference, demand-curve | `line_through_chart` | `share_chart`, a rule across the bars and axis | true |

Six findings, six true, none false, on 5 of the 34 slides; the other 29 give no finding. Tightening
every tolerance (margin 0, straddle 0.5pt, crossing 0.5pt) adds no finding: nothing is on the
edge of a threshold. Loosening them (margin 0.25, straddle 8pt, crossing 6pt) loses three true
findings (real run 1, real run 4's label, luna s5 "21%"), which is why the margin is 0.10.
`straddle` on text
fired on none of the 34 even at 0.5pt, so its text half rests on synthetic tests only.

**Not catchable by rule** (what a reviewer has to see): real run 4's last timeline item
("Roll out only changes ...") ends 2pt above the band's top edge and *looks* as if it sits on
it (tight clearance, not a straddle); labels detached from their figures (real run 2 "0" and
its caption, bench luna s8 "PILOT BUDGET" far above "$85k"); a figure running into a chart's
axis labels without overlapping its frame (luna s2 demand-curve "42%"); a headline broken in
two frames with a gap (sol s1-title none); crowded, uneven gaps between figures (luna s3
demand-curve, "-38%" against "-21%"); accent bars that straddle nothing but do not match the
card they top (sol s3, s6 none).

The designer prompt lost the advice that a line "can be drawn across text on purpose (as a
strike-through)" and gained two requirements, "No line through text or a chart" and "One
ground per item". Real strike-through belongs to a later vocabulary phase. Fixtures:
`tests/studio/fixtures/designed_slides/`; tests: `tests/studio/test_layout_rules.py`.
