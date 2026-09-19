# Changelog

Notable changes to AutoDeck. Newest first.

Maintained per plan §0.6 alongside `DECISIONS.md`. This file records *what changed*;
`DECISIONS.md` records *why*, and the two cross-reference by decision id.

---

## [Unreleased] — Phase 2b: content, linters, validation

All eleven Phase 2b tasks. **GATE 2 is not closed** — it asks the owner to read the claims
table and approve or send claims back, and no claims table has been put to them. **No live
milestone run exists either**: `autodeck content` refuses to run without an approved
outline, and no flag anywhere approves a gate. See `docs/handovers/PHASE-2B.md` §3 and §10.

### Added
- `autodeck/audit/numeric_linter.py` — **A2**. Every numeral in deck text traces to a cited
  span or to a derivation that re-executes to its stated result. Normalisation is
  declarative (each row carries a `why`, and import fails if two rules claim the same
  surface form), arithmetic is `Decimal`, and formulas are re-executed by AST walk rather
  than `eval` — they are model-generated text, so that is a security property.
- `autodeck/audit/framing_linter.py` — **A5**. A `framing` block carrying a fact is
  **demoted** to `claim`, and the demotion's `materialise()` raises from `Claim.citations`.
  The IR's refusal to construct the block *is* the A1 failure; nothing re-implements it.
- `autodeck/audit/verdicts.py` — **A3**'s rule, in a guardrail path. Four ordered bounds
  applied to the model's answer after the fact, so a model that ignores its instructions
  still cannot produce `supported` with no evidence. `ValidatorEvidence` refuses at
  construction any citation not marked `retrieved_by="validator"`.
- `autodeck/agents/content.py` — one `content` call per slide. The model picks a verbatim
  quote; the **code** resolves it into a citation with a real page, bbox and hash. A quote
  that does not resolve drops the claim rather than producing an uncited block.
- `autodeck/agents/validation.py` — independent re-retrieval, a separate contradiction
  pass, six claims per `validation` call. A provider failure returns `unverified` with a
  reason, never a guess.
- `autodeck/audit/report.py` — the working shown for every derivation, per-input
  traceability, and conflicts recorded with **both** spans. A test asserts the averaged
  figure is absent: averaging two disagreeing sources invents a number nobody measured.
- `autodeck/audit/manifest.py` — `canonical_pptx_digest`, `knowledge_commit`,
  `knowledge_dirty`, `Manifest.reproducible()`. Nothing is named `bytes_match` (B29).
- `autodeck/design/budget_check.py` and per-slot budgets in
  `autodeck/design/components/catalog.py` — over-budget text is rejected **before** render.
- `autodeck/pipeline/send_back.py` and four CLI commands — `content`, `validate`, `gate2`,
  `send-back`. Rejecting a named claim existed nowhere before this phase.
- `prompts/content.md`, `prompts/validation.md` — the writer and its adversary.

### Fixed
- **`budgets.py` under-predicted line height by ~7.4%, in the direction that overflows.**
  Pitch was derived from hhea `ascent + descent` (1.1172 for Liberation Sans); LibreOffice
  renders **1.20** for every family tested, whose own metrics range 1.059–1.200. It is an
  engine convention, not a value read from the font, so `LINE_HEIGHT_FACTOR` is now measured
  rather than derived.
- **The LibreOffice cross-check could not have caught that**, and read as agreement while
  being two errors cancelling: it compared rendered *ink* against a predicted *line box*.
  It now measures line pitch, the quantity the prediction is actually about.
- **A derivation could cite real spans and still invent its inputs.** B13 required a value
  *and* a citation, but never that the value appear in the quote — reproduced with inputs
  900/300 against spans reading 671/412, which passed every check and traced to itself.
  `check_derivation_inputs` closes it.
- **A clean `Deck` was no longer sufficient evidence that A1 and A5 hold.** A demoted
  framing block, and a validation pass that failed outright, both leave
  `Deck.blocking_blocks()` empty. `require_safe_to_render` is now the single place that
  knows what "safe to render" means.
- `prompts/validation.md` asked the model for citation objects with pages and hashes, which
  no model can compute. It asks for verbatim quotes; the system resolves them, and an
  unmatched quote is dropped.
- Two component slots had no budget coverage at all — `big_number.supporting_points` (whose
  presence also switches the renderer to two columns, halving the *other* slots' widths) and
  multi-point `two_column_compare` columns.

### Changed
- Phase branches 2b–3b stack on each other and **merge nothing** until the owner works each
  gate (**B27**) — BRANCHING rule 3 derives from A7, rule 1 is a topology convention, so the
  convention yields.
- Guardrail paths hold their model tier regardless of a task's tag (**B28**). A3's rule and
  the aesthetic action set were *split* out of their agents so the invariant sits inside a
  guardrail path rather than being de-tiered with its plumbing.
- Five invariant cells move to `tested`; **A6 deliberately does not** (see below).

### Open
- **B29 — A6 promises "byte-comparable" PPTX output, which is measurably impossible.** Two
  identical saves two seconds apart differ in bytes from four causes outside our control,
  while the canonical digest matches; A6's own "watch for" line contradicts its headline.
  `docs/INVARIANTS.md` is deliberately unedited — changing what an invariant says is the
  owner's call, not the implementer's.
- **A gate approval does not survive the machine.** Approvals live in
  `runs/<id>/state.json`, which is derived data and not committed (B22).

---

## [Unreleased] — Phase 2a: planning agent & outline

All nine Phase 2a tasks. **GATE 1 is not closed** — it asks the owner whether an outline
delivers the brief's argument, and no outline has been put to them. See
`docs/handovers/PHASE-2A.md`.

### Added
- `DeckBrief` with `KeyMessage`, `OpenRisk` and `LayoutPin`. **A8 lands structurally**: a
  key message the evidence check calls `thin` or `unsupported` cannot reach a signed brief
  without a matching `OpenRisk` naming who accepted it. Deliberately not a block on weak
  messages — blocking would push the planner toward marking things `supported` to get past
  the validator, which is the failure A8 is about.
- `autodeck/agents/evidence_gap.py` — the phase's reason for existing (§6.13). Deterministic
  retrieval, model judgement, and a **ceiling on the judgement**: zero citable spans is
  `unsupported` with the classifier never called; a single non-curated hit is capped to
  `thin`. Applied to the model's answer rather than requested in the prompt.
- `autodeck/agents/planner.py` — the planning session. Ends only on human sign-off, which is
  A7 approval 1 of 4. `ready_for_signoff` is a suggestion the code never reads.
- `autodeck/agents/outline.py` — signed brief → IR skeleton, with nowhere to put prose.
- `autodeck/audit/gate1.py` — GATE 1's mechanical checks. Reports; decides and fixes nothing.
- `prompts/planner.md`, `prompts/outline.md`; `autodeck plan` and `autodeck outline`.
- `Slide.intent`, `.message_ids`, `.pin_deviation`; briefs versioned as YAML.

### Fixed
- **Gemini silently dropped every nullable nested array** (B26). Live sessions produced good
  briefs in prose and recorded nothing — no error, and non-deterministic. The `gemini` schema
  flavor now emits `nullable: true` rather than `anyOf: [X, null]`, and the planner's core
  fields are required.
- `ModelRegistry.provider_for(role, model=...)` raised `TypeError` — `model` was pinned
  ahead of `**overrides`, so the only useful override could not be used.
- Dev bindings pointed at the retired `gemini-2.5-pro` (B23).
- GATE 1 blocked on a missing `must_include`, which is weak evidence at outline stage. Now
  advisory; `must_avoid` appearing stays blocking.

### Changed
- Dev roles spread across five Gemini models (B25) — daily quota is per model, and a
  validator on a different model from the writer is better for A3.
- Evidence spans truncated to 500 chars for classification (B24).

---

## [Unreleased] — Phase 1: ingestion & knowledge

All ten Phase 1 tasks. **GATE 1a approved** 2026-08-02 (DECISIONS.md G1a) — the owner
reviewed the spot-check worksheet and four of the ten rendered pages. See
`docs/handovers/PHASE-1.md`.

### Added
- `autodeck/ingest/` — the provenance chain (A1). `document_store.py` is the chokepoint:
  verbatim `text` and generated `description` are separate fields because a single
  `content` field would eventually be searched by something that did not know the
  difference. `provenance.py` matches tolerantly (ligatures, curly quotes, line-break
  hyphens) but never approximately, returning offsets into the verbatim string.
  `docling_runner.py` splits at the ML seam so every provenance decision sits in a pure
  function testable without model weights.
- `autodeck/ingest/figure_describer.py` — VLM figure descriptions via the `ingest_vlm`
  role. Descriptions are retrievable and **structurally cannot be cited**: they are written
  to `description` only, and the invariant is re-asserted after each write rather than
  assumed.
- `autodeck/ingest/grobid.py` — a deliberate stub that raises, documenting the three
  triggers that would justify implementing it (plan §6.3).
- `autodeck/knowledge/` — two-tier folders (D8) and **A4 client isolation**. One namespace
  per build, bound at construction; every read goes through it, including the non-obvious
  leak paths — reference decks and cached retrieval indices.
- `autodeck/retrieval/hybrid.py` — BM25 + optional embeddings fused by reciprocal rank.
  **There is no chunker**: elements are the chunks, so a hit cannot exist without
  resolvable provenance.
- `autodeck/audit/spotcheck.py` — renders a citation's bbox onto its source page for
  GATE 1a. Emits no verdict, and says in as many words that a passing hash is not evidence
  the box is right.
- `autodeck knowledge validate | ingest | ask | spotcheck`, plus the first CLI tests.
- `knowledge/` — the seed corpus: five CC BY 4.0 papers on LLM inference efficiency, 16
  curated claims all hash-verified, and two fictional clients (two, because A4 is not
  demonstrable with one). See B20, B21.

### Fixed
- **Docling bboxes were vertically mirrored.** The conversion swapped `t` and `b` instead of
  computing `page_height - y`, producing well-formed rectangles still in bottom-left space.
  Nothing crashed and a mirrored bbox hash-verifies perfectly; it was caught only by
  rendering a real page and looking at the box.
- **A cross-client reference in the seed corpus**, caught by `check_text` on its author:
  `contoso-health/client.md` named the other client while explaining its own purpose, in a
  file loaded into prompts.
- **`knowledge ask --client` accepted a client that did not exist.** `use_index` checks the
  index's namespace, not the client's existence, so a typo passed silently.

### Changed
- `run_docling` takes `generate_picture_images`; `ingest_pdf` takes a `vision_provider`.
- `corpus/` and `spikes/gate1a/` are gitignored as derived data (B22).

---

## [Unreleased] — Phase 0: foundations & de-risking

All seven Phase 0 tasks. **GATE 0 is not closed** — its criteria require the owner to open
the spike files in PowerPoint, which no headless environment can do. See
`docs/handovers/PHASE-0.md` §10.

### Added
- `autodeck/ir/` — **Deck IR v1** (D4). `models.py` finalises the §6.1 sketch; `schema.py`
  exports JSON Schema in three provider dialects; `store.py` versions IR immutably under
  `runs/<id>/` and diffs two versions by object id so an inserted slide reads as one
  addition rather than a cascade.
- **A1 enforced structurally**: `Claim.citations` has `min_length=1`, so a claim carrying no
  evidence cannot be constructed — speaker notes included.
- `autodeck/providers/` — provider protocol with schema-enforced `complete_structured`,
  repair-retry that hard-fails rather than returning a partial object, 429-aware backoff,
  and a resumable on-disk response cache. Gemini, Groq and Claude adapters over one shared
  httpx transport (B14); environment-tiered registry with `--env` (B8).
- `autodeck/design/` — font resolution that raises rather than substituting (B11);
  glyph-metric text budgets (§6.7); OOXML theme and slide-master generation (D1);
  `layout_kit` v0; `big_number` and `two_column_compare`; SVG→DrawingML `custGeom` icon
  converter with ten vendored Lucide icons under ISC (D11).
- `autodeck/render/qa/libreoffice.py` — headless render to PNG that **refuses to render**
  when a declared font is absent, rather than producing a silently substituted preview.
- `autodeck/pipeline/orchestrator.py` — run directories, resumable stages, and A7 gate
  stubs that raise `GateBlocked`. A test asserts no CLI flag can bypass a gate.
- `autodeck/audit/manifest.py` — A6 build manifest recording environment, resolved model
  IDs, prompt hashes and IR hash; compares two builds excluding timestamps.
- `autodeck/cli.py` — `run --stub`, `approve`, `status`, `models`, `ir`, `fonts`, `spike`.
- `config/models.yaml`, `config/tokens/{aptos,dev}.json`, `.github/workflows/ci.yml`,
  `pyproject.toml`, `fonts/README.md`, `prompts/README.md`.
- `spikes/gate0/` — the three GATE 0 artifacts, their previews, and `provenance.json`
  recording which font family each was rendered in.
- `docs/handovers/PHASE-0.md`.

### Changed
- `.gitignore` — comment clarifying that `tokens/` is v1's *secrets* directory, which is
  why v2 design tokens live in `config/tokens/` (B18).
- `STATUS.md`, `docs/INVARIANTS.md` coverage tracker, `docs/handovers/README.md` index.

### Findings
- **Spike 0.5 supports D5.** Two components reach a high visual bar authored natively, and
  the edit→preview loop runs at **2.25s median** — fast enough for a 15-component library.
- **Spike 0.6 supports D11** at the geometry level: ten icons round-trip to native
  theme-recolourable vector strokes, arcs and compound paths included.
- **B11 check #4 answered by verification, not assumption: Aptos has no metric-compatible
  open clone.** "Aptos installed on the build machine" is a hard prerequisite for Phase 2b.
- Groq serves no multimodal model, so it cannot relieve Gemini's free-tier pressure on
  `ingest_vlm` (B16).

### Decisions
B13 (derivation inputs carry values), B14 (one HTTP transport), B15 (resolved model IDs),
B16 (Groq text-only), B17 (`TextStyle` unifies measurement and rendering), B18 (token path).

---

## [Unreleased] — v2 scaffold

Planning scaffold for the v2 rewrite. No v2 package code — see `STATUS.md`.

### Added
- `README.md` — v2 durable context: v1 post-mortem, locked decisions D1–D13, accuracy
  invariants A1–A8 in full, target architecture, roadmap, model routing summary.
- `STATUS.md` — current build state and next action.
- `DECISIONS.md` — append-only log seeded with D1–D13 and build decisions B1–B9.
- `CHANGELOG.md` — this file.
- `docs/AUTODECK_V2_PLAN.md` — vendored specification, the source of truth.
- `docs/BRANCHING.md` — branch topology, gate protocol, PR and commit conventions.
  Distinguishes the six build-time GATEs from the four runtime approvals (A7).
- `docs/MODEL_ROUTING.md` — dev-time tiers with path guardrails, escalation and
  de-escalation rules, the docstring-delegation pattern, and environment-tiered runtime
  bindings.
- `docs/INVARIANTS.md` — A1–A8 as checkable items with enforcer, owning phase, proving
  test, and a coverage tracker.
- `docs/phases/PHASE-{0,1,2A,2B,3A,3B,4,5}.md` — eight phase briefs, every task tagged
  with a model tier, human-checkable gate criteria, and named escalation triggers.
- `docs/handovers/TEMPLATE.md` and index — per-phase handover format.
- `docs/reference/slide-geometry/` — vendored skill seeding the diagram engine (§6.11.2),
  with a note that the python-pptx column of `construction.md` is authoritative (B6).
- `legacy/v1/LEGACY.md` — salvage and retire map with function-level pointers.

### Changed
- v1 moved to `legacy/v1/` via `git mv`, history preserved (B2). The tree is frozen;
  nothing in `autodeck/` may import from it.
- Runtime provider strategy is environment-tiered — Gemini + Groq for `dev`, Claude for
  `sit`/`prod` (B8). Phase 0 now builds three provider adapters rather than two.

### Removed
- `.DS_Store` (tracked by accident, already in `.gitignore`).
- `generated_decks/temp_slide_{0..4}.pptx` (render artifacts). Both recoverable from
  `main` and from history.

### Notes
- Plan §8 lists v1's validation agent as salvage. Inspection shows it is mostly
  *image-quality* checking; A3's independent re-retrieval and contradiction search have no
  v1 ancestor. Recorded in `legacy/v1/LEGACY.md` so Phase 2b is scoped as new construction.
