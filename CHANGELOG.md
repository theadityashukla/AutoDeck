# Changelog

Notable changes to AutoDeck. Newest first.

Maintained per plan §0.6 alongside `DECISIONS.md`. This file records *what changed*;
`DECISIONS.md` records *why*, and the two cross-reference by decision id.

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
