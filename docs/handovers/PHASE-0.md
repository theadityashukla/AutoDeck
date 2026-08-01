# Phase 0 — Foundations & de-risking — Handover

---

## 1. Identification

| | |
|---|---|
| **Phase** | 0 — Foundations & de-risking |
| **Branch** | `v2/phase-0-foundations` |
| **PR** | not opened — the owner has not asked for one |
| **Started / completed** | 2026-07-26 → 2026-08-01 |
| **Gate** | GATE 0 |
| **Gate status** | **approved with conditions** — see DECISIONS.md G0 |
| **Approved by / when** | Owner, 2026-08-01: *"the presentation is good. let's proceed."* |
| **What the owner actually checked** | The rendered output of spike 0.5 — `big_number` and `two_column_compare` meet the visual bar. The owner did **not** separately report the two PowerPoint-behaviour checks: palette under Design → Variants (0.4), and icon select/scale/recolour as a native shape (0.6). |

**What the approval settles, and what it does not.** D5 was the architectural risk — plan
§6.6 rejects every alternative rendering path, so a failure there would have forced
re-planning before Phase 3. It passed: native authoring reaches the bar, and the measured
2.25s edit→preview loop makes a 15-component library credible.

D11 is carried as **verification debt**. The converter is proven at the geometry level
(ten icons round-trip and rasterise correctly) but not in PowerPoint, which is where the
criterion lives. **Phase 3a must confirm it before building the icon system on it**; the
documented retreat is `svgBlip` + PNG embedding (plan §9), which costs "icons are vectors
end to end" but not the architecture. The theme check (0.4) is in the same position.

This is recorded precisely rather than as blanket sign-off because plan §0.3 forbids the
implementing agent self-approving a criterion nobody exercised.

## 2. What shipped

| Path | What it does | Tests |
|---|---|---|
| `pyproject.toml`, `.github/workflows/ci.yml` | Python 3.11+, uv, ruff/pyright/pytest. CI runs lint, types, tests only — no container, no LibreOffice (B10) | CI itself |
| `autodeck/ir/models.py` | Deck IR v1. **A1 is a schema constraint**: `Claim.citations` has `min_length=1` | `tests/test_ir_models.py` |
| `autodeck/ir/schema.py` | JSON-Schema export in three provider dialects (standard / OpenAI-strict / Gemini) | `tests/test_ir_schema.py` |
| `autodeck/ir/store.py` | Immutable versioned IR under `runs/<id>/ir/v<N>.json`; id-keyed diff for gate review | `tests/test_ir_store.py` |
| `autodeck/providers/*` | Provider protocol, repair-retry, 429 backoff, resumable response cache, Gemini/Groq/Claude adapters | `tests/test_providers.py`, `tests/test_providers_live.py` |
| `config/models.yaml`, `providers/registry.py` | `dev`/`sit`/`prod` bindings selected with `--env` (B8) | `tests/test_registry.py` |
| `autodeck/design/fonts.py` | Font resolution. A missing family is `FontNotFoundError`, never a substitution | `tests/test_design.py` |
| `autodeck/design/budgets.py` | Wrapped-text measurement from real glyph metrics; per-slot budgets (§6.7) | `tests/test_design.py` |
| `autodeck/design/theme/{tokens,master_builder}.py` | `DesignTokens`; real OOXML `theme1.xml` written into the package | `tests/test_design.py` |
| `autodeck/design/layout_kit.py` | Boxes, stacks, grids, baseline rhythm, `TextStyle`, `Canvas` | `tests/test_design.py` |
| `autodeck/design/components/renderers/` | `big_number`, `two_column_compare` | rendered artifacts |
| `autodeck/design/icons/` | SVG path parser, `custGeom` converter, 10 vendored Lucide icons (ISC) | `tests/test_design.py` |
| `autodeck/render/qa/libreoffice.py` | Headless render → PNG, refusing to render when a declared font is missing | `render` marker |
| `autodeck/pipeline/orchestrator.py` | Run dirs, resumable stages, **blocking** A7 gate stubs | `tests/test_orchestrator.py` |
| `autodeck/audit/manifest.py` | A6 manifest: env, resolved model IDs, prompt hashes, IR hash | `tests/test_orchestrator.py` |
| `autodeck/cli.py` | `run --stub`, `approve`, `status`, `models`, `ir diff/versions/schema`, `fonts check`, `spike build` | exercised in §10 |
| `config/tokens/{aptos,dev}.json` | The deliverable token set and the container one | `tests/test_design.py` |
| `spikes/gate0/` | The three GATE 0 artifacts, their previews, and `provenance.json` | owner review |

**192 tests pass; ruff and pyright are clean.**

## 3. What did not ship

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|
| 0.3 — live Claude structured-output proof | No `ANTHROPIC_API_KEY` in this environment. Adapter is written and unit-tested against a mocked transport; only the live call is missing | **Owner**, before GATE 0 closes — `pytest -m live -k claude` |
| 0.4 — B11 check #2, budgets measure *real Aptos* metrics | The mechanism is built and proven against Inter; Aptos itself is unobtainable here | **Owner**, locally |
| 0.4 — B11 check #3, headless LibreOffice has Aptos | Structurally unanswerable in a container | **Owner**, locally |
| 0.4 — B11 check #1, TTFs obtainable on the build machine | Documented in `fonts/README.md` with per-platform paths; not verifiable here | **Owner**, locally |
| 0.5 / 0.6 — the visual and PowerPoint-behaviour judgements | Need PowerPoint | **Owner**, at GATE 0 |
| Slide **layouts** beyond the blank master | Task 0.4 asks for "one slide master"; the theme and master ship, but the layout set proper belongs with the component catalogue | **Phase 3a** |

## 4. Decisions made this phase

Recorded in `DECISIONS.md`:

- **B13** — `Derivation.inputs` carries values, not bare citations (A2 needs re-executable arithmetic).
- **B14** — one shared httpx transport instead of three vendor SDKs.
- **B15** — resolved model IDs for `dev`, looked up live; Claude IDs unverified.
- **B16** — Groq is text-only; the registry refuses to bind it to a vision role.
- **B17** — `TextStyle` unifies measurement and rendering.
- **B18** — design tokens live in `config/tokens/`, not `tokens/`.

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | not-started | **tested** | `test_claim_without_citations_is_rejected`, `test_speaker_notes_are_blocks_and_get_the_same_treatment`, `test_citation_hash_must_match_its_quote` |
| A2 numbers | not-started | partial | `test_derivation_inputs_must_appear_in_the_claim_citations`, `test_derivation_carries_values_so_the_formula_can_be_re_executed` — the IR can express a re-executable derivation; the linter is Phase 2b |
| A3 validation | not-started | partial | `test_failing_verdicts_block_render` — verdicts exist and identify blocking blocks; the validator is Phase 2b |
| A4 isolation | not-started | not-started | — (Phase 1) |
| A5 framing | not-started | not-started | — (Phase 2b) |
| A6 reproducibility | not-started | partial | `test_two_builds_match_despite_different_timestamps`, `test_a_changed_model_binding_breaks_the_match` — manifest exists and compares correctly; render determinism is Phase 3b |
| A7 gates | not-started | **enforced** | `test_an_unapproved_gate_raises`, `test_no_command_can_bypass_a_gate` — mechanism proven; the four real gates are wired in 2a/2b/4 |
| A8 uncertainty | not-started | not-started | — (Phase 2b, eval-defended in Phase 5) |

## 6. Spike and experiment findings

### 0.4 — theme: passes on everything testable here

Real OOXML `theme1.xml` with `clrScheme`, `fontScheme` and `fmtScheme` is generated and
substituted into the package by rewriting the zip entry — python-pptx has no API for theme
parts. A test asserts the substitution changes **exactly one** part. LibreOffice opens the
result cleanly, which is a real (if weak) validity signal.

Two details that would have cost time later: `dk1`/`lt1` need `a:sysClr`, not `a:srgbClr`,
or PowerPoint's text/background UI pairs them wrongly; and each `fmtScheme` list needs
exactly three entries or PowerPoint offers to repair the file.

**Unproven here:** that the palette appears in PowerPoint's Design → Variants UI. That is a
GATE 0 criterion and needs the owner.

### The four Aptos checks (B11)

| # | Check | Result |
|---|---|---|
| 1 | TTFs obtainable on the build machine | **Open.** Per-platform Office font paths documented in `fonts/README.md`. Unverifiable here |
| 2 | `budgets.py` measures the real Aptos metrics | **Mechanism proven, font unproven.** Measurement reads the actual TTF via fontTools and `require_fonts()` raises when the family is absent. Verified end-to-end against Inter; `config/tokens/aptos.json` correctly raises `FontNotFoundError` here |
| 3 | Headless LibreOffice has Aptos | **Unanswerable in this container.** `render_pptx` now *refuses to render* rather than producing a substituted preview, so the failure is loud instead of silent — but only the owner's machine can answer it |
| 4 | Is there a metric-compatible fallback? | **Verified: no.** Not assumed. The familiar substitution pairs (Carlito↔Calibri, Caladea↔Cambria, Liberation↔Arial) all exist because those faces are decades old and were cloned deliberately. Aptos is recent and has no such clone; nothing in this container's 59 installed families is metric-compatible with it. **"Aptos installed on the build machine" is a hard prerequisite, not a convenience** — treat it as a setup step for Phase 2b and Phase 3 |

### 0.5 — native design: **passes.** D5 is supported on both quality and speed

Two components authored natively reach a bar I would put in front of a client (see
`spikes/gate0/previews/components-*.png`). The owner's judgement is the one that counts.

**Iteration speed: 2.25s median edit→preview** (five cycles; min 1.97s, max 2.97s; two
slides per cycle). Comfortably fast enough to sustain a 15-component library — this was an
explicit exit criterion and it is not close to the line.

**The most valuable finding of the phase is a bug the loop caught immediately.** The
renderer applied a 1.25 line-spacing multiplier that the measurement function knew nothing
about, so every measured height was ~20% short and each element was drawn on top of the
previous one's last line — an accent rule struck straight through a headline. This is
*exactly* the class of failure the budget system exists to prevent, arriving by the back
door: measurement and rendering had drifted apart because they took separate arguments.

Fixed at the class level, not per-site: one `TextStyle` now feeds both, so the divergence
is unrepresentable rather than merely discouraged (B17). **Phase 2b and 3a should treat
this as the standing rule — anything that affects rendered height must reach the renderer
and the measurer as one object.**

Two further defects the loop surfaced, both fixed:
- padding only the *emphasised* comparison column pushed its title half a line below its
  neighbour, breaking the alignment that makes a comparison readable across;
- the emphasis panel was drawn at full region height while its content was stacked
  independently, so the last row overflowed the panel. Column height is now measured, and
  genuine overflow raises `LayoutOverflowError` rather than drawing past the edge.

**A negative result worth keeping:** the original sample content — a two-line headline plus
four two-line comparison points at 16pt — genuinely does not fit a 16:9 slide. The budget
guard caught it and the content was shortened, which is precisely the loop §6.7 describes.
Phase 2b's content agent will hit this constantly; budgets must reach it as hard prompt
constraints, not advice.

### 0.6 — icon vector: **passes at the geometry level.** D11 is supported

Ten Lucide icons round-trip SVG → `custGeom` and render as true vector strokes in five
different theme accent colours, including arcs (`git-branch`), compound paths (`layers`)
and multiple circles (`target`). See `spikes/gate0/previews/icon-1.png`.

**Converter edge cases, as the brief requires:**

- **Packed arc flags — the one that actually bit.** SVG arc flags are single characters and
  may run together with the following coordinate: `a1.5 1.5 0 00-2.474-1.561` is
  rotation `0`, large-arc `0`, sweep `0`, x `-2.474`. A regex tokeniser reads `00` as the
  single number `0` and every subsequent argument shifts. Lucide's `zap` icon does this.
  The parser is therefore a **position scanner** that knows which argument index is a flag,
  not a token list. Any future SVG parser in this codebase must keep that property.
- **Arcs** are converted to cubic Béziers via the SVG spec's endpoint-to-centre
  parameterisation, split at 90°. `a:arcTo` was not used: it is parameterised by swing
  angles, so the same arithmetic is required either way, and doing it in the parser keeps it
  testable in isolation.
- **Compound paths** get **one shape per subpath**, grouped by name. A single `custGeom`
  with several `<a:path>` elements shares one fill rule, which renders a set of separate
  strokes as one filled blob.
- **Fill rules** are moot for this family: Lucide is stroke-only, so shapes carry `a:noFill`
  plus a themed `a:ln`, and `fill="none"` on the path stops PowerPoint closing open strokes.
  A fill-based icon family would need `evenodd`/`nonzero` handling that does not exist yet.
- **Round caps and joins** must be set explicitly (`cap="rnd"` + `<a:round/>`), or the
  strokes end square and the icons read as a different, blockier family.

**Unproven here:** that the shapes select, scale and recolour *in PowerPoint*. LibreOffice
rasterises them correctly, which is encouraging but not the criterion.

### 0.3 — provider parity

Gemini and Groq both pass structured output against a trivial schema, and both recover
through the repair path from a deliberately hostile prompt. Claude is unverified — no key.

**Groq serves no multimodal model** (B16), confirmed by a live 400: `messages[0].content
must be a string`. It therefore cannot relieve Gemini's free-tier pressure on `ingest_vlm`,
which `docs/MODEL_ROUTING.md` predicts is where rate limits bite first in Phase 1. The
registry now rejects such a binding at config load rather than at the first figure of a
corpus run.

### Environment findings (not in the brief, but they cost time)

The container needed three packages installed that a fresh machine will also need:
`libreoffice-impress` (the base image had `libreoffice-core` only, so *every* PPTX failed
to load with a misleading "source file could not be loaded"), `poppler-utils` (LibreOffice's
own PNG export emits only the first slide, so multi-slide decks rasterise via PDF), and a
font family. Worth a `SessionStart` hook or a setup script in Phase 1.

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| GATE 0's three PowerPoint checks unperformed | The rendering strategy is unratified; Phase 3 would build on an unconfirmed D5/D11 | **Owner**, now |
| Claude adapter never called live | A `sit` run would be the first real test of the binding that gates client work | **Owner** / Phase 2a |
| Aptos absent from the build machine (checks 1–3) | Phase 2b's budgets and Phase 3's design loop are both wrong-by-default without it, and no metric-compatible fallback exists | **Owner**, before Phase 2b |
| Slide *layouts* not authored | Phase 3a needs a layout set, not just a master | Phase 3a |
| `vision()` unproven on Claude | Phase 3b's aesthetic critique runs on it in sit/prod | Phase 3b |
| Preview loop is local-only (B10) | No CI can catch a visual regression; the golden-PNG discipline in §6.6 is the only guard | Phase 3a |
| Two components ≠ a component catalogue | The `catalog.py` registry (name → role → slots → budgets → renderer) does not exist yet | Phase 3a |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| 0.1 skeleton | Opus scaffolds, Haiku fills | Opus throughout | No delegation was available in this session; the work was small enough that routing it would have cost more than it saved. **Not a precedent** — 0.1-style boilerplate is exactly what Haiku should do |
| 0.2 Deck IR | Opus | Opus | Correct, and the guardrail earned its keep: the `Derivation` change (B13) was a contract decision, not an implementation detail |
| 0.3 providers | Opus | Opus | Repair semantics and the retry/no-retry split are judgment |
| 0.4–0.6 spikes | Opus | Opus | Correct per the routing doc |
| 0.7 orchestrator | **Sonnet** | Opus | Escalated. The gate mechanism *is* A7, and `autodeck/audit/manifest.py` is an Opus guardrail path, so the task straddled the line — `docs/MODEL_ROUTING.md` says take the higher tier when it does |

**Honest note:** this phase ran entirely at Opus tier, against tags that assumed a mix. The
tags are not wrong — Phase 0 is unusually contract-heavy and three of its seven tasks are
spikes whose output is a judgement. But **Phase 1 has no such excuse**: the Docling runner,
document store, knowledge loader and retrieval are Sonnet work against settled interfaces,
and the de-escalation rule (`MODEL_ROUTING.md` §5) should start paying from there.

## 9. Preconditions for the next phase

Phase 1 is `v2/phase-1-ingest-knowledge`. Before cutting it:

1. **GATE 0 approved** by the owner, per §10. Nothing merges before its gate
   (`docs/BRANCHING.md` rule 3).
2. **Q2 answered** — which project and client seed the build, real or anonymised? This is
   the next open question and it blocks Phase 1 directly.
3. **Aptos installed** on the build machine, and B11 checks 1–3 confirmed. Not strictly a
   Phase 1 blocker, but it blocks Phase 2b and is cheapest to do while the context is fresh.
4. `ANTHROPIC_API_KEY` available if the Claude live proof is to close with GATE 0.
5. Setup: `libreoffice-impress`, `poppler-utils`, and the font family on any machine that
   runs the preview loop.

## 10. Verifying this phase from a cold start

```bash
uv sync
uv run ruff check . && uv run ruff format --check .   # All checks passed!
uv run pyright                                        # 0 errors, 0 warnings
uv run pytest -q                                      # 192 passed, 10 deselected

# Provider bindings and credentials for an environment.
uv run autodeck models --env dev

# Live structured output. Gemini + Groq pass here; Claude skips without a key.
uv run pytest -q -m live                              # 6 passed, 4 skipped

# The Phase 0 milestone: a versioned IR and a manifest, then a BLOCKED gate.
uv run autodeck run demo-001 --stub --env dev         # exits 3 at GATE 'brief'
uv run autodeck status demo-001
cat runs/demo-001/ir/v1.json runs/demo-001/build_manifest.json

# Re-running skips completed stages (resumability).
uv run autodeck run demo-001 --stub --env dev         # "skipped (already complete)"

# Gates are approved explicitly, never as a side effect.
uv run autodeck approve demo-001 brief --by aditya

# Rebuild the spike artifacts and previews.
uv run autodeck spike build --tokens config/tokens/dev.json

# Aptos correctly reports missing here, and loudly.
uv run autodeck fonts check --tokens config/tokens/aptos.json   # exits 1
uv run autodeck fonts check --tokens config/tokens/dev.json     # OK
```

### The part that actually closes GATE 0 — owner, in PowerPoint

Download `spikes/gate0/*.pptx` from this branch and open them in **PowerPoint**, not a
viewer.

1. **`theme.pptx`** — Design → Variants: does the palette appear as this deck's theme
   colours? Insert a slide by hand: does it inherit the fonts and colours? Select a swatch
   on slide 2 and open the fill picker: does it sit in the **Theme Colors** row?
2. **`components.pptx`** — do `big_number` and `two_column_compare` meet your visual bar?
   Bear in mind they are set in **Inter**, not Aptos (`provenance.json` records this).
3. **`icon.pptx`** — click an icon: does it select as a **shape**, not a picture? Drag a
   corner: do the strokes stay crisp? Open the shape *outline* colour picker: is the colour
   in the Theme Colors row, and does switching the theme variant recolour it?
4. On a machine with Aptos installed:
   `uv run autodeck spike build --tokens config/tokens/aptos.json` — judge the components
   in the real face, and confirm the preview does not fall back (it will refuse rather than
   substitute).
5. `export ANTHROPIC_API_KEY=… && uv run pytest -q -m live -k claude`

If 0.5 fails your visual bar, **escalate rather than improvise** — D5 is in question and
§6.6 forbids substituting an HTML path. If 0.6 fails in PowerPoint, D11 is in question and
the `svgBlip` + PNG fallback is the documented retreat, but it weakens "icons are vectors
end to end".

## 11. Reading notes for the next implementer

**Read `autodeck/ir/models.py` first.** Everything else derives from it, and the two places
worth understanding are `Claim.citations` (`min_length=1` — that single constraint *is*
A1) and `Block._payload_matches_kind`. If you find yourself wanting to relax either, stop
and re-read plan §0.4.

**The `TextStyle` lesson generalises.** The one real bug this phase produced came from two
functions that needed the same information and were given it separately. When you add
anything that affects rendered geometry — a new type role, paragraph indents, tighter
tracking — put it on `TextStyle` and pass the object. Do not add a keyword argument to
`add_text`; there is no longer a legitimate reason to.

**Things that look wrong but are deliberate:**

- `apply_theme` rewrites a zip entry by hand. python-pptx genuinely cannot author theme
  parts, and the alternative is hand-building the whole package.
- Adapters are ~80 lines each with no SDK (B14). The point is that the schema on the wire
  is exactly what `ir/schema.py` produced.
- `ProviderResponseError` is *not* retried while a 503 is. A safety block is deterministic
  for a given request; retrying it spends free-tier quota to learn nothing.
- The stub deck in `cli.py` carries a real citation. A1 has no exemption for stubs, and a
  stub that violated it would be the first thing someone copied.
- `runs/` is gitignored and `spikes/` is not. Spike artifacts *are* the gate deliverable.

**What I would do differently.** I would have written `TextStyle` before the first
component rather than after the first bad render — although in fairness, the render is what
proved it was needed, which is what a spike is for. I would also have installed
`libreoffice-impress` before assuming the PPTX was malformed; roughly twenty minutes went
into debugging a perfectly valid file against a LibreOffice that had no Impress filter.

**On the gate.** Do not let this branch merge on the strength of the PNGs. They were
rendered by LibreOffice, in Inter, on Linux. The deliverable is a PPTX opened in PowerPoint,
in Aptos, by the owner — and GATE 0 is described in the plan as the go/no-go for the entire
rendering strategy. It is worth the download.
