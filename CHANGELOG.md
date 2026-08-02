# Changelog

Notable changes to AutoDeck. Newest first.

Maintained per plan §0.6 alongside `DECISIONS.md`. This file records *what changed*;
`DECISIONS.md` records *why*, and the two cross-reference by decision id.

---

## [Unreleased] — Phase 1: ingestion & knowledge

All ten Phase 1 tasks. **GATE 1a is not closed** — it requires the owner to spot-check ten
citations against the source PDFs. Materials are generated and delivered; the checkboxes are
unticked. See `docs/handovers/PHASE-1.md`.

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
