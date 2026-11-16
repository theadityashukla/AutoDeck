# v3 studio (mock-up, Phases 0 to 3, slide bench, post-run fixes) — Handover

> Written 2026-11-16, after development was paused at the owner's instruction (end of the
> session of 2026-11-15). It follows `TEMPLATE.md`'s sections. It leans on the three phase
> documents by reference instead of repeating them: `docs/phases/V3-PHASE-0.md`,
> `V3-PHASE-1.md`, `V3-PHASE-2-3.md`. Read `README.md`, `STATUS.md`, then this, then
> `docs/AUTODECK_V3_PLAN.md` (see its "What actually happened"). Cost figures are estimates
> from assumed prices, never charges.

---

## 1. Identification

| | |
|---|---|
| **Phase** | v3: the mock-up, Phase 0 (foundations), Phase 1 (conversation core), the slide bench, Phases 2 and 3 merged (layers, routing, design layer), and the work after the first layered real-model run (close-out fixes, studio layout rules, reviewer prompt and bench support, two reviewer tests) |
| **Branch** | `claude/autodeck-principles-review-zp7nsm`, built on `v2/integration` (merge base `1b5e38c`). The plan recommended `v3/integration`; that was not possible in the session that did the work, so the owner may want to rename or rebase |
| **PR** | None recorded in the repository |
| **Started / completed** | 2026-11-12 (plan, mock-up) → 2026-11-15 (last commit `9c31d8e`). Paused, not finished: see section 3 |
| **Gate** | None. v3 has no build-time gates |
| **Gate status** | n/a |
| **Approved by / when** | The owner accepted the mock-up as the direction and settled decisions V1 to V10 in the review conversation (2026-11-12); suggested the slide bench; set the spending limit and the pause. Whether the owner has used the studio beyond that is not recorded in the repository |
| **What the owner actually checked** | Not recorded beyond the above. What *was* checked, by the build sessions, is in each phase document's Result section: scripted walkthroughs in a browser, and two real-model runs driven over the HTTP API |

## 2. What shipped

All under `autodeck/studio/` unless stated; a module map is `autodeck/studio/README.md`.

| Area | Paths | What it does | Tests (in `tests/studio/`) |
|---|---|---|---|
| Mock-up | `mockups/v3/` | Clickable scripted mock-up, throwaway | none |
| Base model and state | `models.py`, `serialise.py`, `diff.py`, `changelog.py`, `store.py`, `edits.py` | Plain deck (no claims or citations), canonical serialisation, id-keyed diff, change log as a tree with a head, exact undo and redo by stored snapshot | `test_models*`, `test_serialise`, `test_diff`, `test_changelog`, `test_store`, `test_edits*`; exit test `test_phase0_done.py` |
| Engagement and isolation | `paths.py`, `engagement.py` | Engagement over `knowledge/`; A4 enforced on knowledge and workspace trees | `test_paths*`, `test_engagement` |
| Rendering | `render_adapter.py`, `render.py`, `design_render.py`, `layout_rules.py`, `previews.py` | Plain deck through v2's drawing code and layout checks (no v2 change); render in a design system (dk1/lt1 patched in the studio's copy); three studio layout rules; background previews | `test_render*`, `test_design_render`, `test_layout_rules`, `test_previews` |
| Conversation | `session.py`, `loop.py`, `conversation.py`, `context.py`, `threads.py`, `proposals.py`, `sources.py`, `prompt.py`, `tool_args.py`, `tools.py`, `views.py`, `change_summary.py`, `events.py` | Threads from state, loop ending on a text reply, 22 lead tools plus mechanic tools, proposals, sources behind the guard, views for the model and the API | `test_session*`, `test_loop*`, `test_context`, `test_threads`, `test_proposals`, `test_sources`, `test_tools*`, `test_views*`, `test_change_summary`, `test_events` |
| Layers | `compose.py`, `designer.py`, `designer_prompt.py`, `system_layer.py`, `design.py`, `routing.py`, `mechanic.py`, `usage.py` | Briefs, parallel per-slide design, palette from a direction with a contrast check, design systems as immutable versions, routing by rule then router model, per-turn layers and estimated cost; staleness (`models.composition_status`) | `test_compose`, `test_designer*`, `test_system_layer`, `test_design_system`, `test_routing`, `test_usage`; exit test `test_phase23_done.py` |
| Models | `bindings.py`, `responses.py`, `scripted.py`, `config/studio.yaml`, `config/studio_prices.yaml` | Bindings per layer and environment; the OpenAI Responses path; a scripted stand-in per role | `test_bindings`, `test_responses`, `test_scripted` |
| Interface | `api.py`, `server.py`, `__main__.py`, `static/` | Local web interface on 127.0.0.1, Server-Sent Events, plain JavaScript; `python -m autodeck.studio` | `test_api*`, `test_server` |
| Prompts | `prompts/studio/` (`lead`, `system`, `designer`, `mechanic`, `router`) | One per layer | `test_prompt` |
| Bench | `bench/slides/` | Slide-level design tests; reviewer support; results | `bench/slides/tests/` |
| Demo | `scripts/studio_demo.py` | Phase 0 demo: render, edit, list, undo, timings | `test_studio_demo` |
| Docs | this handover, `docs/phases/V3-PHASE-*.md`, `docs/STUDIO-GUIDE.md`, `docs/AUTODECK_V3_PLAN.md` | | |

## 3. What did not ship

| Item | Why | Now owned by |
|---|---|---|
| The reviewer as a product layer | Tested twice on the bench: precise, weak on composition; judged worth a cheap extra pass but not built | Next work; `bench/slides/results/README.md`, V19 |
| Trimming the lead's per-call context (about 14k tokens resent each call) | Found in the real run; not addressed | Next work |
| Phase 4: selection as scope, propose-first, export confirmation, several threads on one artifact, undo from the middle of the history | Staleness and recomposition were pulled forward; the rest was not reached | Plan §12 Phase 4 |
| Phase 5: meeting notes on the new core, source notes, fact-check tool | Not reached | Plan §10, §12 |
| Phase 6: the strict overlay | Not reached; v2 is the route to traceable decks meanwhile | Plan §9, §12 |
| Phase 7: routing benchmark | Not reached; the change log records layer and model for it | Plan §12 |
| Vocabulary phase (styled charts, curves and diagonals, emphasis in a line of text, more fonts, strike-through, shapes, images, the base theme colours fix) | Found by the bench; not in the original plan | `V3-PHASE-2-3.md` "Layout vocabulary gaps" |
| Vocabulary review against the owner's reference decks (plan §7.3, §14 q4) | No reference decks recorded | Plan Phase 3 note |
| Taste notes to owner memory | Memory is read-only context | Plan §7.2 |
| Diagrams in the base model | v2's diagram nodes are typed claims | `V3-PHASE-0.md`; vocabulary or overlay phase |
| Export (PPTX download) | Phase 4's single confirmation | Phase 4 |
| Any run on an Anthropic model | No key or budget used for it | Before relying on `sit` or `prod` |
| Token streaming | The provider layer returns whole turns | Not planned |

## 4. Decisions made

`DECISIONS.md`, V-series (entries use the `V` prefix; B84 is still the next free `B` id):

| Id | One line |
|---|---|
| V0 | v3 turns v2 round: plain base, strict as an overlay; principles P1 to P7 |
| V1 to V10 | The plan's settled decisions: chat is the centre; one conversation; auto editing with propose-first as alternative; every edit in the change log and undoable; routing by layer with override; one export confirmation; A6 strict-only; no claim typing or validation outside strict, fact-check a tool never a gate; A4 everywhere; strict as an overlay |
| V11 | D7 reversed; D9 and D13 re-scoped; invariants scoped to strict |
| V12 | Phases 2 and 3 merged |
| V13 | Design tested at the level of one slide first (the slide bench) |
| V14 | Design system as a versioned artifact; every palette checked by code |
| V15 | Staleness as a pure function of fingerprints; staleness pulled forward from Phase 4 |
| V16 | Provisional model tiers (OpenAI models; no Anthropic run) |
| V17 | Every cost is an estimate from assumed prices |
| V18 | Studio layout rules |
| V19 | The reviewer is precise, weak on composition, not in the product |
| V20 | Two design directions by default; incomplete directions reported |
| V21 | Development is paused |

## 5. Invariant coverage delta

v3 scopes the invariants to strict mode (V11); the strict overlay is not built, so the v2
tracker in `docs/INVARIANTS.md` is unchanged and describes v2. For v3:

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | n/a | Not enforced in the base, by decision | none (the base model has no citation field) |
| A2 numbers | n/a | Not enforced in the base | none |
| A3 validation | n/a | Not enforced in the base | none |
| **A4 isolation** | n/a | **Enforced and tested in every mode**; symlink cases untested (section 7) | `test_paths*`, `test_engagement`, `test_sources`, `test_api` |
| A5 framing | n/a | Not enforced in the base | none |
| A6 reproducibility | n/a | Not required in the base; change log only. Exact undo is tested | `test_changelog`, `test_store`, `test_phase0_done` |
| A7 gates | n/a | One export confirmation planned, not built | none |
| A8 uncertainty | n/a | Not enforced in the base | none |

A base v3 deck is not traceable. A misquoted figure can reach a client unchecked; this is an
accepted trade (V8).

## 6. Spike and experiment findings

Positive and negative, in the order they happened. Details and numbers are in the phase
documents and `bench/slides/results/README.md`.

1. **Preview speed (Phase 0).** Four slides at 150 dpi: PPTX build about 0.07 s, rasterisation
   about 1.5 to 1.9 s (re-measured on 2026-11-16 with `scripts/studio_demo.py`: 0.07 s and 1.86 s).
   Mostly one LibreOffice start. Not measured on a full deck.
2. **First real-model run (Phase 1, `gpt-5.4-mini`, 2026-11-14).** The loop and the 19 tools
   worked on a real model. **The slides were generic**: a title, a rule and paragraphs on white.
   The model passes layout QA by staying in a safe pattern. One defect (a chosen opening was
   appended as a fourth slide instead of replacing slide 1, and the model said it had replaced
   it). About $1.27 estimated.
3. **Slide bench, round 1.** Given one slide, a concept and a composition prompt, `gpt-5.6-sol`
   was clean on every slide it finished (1 to 2 attempts, about $0.42 to $1.05 a slide) and
   `gpt-5.6-luna` on 14 of 16 (2 to 4 attempts, about $0.08 to $0.40). **`gpt-5.4-mini` failed
   layout QA on all five slides it attempted.** With a concept, slides read as one deck; without
   one they do not match. The budget guard overshot its cap (estimated $14.55 against $13) with
   four parallel workers.
4. **Slide bench, round 2.** A model shown its own render revised 2 of 7 slides and only
   changed a headline to one line; it left a visible flaw alone. Self-review adds little.
5. **Layered real-model run (Phases 2 and 3, 2026-11-15).** Ran end to end, no API, adapter or
   schema error; the Responses path worked on its first real call. Slides looked designed.
   Estimated $8.69 over seven turns (designer about $5.5). Six defects: layout QA passed slides
   with visible flaws; failed design samples were silent; the lead told the owner everything
   composed cleanly after a failure; about 14k tokens resent per call; technical change
   descriptions; palette retries unrecorded. Four of the six were fixed afterwards, and the first
   was answered by the layout rules (below). The 14k-token problem is open.
6. **Layout rules.** Six findings, all true, none false, on 5 of 34 designed slides; nothing near
   a threshold. The text half of `straddle` fired on none of the 34 (synthetic tests only). Not
   catchable by rule: tight clearance, labels detached from figures, crowding.
7. **Reviewer tests.** In 40 reviews no good slide was sent back; findings were specific enough
   that the designer fixed them in one revision; about a third on top of the designer's cost
   (estimated). Recall on composition flaws is weak (it missed floating labels, uneven labels, two
   crowded figures and passed a scattered slide).

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| Lead resends about 14k tokens per call | Every question to the lead costs about $0.17 estimated; first build 128k input tokens over nine calls | Next work |
| Design proposals are the most expensive action | About $3.63 estimated in the real run (before the two-direction default; not re-measured) | Measure on the next real run |
| Reviewer not in the product; layout rules cannot see composition | Flaws like detached labels reach the owner | Reviewer work; the owner still looks |
| Private v2 names used: `ir.store._diff`, `render.renderer._BLANK_LAYOUT`, `SLIDE_TAG_PREFIX` | A v2 refactor breaks the studio (tests would catch it) | Whoever changes v2 |
| Isolation symlink cases untested: workspace `engagements/<client>` as a symlink; a project folder symlinked into another client; listings that follow symlinks. v2's own guard may share the gap (not verified) | A confidentiality hole in unusual layouts | Next isolation pass |
| Store assumes one process; no crash repair (a crash between the log and `current.json` is detected, not repaired) | Corruption on concurrent writers | Phase 4 |
| Undo from the middle of the history | Owner must undo newer changes first | Phase 4 |
| A turn that fails before it starts is printed only on the server | Interface waits silently | Fix when touched |
| A failed preview is stored and not retried until the deck changes | A missing LibreOffice looks permanent | Fix when touched |
| Error types `guarded` does not convert (for example `KnowledgeError` during a source read) end the turn | A turn ends instead of the model correcting | Fix when touched |
| `api.py` and `context.py` read the deck and its log as two calls | A slightly inconsistent view in a race | Phase 4 |
| Proposal candidates sharing a slide id replace one another silently | Odd results | Fix when touched |
| Project knowledge and documents are shared across clients by design (D8); source tools cannot tell where a project document came from | Cross-client origin of project material not visible | Owner decision |
| Owner memory defaults to the real home directory (`~/.autodeck/memory/owner.md`) | Tests and demos must pass a temporary path | Known |
| The owner's words on a message that changed the deck persist in the change log and reach later threads | Sensitive pasted text persists | Known, by design |
| Prices are assumptions | Every cost figure is an estimate | Replace both price files before reading any number as fact |
| `gpt-5.6-terra` as lead and the whole tiering are provisional; `sit` and `prod` untested | Quality and cost unknown on Anthropic models | Run before relying on them |
| Several module docstrings are stale (for example `edits.py` "enough for Phase 0") | Misleading for a newcomer | Fix when touched |
| WIP commit `af010f0` contains prototype bodies for five modules captured while scaffolding | A reader could mistake them for the code | Read the working tree, not that commit |
| v2's one failing test `test_a_missing_face_is_as_loud_as_a_missing_family` | Red full suite in this environment | v2 |

## 8. Model routing: planned vs actual

Build time. Each phase document's task table carries a planned tier per task (Haiku for
mechanical bodies pinned by docstrings and tests, Sonnet for implementation, the lead tier for
verification and prompts). **Actual tiers were not recorded** in the repository, and I did not
audit the commit history for deviations; treat the planned tags as the record. Runtime: the
provisional layer bindings are in `config/studio.yaml` and `docs/MODEL_ROUTING.md` Part 3.

## 9. Preconditions for the next phase

- The owner decides the order (STATUS.md lists mine). Nothing is scheduled.
- Decide the branch: rename, rebase, or cut `v3/integration` from this branch.
- Keys: `OPENAI_API_KEY` for `dev-openai`; `ANTHROPIC_API_KEY` before any `sit` or `prod` run;
  `MISTRAL_API_KEY` for `dev-mistral`. A real run costs money; the owner's limit for the last
  session was 50 US dollars, with about 39.50 estimated spent. Confirm the real price lists and
  update `config/studio_prices.yaml` and `bench/slides/prices.yaml` first.
- Reference decks the owner considers well designed, if a vocabulary review is wanted.
- The owner's answer to plan §14 q5: when strict is needed. It sets where Phase 6 falls.
- v2 loose ends, if v2 matters: the live check of meeting step 9, step 13 on the real
  recording (on the owner's Mac), GATE 2 and GATE 3 (`docs/handovers/AGENT-MEETING-1.md`).

## 10. Verifying this phase from a cold start

```bash
./scripts/setup-dev-env.sh && uv sync
uv run pytest -q -p no:cacheprovider tests/studio
# expected (2026-11-16): 564 passed, 8 deselected
uv run pytest -q -p no:cacheprovider -m render tests/studio
# expected: 8 passed, 564 deselected (needs LibreOffice and fonts)
uv run pytest -q -p no:cacheprovider bench/slides/tests
# expected: 70 passed, 1 deselected
uv run pytest -q -p no:cacheprovider
# expected: 2696 passed, 1 failed (tests/test_design.py::test_a_missing_face_is_as_loud_as_a_missing_family), 6 skipped, 60 deselected
uv run python scripts/studio_demo.py
# expected: engagement northwind-retail / llm-inference-efficiency; 4 slides; pptx build about 0.07s;
# previews about 1.9s; an edit; undo "byte-identical to before: yes"
uv run python -m autodeck.studio --script tests/studio/fixtures/scripts/design_flow.json \
    --workspace /tmp/studio-check --port 8796
# then follow docs/STUDIO-GUIDE.md; Ctrl-C to stop. Use an empty workspace.
```

## 11. Reading notes for the next implementer

- **Read order for the code:** `models.py` (the base model and staleness), `store.py` and
  `changelog.py` (exact undo), `session.py` (`_run_turn_locked`, the turn in its fixed order),
  `tools.py`, `compose.py`, then `designer.py`. `docs/phases/V3-PHASE-2-3.md` "Design choices" is
  the best single explanation of why it is shaped this way.
- **The exit tests** are `tests/studio/test_phase0_done.py` and `test_phase23_done.py`. Phase 1's
  own exit test and its script `two_threads.json` were retired in Phase 2-3 (it was built on the
  retired `write_slide` tool); its guarantee, that a second thread opens from state with no
  transcript, is carried by the new exit test's thread two and by `test_context.py`.
- **Phase 1's document describes the Phase 1 tool set and contract.** Phase 2-3's document says
  what replaced them. Where they differ, Phase 2-3 wins.
- **The scripted model matches by text.** `design_flow.json` finds designer calls by
  `Slide id: s2` and `Name: Demand curve`; `brief_user_text` is pinned byte for byte, so changing
  it means updating the script's matches.
- **Do not copy v2's habit of strict-first.** The base model deliberately has no claim,
  citation or approval. When the overlay is built it keys on `slide_id:block_id`, which Phase 0
  keeps stable across edits.
- **What looks wrong but is deliberate:** the studio draws through v2's low-level functions
  rather than `render_deck`, because `render_deck` runs v2's A2 and A5 guards, which are right for
  v2 and must not be loosened; a few chart and figure objects are built with `model_construct` to
  skip the citation requirement for the length of a draw; the palette is copied onto the deck's
  design reference so a render is a pure function of the deck; the `stale` marker is never set by
  code because staleness is computed.
- **The real finding of the build:** one model doing everything in a loop gives generic slides
  that pass QA; one slide per call with a design decided once gives designed slides. Keep the lead
  out of layout, and keep measuring at the slide level before the deck level (owner decision).
- **Suggested before anything else:** confirm the real price lists, so no figure needs the word
  "estimate"; and run one Anthropic-model session, so the `sit` and `prod` bindings are not
  carried on faith.
