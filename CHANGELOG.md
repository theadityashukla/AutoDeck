# Changelog

Notable changes to AutoDeck. Newest first.

Maintained per plan §0.6 alongside `DECISIONS.md`. This file records *what changed*;
`DECISIONS.md` records *why*, and the two cross-reference by decision id.

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
