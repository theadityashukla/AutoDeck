# Decision log

Append-only. Newest entries at the bottom of each section. Never edit or delete a past
entry — if a decision is reversed, add a new entry that supersedes it and mark the old
one `SUPERSEDED BY <id>`.

Per plan §0.6: when the plan is ambiguous, make the smallest reasonable decision, record
it here, and flag it in the phase summary.

**Who writes here:** Opus only (see `docs/MODEL_ROUTING.md`).

**Entry format:**

```
### <ID> — <one-line decision>
- **Date:** YYYY-MM-DD
- **Phase / branch:** 
- **Status:** active | superseded by <ID>
- **Context:** what forced a decision
- **Decision:** what we chose
- **Rationale:** why, including what we gave up
- **Consequences:** what this now constrains
```

---

## Locked product decisions (D1–D13)

These come from `docs/AUTODECK_V2_PLAN.md` §2 and are **locked**. Do not relitigate
without human sign-off; a reversal requires a new `R<n>` entry below with explicit
owner approval quoted.

| # | Decision | Rationale |
|---|---|---|
| D1 | Deliverables are fully editable native PPTX on a real slide master/theme XML | Clients reuse and extend decks; theme colours/fonts must appear in PowerPoint's own UI |
| D2 | Cloud APIs for everything; no local models | Removes MLX complexity; runs anywhere |
| D3 | Ingestion via Docling; provenance (page, bbox) preserved end to end | Serves auditability directly |
| D4 | Deck IR is the single source of truth; renderers are downstream | Auditability, swappability, review on diffs |
| D5 | PPTX is the medium end to end; **no HTML→PPTX conversion anywhere** | Conversion ports are where fidelity dies |
| D6 | Provider abstraction with structured outputs; Gemini first, Claude added | Model mobility |
| D7 | CLI/pipeline-first, headless core; review UI deferred | v1's Streamlit state machine was a documented cost |
| D8 | Knowledge = curated markdown folders loaded fully; retrieval only for paper corpora | Curated context beats blind chunk search |
| D9 | Accuracy invariants are blocking, not advisory | Consulting use case |
| D10 | Charts are native editable PowerPoint charts with data provenance | Clients restyle charts |
| D11 | Icons are vectors end to end (DrawingML shapes); raster icons forbidden | Clients recolour and scale icons |
| D12 | Header voice is a learnable per-client style profile; headers with facts are claims | Talking headers carry the argument |
| D13 | Text/icon/diagram balance enforced by deterministic grammar lints, not model taste | Prevents text walls and hieroglyphics |

Rejected alternatives that must **not** be revisited (plan §6.6): runtime HTML→PPTX
conversion; design-time HTML with hand-porting; PptxGenJS or other JS generators;
Office.js add-ins or macro-enabled files.

---

## Accuracy invariants (A1–A8)

Stated in full in `README.md` and made checkable in `docs/INVARIANTS.md`. They are
**contract, not preference**. Per plan §0.4: never weaken an invariant to make a test
pass or a demo work. If an invariant blocks progress, stop and surface the conflict to
the owner with options.

---

## Build-process decisions

### B1 — `v2/integration` is the v2 integration branch
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** v2 is a 20+ week, six-phase rewrite. It needs a long-lived branch that
  accumulates completed phases while `main` stays a working v1.
- **Decision:** the designated feature branch is the v2 integration branch. `main` is
  frozen at v1. Phase branches are cut from the integration branch tip and merge back
  into it.
- **Rationale:** keeps a shippable v1 on `main` for the whole v2 build; gives each phase
  an independently revertible merge commit.
- **Consequences:** no phase branch is ever cut from `main` or from a sibling phase
  branch. See `docs/BRANCHING.md`.

### B2 — v1 moves to `legacy/v1/` rather than being deleted
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** plan §8 requires v1 as salvage reference, but a v1 tree at the repo root
  competes with the new `autodeck/` package and confuses the entry point.
- **Decision:** `git mv` the tracked v1 tree into `legacy/v1/` with a `LEGACY.md`
  salvage map. Two build-artifact paths (`.DS_Store`, `generated_decks/temp_slide_*.pptx`)
  are deleted rather than moved.
- **Rationale:** `git mv` preserves history (`git log --follow` still works), so salvage
  reading is a directory away rather than a branch away.
- **Consequences:** `legacy/v1/` is frozen. Nothing in `autodeck/` may import from it.

### B3 — Model routing governs both dev-time and runtime
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** the owner asked that the build use Opus for architecture and scaffolding,
  Sonnet for code and functions, Haiku for heavy lifting.
- **Decision:** `docs/MODEL_ROUTING.md` defines both (a) which model implements which
  build task, enforced by a `model` tag on every task row in every phase brief, and
  (b) AutoDeck's own runtime provider-registry roles per plan §6.2.
- **Rationale:** routing left to per-task judgment decays immediately. Tags plus
  path-based guardrails make it structural.
- **Consequences:** a task without a `model` tag is not ready to start. Haiku is barred
  from `autodeck/ir/`, `autodeck/audit/`, `prompts/`, and invariant tests.

### B4 — Each phase lands via PR into the integration branch
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** plan §7 defines gates that must not be self-approved (§0.3).
- **Decision:** every phase branch opens a PR into the integration branch. The PR body
  carries the phase handover document; owner approval on the PR **is** the gate sign-off
  and is recorded here.
- **Rationale:** gives each gate a durable artifact and a review surface that is not chat.
- **Consequences:** PRs are opened only when the owner asks. Merge is `--no-ff`.

### B5 — Phase 2 and Phase 3 are each split into two branches
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** plan §7's Phase 2 is 4–5 weeks and already contains GATE 1 mid-phase;
  Phase 3 is 6–7 weeks across 10 tasks. Either as a single PR is unreviewable.
- **Decision:** split Phase 2 at its internal gate (2a planning + outline → GATE 1;
  2b content + linters + validation → GATE 2) and Phase 3 at the design/render seam
  (3a design system; 3b renderer + QA + art direction → GATE 3). Source-plan phase
  *numbering* is preserved so the two documents cross-reference cleanly.
- **Rationale:** review quality collapses past a few thousand changed lines, and gates
  are the accuracy backstop.
- **Consequences:** eight phase branches, six gates. GATE assignments in
  `docs/BRANCHING.md`.

### B6 — The `slide-geometry` skill is vendored, with a python-pptx precedence note
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** plan §6.11.2 names the owner's `slide-geometry` skill as the seed for
  `DiagramSpec` types and requires the two be kept in sync. Its `construction.md`
  leads the shape-vocabulary table with **pptxgenjs** presets and gives pptxgenjs canvas
  dimensions — but D5 and §6.6 rejection (c) rule out JS generators for AutoDeck.
- **Decision:** vendor all three files under `docs/reference/slide-geometry/` at the
  paths `SKILL.md` already references, and add a header note to the vendored
  `construction.md` stating that the `python-pptx MSO_SHAPE` column is authoritative and
  the pptxgenjs column is cross-reference only.
- **Rationale:** without the note a Phase 3a implementer reads left-to-right and builds
  against the wrong column.
- **Consequences:** the note is on AutoDeck's copy only, not on the owner's skill.
  Phase 3a must propose any new `DiagramSpec` type back upstream to keep them in sync.

### B8 — Environment-tiered providers: Gemini + Groq for dev, Claude for SIT/prod
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** the owner wants Claude reserved for production use, with development on
  free-tier Gemini and Groq to keep iteration cost and risk low, plus a SIT/UAT stage on
  Claude before production.
- **Decision:** three environments (`dev`, `sit`, `prod`) in `config/models.yaml`,
  selected with `--env`, defaulting to `dev`. Gemini and Groq back every role in dev;
  Claude backs the judgment-heavy roles in sit and prod. `ingest_vlm` stays on Gemini
  everywhere. The manifest records the environment and every resolved model ID.
- **Rationale:** the build has months of high-volume iteration ahead of it and free tiers
  make that affordable. Gemini and Claude end up in disjoint stages rather than competing.
- **Consequences:**
  - Phase 0 task 0.3 builds **three** provider adapters, not two, plus environment config.
    Structured-output parity and free-tier rate limiting become explicit Phase 0 concerns.
  - **A3 and A8 are model-sensitive**, so accuracy results from dev do not transfer to
    prod. Phase 5 eval numbers are only valid for the binding they were measured on, and
    headline metrics must be measured on `sit`. The deterministic invariants (A1, A2, A4,
    A5, A6) are code and transfer unchanged.
  - A dev-built deck must never be mistaken for a production one — hence the manifest
    requirement.

### B9 — Docstring-delegation: Sonnet specifies, Haiku fills the body
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** the owner proposed having Haiku fill in the code of lengthy functions from
  docstrings written by Sonnet.
- **Decision:** adopt the pattern, but scope it by **specification completeness rather
  than function length**. Delegate a body when the docstring fully determines behaviour
  (pure transformation, named error cases, specified edge cases). Keep it with Sonnet when
  the contract leaves judgment — retry/repair semantics, or anything failing silently.
  Existing path guardrails are unchanged and override the pattern.
- **Rationale:** length correlates with branching, and branching is where a cheaper
  model's errors hide inside plausible-looking code; a short function with a vague contract
  is the riskier delegation. Separately, the project's Clean Code discipline means a
  well-factored codebase should not contain many lengthy functions in the first place —
  the decomposition is what makes the delegation safe, and it shifts the payoff from
  function length to function volume.
- **Consequences:** if a function looks long enough to delegate on size alone, extract it
  first. No body under `autodeck/ir/`, `autodeck/audit/`, or `prompts/` is delegated
  regardless of docstring quality — in the numeric linter the invariant lives in the edge
  cases, so a complete-looking docstring is precisely the trap.

### B12 — Integration branch renamed to `v2/integration`
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active — amends B1
- **Context:** the branch was created by tooling as
  `claude/phased-feature-branch-plan-atygas`, a name that describes nothing. A rename to
  `autodeck-v2-nightly` was briefly considered and dropped: the branch is not a
  nightly-build branch — nothing builds from it on a schedule, and B10 rules out the CI
  that would normally host one — so the name would have misdescribed it.
- **Decision:** `v2/integration`.
- **Rationale:** says what the branch is, and sits in the same `v2/` namespace as the
  `v2/phase-*` children so the whole v2 effort groups together in branch listings. (A bare
  `v2` was rejected: a ref named `v2` collides with the `v2/` ref directory the phase
  branches live in.)
- **Consequences:** the old remote branch is deleted, so any link or checkout referencing
  it breaks. Commit history is unaffected — a rename moves the ref, not the commits. B1's
  substance is unchanged; only the branch name it names.

### B10 — Local development only; containerisation deferred to v3
- **Date:** 2026-07-26
- **Phase / branch:** scaffold (answers plan §11 Q1)
- **Status:** active
- **Context:** plan §11 Q1 asked whether the pipeline targets local dev only or a
  containerised small-team setup. It gates CI and packaging in Phase 0 task 0.1.
- **Decision:** local development only. Containers are a v3 consideration.
- **Rationale:** one user, one machine; containerisation would be scaffolding for a team
  that does not exist yet.
- **Consequences:**
  - Task 0.1 ships no Dockerfile and no container CI. CI runs lint, types, and unit tests
    only — **not** the LibreOffice render path, which needs fonts and a display stack.
  - D2's stated rationale ("runs anywhere — laptop, container, CI") is now *aspirational*
    rather than demonstrated. The provider abstraction still keeps it reachable; nothing
    should assume a local filesystem layout beyond `runs/` and `knowledge/`.
  - Anything requiring a rendered slide (design preview loop, `qa/libreoffice.py`,
    `qa/aesthetic.py`) is a **local-machine** operation. Phase 3 planning should not
    assume CI can verify visual output.

### B11 — Aptos is the default type family
- **Date:** 2026-07-26
- **Phase / branch:** scaffold (answers plan §11 Q3)
- **Status:** active
- **Context:** plan §11 Q3 asked whether brand fonts are licensed for the seed client, or
  whether to design against a safe default and swap later. The Phase 0 font spike (0.4)
  needs a concrete family to measure and embed.
- **Decision:** Aptos, using Aptos Display for headings and Aptos for body — the pairing
  Microsoft ships as the Office default font scheme.
- **Rationale:** as the current Office default it is present on essentially every
  corporate client machine, so deliverables render as intended without relying on
  embedding, and decks look native rather than obviously templated. It also maps cleanly
  onto the theme XML's major/minor font scheme (§6.8).
- **Consequences / risks — resolve in spike 0.4:**
  - **The font files are not freely redistributable.** Aptos is bundled with Microsoft 365
    rather than openly licensed. The TTFs must **not** be committed; `.gitignore` already
    excludes `fonts/*.ttf` and `fonts/*.otf`. The build machine sources them from a local
    Office installation, and setup documents that path.
  - **Budget measurement (§6.7) requires the real TTF.** If the files are absent, metrics
    fall back to a substitute and every computed budget is quietly wrong — the same class
    of failure that produced v1's overflow problem, arriving through a new door.
  - **Headless LibreOffice needs Aptos installed too**, or preview PNGs render in a
    substituted face. That would make the "true render" (D5) untrue and mislead both the
    design loop and the vision critique.
  - **Metric-compatible substitution is likely unavailable.** The familiar pairs
    (Carlito↔Calibri, Caladea↔Cambria, Liberation↔Arial) exist because those fonts are old;
    Aptos is recent and probably has no metric-compatible open clone. **Verify this in
    0.4** rather than assuming a fallback exists — if none does, "Aptos present on the
    build machine" becomes a hard prerequisite, not a convenience.
  - Client brand fonts still override per-client in Phase 4 onboarding; Aptos is the
    default and the development target, not a lock-in.

### B7 — Open questions from plan §11 are carried, not answered
- **Date:** 2026-07-26
- **Phase / branch:** scaffold
- **Status:** active
- **Context:** plan §11 lists five open questions (deployment target, seed project and
  client, brand fonts, audit-report audience, corporate-template reference) and states
  they do not block Phase 0.
- **Decision:** carry them into `docs/phases/PHASE-0.md` as tracked open items with the
  phase each one starts blocking.
- **Rationale:** answering them without the owner would be guessing on questions with
  real consequences (font licensing, client confidentiality).
- **Consequences:** Phase 0 cannot close its gate without at least Q1 and Q3 answered —
  they determine CI packaging and what the font spike measures.
