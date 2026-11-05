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

### B13 — `Derivation.inputs` carries values, not bare citations
- **Date:** 2026-07-26
- **Phase / branch:** Phase 0, task 0.2 / `v2/phase-0-foundations`
- **Status:** active
- **Context:** plan §6.1 sketches `Derivation.inputs` as `dict[str, Citation]`. A2 requires
  the numeric linter to **re-execute** every derivation formula to confirm the arithmetic.
  A citation carries a quote, not a number, so re-execution would have to re-parse the
  quote and guess which numeral the writer meant — and a quote like "rose from 412 to 671"
  contains two.
- **Decision:** `inputs` maps a name to a `DerivationInput` holding both `value: float` and
  `citation: Citation`. A further validator requires every derivation input's citation to
  also appear in the claim's own `citations`.
- **Rationale:** the value makes A2's re-execution possible at all; the citation still
  proves the number was copied rather than invented, so nothing is given up. The
  subset rule prevents a derived figure resting on a span that never reaches the claims
  table — which would make the audit report (A6) show working citing sources it does not
  list.
- **Consequences:** Phase 2b's content agent must emit values alongside citations, and the
  numeric linter can be pure arithmetic over the IR with no re-parsing of source text.
  The §6.1 sketch is superseded on this field; plan §0.6 covers the deviation.

### B14 — One HTTP transport, not three vendor SDKs
- **Date:** 2026-07-26
- **Phase / branch:** Phase 0, task 0.3 / `v2/phase-0-foundations`
- **Status:** active
- **Context:** task 0.3 needs Gemini, Groq and Claude adapters. The obvious route is each
  vendor's Python SDK.
- **Decision:** all three adapters are thin request builders over a single shared `httpx`
  transport in `providers/base.py`. No vendor SDK is a dependency.
- **Rationale:** the three providers disagree about JSON Schema, and the *whole point* of
  `ir/schema.py` is controlling exactly which dialect goes on the wire — an SDK that
  helpfully reshapes the schema defeats that. One transport also means one backoff policy,
  one cache, one place where 429s are read, and a mocked-transport test that exercises the
  real code path rather than three sets of SDK internals. Three SDKs would be three
  independent version-drift surfaces for a request body that is a dozen lines each.
- **Consequences:** SDK conveniences (streaming helpers, batch, prompt caching) must be
  implemented here if they are ever wanted. Adding a provider means one small subclass:
  `build_request`, `parse_response`, and a schema flavour. Adapters must never let a raw
  parsing error escape — `_send_once` wraps them as `ProviderResponseError`.

### B15 — Resolved model IDs for the `dev` environment
- **Date:** 2026-07-26
- **Phase / branch:** Phase 0, task 0.3 / `v2/phase-0-foundations`
- **Status:** active
- **Context:** plan §6.2 and §9 require model IDs to be looked up at implementation time
  rather than recalled, and recorded here.
- **Decision:** IDs listed from the live provider APIs on 2026-07-26 and written into
  `config/models.yaml`:
  - **dev** — `planner`, `outline`, `validation`, `aesthetic`: `gemini-2.5-pro`;
    `ingest_vlm`: `gemini-2.5-flash`; `content`: `openai/gpt-oss-120b` (Groq).
  - **sit / prod** — `claude-opus-5` for the judgment-heavy roles, `claude-sonnet-5` for
    `content`, with `ingest_vlm` staying on `gemini-2.5-flash`.
- **Rationale:** Gemini's live list offered newer preview families (`gemini-3.x`), but dev
  is where months of iteration happen and a preview ID that is withdrawn breaks the build;
  `gemini-2.5-pro` and `-flash` are GA. On Groq, `openai/gpt-oss-120b` is the strongest
  served model that supports `response_format: json_schema`.
- **Consequences:** the **Claude IDs are unverified against a live API** — this environment
  has no `ANTHROPIC_API_KEY`. Confirm them against the models endpoint before the first
  `sit` run. Every deck's manifest records the environment and the resolved IDs (A6), so a
  dev-built deck is never mistaken for a production one.

### B16 — Groq is text-only; the registry refuses to bind it to a vision role
- **Date:** 2026-07-26
- **Phase / branch:** Phase 0, task 0.3 / `v2/phase-0-foundations`
- **Status:** active
- **Context:** the live provider test sent an image to Groq and got
  `messages[0].content must be a string`. Groq's served model list on 2026-07-26 contains
  no multimodal model at all.
- **Decision:** `GroqProvider.supports_vision = False`, and `ModelRegistry` rejects any
  config binding a text-only provider to `aesthetic` or `ingest_vlm` **at load time**.
- **Rationale:** the current config never makes that binding — Groq serves only `content`,
  which is text — so nothing is broken today. But `ingest_vlm` is the highest-volume
  role in Phase 1 and the natural place to reach for a cheap free-tier provider, and the
  failure would otherwise land at the first figure of a corpus run rather than at startup.
- **Consequences:** the vision roles stay on Gemini in `dev` and on Gemini/Claude in
  `sit`/`prod`. If Groq later serves a multimodal model, flip the flag rather than removing
  the guard. A negative result worth keeping: Groq cannot relieve Gemini's free-tier
  pressure on `ingest_vlm`, which is where §MODEL_ROUTING predicts rate limits bite first.

### B17 — `TextStyle` unifies text measurement and text rendering
- **Date:** 2026-07-26
- **Phase / branch:** Phase 0, spike 0.5 / `v2/phase-0-foundations`
- **Status:** active
- **Context:** the first component render placed an accent rule straight through a
  headline's second line. The renderer applied a 1.25 line-spacing multiplier that the
  measurement function knew nothing about, so every measured height was ~20% short and each
  element was drawn over the previous one. This is precisely the failure the §6.7 budget
  system exists to prevent, arriving through the back door: measurement and rendering had
  drifted apart because they took *separate arguments*.
- **Decision:** a single frozen `TextStyle` (family, size, colour, weight, alignment,
  line spacing, paragraph spacing) is passed to both `Canvas.measure`/`Canvas.fit` and
  `draw.add_text`. `add_text` takes no loose text keyword arguments at all.
- **Rationale:** fixing the two call sites would have left the class of bug alive, and it
  is a class that fails *quietly* — a slide that is 20pt out looks like a design choice
  until someone measures it. Passing one object makes the divergence unrepresentable rather
  than merely discouraged.
- **Consequences:** anything later affecting rendered height — paragraph indents, tracking,
  a new type role — goes **on `TextStyle`**, never into a renderer argument. Phase 3a's
  component library and Phase 2b's budget checks both depend on this holding. A related
  guard landed alongside it: `LayoutOverflowError` is raised when content exceeds its
  region, because §6.9 calls the geometry check a safety net and a net that silently draws
  past the edge is not one.

### B18 — Design tokens live in `config/tokens/`, not `tokens/`
- **Date:** 2026-07-26
- **Phase / branch:** Phase 0, spike 0.4 / `v2/phase-0-foundations`
- **Status:** active
- **Context:** `DesignTokens` files were written to `tokens/`, which git silently refused to
  track: v1's `.gitignore` claims `tokens/` under "Secrets" for API tokens.
- **Decision:** design tokens live in `config/tokens/`, beside `config/models.yaml`. The
  `.gitignore` rule keeps its v1 meaning and gains a comment explaining the collision.
- **Rationale:** un-ignoring a directory named for secrets to make room for config is the
  wrong direction on a repository that will hold client material. Per-client tokens still
  live at `knowledge/clients/<c>/theme/tokens.json` per §6.4; `config/tokens/` holds only
  the project-level `aptos` and `dev` sets.
- **Consequences:** `--tokens config/tokens/<name>.json` throughout. Phase 4 onboarding
  writes per-client tokens to the knowledge folder, not here.

### B19 — `.gitignore` patterns anchored to the repo root; corrects a false claim in B18
- **Date:** 2026-08-01
- **Phase / branch:** Phase 1 / `v2/phase-1-ingest-knowledge`, hotfixed directly onto `v2/integration`
- **Status:** active — corrects B18's rationale; does not reverse B18's placement decision
- **Context:** the owner reported both open PRs failing CI. Investigation showed **every
  CI run since the first Phase 0 push** — seven consecutive runs across
  `v2/phase-0-foundations`, `v2/integration`, and `v2/phase-1-ingest-knowledge` — had
  failed the same way: `config/tokens/{dev,aptos}.json` not found. B18 asserted that
  moving design tokens to `config/tokens/` let "the `.gitignore` rule keep its v1
  meaning" without colliding. That was never checked against an actual `git status`, and
  it was false: a gitignore pattern with **no leading slash** (`tokens/`) matches a
  directory of that name at **any depth**, not only at the repo root, so it silently
  matched `config/tokens/` too. The files were never committed. Local development never
  noticed because every local test run read them straight off disk — the bug was only
  visible from a fresh checkout, which is what CI always does and what Phase 0's
  verification never did (§10 of the Phase 0 handover runs commands in the working tree,
  not a clone).
- **Decision:** anchor the pattern to the repo root (`/tokens/`), and pre-emptively fix
  the same class of bug in `*.pdf` (→ `/*.pdf`), which would otherwise have swallowed the
  task 1.9 seed corpus under `knowledge/projects/*/papers/*.pdf` the moment it was added.
- **Rationale:** anchoring is what B18 should have specified originally; B18's chosen
  *location* for design tokens (`config/tokens/`, separate from per-client
  `knowledge/clients/<c>/theme/tokens.json`) remains correct and is not reversed.
- **Consequences:** verification of a `.gitignore` change, or of any claim that a path
  "is/isn't tracked," must check a fresh clone or `git ls-files`/`git check-ignore -v` —
  never the working tree alone, since an untracked-but-present file is invisible to every
  local check except those two. Both `v2/integration` and
  `v2/phase-1-ingest-knowledge` were hotfixed with the identical commit
  (cherry-picked) and both re-verified green on GitHub's own runners before being
  reported fixed.

### G0 — GATE 0 approved: the rendering strategy proceeds
- **Date:** 2026-08-01
- **Phase / branch:** Phase 0 / `v2/phase-0-foundations`
- **Status:** active
- **Context:** GATE 0 is plan §7's *"go/no-go for the whole rendering strategy"*. Phase 0
  delivered all seven tasks and three spike artifacts under `spikes/gate0/`.
- **Decision:** **approved by the owner** — *"the presentation is good. let's proceed."*
  Phase 0 merges to `v2/integration` and Phase 1 is cut.
- **What the owner actually confirmed:** the rendered output of spike 0.5 —
  `big_number` and `two_column_compare` meet the visual bar. That is the criterion D5
  turns on, and it is the substantive go/no-go: native authoring in python-pptx can be
  beautiful. Combined with the measured 2.25s edit→preview loop, a 15-component library is
  credible.
- **What was *not* separately confirmed, and is carried forward:** the owner did not
  report the two PowerPoint-behaviour checks — that the palette appears under Design →
  Variants (0.4), and that an icon selects, scales and recolours as a native shape (0.6).
  Both artifacts are committed and were sent directly. Recording this precisely rather
  than reading "proceed" as blanket sign-off, because the handover template asks what the
  owner *actually checked* and plan §0.3 forbids the implementing agent self-approving a
  criterion nobody exercised.
- **Rationale:** D5 was the architectural risk — §6.6 rejects every alternative rendering
  path, so a failure there needed re-planning before Phase 3. It passed. D11 is narrower
  and has a documented retreat (`svgBlip` + PNG, plan §9), so carrying it as verification
  debt costs a fallback rather than a re-plan.
- **Consequences:**
  - **Phase 3a must confirm the icon and theme behaviour in PowerPoint before building on
    it.** The converter is proven at the geometry level only. If it fails there, D11 falls
    back to `svgBlip` and "icons are vectors end to end" weakens.
  - Aptos remains a hard prerequisite (B11 check #4 verified: no metric-compatible clone).
    Phase 2b's budgets are wrong-by-default on a machine without it.
  - The Claude adapter is still unexercised live; the first `sit` run will be its first
    real call.

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

### B20 — Seed corpus selects on licence first, topic second
- **Date:** 2026-08-02
- **Phase / branch:** Phase 1 / `v2/phase-1-ingest-knowledge`
- **Status:** active
- **Context:** task 1.9 needed public papers committable to a public repository. The
  obvious candidates for an inference-efficiency corpus — *Attention Is All You Need*
  (1706.03762), *Scaling Laws* (2001.08361), *FlashAttention* (2205.14135), *Chinchilla*
  (2203.15556) — all carry arXiv's default **perpetual non-exclusive licence**, which
  grants *arXiv* the right to distribute, not third parties. Committing them would be a
  redistribution nobody licensed.
- **Decision:** filter candidates on licence **before** choosing the corpus topic, and
  accept only CC BY 4.0 (or equally redistributable). The topic — LLM inference efficiency
  — is what the CC BY papers happened to support coherently, not what was wanted first.
  Recorded in `knowledge/projects/*/papers/SOURCES.md` with the licence checked per arXiv
  ID and the date it was checked.
- **Rationale:** the alternative orderings both fail. Pick the topic first and the corpus
  is either unlicensed or full of gaps; check licences at review time and the PDFs are
  already in git history, where removing them is a rewrite.
- **Consequences:**
  - Adding a paper means checking its licence first. `SOURCES.md` says so.
  - A non-redistributable paper can still be used: keep the PDF out of the repo, point
    `claims.md` at a local path. An uningestable corpus is a smaller problem than an
    unlicensed redistribution.
  - `export.arxiv.org` is not reachable from this environment; licences were read from
    `arxiv.org/abs/<id>` pages instead.

### B21 — `doc_id` is a readable slug, not the source identifier
- **Date:** 2026-08-02
- **Phase / branch:** Phase 1 / `v2/phase-1-ingest-knowledge`
- **Status:** active
- **Context:** `doc_id` is the PDF's filename stem, and it appears in every citation a
  human reads — including the ten a reviewer works through at GATE 1a.
- **Decision:** name paper files `kwon-2023-pagedattention-vllm.pdf`, not
  `2309.06180.pdf`. The canonical identifier lives in `SOURCES.md`.
- **Rationale:** `kwon-2023-pagedattention-vllm, p. 7` can be checked against the right
  paper without a lookup; `2309.06180, p. 7` cannot. GATE 1a is deliberately manual, and
  anything that adds friction per citation gets skimmed — which is the failure the gate
  exists to prevent.
- **Consequences:** renaming a paper changes its `doc_id` and orphans any cached claim
  citing it. `tests/test_cli_knowledge.py::test_every_seed_claim_points_at_a_paper_that_exists`
  catches this at test time rather than at build time.

### B22 — Derived artifacts stay out of git; `spikes/gate0/` is the exception
- **Date:** 2026-08-02
- **Phase / branch:** Phase 1 / `v2/phase-1-ingest-knowledge`
- **Status:** active
- **Context:** Phase 1 produces two large derived artifacts — the ingested document store
  (`corpus/`, ~1.2 MB of JSON) and the GATE 1a spot-check renders (`spikes/gate1a/`,
  ~4.7 MB of page images). Both are regenerable from tracked inputs.
- **Decision:** gitignore both. Keep `spikes/gate0/` tracked.
- **Rationale:** size is the smaller reason. The real one is staleness: a committed
  spot-check sheet keeps showing boxes drawn from a previous ingestion, so after any
  re-ingest it displays citations that no longer match while looking authoritative. That
  is worse than no sheet. `spikes/gate0/` is different in kind — those artifacts need
  PowerPoint to judge and cannot be regenerated by a reader who does not run the code.
- **Consequences:**
  - A fresh clone must run `autodeck knowledge ingest` (~16 min) before `ask` or
    `spotcheck` work. Documented in the Phase 1 handover §10.
  - GATE 1a materials are delivered to the owner directly rather than through the repo.

### G1a — GATE 1a approved; the provenance chain is signed off
- **Date:** 2026-08-02
- **Phase / branch:** Phase 1 / `v2/phase-1-ingest-knowledge`
- **Status:** active
- **Context:** GATE 1a asks the owner to spot-check ten citations against the source PDFs —
  correct page, bbox on the right region, quote verbatim, all ten resolving exactly. The
  gate is deliberately manual because **a wrong bbox hash-verifies perfectly**: the quote is
  unchanged and only its location is wrong, so no automated check can close it.
- **Decision:** **approved.** The owner reviewed the delivered spot-check materials and
  answered "Looks good. Let's proceed."
- **What the owner actually reviewed:** `spikes/gate1a/index.md` — the worksheet listing all
  ten citations with claim, verbatim quote, bbox, sha256 prefix and hash status — together
  with four of the ten rendered pages (`01` dettmers p1, `04` kwon p2, `09` and `10` frantar
  p2). The remaining six renders were generated and referenced but not sent inline.
  Recorded at this precision rather than as "reviewed all ten", because plan §0.3 forbids
  the implementing agent self-approving a criterion nobody exercised, and G0 set the
  precedent of writing down what was actually looked at.
- **Rationale:** the examined sample covers three of the five papers, both single- and
  two-column layouts, and the two failure modes the gate exists to catch (mirrored vertical
  origin, wrong page). All ten reported `hash ok`. Two were additionally verified during
  implementation by rendering the page and inspecting the box directly.
- **Consequences:**
  - A1 is `tested` end to end rather than on mechanism alone. Phase 2a may build on the
    assumption that a resolved citation points where it says it does.
  - **The six unexamined renders remain the thinnest part of this gate.**
    `leviathan-2023-speculative-decoding` and
    `pope-2022-efficiently-scaling-transformer-inference` are the least-inspected papers in
    the sample — if a citation later looks wrong, check those first rather than assuming the
    gate covered all five evenly.
  - Phase 1 merges to `v2/integration`; `v2/phase-2a-plan-outline` is cut from the result.

### B23 — Dev-tier model IDs re-resolved; there is no pro model on the free tier
- **Date:** 2026-08-02
- **Phase / branch:** Phase 2a / `v2/phase-2a-plan-outline`
- **Status:** active — supersedes the dev bindings recorded under B15
- **Context:** the first live run of the evidence-gap check (task 2a.4) failed every probe.
  Two separate causes, both found by running it rather than by reading anything:
  1. **`gemini-2.5-pro` is retired.** It still appears in the `v1beta/models` listing but
     every `generateContent` call returns 404 *"no longer available to new users"*. Four dev
     roles were bound to it (planner, outline, validation, aesthetic), so all four were dead.
  2. **No pro model is reachable at all on this tier.** `gemini-3.1-pro-preview` and
     `gemini-pro-latest` both return 429 with no free-tier quota. Only flash models respond.
- **Decision:** bind the four reasoning roles to `gemini-3.7-flash` in dev, verified by an
  actual completion rather than by appearing in a listing. Keep `ingest_vlm` on
  `gemini-2.5-flash`, which still answers.
- **Rationale:** a listing is not availability — that is the specific trap here, and it is
  why B15's "resolve, never recall" needs to mean *call it*, not *look it up*. Aliases
  (`gemini-flash-latest`) were rejected: an alias moves underneath a build, so the same
  manifest could resolve to a different model on a re-run and A6's byte-comparability claim
  would be false in a way nothing detects.
- **Consequences:**
  - **B8's warning gets stronger.** Dev now runs the reasoning roles on a *flash* model,
    weaker than this file assumed when it was written. A dev pass on A3 or A8 was already a
    smoke test; it is now a smoke test on a smaller model. Headline accuracy must be
    measured on `sit`.
  - Model IDs go stale mid-project. Re-resolve at the start of any phase that calls a
    provider, not once per project.
  - The `sit`/`prod` Claude IDs remain unverified — still no `ANTHROPIC_API_KEY`.

### B24 — Evidence spans are truncated before classification
- **Date:** 2026-08-02
- **Phase / branch:** Phase 2a / `v2/phase-2a-plan-outline`
- **Status:** active
- **Context:** the evidence-gap check shows the classifier up to six retrieved spans. A
  Docling element is a whole paragraph, and six research-paper paragraphs measured ~9.8k
  tokens against the real seed corpus — over the Groq free tier's 8000 TPM limit, which
  returned HTTP 413 and failed the probe rather than returning a verdict.
- **Decision:** truncate each span to `SPAN_CHARS` (500) for classification, and mark the
  truncation visibly with `…[truncated]`.
- **Rationale:** the judgement needs the sentence that does or does not support the message,
  not the rest of the paragraph. Marking rather than silently cutting matters for A8: a
  classifier that cannot see the end of a paragraph should not read an absent qualifier as
  an absent caveat.
- **Consequences:**
  - Truncation applies only to what the *classifier* sees. Citations are still resolved
    verbatim through the document store, so A1 is untouched.
  - `claims.md` spans are already human-selected quotes and are short by construction, so
    this rarely affects the curated path.

### B25 — Dev roles are spread across different Gemini models
- **Date:** 2026-08-02
- **Phase / branch:** Phase 2a / `v2/phase-2a-plan-outline`
- **Status:** active
- **Context:** the free tier allows **20 requests per day, per model**. A single planning
  session — two turns, four key messages probed each turn — spent one model's entire daily
  allowance on the first run, and every subsequent call that day returned 429.
- **Decision:** bind each dev role to a different Gemini model (`planner` 3.7-flash,
  `outline` 3.6-flash, `validation` 3.5-flash, `aesthetic` 3.1-flash-lite, `ingest_vlm`
  2.5-flash) so each has its own daily bucket.
- **Rationale:** quota is the immediate reason, but the split is independently right for
  A3. The validator re-retrieves independently and hunts for contradicting spans, and a
  validator on the same model as the writer is likelier to share its blind spots. This is
  the cheap version of that independence and it costs nothing.
- **Consequences:**
  - Dev capacity is roughly 20 planner turns per day. A long session will hit it; the
    Phase 0 response cache is what makes a resumed run not re-pay for completed calls.
  - `ModelRegistry.provider_for(role, model=...)` now works (it raised `TypeError` before —
    `model` was pinned ahead of `**overrides`), so a role whose quota is spent can be
    pointed elsewhere without editing config.

### B26 — Gemini structured output: nullable nested arrays are unreliable
- **Date:** 2026-08-02
- **Phase / branch:** Phase 2a / `v2/phase-2a-plan-outline`
- **Status:** active
- **Context:** the first live planning sessions produced excellent briefs *in prose* and
  recorded nothing. Investigation, not inference:
  1. The raw HTTP response was inspected. Scalar fields (`objective`, `probe_messages`)
     were present; `key_messages`, `layout_pins` and `open_risks` — all typed
     `list[Model] | None` — were **absent from the JSON entirely**. No error, no warning.
  2. Two prompt rewrites (hoisting the instruction to the top of `planner.md`, then adding
     a positional reminder after the context) improved the prose and changed nothing about
     the fields.
  3. It is **non-deterministic**: the same model on the same prompt populated the arrays
     once and omitted them on the next call.
- **Decision:** two changes, at different layers.
  - **Schema (all agents):** the `gemini` flavor now collapses `anyOf: [X, {"type":
    "null"}]` into X with `nullable: true` — Gemini's own representation. Carries
    annotations across, and leaves genuine two-type unions alone.
  - **Planner model:** `objective`, `audience` and `key_messages` are **required and
    non-nullable**. Required fields arrive; nullable nested arrays do not. Empty now means
    "unchanged" rather than "cleared" — a brief cannot legitimately fall to zero key
    messages, so an empty list is far likelier to be an omission than an intent to wipe
    ten minutes of work.
- **Rationale:** the failure mode is the worst available — nothing raises, the conversation
  reads perfectly, and the artifact is blank. It cannot be left to prompt discipline, and
  the schema-level half fixes it for every agent rather than only this one.
- **Consequences:**
  - A list cannot be *cleared* through the planner; that is done by editing the signed
    YAML, which is a deliberate act with a diff.
  - The model restates the whole brief each turn. That was already the documented contract
    ("the complete current set, not a delta"), so only the reliability changed.
  - **Expect this class of bug on other providers.** When an agent's output looks right in
    prose and empty in the artifact, read the raw response before touching the prompt.

### G1 — GATE 1 approved
- **Date:** 2026-09-18
- **Phase / branch:** Phase 2a / `v2/phase-2a-plan-outline`
- **Status:** active
- **Context:** GATE 1 asks whether an outline delivers the brief's key messages, in the
  brief's order, honouring its pins — deliberately not "is this a good outline" (§6.13).
- **Decision:** **approved.** The owner reviewed the delivered materials and answered "This
  looks good. Lets go ahead and implement the other phases as well."
- **What the owner actually reviewed:** `GATE-1-review.md` — the signed brief v1 (objective,
  audience, four key messages with evidence status, two accepted risks with `accepted_by`,
  one layout pin), the ten-slide outline with each slide's role, component, served messages
  and intent, and the mechanical report (0 blocking, 3 advisory) — together with
  `brief/v1.yaml`. Recorded at this precision rather than as blanket sign-off, per plan
  §0.3 and the precedent set by G0 and G1a.
- **Rationale:** the mechanical half was clean. The judgement half — whether the sequence of
  intents makes the argument — is what the owner answered, and the approval arrived in the
  same message as the instruction to proceed through the remaining phases.
- **Consequences:**
  - A7 approval 1 of 4 is proven end to end on a real run.
  - Phase 2b may start. Phase 2a merges at the review session (B27), not now.
  - The outline's messages were all `unprobed` because the classifier hit the daily quota
    mid-run (B25). The brief was signed anyway, which is legitimate — `unprobed` is honest
    and GATE 1 surfaced it as advisory — but the evidence-gap check has still not run to
    completion on a full brief. Phase 2b's validator is the next chance to catch anything it
    would have found.

### B27 — Phases 2b–3b stack without merging; gates are reviewed as a batch
- **Date:** 2026-09-18
- **Phase / branch:** Phase 2b / `v2/phase-2b-content-validate`
- **Status:** active — deviates from `docs/BRANCHING.md` rule 1 for this batch only
- **Context:** the owner asked for Phases 2b, 3a and 3b to be built in one pass, stating
  they cannot take time to review each step. Two BRANCHING rules collide under that
  instruction: rule 1 (a phase branch is cut from the integration tip) and rule 3 (nothing
  merges until its gate is approved by the owner in writing; the implementing agent does
  not self-approve). Honouring rule 1 requires merging 2b before cutting 3a, which requires
  approving GATE 2 without the owner — exactly what rule 3 and A7 forbid.
- **Decision:** cut each phase branch from the **previous phase's tip** rather than from
  `v2/integration`, and **merge nothing**. Every gate stays `pending` in its handover with
  "what the owner actually checked: nothing yet". At the review session the owner works
  GATE 2 then GATE 3; each approval is recorded, the branch is re-cut onto the integration
  tip, and the PR merges `--no-ff` in phase order.
- **Rationale:** rule 3 is derived from an accuracy invariant (A7) and rule 1 is a
  topology convention, so the convention yields. Stacking is safe here because nothing else
  advances `v2/integration` during the batch, making the eventual re-cut a clean replay.
- **Consequences:**
  - Three unmerged branches exist at review time, each building on the last. A rejection at
    GATE 2 invalidates work in 3a and 3b that was built on it — an accepted cost of the
    owner's instruction, and the reason the accuracy core is built first and each phase
    boundary is a clean stopping point.
  - `docs/BRANCHING.md` is not edited. This is a recorded deviation for one batch, not a
    change to the protocol.

### B28 — Guardrail paths hold their tier; budget de-escalation is recorded per task
- **Date:** 2026-09-18
- **Phase / branch:** Phase 2b / `v2/phase-2b-content-validate`
- **Status:** active
- **Context:** the owner set a $50 ceiling on delegated implementation and asked that the
  code be written by Sonnet and Haiku rather than by the orchestrating model.
  `docs/MODEL_ROUTING.md` makes `autodeck/ir/`, `autodeck/audit/`, `prompts/`,
  `DECISIONS.md` and `docs/handovers/` top-tier regardless of a task's tag, and states that
  a tag-versus-guardrail conflict is won by the guardrail.
- **Decision:** the **guardrail paths keep their tier** and are implemented by Opus
  subagents. Tasks *tagged* Opus in a phase brief but living outside a guardrail path —
  `design/budgets.py`, `layout_kit.py`, `components/catalog.py`, `design/grammar.py` — are
  de-escalated to Sonnet, and each de-escalation is named in the owning handover §8.
- **Rationale:** the routing doc's own tie-breaker is "the cost of over-tiering is money,
  the cost of under-tiering is a defect in an accuracy-critical path." A budget makes that
  trade explicit rather than hypothetical, so the money is spent where a defect would land
  on an invariant and saved where it would land on a layout.
- **Consequences:**
  - Two accuracy-critical modules are **split** so their invariant logic sits inside a
    guardrail path: A3's verdict assignment and contradiction rule go to
    `autodeck/audit/verdicts.py` (Opus) with `agents/validation.py` as a Sonnet wrapper; the
    aesthetic loop's closed action set goes to `autodeck/ir/actions.py` (Opus) with
    `render/qa/aesthetic.py` as a Sonnet loop. The type system is the invariant in both.
  - Every task is independently reviewed by a second Sonnet agent against its spec, standing
    in for the step-by-step human review the owner cannot give.
  - Spend is tracked per dispatch. At ~$40 the current task is finished, committed and
    pushed, and the batch stops and reports rather than starting the next one.

### B29 — A6 says "byte-comparable"; that is not achievable for PPTX
- **Date:** 2026-09-19
- **Phase / branch:** Phase 2b / `v2/phase-2b-content-validate`
- **Status:** **accepted by the owner, 2026-09-27, and applied.** The owner's answer: "Okay,
  no problem." `docs/INVARIANTS.md` A6 now reads "re-renders normalised-comparable output
  under a recorded normalisation", and its "proves it" line compares digests, never bytes.
- **Context:** A6's headline says *"Same manifest + IR re-renders byte-comparable output."*
  Implementing task 2b.10 established that no PPTX can satisfy that, for reasons outside
  AutoDeck's control. Measured directly in this container: **two `Presentation().save()`
  calls two seconds apart, on an identical presentation, produce different bytes.**

  ```
  identical decks, saved 2s apart:  raw bytes 4b504b3cb189… vs 13012257 40ab…  -> DIFFER
  under canonical_pptx_digest:      8609e277b720…  vs 8609e277b720…            -> SAME
  ```

  Four independent causes: `zipfile` stamps every entry header with wall-clock save time;
  entry order follows the writing library's iteration, not the document; the DEFLATE stream
  depends on the zlib build and compression level, so the same input bytes give different
  archive bytes on another machine; and `docProps/core.xml` carries `dcterms:modified` and
  `cp:revision`, which move whenever the file is saved at all.
- **The invariant already half-concedes it.** A6's own "watch for" line reads *"normalise
  before comparing, and record the normalisation"* — which contradicts the headline in the
  same entry. The wording was internally inconsistent before this phase; implementing it
  is what surfaced that.
- **Proposed decision (for the owner):** correct A6's headline to **"re-renders
  normalised-comparable output under a recorded normalisation"**, and keep the existing
  "watch for" as the definition of the normalisation. This is a wording correction to match
  what the invariant always meant, not a relaxation — plan §0.4 forbids weakening an
  invariant, and nothing here proposes accepting a weaker guarantee. It proposes describing
  the guarantee accurately.
- **What was built in the meantime.** `canonical_pptx_digest` with a versioned normalisation
  (`pptx-canonical-v1`) whose three rules each carry `what` / `why` / `safe_because`; the
  normalisation id is hashed into the digest, so a v1 digest can never be read as a v2 one.
  Nothing is named `bytes_match`, and
  `test_naive_byte_comparison_fails_on_two_identical_decks` asserts the failure so the claim
  is evidenced rather than argued. Excluded: zip entry order, per-entry storage metadata,
  and five volatile `docProps/core.xml` fields. Not excluded: relationship ids, `app.xml`,
  and every part's decompressed bytes.
- **Consequences if the correction is accepted:** A6's coverage cell means
  normalised-comparability, and Phase 3b's render determinism test targets the digest rather
  than raw bytes. **If it is rejected**, A6 is unsatisfiable as written and Phase 3b cannot
  close against it — which is the reason this is flagged now rather than at GATE 3.
- **Applied:** the accepted branch above holds. Phase 3b's render determinism test compares
  `canonical_pptx_digest` across two renders of one manifest+IR.

### B30 — A gate approval does not survive the machine. Owner decision needed.
- **Date:** 2026-09-19
- **Phase / branch:** Phase 2b / `v2/phase-2b-content-validate`
- **Status:** **open — no change made.** Flagged for the owner at GATE 2.
- **Context:** `Orchestrator.approve` records an approval as
  `state.approvals[gate] = "<timestamp> by <approver>"` in `runs/<run_id>/state.json`.
  B22 keeps derived artifacts out of git, and `runs/` is squarely derived data — run
  directories hold model output, intermediate IR versions and caches. So `state.json` is not
  committed.

  The consequence surfaced while trying to run this phase's milestone. GATE 1 was genuinely
  approved on 2026-09-18 against a real brief and a real ten-slide outline (**G1**). That
  approval lived in a container that no longer exists. On a fresh clone there is no record
  of it that any code can read: `autodeck content` correctly refuses to proceed, and the
  only surviving trace of the owner's decision is the prose we wrote into this file by
  convention.
- **Why this is not simply "re-run it".** Re-creating the run means a fresh `/sign` on a
  fresh brief — A7 approval 1 of 4, a human act — and a fresh GATE 1 judgement on a
  different outline, because the planning session is a model conversation and does not
  reproduce. The owner would not be re-confirming a decision they made; they would be making
  a new one about different material. **An approval is not reproducible, which is exactly
  why it is the one thing in a run that should not be treated as derived.**
- **Why it matters beyond convenience.** A6 asks what produced an artifact and A7 asks who
  approved it. A build manifest that can name the model IDs, the prompt hashes and the
  knowledge commit, but cannot name who approved the claims table or when, is missing the
  only field in it that a human is accountable for. At Phase 4, "who signed off on this
  deck" is a question a client may ask about a deck that shipped months earlier.
- **Options for the owner, in the order I would take them:**
  1. **Commit approvals, not runs.** `autodeck approve` also appends to a small committed
     ledger (`approvals/<run_id>.yaml`) carrying gate, approver, timestamp, the IR version
     approved and its hash. Derived data stays out of git; the human act does not. The IR
     hash matters: it is what stops an approval being read as covering content that changed
     after it was given.
  2. **Fold the approval into the build manifest**, which is already the A6 record and is
     already committed for a shipped deck. Less machinery, but it only exists once a deck is
     built, so GATE 1 and GATE 2 approvals have nowhere to live in the meantime.
  3. **Leave it, and rely on `DECISIONS.md`.** Honest, and it is what we have been doing —
     but it is a convention rather than a mechanism, and conventions are what A7 exists
     because we do not trust.
- **Not decided here.** Any of the three touches `autodeck/pipeline/orchestrator.py` and
  option 1 adds a committed artifact, which is a project-shape decision rather than an
  implementation detail. **No code was changed on the strength of this entry.**
- **Consequence either way:** the Phase 2b milestone run starts from `autodeck plan`, and
  `docs/handovers/PHASE-2B.md` §10 is written on that assumption.

### B31 — Phase 3a starts with three preconditions unmet, knowingly
- **Date:** 2026-09-19
- **Phase / branch:** Phase 3a / `v2/phase-3a-design-system`
- **Status:** active
- **Context:** `docs/phases/PHASE-3A.md` lists four preconditions. Three are not met, and
  proceeding anyway is a decision rather than an oversight, so it is recorded here.
- **1. "GATE 2 approved."** It is not, and cannot be before the review session — **B27** is
  the standing decision that phases 2b–3b stack unmerged and every gate stays `pending`. The
  cost was stated when B27 was taken and is restated here: **a GATE 2 rejection invalidates
  whatever Phase 3a builds on top of it.** The owner accepted that trade when choosing the
  batch. Nothing in 3a may alter a verified fact, which the phase's own exit criteria
  already require ("Phase 2b's audit report is still clean").
- **2. "GATE 0 spikes all passed"** — they passed *on the visual bar only* (**G0**). The
  icon and theme behaviour has never been confirmed in PowerPoint itself, and PHASE-3A says
  Phase 3a must check both **before** building on them. There is no PowerPoint in this
  environment and no way to obtain one. **Resolution: build against headless LibreOffice,
  which is what the golden-PNG loop uses anyway, and carry the PowerPoint check forward as
  owner debt rather than claiming it.** Two specific behaviours must be listed in the Phase
  3a handover for the owner to check at GATE 3 with a real PowerPoint: that a theme appears
  in PowerPoint's own theme UI and that hand-added slides inherit it (3a.1's done-when), and
  that icons arrive as recolourable native shapes rather than pictures (3a.7's). LibreOffice
  agreeing is evidence, not proof; the two engines disagree about OOXML in exactly the areas
  D10 and D11 care about.
- **3. "Owner answer to Q5"** (a client with a mandated corporate template). Unanswered.
  Per the batch plan: **mode (b) — generate from tokens — is built fully; mode (a) is built
  against a synthetic corporate template and the gap is recorded.** A synthetic template
  exercises the extraction path but proves nothing about the malformed, decade-old templates
  real clients mandate, which is the only interesting case.
- **Also recorded: the budget ceiling was lifted by the owner**, which retires the
  budget-driven half of **B28**. B28's rule was "guardrail paths keep their tier; Opus-tagged
  work *outside* them drops to Sonnet under the budget". With no budget pressure, Opus-tagged
  tasks run on Opus, and the de-escalations 3a.4 and 3a.6 anticipate stay in place because
  those are *pattern-driven* — the nth mechanical instance of an established component
  renderer genuinely does not need a top-tier model — not budget-driven. **Fable 5.1 is
  unavailable on this account** (HTTP 429, "requires usage credits"), so Opus is the top tier
  actually available, including for the review passes the plan reserved for Fable.
- **Consequence:** the Phase 3a handover's §3 and §7 carry all three gaps, and none of them
  may be quietly closed by a later phase noticing the box is ticked.

### B32 — Opus writes the scaffold; Sonnet writes the code
- **Date:** 2026-09-27
- **Phase / branch:** Phase 3a / `v2/phase-3a-design-system`
- **Status:** active — supersedes B28's "guardrail paths hold their tier" for code
- **Context:** owner instructions during this batch — "use Sonnet and Haiku" (start), "Why
  is Opus doing all the work? … use the correct model" (2026-09-20), "Opus should only
  create the scaffolding. The code can be filled in by sonnet" (2026-09-27). Before the
  correction the batch had run 10 Opus / 12 Sonnet / 0 Haiku dispatches; two Opus dispatches
  were outside any guardrail path, justified by "foundational" and "accuracy-critical",
  which is not the rule.
- **Decision:** Opus writes design decisions, module layout, types, contracts as
  docstrings, and tests as named stubs stating exact inputs and expected results; Sonnet
  implements; Opus verifies against the scaffold. **This applies in guardrail paths too**,
  superseding B28's "guardrail paths hold their tier" for code. Mechanism: the scaffold is
  its own commit (so history shows design vs implementation), function bodies raise
  `NotImplementedError`, test stubs are `xfail(strict=True)` so a passing stub still wearing
  its marker fails the suite and no marker can survive the fill. Documentation follows the
  same split: Opus writes a skeleton of every fact and judgement, Sonnet writes the prose.
- **Rationale:** the owner's correction was explicit and repeated; the previous rule (B28)
  optimised for which module a task touched, not for who should be deciding versus
  implementing within it.
- **Consequences:**
  - Opus reviews every guardrail-path diff.
  - First two uses (A2 quantity nouns, components 13–15) landed with the contract intact and
    one scaffold error found and reported by the implementer.

### B33 — Registering a component is not a local change
- **Date:** 2026-09-20
- **Phase / branch:** Phase 3a / `v2/phase-3a-design-system`
- **Status:** active
- **Context:** commit 6f2c3ae registered seven components; seven citation-resolution tests
  in `test_content.py` failed, because those names had been unregistered, so budgets had
  been skipped for them, and `ContentResult.rejections` mixed "the writer produced something
  that does not fit" with "the writer produced nothing for this slot".
- **Decision:** a missing required slot is its own finding kind — `ContentResult.incomplete_slots`
  — separate from `rejections`.
- **Rationale:** the two failure kinds need different downstream handling (send-back vs
  a gap in coverage) and conflating them under `rejections` hid which one had actually
  occurred.
- **Consequences:**
  - A test that needs an unregistered component must use a name guaranteed never to be
    registered.
  - `headers/flow.py` and `cli.py`'s content summary also change behaviour on registration
    (the CLI now under-reports `incomplete_slots` — open).

### B34 — The environment is part of the project
- **Date:** 2026-09-27
- **Phase / branch:** Phase 3a / `v2/phase-3a-design-system`
- **Status:** active
- **Context:** fresh containers lacked the Inter fonts, `libreoffice-impress` and
  `poppler-utils`. Without the fonts, budgets are refused (B11); without the other two, 32
  render tests — every prediction-vs-render check — fail. CI deselects render tests (B10),
  so CI stayed green while those checks could not run.
- **Decision:** `scripts/setup-dev-env.sh` installs all three; CI installs the fonts only.
- **Rationale:** CI has no render path to protect (B10), so only the fonts are worth its
  time; a developer or render machine needs the full set to trust a green suite at all.
- **Consequences:**
  - A green local suite is meaningful only after the setup script has run.

### B35 — No component can place an icon on the face; icon-anchored slides need one first
- **Date:** 2026-10-01
- **Phase / branch:** Phase 3b / `v2/phase-3b-render-qa`
- **Status:** active — sequencing decided here; the component itself goes through B33
- **Context:** filling the aesthetic loop (3b.5) showed that no registered component has a
  slot an `icon` block can sit in, so `render_deck` refuses a deck with a face icon
  (`UnplacedBlockError`). `Frame.icon` exists and draws theme-recolourable icons, but no
  component renderer calls it. Consequences: `SwapGlyph` and `SetIconColour` are correct
  and tested against the IR, but cannot be exercised on a rendered deck; and the
  art-direction pass (3b.7) cannot meaningfully assign `icon_anchored` (D13; plan §6.11.2
  pairs it with "capability pillars"), nor can GATE 3 check 2 ("an icon can be selected and
  recoloured") be performed on a real deck.
- **Decision:** treat it as PHASE-3B's escalation case — a component design gap, returned
  to the 3a catalog rather than special-cased in the renderer. Before 3b.7, register one
  icon-bearing component (working name `icon_pillars`: 3–4 columns, each an icon, a short
  label and an optional one-line point), under B33's full procedure (budgets, golden
  preview, `placeable_slots` entry, grammar lints: icon adjacent to its label, ≤ 50 words).
  Opus scaffolds the content type and slots; Sonnet fills (B32).
- **Rationale:** the alternative — have 3b.7 avoid `icon_anchored` — would ship a
  communication mode that exists in the IR, the grammar lints and the prompt, but can never
  be rendered, and would leave GATE 3 check 2 unperformable.
- **Consequences:**
  - 3b.7 is sequenced after this component lands.
  - The golden preview for the new component is reviewed by the owner with the rest of
    GATE 3; it is not self-approved.

### B36 — Art direction: modes by rule, taste by model, no automatic section dividers
- **Date:** 2026-10-01
- **Phase / branch:** Phase 3b / `v2/phase-3b-art-direction`
- **Status:** active
- **Context:** task 3b.7 asks for deck-level rhythm, component swaps, communication-mode
  decisions and section dividers, honouring pins, without being able to alter a fact.
  Designing it surfaced three IR facts: (1) `Block` let any kind carry `text`, so an icon or
  claim block could hold an uncited sentence that nothing renders and nothing lints;
  (2) `fact_fingerprint` keyed every block, so adding an icon block — the only way an
  `icon_pillars` slide gets icons (B35) — would trip the fact-mutation detector; (3) art
  direction is not one of plan §6.2's six model roles.
- **Decision:**
  1. `text` is permitted only on text kinds (`framing`, `section_header`).
  2. Given (1), icon blocks hold no fact (their `IconRef` was already excluded) and are
     excluded from `fact_fingerprint`; every other block kind stays keyed in.
  3. New action `AssignIcons` (art direction only), in a separate vocabulary `ArtAction`
     that excludes mode-setting and glyph restyling.
  4. Communication mode is derived by rule from face content (diagram → diagram_led; icons →
     icon_anchored; else text_led); a brief `communication_mode` pin overrides it.
  5. The model proposes taste only, through `ArtAction`, accepted per action by the shared
     `render/trial.try_action` (applies, renders, no new grammar finding) — which the
     aesthetic loop now also uses.
  6. Art direction runs on the `outline` role's binding.
  7. Section dividers are not inserted automatically: a divider's title is slide copy with
     no fact-safe source. The model may recommend them in its rationale, for a human.
- **Rationale:** plan §6.11.2 already describes mode as a function of content shape and
  asks for taste as checkable rules wherever possible; a rule is reproducible (A6) and makes
  every slide's mode explicit with a recorded source (D13). Closing the `text` hole is what
  makes excluding icon blocks from the fingerprint safe rather than a new blind spot.
- **Consequences:**
  - A deck that relied on `text` on a non-text block now fails to load; none in the repo
    does (golden fixture checked).
  - The plan's "section dividers" item is partially delivered; dividers remain a human edit
    or a future, separately designed, fact-safe mechanism.
  - The `outline` role's daily quota now also covers one art-direction call per deck.

### B37 — The content writer authors process-flow diagrams; A5 reaches diagram labels
- **Date:** 2026-10-01
- **Phase / branch:** Phase 3b / `v2/phase-3b-diagram-content`
- **Status:** active
- **Context:** verifying the owner guide against the real CLI showed that no deck built by
  the pipeline can pass GATE 3: criterion 4 needs a native diagram, the outline can assign
  `framework_diagram` and `timeline`, but the content writer's schema (2b.4) never included
  diagrams — "left for the phase that actually assigns those components", which no phase
  then did. Looking for who would lint the new labels found a second gap: nothing called
  `DiagramSpec.framing_texts()`, so A5 never read a diagram's uncited text.
- **Decision:** the writer may propose `kind: "diagram"` blocks, **process_flow only** in
  this round, through a flat, fully-required schema (B26). Each step declares `status`
  (`claim` with citations, or `framing` with a `LabelReason`); claims resolve through the
  same `_resolve_claim` as claim blocks; any failing step drops the whole diagram.
  `lint_framing` now runs over every diagram's `framing_texts()`, and a finding there
  demotes the diagram block and blocks render like any other A5 demotion.
- **Rationale:** process_flow is the geometry `timeline` requires and the plan's own
  example; one geometry proven live is worth more than three schemas guessed at. Dropping
  the whole diagram on any failed step follows the same logic as an incomplete
  `slot_map`: a sequence missing a step is a different fact.
- **Consequences:**
  - `two_by_two` and `layered_stack` are still not writer-authorable; Phase 4 or a follow-up.
  - `prompts/content.md` gains a diagram section (own commit).
  - Any existing diagram fixture whose labels A5 now flags will fail render-safety — by
    design.

### B38 — `render` starts from the validated IR, so a render is reproducible
- **Date:** 2026-10-02
- **Phase / branch:** Phase 3b / `v2/phase-3b-render-qa`
- **Status:** active
- **Context:** verifying the owner guide showed that re-running `autodeck render` with
  identical model replies produced a different deck, voiding a `final_render` approval.
  Two causes. (1) `render` loaded the *latest* IR — the previous render's art-directed and
  critiqued output — so each run art-directed an already art-directed deck and changes
  compounded. (2) Found while proving the fix: every native chart embeds an `.xlsx` whose
  `docProps/core.xml` carries its write time, so any deck with a chart digested differently
  on every render, whatever the IR said.
- **Decision:** `render` always starts from the IR version the `validate` stage recorded
  (the facts the claims approval covers, in the presentation content left them). Art
  direction and the critique then write new IR versions on top as today.
- **Rationale:** a render becomes a function of approved content plus model replies; with
  the response cache, re-running reproduces the same deck (A6), and an approval survives an
  identical re-run instead of being voided by drift nobody asked for.
- **Consequences:**
  - A manual presentation edit made to a post-render IR version is not carried into the
    next render (there is no supported way to make one today).
  - `gate3` also records which criteria failed, so `approve ... final_render` can name them
    when it refuses.
  - The embedded chart workbook's created/modified times are pinned to 1980-01-01T00:00:00Z
    (the date its zip entries already carry), at the source in `design/charts.py`.
  - The provider response cache keys vision calls on the images' bytes, not their count, so
    a cached critique is replayed only for the render it was given. LibreOffice renders were
    verified byte-stable for the same deck, so reproducibility is kept.

### B39 — Phases 2a–3b merge to `v2/integration` before their gates, so the owner can build a UI
- **Date:** 2026-10-02
- **Phase / branch:** Phases 2a–3b / `v2/phase-3b-render-qa` → `v2/integration`
- **Status:** active — owner's instruction
- **Context:** B27 stacked Phases 2b–3b and held them off `v2/integration` until the owner
  had worked the gates. The owner wants to build a UI on top of the pipeline and test the
  gates through it, which needs the code on the integration branch first.
- **Decision:** merge `v2/phase-3b-render-qa` (Phases 2a through 3b) into `v2/integration`
  now, by the owner's explicit instruction, superseding B27's hold for this merge.
- **What this is not:** a gate approval. GATE 2 (claims) and GATE 3 (final render) are still
  pending; approvals are recorded only by a person through `approve` / `/sign` (A7), and a
  UI that triggers them is that person acting, not the merge. Nothing in this merge records
  or implies an approval.
- **Consequences:**
  - `v2/integration` carries code whose GATE 2 and GATE 3 reviews have not happened; issues
    found in UI testing are fixed on `v2/integration` (or branches off it), not on the old
    phase branches.
  - The UI must call the CLI/orchestrator's existing gate paths and must not add a new way
    to approve — the gate-bypass tests (`test_no_command_can_bypass_a_gate`,
    `test_none_of_the_new_commands_can_record_an_approval`) should be extended to cover it.

### B40 — The review UI: a local web front end in a native window, over the existing pipeline
- **Date:** 2026-10-02
- **Phase / branch:** UI / `v2/integration`
- **Status:** active — owner's decision
- **Context:** D7 deferred a "thin review UI"; B39 brought Phases 2a–3b onto `v2/integration`
  so the owner can build one. The owner's requirements: it runs on macOS and Windows, needs
  minimal downloads, has a clean glass look, and is an interface over the codebase
  (everything the CLI does), not a separate system.
- **Decision:** new package `autodeck/ui/`. A standard-library HTTP server
  (`http.server.ThreadingHTTPServer`) bound to 127.0.0.1 serves a JSON API and static
  HTML/CSS/JS. `pywebview` (optional dependency group/extra `ui`) opens it in the OS's own
  web view (WebView2 on Windows, WKWebView on macOS). If pywebview is unavailable or fails,
  the same local URL opens in the default browser (the fallback the owner asked for).
  Command: `autodeck ui`. System fonts only, and CSS `backdrop-filter` for the glass; no
  font, icon or JS framework downloads.
- **Rationale:** one language (Python) end to end; no Electron or Node; the web view already
  ships with both OSes; and the fallback means a failed native window never blocks the owner.
- **Consequences:**
  - The UI calls the same functions as the CLI; it adds no new way to approve a gate (B39,
    A7) — an approval in the UI is a person acting through the existing approval path, and
    the gate-bypass tests are extended to cover the UI's API.
  - The server binds to localhost only and has no auth, so it is a single-user local tool.
  - The model environment (dev/sit/prod) is a Settings choice, and every screen shows which
    tier a run used so a dev draft is never mistaken for a client deliverable.

### B41 — Redesigning an existing deck: the uploaded deck is the source document
- **Date:** 2026-10-02
- **Phase / branch:** UI / `v2/integration`
- **Status:** active — owner's decision
- **Context:** the owner wants to hand AutoDeck a finished deck's text and have it rebuilt in
  the client's brand, changing layouts where that helps. Under A1 every factual statement
  needs a citation, and §6.12 says reference decks teach style, never truth — so a deck's own
  text would otherwise be uncited.
- **Decision:** in a redesign run the uploaded deck is ingested as a source document in the
  run's corpus (its slides play the role of pages, a text frame's location the role of a
  bbox). Every statement on a redesigned slide cites the original slide's verbatim text. Not
  implemented yet; this records the rule the implementation must follow.
- **Rationale:** keeps A1–A3 and A8 intact rather than adding a "trust me" mode: A2 still
  requires every numeral to match the original or a declared derivation; A3's validator
  checks the redesigned wording is faithful to the original; A8 surfaces any place the deck
  contradicts itself.
- **Consequences:**
  - Such a citation proves faithfulness to the client's deck, not truth. The audit report
    must label these citations "client-supplied deck" so a reader can tell them from
    research-paper citations.
  - An optional check of figures against the project's papers can be offered.
  - The deck is a source for that run only and stays inside the client's namespace (A4).
  - The four approvals (A7) apply unchanged.

### B42 — The UI runs the whole deck flow, approving through the CLI's own approval path
- **Date:** 2026-10-02
- **Phase / branch:** UI / `v2/integration`
- **Status:** active — owner's decision (design approved on the canvas, built on request)
- **Context:** B40's UI covered planning and setup; the outline, claims and final-deck
  approvals still needed the terminal. The owner approved a design for every screen and
  asked for it to be built, with approvals signed automatically under the admin's name
  ("since it's a UI, that's kinda obvious") and a profile in Settings to pick that name.
- **Decision:**
  - **Steps run as the CLI.** `autodeck/ui/jobs.py` runs `python -m autodeck.cli <step>`
    in a subprocess, one chain per person action: `outline`; `content` → `validate` →
    `gate2`; `render` → `gate3`. The UI runs exactly what the terminal runs, gate checks
    included; exit 4 (a report with findings) continues a chain, any other non-zero stops it.
  - **One approval path.** `POST /api/runs/<id>/approve` → `approvals.approve_gate` →
    `Orchestrator.approve`, the method `autodeck approve` calls, so every CLI refusal applies
    unchanged. The brief stays signed through `PlannerSession.sign_off`. "Approve & proceed"
    approves, then starts the next chain; the approval is the click, never the chain.
  - **The name comes from the profile.** Settings › Profile stores the approver name in
    `~/.autodeck/profile.json` (the person at this machine, not the project); until saved it
    defaults to `git config user.name`, then the system account. Approving with no name at
    all is refused.
  - **No approval while a step runs** for that run, so an approval always covers what the
    person saw.
- **Rationale:** A7 is about who decides, not about typing. A name typed into a box on every
  approval proves nothing a saved profile does not; the click on a reviewed screen is the
  human act, and the orchestrator still binds it to the artifact's sha256.
- **Consequences:**
  - The A7 guard tests in `tests/test_ui.py` now pin exactly two routes: only `approvals.py`
    calls `.approve(`, reachable only from the approve route; only `plan_sign` calls
    `.sign_off(`; `jobs.py` never imports the approvals module.
  - The five PowerPoint checks are ticked in the browser only; nothing in the code verifies
    them, as before (`docs/OWNER-GUIDE.md` §6b).
  - Redesign (B41) appears on the start screen but stays disabled until it is built.
  - B30 is unchanged: approvals still live in the run's uncommitted `state.json`.

### B43 — Phase 3c: draft-first build (A7 amended: approvals are given on the assembled draft)
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c / `v2/integration` (phase plan `docs/phases/PHASE-3C.md`)
- **Status:** active — owner's decision. The owner, after using the B42 UI: *"It should be
  able to brief and outline after the first prompt itself, it is AutoDeck. Whenever it
  writes something it should cite it. All of this should happen in the same call."* On the
  phase plan's proposals (D-A7, D-A3, D-PLAN, D-SIZE, D-GATES): *"Aligned with the
  implementation, lets go."*
- **Context:** the gate-first pipeline asks for a brief and an outline approval before any
  slide exists, and spends ~25–35 model calls before a draft is visible. The owner's view:
  people find what is missing only once the pieces assemble.
- **Decision (D-A7):** the four approvals stay mandatory and stay a person's. The pipeline
  may build an **unapproved draft** end to end — brief, outline, slides, citation checks,
  validation and DRAFT-marked previews — without any approval. It may not write the final
  `deck.pptx`, export, or label anything final without all four approvals current, and an
  approval still binds to the fingerprint of what it covers, so a revision that changes an
  artifact voids exactly the approvals that covered it.
- **Rationale:** A7 protects who decides, not the order things are built in. Approving a
  brief after seeing the slides it produced is a better-informed approval of the same brief.
  Rejected: fewer approvals (the audit trail records four; the UI makes each a click).
- **Consequences:** `docs/INVARIANTS.md` A7 is amended to this wording. The gate-bypass
  tests stay and extend to the new commands; new tests pin that no draft path writes
  `deck.pptx` or reads as final.

### B44 — A3 independence is about who judges, not how many calls
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c
- **Status:** active — owner's decision (D-A3 in the phase plan, approved with B43)
- **Decision:** the validator keeps its own retrieval and a model different from the
  writer's, and judges the whole deck in as few batched calls as its token budget allows
  (one for a typical deck) instead of a fixed six claims per call. The writer's citations
  never count as validation; code-side resolution (A1) proves a quote exists, the validator
  (A3) judges whether it supports the sentence.
- **Consequences:** `validation.BATCH_SIZE` becomes a token-budgeted batcher; the A3
  contradiction test must still pass on the new path.

### B45 — One compose call writes brief, outline and slides; citations are its output contract
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c
- **Status:** active — owner's decision (the phase's core; D-PLAN and D-SIZE approved with B43)
- **Decision:** a new `composer` role makes one structured call from the prompt and a
  deterministic evidence pack, returning brief + outline + every slide's blocks. Every claim
  and every key message carries `(span id, verbatim quote)` pairs, resolved in code through
  the existing resolvers (`agents/content.py`), never composed. Key-message evidence status
  is computed from what resolved, with the existing `_cap` rule — no per-message probe call.
  Above a token budget (roughly 10–12 slides) the brief and outline come in one call and the
  slides in section-sized calls under the same contract. The planner conversation becomes
  optional: a way to revise the draft.
- **Consequences:** the evidence-gap probe leaves the default path (kept as a library);
  per-slide content writing remains only as the scoped path for a revision.

### B46 — The pending GATE 2 / GATE 3 reviews move to GATE 3c
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c
- **Status:** active — owner's decision (D-GATES, approved with B43)
- **Decision:** GATE 2 and GATE 3 are not run on the gate-first flow. Phase 3c keeps every
  component they judge (validation, render, QA, audit) and GATE 3c exercises them on the
  draft-first flow; the owner reviews once.
- **Consequences:** `STATUS.md` names GATE 3c as the next gate when the phase lands.

### B47 — Draft-first always asks first; a chat mode stays available before drafting
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c
- **Status:** active — owner's decision; **refines B45's planner clause (D-PLAN)**. The owner,
  on the phase plan: *"There should be a way to switch to chat mode before planning. And in
  any case, it should always ask questions/clarifications before jumping into the deck."*
- **Decision:**
  - **Clarify, always.** Between the prompt and the compose call there is one `clarify`
    call: from the prompt and the evidence pack it asks a few (one to four) questions the
    draft genuinely depends on — audience, decision, length, and above all the gaps the
    evidence shows ("the review has no head-to-head data against X: include the comparison
    or leave it out?"). Each question carries a suggested answer the person can accept as
    is. The person's answers go into the compose call. The draft never starts without this
    step. First draft: three calls (clarify, compose, validate) instead of two.
  - **Chat mode, optional.** The start screen offers "Draft from a prompt" or "Plan in a
    chat first". Chat mode is the existing planner conversation; it ends in "Draft the
    deck", and compose takes the conversation's brief as given (writing the outline and
    slides to it) instead of writing a brief of its own.
- **Rationale:** the questions are where the owner's knowledge enters before the expensive
  call, at the cost of one short turn; grounding them in the evidence pack makes them about
  this deck's real gaps rather than a form. Chat mode keeps the planner for people who want
  to think aloud first.
- **Consequences:** `docs/phases/PHASE-3C.md` gains the clarify step and chat mode;
  `prompts/clarify.md` is a new Opus-owned prompt; the gate 3c call budget is ≤ 3 calls.

### B48 — Ask only what changes the deck; one conversation; agreed messages are never silently dropped
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c
- **Status:** active — owner's decision; **refines B47**. Proposed by the orchestrator, the
  owner's answers: *"Aligned on ask if required"*; on one chat: *"Okay"*; on calling out what
  the draft skipped: *"Yes, I agree, anything that's skipped should be called out. Better
  yet, if it's aligned and then skipped due to thin evidence, keep it and call out."*
- **Decision:**
  - **The checkpoint always appears; questions only when they matter.** Before the compose
    call the person always sees what the draft will assume (audience, decision, length, the
    evidence it will lean on) and zero to three questions — only those whose answer would
    change the deck, each with a suggested answer. One click drafts. Refines B47's "always
    ask": the step is never skipped, a question is never invented to fill it.
  - **One conversation.** A single chat on the run: before a draft exists, a message shapes
    the brief (the planner); once it exists, a message is a scoped revision. One transcript
    for the person; the two jobs keep their own prompts underneath.
  - **Coverage is called out, and agreed messages stay.** A key message the person agreed to
    (in their prompt, their answers or the chat) is never dropped for weak evidence. If the
    evidence is `thin`, the message stays on its slides, hedged as `prompts/content.md`'s A8
    section requires, and is flagged. If it is `unsupported`, it stays in the brief and the
    review screen shows it as a gap with the three options (source it, reword it, carry it as
    a named risk); no uncited sentence is written for it (A1 is not relaxed). Anything the
    draft leaves out — an answer it could not honour, a `must_include` with no slide — is
    listed in a coverage section of the review screen and the audit report.
- **Consequences:** compose returns a coverage report beside the draft; approving the brief
  of a draft with `thin` or `unsupported` messages asks the person to accept each as a named
  risk, which is how `DeckBrief`'s `_gaps_are_accounted_for` rule is met.

### B49 — Phase 3d defaults: one-for-one redesign; figure check against papers is opt-in
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3d (redesign, B41) on top of Phase 3c
- **Status:** **provisional** — taken by the orchestrator under plan §0.6 while the owner was
  away ("then pick up the existing deck part"); the owner should confirm or reverse both.
- **Context:** `docs/phases/PHASE-3D.md` left two questions open: may a redesign merge or
  split slides, and is checking figures against the project's papers on by default?
- **Decision:**
  - **One-for-one by default.** Each original slide becomes one redesigned slide, in order.
    The clarify checkpoint may *ask* to merge or split when the deck plainly needs it (an
    overloaded slide, two half-empty ones); only the person's answer allows it.
  - **The paper check is opt-in.** B41 calls it optional; it costs evidence-pack space and a
    second store, and a redesign's first promise is faithfulness to the client's own deck.
- **Rationale:** both are the smallest reasonable reading of B41 and both are easy to widen;
  the reverse (merging slides or checking papers the person did not ask for) changes their
  deck in ways they did not request.
- **Consequences:** `prompts/redesign.md` states the one-for-one rule and the exception;
  the redesign settings default `check_papers` to false.

### B50 — On a redesign, a key message stated on one slide of the client's deck is "supported"
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3d
- **Status:** **provisional** — taken by the orchestrator while the owner was away; confirm.
- **Context:** key-message evidence status uses `evidence_gap._cap`: one non-curated passage
  is `thin`. On a redesign every message cites the client's own slides, so almost every
  message would be `thin`, and approving the brief would mean accepting a named risk for each.
- **Decision:** when every resolved citation of a key message is to the client-supplied deck
  (`client-deck--`), the message is `supported`, noted "stated in the client's deck: slide N".
  A message mixing deck and paper citations, or citing papers only, is graded as before.
- **Rationale:** B41 — a redesign citation proves faithfulness to the client's deck, not
  truth, and the audit report labels it so. `_cap` exists because one research passage is a
  thin basis for a general claim; one slide of the client's own deck is the whole basis a
  redesign claims.
- **Consequences:** a redesign's brief approval asks about risks only for messages the deck
  does not state at all (`unsupported`). The truth of the deck's claims is what the opt-in
  paper check (B49) is for.

### B51 — A `dev-mistral` environment on small paid Mistral models
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c
- **Status:** active — owner's instruction ("We only have $10 so lets use a small model")
- **Context:** the Gemini free tier stopped being usable for a full run: 20 requests per day
  per model (B25) and frequent 503s. The owner wants no token spend beyond the $10/month API
  allowance included in their Mistral plan. Hugging Face's free inference credit ($0.10/month)
  and the free tiers that cap input at 8k–12k tokens (Groq, Cerebras, GitHub Models) cannot
  take a compose call of about 30k tokens.
- **Decision:** add a Mistral adapter (`autodeck/providers/mistral.py`, strict schema
  dialect) and a `dev-mistral` environment. `ministral-14b-2512` serves every role except
  `validation` and `ingest_vlm`, which run on `ministral-8b-2512`, so the judge is not the
  writer (B44). Mistral Small and Medium were the first choice, but this account's limit
  on both is 0 requests per minute; the Ministral models allow 30 and 188.
  `ingest_vlm` moves to Mistral in this environment only. `dev` itself is unchanged.
- **Rationale:** at about $0.20/M tokens a draft run costs a few
  cents, so the allowance covers hundreds of runs. Small models fit the B8 position that a
  dev result is a smoke test, not an accuracy measurement.
- **Consequences:** B8's "Gemini and Groq back every role in dev" and "`ingest_vlm` stays on
  Gemini everywhere" hold for `dev`, not for `dev-mistral`. A3 and A8 results from this
  environment say nothing about `sit`.

### B52 — A near-verbatim quote is cited in the source's words, not dropped
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c
- **Status:** active — owner's decision ("the focus should be on ensuring that the meaning
  does not change. That's why we have LLMs checking it rather than static code")
- **Context:** the first live draft (`dev-mistral`, run `Xls`) dropped 10 of 12 citations as
  "not verbatim". Most were the right passage copied imperfectly: a period added where the
  model cut a sentence short (3), reference markers like "[50, 51]" left out (1), a PDF
  extraction space in "( p = 0.76)" tidied away (1). Two were real splices of two sentences.
  The dropped blocks emptied two chart slots, and the draft preview then crashed.
- **Decision:**
  - The model's quote decides only *which passage* it points at. When it is not found
    exactly, `provenance.snap_span` looks for one passage among the evidence that slide was
    shown which accounts for ≥85% of the quote, in order, within 1.5× its length (quotes
    under 20 characters never snap). The citation is then built from that passage's
    verbatim text through the usual A1 path (`to_citation` → `resolve_quote`), with its
    hash; the model's wording is discarded. Compose and revise list each snap in
    `corrections`.
  - The validator's quotes use the same rule (`ValidatorEvidence.find`), so a judge that
    copies its supporting span slightly wrong is not capped to `unsupported` for it.
  - Whether the passage supports the slide's sentence stays the validator's judgement (A3).
  - The draft preview draws a slide its component cannot draw (a required slot emptied by a
    dropped block) as a labelled placeholder instead of failing the whole preview.
- **Rationale:** A1 exists so every citation is the document's real words at a real
  location. That holds: nothing the model wrote reaches a citation. What changes is that an
  imperfect pointer to the right passage no longer costs the claim. A paraphrase, or text
  the evidence does not contain, still resolves to nothing, so a fabricated quote cannot
  pass.
- **Consequences:** re-running the `Xls` quotes: 5 of the 7 failures snap; the 2 splices are
  still dropped. Thresholds are constants in `autodeck/ingest/provenance.py`.

### B53 — One bounded repair call after a draft loses content
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c follow-up (LIVE-RUN-1)
- **Status:** active — owner's decision ("One bounded repair")
- **Context:** in run `Xls` a block that failed its budget or whose quote did not resolve was
  removed and nothing told the writer why (LIVE-RUN-1 §4c). Two slides were left with a
  headline only. `prompts/content.md` already promised "a rejected block and a rewrite"; no
  rewrite existed.
- **Decision:**
  - After `compose_deck` resolves the draft and runs the draft-time checks (B56), and only
    when something was dropped or an invariant check failed, the composer makes **one**
    repair call (`prompts/repair.md`, schema `RepairDraft`). It lists each failure with its
    kind, concrete numbers and the original block, and asks for replacement blocks for
    those failures only, or a declined reason.
  - The repair runs **before** the IR is saved, so it creates no IR version and touches no
    approval (A7, B43).
  - A1 is unchanged: replacements go through the same `resolve_blocks` path. Each failure's
    candidate passages are drawn only from the evidence that slide was shown, and a
    replacement may cite nothing else. Whatever still fails is dropped as before.
  - B48 holds (agreed messages are never dropped to escape a failure). B49 holds (with
    "keep my words" a repair may only cut).
  - If the repair call itself fails, the first draft stands and a note says so.
- **Rationale:** the owner's position (LIVE-RUN-1 §5) is that basic quality must not depend
  on model class. A small model that overshoots a budget by 40 characters can fix it when
  told the number. Dropping the block cannot.
- **Consequences:** PHASE-3C's exit criterion "first draft in ≤ 3 model calls" becomes "≤ 3,
  or 4 when the repair call runs". `ComposeResult.provider_calls` counts it truthfully.
  Schema-repair retries inside a provider remain uncounted (existing gap). The repair is
  written so `revise_deck` can use it later.

### B54 — Talking headers: the headline states the slide's bottom line (BLOT)
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c follow-up (LIVE-RUN-1)
- **Status:** active — owner's decision ("We typically write talking headers with BLOT. BLOT
  may have an assertion or may paint an overall picture. So, citation may not make sense in
  most cases")
- **Context:** the live draft's headlines were topic labels ("Safety and Tolerability of
  Oral Semaglutide"). The draft-first prompts gave no headline rule, and the default header
  profile was `topic_led`. The A5 framing fence forbade numerals in a header, so a header
  could not carry the slide's number even when the slide cited it.
- **Decision:**
  - A content slide's headline is a full sentence that puts the slide's bottom line first.
    It may assert or synthesise, and it carries no citation of its own.
  - Any specific fact in it (a number, a named trial or study, a comparison) must be stated
    by a cited block on the **same slide**. Code checks numbers (A2, scoped to that slide's
    citations and derivations) and named sources (`audit/header_linter.py`). The validator
    judges meaning: a header is no stronger than the claims it summarises.
  - On a slide with cited content, that rule replaces the A5 numeral and comparative fence
    for the header. On a slide without cited content (title, divider, agenda), the full A5
    fence still applies.
  - The default header style becomes `blot`.
- **Rationale:** headers are the most-read text in a deck (plan §6.11.1). A per-headline
  citation does not fit a synthesis, but an unbacked figure in the largest type on the page
  is the worst place for one.
- **Consequences:** the header verdict is capped at the worst verdict among the slide's face
  claims. Meaning checks are model-sensitive (B8).

### B55 — Two provenance modes: `strict` (MLR) and `normal` (default)
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c follow-up (LIVE-RUN-1)
- **Status:** active — owner's decision ("There should be two versions … full citation only
  and the normal, where we still fact check but it could also have new information")
- **Context:** A1 required every factual assertion to trace to a corpus span. That is right
  for a rep's deck for an HCP, which goes through MLR review. It blocks an ordinary working
  deck. For example, the owner proposes an architecture slide whose content exists only in
  their conversation with Claude.
- **Decision:**
  - Mode is a **project** setting (`knowledge/projects/<p>/settings.yaml`,
    `provenance: strict|normal`, missing = `normal`). It is snapshotted into the run when the
    run starts, recorded on the Deck (`Deck.provenance`) and in the build manifest, and
    shown in the UI. A run's mode does not change once a draft exists.
  - **strict:** today's A1. Only document spans (corpus, or the client's own deck in a
    redesign) may be cited.
  - **normal:** adds two source classes.
    1. **From you:** what the person typed in this run (request, typed answers,
       corrections, chat turns, revise instructions) becomes a run-local source document
       `conversation--<run>`, cited verbatim like any other span. Accepted model-suggested
       answers are not citable. A key message backed only by it is `supported` and labelled
       "from you", as B50 does for a redesign's own deck.
    2. **Unsourced:** the model's general knowledge, as a `claim` with
       `basis: "unsourced"` and no citations. **Qualitative only:** no numerals, dates or
       named studies (A2 blocks numerals already; a named-source fence blocks the rest). The
       validator checks it against the corpus. Corpus support gives `supported` (with a
       suggestion to cite), a contradicting span gives `contradicted`, and otherwise code
       assigns the new verdict `uncorroborated`, which does not block render.
  - Strict mode is enforced twice: the evidence pack omits the conversation, and a `Deck`
    validator refuses any unsourced claim or `conversation--` citation.
  - The final deck looks the same in both modes. Source classes appear in the audit report
    and as badges in the review UI.
- **Rationale:** fact-checking stays universal and provenance stays recorded. What changes
  in normal mode is that "the person said so" and "general knowledge, checked" are legitimate,
  visibly labelled sources.
- **Consequences:** A1, A2 and A3 wording amended in `docs/INVARIANTS.md`. A redesign never
  allows unsourced claims (B41). Every consumer of `Verdict` learns `uncorroborated`. Set
  `strict` explicitly on HCP-facing projects.

### B56 — Deterministic checks run on the draft, before the person sees it
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c follow-up (LIVE-RUN-1)
- **Status:** active — recommended set accepted with the plan
- **Context:** the A2 and A5 linters ran only on the gate-first path and at render. The live
  draft showed a framing block claiming "superior glycemic control … compared to active
  comparators", which validation later found contradicted.
- **Decision:** `agents/draft_checks.py` runs on every draft.
  - **Checks that trigger the B53 repair:**
    - the A5 fence, with B54's header rule;
    - A2 per slide;
    - header facts not backed on the slide;
    - the provenance mode;
    - redesign "keep my words" rewording;
    - a required slot emptied by a drop.
  - **Advisories,** shown in the UI and passed to a repair only if one is already running:
    - topic-label headers;
    - `headers/flow.py` storyline findings.
  - **Dividers:** code removes and reports a `section_divider` in a deck under 8 slides, two
    in a row, or one with fewer than 2 slides after it, unless the person asked for
    sections. A divider carries no fact, so removing one is safe (cf. B36).
  - **Framing linter:** extended to "superior … compared/relative/versus", "compared
    with/to", "relative to", "more effective" and evidence verbs ("demonstrates",
    "establishes").
- **Rationale:** every check is free and deterministic, and each one guards an invariant or
  content that was lost. Quality-only findings do not spend a model call.

### B57 — Preview fonts: what the renderer can see, verified after render
- **Date:** 2026-10-03
- **Phase / branch:** Phase 3c follow-up (LIVE-RUN-1)
- **Status:** active
- **Context:** on macOS, headless LibreOffice uses CoreText and does not read
  `~/.local/share/fonts`. It drew "Inter Display" bold as Arial Black, about 18% wider than
  the Inter metrics the layout was measured with. The title and takeaway then wrapped one
  line more than measured and overprinted the line below. The font gate asked Python's font
  lookup, not the renderer, so it passed (a B11 breach).
- **Decision:** the dev token set uses **Carlito** (owner: "switch to a compatible font"). It
  ships with LibreOffice on every platform, has all four faces, is SIL OFL, and is
  metric-compatible with Calibri. Previews therefore render in exactly the font they were
  measured with, with nothing to install. Deliverables still use `aptos.json`.
  `install-dev-fonts.sh` (Inter) is optional; it also installs to `~/Library/Fonts` on macOS.
  The pre-render gate checks the folders the renderer reads, for every face drawn. After
  conversion, `pdffonts` must list only the declared families (plus LibreOffice's own symbol
  font), or the preview fails with `FontSubstitutionRisk`. Text boxes no longer carry
  `spAutoFit`. Bar charts set `invertIfNegative=0`, because python-pptx's default made
  negative bars invisible.
- **Consequences:** golden previews and digests change once; the owner re-reviews them.

### B58 — Digits inside names are not quantities
- **Date:** 2026-10-04
- **Phase / branch:** Phase 3c follow-up (LIVE-RUN-1)
- **Status:** active — owner's decision ("Glued digits + glossary")
- **Context:** the A2 extractor took every digit run as a numeral. "Type 2 diabetes",
  "HbA1c", "GLP-1" and "PIONEER 7" all needed a cited span containing the digit. On a framing
  line, a title or a speaker note they were demoted outright (A5: no numerals). Replaying the
  live run's draft flagged the title slide, a note and a headline for this reason alone.
- **Decision:**
  - Digits inside a word that **begins with a letter** are part of a name and are skipped by
    A2 matching and the A5 numeral rule (`numeric_linter.is_name_numeral`). Examples:
    `HbA1c`, `GLP-1`, `A100`, `int8`, `GPT-4`. Digit-first words (`3x`, `13B`, `10ms`) and
    dates are quantities, as before.
  - Names whose digits stand apart ("Type 2 diabetes", "PIONEER 7") are listed per project
    in `knowledge/projects/<p>/settings.yaml` under `named_terms`. They are carried on the
    deck (`Deck.named_terms`), so the draft checks and the render gate read the same list.
    Their digits are masked before extraction (`numeric_linter.mask_terms`).
- **Rationale:** a name's digits are not a measurement anyone can misstate without naming a
  different thing. Whether the right trial is named is the validator's question (A3), not
  A2's. The glossary is explicit and reviewable, and the knowledge commit records it (A6).
- **Consequences:** this reverses the extractor docstring's position that a model name must
  trace to a span like any number. A quantity written in a name's clothing (a version
  number used as a figure) is no longer caught by A2. The glossary is owner-maintained.

### B59 — Deck craft lives in skill files, shared by every writer role
- **Date:** 2026-10-05
- **Phase / branch:** Phase 4a (`v2/integration`)
- **Status:** active. The owner's decision ("the deck guidance can be loaded as skill files. We
  should keep it modular"). The research basis is `docs/research reports/Report 1.md` and
  `Report 2.md`.
- **Context:** live run 1 produced topic-label headlines and slides with no body. The model
  wrote bullets as near-copies of source sentences (92–132 characters against an
  88-character ceiling), so all of them were dropped. The prompts taught citation mechanics
  (`content.md` was about 80% quote rules) and almost nothing about what a deck is: an
  argument for a decision, whose facts are grounded but re-expressed for the audience.
- **Decision:**
  - The craft goes into `prompts/skills/`: 12 files, each with front matter (`name`,
    `summary`, `use_when`) and a body:
    - `deck-thinking` (core);
    - `storyline`, `headlines`, `from-source-to-slide`, `slide-bodies`, `fidelity`;
    - `writing-style`, `charts-and-diagrams`, `citations`;
    - `reworking-decks`, `self-review`, `visual-review`.
  - `autodeck/agents/skills.py` loads them. `SKILL_SETS` fixes the static set and order for
    each writer role.
  - The draft-first writer's system prompt becomes role + `components.md` + skills +
    provenance. The gate-first per-slide writer's becomes `content.md` (now a short role
    file) + skills.
  - Role files (`compose`, `revise`, `redesign`, `repair`, `content`) keep only what is
    specific to their call.
  - Central rule: the slide sentence (`claim.text`) is the writer's, written for the audience.
    The quote is the source's, verbatim, and is the shortest run that proves the sentence.
    Paraphrase is expected; a change of meaning is not.
- **Rationale:**
  - One craft is taught to every role instead of being re-stated per prompt.
  - Skills can be loaded on demand once the deck agent exists (Phase 4c, a later decision).
  - Every skill is under `prompts/`, so the manifest already hashes it (A6).
- **Consequences:**
  - Each writer call's system prompt grows by about 20k tokens (85 KB of skills; about 26k tokens total once B63 added the exemplars), which is acceptable at the
    composer's context sizes.
  - `visual-review` is not loaded statically. It is for the preview tool and art direction.
  - The gate-first pipeline's planner, outline and art-direction prompts are not yet aligned
    (Phase 4d).

### B60 — Labelled implications on body slides
- **Date:** 2026-10-05
- **Phase / branch:** Phase 4a
- **Status:** active (owner chose "Yes, labelled")
- **Context:** the audience needs the "so what", but the source often does not state it.
  Report 2 recommends separating the consultant's inference from the source's finding with an
  explicit label.
- **Decision:** a writer's own inference may appear on any slide as a `framing` block whose
  text begins "Implication:". It carries no number, named study or factual comparison: the A5
  fence applies unchanged. It is never the factual basis of a headline. Taught in `fidelity`.
- **Rationale:** the label makes the inference visible and reviewable, and the A5 fence stops
  it from smuggling in facts.
- **Consequences:** prompt-only. No schema or linter change. A future check may verify the
  prefix.

### B61 — The writer chooses answer-first or question-led
- **Date:** 2026-10-05
- **Phase / branch:** Phase 4a
- **Status:** active (owner chose "Writer decides")
- **Context:** a pyramid deck leads with the answer. When the evidence does not support a
  single governing thought, a forced answer overgeneralises at the scale of the whole deck.
- **Decision:** the deck leads with the answer when the evidence supports one governing
  thought. Otherwise it is question-led: the question, what the evidence shows and does not
  show, and what can be decided now. The writer records which it chose, and why, in the
  draft's `notes`. Taught in `storyline`.
- **Rationale:** a question-led deck is the more faithful form when the evidence is split.
- **Consequences:** prompt-only. Nothing yet surfaces the choice in the UI beyond `notes`.

### B62 — Talking headers get a verdict, and failing draft blocks are dropped
- **Date:** 2026-10-05
- **Phase / branch:** Phase 4a follow-up (run XLP, `v2/integration`)
- **Status:** active. The owner asked: "fix the dropped-block bug and the headline gap too".
- **Context:** run XLP, the first run on the B59 skills, had two problems.
  - **Blocks that failed a draft check stayed in the IR.** An uncited `0.8%` and a speaker
    note with uncited numbers both failed the draft checks and survived the repair call.
    They reached the IR and surfaced only at the final render gate. `run_draft_checks`
    reported failures and nothing removed them. `revise_deck` did not run the checks at
    all.
  - **No check covered the headline's meaning.** The s3 header said HbA1c *and body
    weight* fell "compared to empagliflozin and sitagliptin" over a claim saying weight loss
    was *similar* to empagliflozin. The closing header asserted "significant benefits" over
    no claim at all. Headers carry no citation (B54), so no claim verdict covered them, and
    the draft checks look only at their numbers and names.
- **Decision:**
  - **Dropping failed blocks.** `draft_checks.drop_failed_blocks` removes every block that
    still fails a draft check (`CHECK_KINDS`). `compose_deck` calls it after the final build,
    whether or not repair ran. `revise_deck` now runs the draft checks on the slides it
    rewrote and drops their failures. Untouched slides keep their verdicts. A dropped
    headline leaves its slide headless, and the preview shows the gap.
  - **Headline verdicts.** A new IR field, `Slide.headline_check`, holds `HeadlineCheck`
    (`carried` | `overstates`, `notes`, and the `headline` that was judged).
  - `validation.check_headlines` runs as part of `validate_deck`: one extra call per deck
    judges every headline against its own slide's claims and their verdicts. Slides with no
    claims are judged too: an ask or a question is carried, an assertion overstates. An
    unchanged headline over unchanged claims reuses its verdict. A failed call leaves
    headlines unjudged (None), never `carried`.
  - An `overstates` verdict blocks the final render (`RenderSafety.overstated_headlines`)
    and fails GATE 2 criterion 1. The slide is flagged `blocking` in the draft view, and the
    UI inspector shows the note with an "Ask AutoDeck to fix" action.
  - `prompts/validation.md` → "Talking headers" says what overstating is.
- **Rationale:** the headline is the sentence a reader is most likely to repeat, and A3's
  purpose covers it as much as any claim. Judging the headline against the slide's own
  claims, rather than re-retrieving evidence, keeps it one cheap call. Whether a claim is
  true is already the claim pass's job. A failing block that reaches the IR turns a draft
  problem into a render-time surprise.
- **Consequences:**
  - Validation makes one more provider call per pass (0 when every headline is reused).
  - A small validator model can wrongly flag a headline. The cost is a revise. A false
    `carried` would let an overclaim ship, so blocking is the safer default.
  - Live check on run XLP with `ministral-8b`: s3 and s6 were flagged `overstates` with
    precise notes, and s2, s4 and s5 came back `carried`.

### B63 — Gold exemplar decks are the quality bar, checked by the same machinery as drafts
- **Date:** 2026-10-05
- **Phase / branch:** Phase 4a follow-up (`v2/integration`)
- **Status:** active. The owner chose the audiences: a P&T committee for oral semaglutide,
  and a CTO for both Attention Is All You Need and LeJEPA.
- **Context:** run XLP had sentence headlines but thin bodies, about 100 body words across
  six slides, with the key HbA1c result missing. The owner proposed hand-drafted decks to
  tune AutoDeck. We chose exemplars over fine-tuning. Fine-tuning would need hundreds of
  examples, would tie quality to one provider while the providers are being changed (Phase
  4b), and would cut against the owner's rule that quality comes from prompts and checks.
- **Decision:**
  - **Three gold decks** of 11–12 slides each, written by hand as `ComposeDraft` JSON at
    `knowledge/projects/<project>/gold/`. Two are answer-first; the LeJEPA deck is
    question-led (B61). They sit inside the git-excluded project folders, alongside their
    corpora.
  - **New projects.** `transformer-attention` and `lejepa-ssl` were ingested
    (`vaswani-2017-attention-is-all-you-need`, `balestriero-2025-lejepa`).
  - **`scripts/check_gold.py`** runs a gold deck through `compose._build` against the whole
    corpus. That covers verbatim resolution (any snap counts as a failure), slot budgets in
    the real font, the A2, A5 and header draft checks, and key-message grading. All three
    decks are clean.
  - **`prompts/skills/exemplars.md`** (in every writer skill set) shows each deck's brief,
    headline outline and worked slides, and what to copy.
  - **Density guidance in `slide-bodies`:** a content slide carries 35–70 body words,
    usually 3 to 5 points. Two points is the floor. `two_column_compare` is only for points
    that fit in about 37 characters.
  - **Number traps added to `citations`:** every number in a sentence must appear in that
    block's own quotes; keep the source's unit; write a derivation's unit word for word; do
    not hyphenate a number onto a word. Writing the gold decks hit every one of them.
  - **Charts start at zero.** Bar, column, stacked-bar and area charts now pin the value axis
    to zero (`design/charts._ZERO_BASED`). Auto-scaling had started a 67–78 accuracy chart at
    62.
- **Rationale:** an exemplar that passes the same checks as a draft shows a model what "good"
  looks like inside this system's constraints. Its density, its sentence-versus-quote
  contrast and its hedges are all achievable, because they were achieved.
- **Consequences:**
  - The gold decks are the reference for the deferred eval suite (memory:
    deferred-test-layers, layer 7).
  - The renders showed three layout issues that are not content problems. They are recorded
    for the owner and not fixed here:
    - single-line 16-pt bullets fill only the top half of the slide;
    - `closing_cta` draws an empty band with the CTA below it;
    - `chart_focus` places its takeaway below the source line.

### B64 — The evidence pack reads each section's opening, uses the person's answers, and examples are fictional
- **Date:** 2026-10-13
- **Phase / branch:** Phase 4a follow-up (live runs XLP2 to XLP4, `v2/integration`)
- **Status:** active
- **Context:** run XLP2 was still thin, and the cause was upstream of the prompts.
  - **The pack starved the writer.** Its queries were the request plus `project.md`'s meta
    lines. It filled 8.5k of 24k tokens and lacked the review's HbA1c-vs-comparator result,
    its adverse-event summary and its cardiovascular outcome.
  - **The person's clarify answers never reached retrieval.**
  - **The model quoted a skill's invented example as evidence.** It used "−1.3% vs −0.9%",
    from an illustration about the same drug.
- **Decision:**
  - **What the pack reads.** `build_evidence_pack` takes `extra_queries` (each answered
    clarify question with its answer, queried right after the prompt). It also appends
    `section_lead_spans`: the first two substantive paragraphs under every non-boilerplate
    section heading of the corpus, in reading order, trimmed last. Using headings as search
    queries was tried first and did not work: BM25 returned the headings themselves.
  - **Examples are fictional.** Every skill example and `compose.md`'s worked slide now uses
    invented subjects (drug A, comparators B and C, the ALPHA trials, model M).
    `deck-thinking` says examples are never evidence. The exception is `exemplars`, whose
    decks are real and checked.
  - **Skill sets are per role.** Redesign alone gets `reworking-decks`; compose and content
    get `exemplars`. Repair gets only `deck-thinking`, `from-source-to-slide`, `slide-bodies`,
    `fidelity` and `citations` (about 12k tokens instead of 26k).
  - **A single slot holds one block.** `content.check_budgets` rejects a second block in a
    slot that is not a list (`overflow_text`, reason `second_block_in_single_slot`). Before
    this, XLP3's preview drew the slide as a placeholder. `repair.md` now says how to merge
    such blocks, and that a split must give two complete statements, never two halves of one
    sentence.
  - **Same-strength synonyms are carried.** `validation.md` says a headline using a word of
    equal strength ("matched" for "similar") is carried.
- **Rationale:** the writer can only be as good as what it is shown. A section's opening
  paragraphs are where a paper states its results. A skill example about a real subject is
  indistinguishable from evidence to a small model.
- **Consequences:**
  - The pack for the semaglutide request grows from 39 spans and about 8.5k tokens to about
    80 spans and 18k tokens, within budget.
  - XLP4 stated the PIONEER 2 HbA1c result correctly, and its CV slide carried the
    noninferior-not-superior distinction.
  - Open issues:
    - the `ministral-8b` validator marked that correct claim unsupported and raised headline
      false positives;
    - the semaglutide gold deck is visible to drafts on the same project, so those runs
      cannot be scored against it;
    - body density is still about 140 words over 5 slides.

### B65 — A draft never sees its own project's gold exemplar
- **Date:** 2026-10-13
- **Phase / branch:** Phase 4a follow-up
- **Status:** active (owner: "hide the project's own gold deck")
- **Context:** run XLP4, a semaglutide draft, copied the semaglutide gold deck's figure label
  word for word. The facts were right, but a draft scored against a gold deck it was shown
  measures copying, not writing.
- **Decision:** each exemplar in `prompts/skills/exemplars.md` is wrapped in
  `<!-- project: <name> -->` … `<!-- end project -->`. `skills.skills_text(role,
  project=…)` drops the sections tagged for that project and strips the tags from the rest.
  Every writer call passes its project:
  - compose, redesign and repair pass the run's project;
  - revise passes `deck.project`;
  - the gate-first content agent passes `index.project`.
- **Consequences:** a project with a gold deck sees only the other exemplars, so its drafts
  can be fairly compared with its own gold deck. A new exemplar must carry a project tag.

### B66 — Providers: Gemini and Groq removed; an OpenAI-compatible base with Nebius and OpenAI; tool calling
- **Date:** 2026-10-13
- **Phase / branch:** Phase 4b (`v2/integration`)
- **Status:** active. Supersedes B16 and B25 (Gemini and Groq as dev providers). Amends B8
  (the dev strategy is now `dev-mistral`) and B26 (the `gemini` schema dialect is removed).
- **Context:** the owner decided to drop Gemini and Groq and to add Nebius Token Factory and
  OpenAI. They asked for one last Gemini run first, and to keep or remove it on the result
  without waiting. On 2026-10-13, clarify succeeded on `dev-gemini`, but compose
  (`gemini-3.6-flash`) failed with HTTP 503 twice, after the provider's own backoff. That
  is the same failure as on 2026-10-03. Gemini removed.
- **Decision:**
  - **One shared base.** `providers/openai_compat.py` implements the Chat Completions format
    for structured output, images and tools. Three adapters sit on it:
    - `mistral.py`, rebased onto it, with image URLs as bare strings;
    - `openai.py`, using `max_completion_tokens`;
    - `nebius.py`, which also puts the schema in the system prompt, as Nebius advises.
    Claude keeps its own adapter. All of them go through the one httpx transport (B14).
  - **Tool calling.** `BaseProvider.converse(messages, tools)` returns an `AssistantTurn`.
    Its cache key covers the full message list and a digest of the tool specs, so a session
    replays exactly (A6). Invalid tool arguments come back as `{"__invalid__": raw}`; they
    never raise. `_RoleBound` forwards `converse`.
  - **Defaults.** `default_env` is `dev-mistral`, and the CLI reads it from the registry. In
    sit and prod, `ingest_vlm` is interim on `ministral-14b-2512`. Model ids for Nebius and
    OpenAI are chosen once their keys exist, from each provider's live model list, never
    guessed.
- **Consequences:**
  - There is no free dev provider. Development runs on the owner's Mistral allowance (B51).
  - Mistral, OpenAI, Nebius and Claude are all ready for the Phase 4c agent.
  - A stronger validator than `ministral-8b` needs a Nebius or OpenAI key.

### B67 — A slide must fit as a whole before render; design-gallery fixes
- **Date:** 2026-10-13
- **Phase / branch:** design test (`v2/integration`)
- **Status:** active
- **Context:** a stress gallery rendered every component with minimal content, content at
  the published targets, content at 60% of each ceiling, and content at the full ceiling,
  plus edge cases (negative charts, eight long categories with three series, six-step
  diagrams). Its findings:
  - **Slots that each fit can overflow together.** The budget engine checks each slot
    against its own box, as if it had the whole region. At 60% of each ceiling,
    `big_number`, `quote`, `before_after` and `two_column_compare` crashed the renderer
    (`LayoutOverflowError`). At the full ceiling, most other components did too. One such
    slide aborted the whole draft preview. Written to the targets, every component except
    `big_number` fits; its `support` target, 543 characters, is too generous.
  - **Chart and layout defects.** Horizontal bars listed categories bottom-up. All-negative
    bars pinned at zero printed their last tick as "-5.55111512312578E-17", a regression
    from B63. `closing_cta` centred its text in the whole region instead of its panel, which
    left the panel empty.
  - **`icon_pillars` can never render in a draft,** because only gate-first art direction
    assigns icons.
  - **Deterministic QA saw almost none of this.** It flagged one 3pt diagram overlap and
    crashed on placeholder text with no explicit colour. The draft marker's grey failed
    contrast (3.95:1).
- **Decision:**
  - **Trial layout.** `content.check_budgets` ends with a trial layout: the component's real
    renderer draws onto a throwaway python-pptx slide (`_trial_overflow`, no LibreOffice).
    While it does not fit, optional slots are dropped first, then list items, longest first
    (`overflow_stack`, reason `slide_does_not_fit_as_a_whole`). A headline, a required slot
    or a required list's last item is never dropped. If only those are left, the slide is
    reported as not fitting and the preview draws a placeholder that says why.
  - **Preview resilience.** `render.draft` draws a slide that raises `LayoutOverflowError`
    or `ChartConstructionError` as a placeholder; the preview no longer aborts. Placeholder
    text has explicit colours, and the draft marker is #6A6A6A (5.4:1 on white).
  - **Charts.** Horizontal bars reverse category order with the value axis kept at the
    bottom, and tick labels use the data's own decimal places.
  - **`closing_cta`** places its text inside the panel it was measured for.
- **Consequences:** a writer that overshoots its targets now loses optional text before
  render instead of crashing it. Not fixed here:
  - **Joint budgets.** The per-slot ceilings shown to the writer are still each computed as
    if the slot owned the region. The catalog should publish ceilings that account for the
    slots sharing a region.
  - **`big_number`'s support target** is too generous.
  - **`icon_pillars` in draft-first.**
  - **`evidence_with_figure`** draws no figure: its "figure" slot is italic text.
  - **Weak composition at low fill:**
    - 16-pt grey body text under 32-pt bold headlines, with the lower half of the slide
      empty;
    - titles that float when a two-column slide has only titles;
    - a single data card stretched over the whole body area;
    - oversized two-step chevrons.
  - **Within a bar cluster, series still stack bottom-up.**
  - **Only one theme can be tested on this machine.** The `aptos` and Northwind themes need
    Aptos Display Bold, which is not installed.

### B68 — A 1.33 type scale, and bullets that fill the slide
- **Date:** 2026-10-13
- **Phase / branch:** design (`v2/integration`)
- **Status:** active. The owner said "fix the type scale and bullet layout first. The slides
  look really ugly".
- **Context:** the product themes (`dev`, `aptos`) set 16pt body under 32pt titles, a 2:1
  jump with nothing between. `bullets_supporting` drew one-line points in the paler text
  colour (`dk2`) behind em-dash markers, 18pt apart whatever the room, so four points sat
  under the headline and the lower half of the slide was empty. Even a 60-word slide read
  as thin.
- **Decision:**
  - **Type scale.** In `config/tokens/dev.json` and `aptos.json`, body goes from 16 to 18pt
    and heading from 22 to 24pt; title stays 32 and display 54. That is a consistent ×1.33
    step from body to heading to title. The Northwind client theme keeps its own scale.
  - **Bullets.** Points are set in `dk1` behind a bold accent "•". The row gap grows with
    the free space, from 3 to 7 baselines (18–42pt). A tinted 0.75pt hairline separates the
    rows. `Stack.place` now records each item's box (`placed_boxes`), so a renderer can draw
    between rows.
  - **Body targets.** `TARGET_LINES` caps body at 4 lines. An uncapped body target was more
    than its region could hold beside the other slots.
- **Consequences:**
  - Every slot's budget shrinks by about 11%: a one-line point holds about 94 characters
    instead of 106. All three gold decks still pass.
  - Written to the published targets, every component fits in the stress gallery except
    `two_column_compare`, which sheds two of its twelve items at target (the trial layout
    does this, B67). `big_number` overflows only when its figure is written as 26
    characters of words; real figures are a few characters.
  - Not changed yet: the composition of `two_column_compare`, `data_card_grid` with one
    card, and two-step diagrams.

### B69 — The writer designs the slide; the slide master is the only fixed layer
- **Date:** 2026-10-14
- **Phase / branch:** design (`v2/integration`)
- **Status:** accepted as direction; not built. The owner said: "this product is useless if it
  follows a template. It should be able to leverage and stick to the slide master, sure, but
  this is way too much. Why can't the LLMs decide whether chrome is required or not?"
- **Context:** the plan in `CRAFT-4A-4B.md` §9 imposed a fixed visual language: a section
  tracker, page numbers and stickers on every content slide, and a catalog of components
  with slot budgets. A design canvas built that way, with six preset themes, looked polished
  but uniform. The owner rejected fixed themes and mandatory chrome for capable models.
- **Decision:**
  - **Fixed layer = the slide master only.** Brand fonts, palette, margins and safe area,
    logo placement and slide size are fixed. Everything else is the writer's call: layout,
    whether a slide carries chrome (tracker, stickers, page number) and how it looks,
    chart form, density, colour emphasis and diagram choice.
  - **Two design modes.**
    - **Creative:** a free-layout IR of positioned primitives (text frames, shapes,
      charts, diagrams, images) inside the master.
    - **Structured:** today's component catalog and slot budgets, plus a library of preset
      palettes for decks with no client master.
  - **Every tier can run creative.** A UI toggle per run picks the mode. The default is
    creative for Sonnet and above and structured for the smaller models (Luna, Haiku,
    ministral). The owner wants the small models tried in creative mode too ("it shouldn't
    be that bad").
  - **What does not relax:**
    - every claim-bearing text node keeps its citations and passes A1/A2;
    - deterministic QA still fails overflow, overlap, contrast below 4.5:1 (3:1 at 24pt
      and above), type below the master's minimum, and content outside the safe area;
    - quality comes from a render-and-review loop (the writer sees its rendered slide
      against `visual-review`), which is Phase 4c.
  - **Gold decks teach judgement, not a house style.** Each gold deck looks the way its
    audience and medium call for, with its design reasons noted per slide.
    `exemplars.md` carries those reasons, not the pixels.
- **Consequences:**
  - This needs a new IR payload for free layout, an Opus path, plus a python-pptx renderer
    for it.
  - Budgets per slot do not apply in creative mode; fit is checked by rendering.
  - The §9 component list remains useful as the structured mode's catalog and as
    vocabulary for the creative writer, not as a requirement.
  - The small-model creative trial is deferred: "lets take a shot later on". The owner
    asked for the toggle now, so every tier can be tried.
- **Built (2026-10-15):**
  - **IR** (`autodeck/ir/models.py`): `Slide.layout: FreeLayout | None`, with
    `component = "free_layout"`, and `Deck.design_mode`.
    - A layout holds `TextElement`, `VisualElement` (chart, diagram, figure or icon) and
      `ShapeElement`. Frames are in percent of the slide; colours are theme tokens; type is a
      role on the master's scale, with an optional point size.
    - **No text lives in a layout**: every word is still a block, so A1, A2, A3 and A5 are
      unchanged.
    - The Slide validator requires every face block to be placed exactly once and as what it
      is. Notes are never placed, and emphasis may name only real chart categories.
    - `Slide.without_blocks` prunes the layout along with the blocks.
  - **Renderer** (`autodeck/design/free_layout.py`): draws elements back to front in theme
    colours. It draws the source line itself, in a reserved band (`SOURCE_BAND_PT`), and
    highlights the chart categories named in `emphasis`. `render_deck` and the draft render
    take this path when a slide has a layout.
  - **QA** (`autodeck/design/free_layout_qa.py`) measures in the real fonts:
    - text fit;
    - text inside the safe area;
    - overlaps;
    - the source band kept clear;
    - type at or above the minimum;
    - contrast: 4.5:1, or 3:1 at 24pt and above.

    In compose:
    - Text too long for its frame is `overflow_frame`, which the repair call may shorten.
    - Every other finding is `layout_fit`: reported, never repaired, and the block is kept.
    - The final render refuses a slide with a finding (`FreeLayoutQAError`); the draft shows
      a placeholder with the reasons.
  - **Writer:** `prompts/creative.md` replaces `components.md`, and the `slide-design` skill
    joins each whole-deck role (`<role>-creative` skill sets).
    - The request carries the master (size, safe area, source band, type roles and palette
      hex) instead of the catalog's budgets.
    - Compose, redesign and revise have creative schemas with a required `layout`.
    - Resolution removes the elements of dropped blocks, and drops blocks the writer never
      placed, each as a correction.
    - A repair that splits a block stacks the parts in its frame.
  - **Palette presets** (`config/palettes/`, `autodeck/design/theme/palettes.py`): 20
    schemes for decks without a client master. Each replaces only the palette.
    - Each keeps body text at 7:1 or better and the focal accent at 3:1 or better as a chart
      mark.
    - The non-focal neutral (`accent6`) is deliberately light, about 1.5:1, so values must be
      labelled and never told apart by colour alone.
  - The design-mode setting is snapshotted per run (like provenance, B55), with a default
    per environment, a CLI flag and a UI toggle.

### B70 — The headers are read in order, as one story
- **Date:** 2026-10-15
- **Phase / branch:** design (`v2/integration`)
- **Status:** active. In the owner's words, the hand-built Transformer and LeJEPA canvas
  decks "don't tell a story", and of one header: "It should always be a talking header.
  You can't read this aloud, it sounds unnatural."
- **Context:** B62 judges each header against its own slide. Nothing judged the headers
  together. Two decks of true, carried headers read as lists of facts, with no stakes and no
  chain from one slide to the next. One header ("…, ensembles included") was grammatical,
  but no presenter would say it.
- **Decision:**
  - **Validation reads the headers in order** in one more call (`check_storyline`): the
    title, each talking header and a callout's takeaway. It records
    `Deck.storyline_check`: `tells_story` plus findings per slide:
    - `unspeakable`: a label, a noun pile, or a written-register tail;
    - `breaks_chain`: the line does not follow by consequence, contrast or addition;
    - `repeats`: it makes a point an earlier header already made.

    Each finding carries a note fixable in one edit. The check is reused when the headers
    are unchanged.
  - **Advisory, never blocking.** A weak story is a craft failure, not a false statement,
    so it does not enter the render guard or GATE 2. It is shown in three places:
    - the audit report ("Storyline (advisory)");
    - the UI (a note per slide, and a line in the Coverage tab);
    - the draft flags (`story`, the lowest priority).
  - **Writer side:** the `headlines` skill gains rule 7 (spoken, not written) and rule 8
    (part of a chain), and `prompts/validation.md` gains a Storyline section.
- **Consequences:**
  - One more validator call per validated deck, or zero when the headers are unchanged.
  - Findings are not yet fed to revise automatically; the person sees them and asks.

### B71 — `draft --agent`: one agent session writes the deck through tools
- **Date:** 2026-10-23
- **Phase / branch:** 4c (`v2/integration`)
- **Status:** active, provisional until a live dev-mistral session is compared with a
  one-shot draft. Supersedes B45's single compose call and B53's repair call **on the agent
  path only**; one-shot compose stays as the default and the fallback.
- **Context:** The owner approved one agent session owning the deck end to end (Phase 4
  plan, 2026-10-05). On 2026-10-23 they rejected a feature design built from fixed LLM
  stages as "too much harness, very little agent". A one-shot writer sees all the evidence at
  once, writes every slide blind to the checks, and gets one repair pass.
- **Decision:**
  - `autodeck/agents/session.py` runs a step-budgeted `converse` loop: the model calls
    tools, sees the results, and stops at `finish`, a step cap (40), an input-token cap or a
    stall (a text-only turn after one nudge).
  - The draft lives in a workspace (`agents/workspace.py`) that holds a `ComposeDraft`
    under construction. Every write is checked by `compose.build_draft`, the same function
    a one-shot draft goes through. The result is an ordinary `ComposeResult`.
  - The agent starts with the request, the client context, a corpus map and about 4k
    tokens of section-lead passages. It loads skills, searches and reads for the rest.
  - B45's "citations are an output contract, resolved in code" is kept unchanged.
- **Rationale:** The writer sees each slide's failures (unresolved quote, overflow, missing
  slot, topic headline) the moment it writes the slide and fixes them with its context
  intact. That replaces a repair call that never saw why it was writing. The cost is about
  10× per draft (about 30 calls), bounded by the step and token caps.
- **Consequences:**
  - Redesign runs stay one-shot for now.
  - `provider_calls` counts every session turn.
  - A session that never sets a brief raises `ComposeError`, and the CLI falls back to
    one-shot.

### B72 — The agent's code execution is a closed tool vocabulary
- **Date:** 2026-10-23
- **Phase / branch:** 4c (`v2/integration`)
- **Status:** active
- **Context:** The 4c design gave the agent "code execution". Arbitrary Python would let a
  session compute a number that never passes through A2's re-execution, or read a file
  outside the client's namespace (A4), and it would make sessions irreproducible (A6).
- **Decision:** Every tool is named, with a pydantic args model validated per call (the B36
  pattern):
  - skills: `load_skill`
  - corpus: `corpus_map`, `search_corpus`, `read_passage`, `read_claims`
  - deck: `set_brief`, `write_slide`, `remove_slide`, `reorder`, `set_notes`,
    `check_slide`, `check_deck`, `component_budgets`, `compute`, `finish`
  - advisor: `ask_advisor`

  Bad arguments, an unknown tool, or a refusal come back to the model as an error result,
  never an exception. A third identical call with no workspace change in between is
  refused. `compute` is only a dry run of `numeric_linter.evaluate_formula`; the derivation
  itself still travels in the claim.
- **Rationale:** Every effect a tool can have is one the existing checks already cover.
- **Consequences:**
  - New capabilities arrive as new tools, each with its own args model and test.
  - Every tool schema is tested to export in strict mode under a size ceiling, so the
    Gemini "too many states" failure is caught before a provider sees it.

### B73 — The advisor role: a fresh-context second reader, never the validator's model
- **Date:** 2026-10-23
- **Phase / branch:** 4c (`v2/integration`)
- **Status:** active
- **Context:** A writer deep in a session cannot read its own headlines cold. The 4c plan
  put the advisor on `ministral-8b`, which is dev-mistral's validation model. That breaks
  B44: the writer would tune slides to the very model that later checks them blind.
- **Decision:**
  - A new `advisor` role in `ROLES`, bound in every environment: dev-mistral
    `ministral-14b-2512`, sit and prod `claude-sonnet-5`.
  - The registry refuses an environment where the advisor's provider and model equal the
    validator's.
  - `ask_advisor` is one cached text completion. It sends `prompts/advisor.md`, the
    question and only what the agent attaches (slides or headlines only, its notes,
    skills, up to 4 source pages). The answer is returned as a tool result. The advisor
    cannot edit, and its words are never evidence.
- **Consequences:** One more role to bind in any new environment.

### B74 — Session transcript, resume and deterministic compaction
- **Date:** 2026-10-23
- **Phase / branch:** 4c (`v2/integration`)
- **Status:** active
- **Context:** `revise` and UI chat should continue the session that wrote the deck, not
  start a stranger. A replayed session must hit the provider cache (A6), and a long session
  must not grow its context without bound.
- **Decision:**
  - `runs/<run>/session/` holds:
    - `transcript.jsonl`: one record per message, with timestamps only in `meta`, never
      in message content;
    - `workspace.json`: draft, notes, citable set;
    - `system.md`: the exact system prompt the session started under;
    - `corpus_map.md`.
  - A resume reloads all four and continues.
  - Tool results older than the last 8 collapse to their stored one-line summary. The
    function that does this is pure, so a resumed session rebuilds byte-identical
    messages.
- **Consequences:**
  - A prompt edit does not change a resumed session's instructions: `system.md` is the
    record. A new draft starts a new session.
  - The manifest records the transcript and corpus-map hashes (manifest version bump).

### B75 — A1's citable set is every passage the session showed
- **Date:** 2026-10-23
- **Phase / branch:** 4c (`v2/integration`)
- **Status:** active
- **Context:** In a one-shot draft the citable set is the evidence pack. An agent pulls
  passages as it goes.
- **Decision:**
  - A span becomes citable when a tool put it in front of the agent:
    - the opening seed;
    - a `search_corpus` hit;
    - a `read_passage` page;
    - a `read_claims` entry (which adds curated claims, so they resolve).
  - The workspace passes exactly that set to `resolve_blocks`, so a quote from a passage
    the agent never saw fails with `doc_not_shown`, as it does against a pack.
  - Snapping (B52) is unchanged.
- **Consequences:** `docs/INVARIANTS.md` A1 notes the session's citable set.
  `workspace.json` records it, so a resumed session cites against the same set.

### B76 — The deck is read cold before the agent may finish; comparison points name their side
- **Date:** 2026-10-23
- **Phase / branch:** 4c (`v2/integration`)
- **Status:** active, provisional until the XLP5-agent re-run is compared with XLP4
- **Context:** In live run XLP5-agent (dev-mistral, first agent draft), validation marked
  two claims `contradicted`; the one-shot XLP4 draft had none. Both were points in the
  subcutaneous column of a `two_column_compare`: "No fasting requirement" (citing an
  unrelated passage) and "HbA1c reductions of 1.9%". Read alone, as A3 and the audit report
  read every claim, they are statements about the oral drug. The agent loaded `self-review`
  but never called `ask_advisor`, the one reader that sees the slides without the writer's
  context.
- **Decision:**
  - **Cold read before finish.** When the session has an advisor, `finish` returns "not
    finished" until an `ask_advisor` call has attached every current slide
    (`DeckWorkspace.cold_read`, persisted). A slide added after the read needs another
    read; rewriting an existing slide does not. `prompts/agent.md` gains a step: a
    headlines-only read of the whole deck, then a read of the riskiest slides with their
    source pages.
  - **Every claim stands alone.** `agent.md` and the `two_column_compare` recipe in
    `slide-bodies` require each claim to name its subject, and a comparison point to name
    its side (*"s.c.: no fasting rule"*). A point the evidence states for only one side is
    never written for the other by inference.
  - **A new advisory draft check, `subjectless_point`.** A comparison claim that uses no
    word distinctive to its column title and opens with no "label:" is flagged on
    `write_slide`, on `check_deck` and in a one-shot draft's advisories. It is advisory
    because the heuristic can miss a synonym.
- **Rationale:** The gate is the cheapest enforcement that does not depend on a small model
  remembering an instruction: at most two advisor calls per draft (about 2% of the session's
  tokens). The claim rule fixes the cause; the check makes the failure visible while the
  slide is being written, not after validation.
- **Consequences:**
  - An agent draft makes at least one advisor call when an advisor is bound.
  - Memory, planned as B76, becomes B77; the meeting decisions become B78–B80.

### B77 — Agent memory: engagement memory under the client, owner memory in the home folder
- **Date:** 2026-10-23
- **Phase / branch:** 4c follow-on (`v2/integration`)
- **Status:** active
- **Context:** The owner wants the agent persistent at three levels: the run, the project,
  and their own preferences. They will not maintain a glossary by hand ("they might tell the
  agent to correct a few terms but that's it"). The run level is B74. The project level
  cannot live in `knowledge/projects/`: that tier is shared across clients by design (D8),
  so people, action items or a client's preferences written there would reach another
  client's build (A4).
- **Decision:**
  - **Engagement memory:** `knowledge/clients/<client>/memory/<project>.md`, read and
    written only through `ClientNamespace.guard`. Sections: Terms, People, Open actions,
    Decisions, Deck preferences.
  - **Owner memory:** `~/.autodeck/memory/owner.md`, with sections Note style and Deck
    habits. Every write is refused if it:
    - names any client or project in the knowledge root;
    - uses a term or person from the current engagement's memory;
    - copies 8 or more consecutive words of a passage shown in the session;
    - states a figure other than a small count (at most 12).
  - **Files:** markdown with fixed `##` sections, one bullet per item, each tagged
    `(run <id>)`. Caps are 8,000 and 3,000 characters; past the cap a write is refused
    until the agent consolidates (`revise_memory`). Every write is appended to
    `audit.jsonl` beside the file. The person can read and edit both files in Settings,
    and edits go through the same checks.
  - **Agent tools:** `remember` (add, or correct with `replaces`), `forget`,
    `read_memory`, `revise_memory`. The opening message carries both files as a section
    headed "context, not evidence".
  - **Memory is never a `Document`**, so it cannot become a citation (A1).
  - **Reproducibility (A6):** each session snapshots both files into `session/memory/`,
    and `session_record` hashes them. `git_state` ignores `clients/*/memory/**` when
    judging the knowledge tree dirty: the snapshot, not HEAD, records what a build
    remembered.
- **Rationale:**
  - Isolation reuses the A4 mechanism that already guards client files, rather than a new
    one.
  - The owner checks are a backstop under the prompt rule, chosen to fail closed: a
    refused style note costs one retry; a leaked client fact costs a breach.
- **Consequences:**
  - Memory files are working state; whether to commit them is the owner's choice.
  - A resumed session keeps the memory text in its transcript. A reseeded one reads memory
    afresh.
  - The meeting feature's glossary is engagement memory (Terms), with no separate file.

### B78 — Meeting recordings are transcribed locally, with pinned models
- **Date:** 2026-10-24
- **Phase / branch:** meeting Stage A (`v2/integration`)
- **Status:** active
- **Context:** The owner wants meeting recordings turned into notes and decks. Recordings
  are client-confidential. A prototype showed that sherpa-onnx with Parakeet TDT 0.6B v2
  (int8) and Silero VAD transcribes a 20-minute meeting well, offline. The same prototype's
  speaker separation split 6 people into 60 clusters.
- **Decision:**
  - **Speech-to-text is code, not an LLM call, and runs on the owner's machine.** The
    pipeline is `autodeck/meeting/`: ffmpeg decode to 16 kHz mono, then Silero VAD
    (min silence 0.4 s, max speech 25 s), then Parakeet per speech segment. Only the
    LLM step that follows sends text off the machine.
  - **Optional diarization:** off by default; `--speakers` and `--num-speakers N` turn it
    on. It uses pyannote segmentation 3.0 with English wespeaker embeddings at threshold
    0.85. Each segment takes the speaker turn it overlaps most, labelled S1, S2… by first
    appearance. With more than 12 clusters it falls back to unlabelled segments.
  - **Models:** downloaded once from the sherpa-onnx GitHub releases into
    `~/.autodeck/models/`. The folder can be overridden by `models_dir` in
    `~/.autodeck/settings.json`, or by `AUTODECK_MODELS_DIR`, for networks that block
    GitHub; the files can be copied in by hand. Each file is verified against a sha256
    pinned in `model_files.py` and never re-downloaded. `transcribe` never downloads; it
    says to run `autodeck meeting models --download`.
  - **Dependencies:** ffmpeg comes from `imageio-ffmpeg` (it is not installed on the
    owner's Mac). All speech dependencies are in an optional `meeting` extra, imported
    lazily with an install hint (the B40 pattern). `sherpa-onnx-core` is named explicitly
    because the lock otherwise drops it.
  - **Confidentiality:**
    - `transcript.json` records the audio's file name and sha256, never its path.
    - Logs and CLI output carry counts, timings and the real-time factor, never text.
    - The temporary WAV is deleted, and the audio is never copied into the repo.
    - Root-level audio files are git-ignored.
- **Rationale:** Measured on the owner's M1 Pro (8 threads) with the 45-second two-voice
  test clip (`tests/fixtures/meeting_clip.m4a`, made with macOS `say`):
  - word error rate 1.6%;
  - ASR at a real-time factor of 0.06;
  - diarization at 0.13, with exactly 2 speakers found.

  For 20 minutes of audio that projects to about 1.2 minutes of ASR, plus about
  2.6 minutes if diarization is on. That still has to be measured on the real recording.
- **Consequences:**
  - A6 rests on the hashed transcript, not on re-running ASR: a model or sherpa-onnx
    upgrade can change the words. `transcript.json` records the model names and the
    sherpa-onnx version.
  - Parakeet v2 is English-only; Hindi fragments come out as noise. A multilingual backend
    (Whisper large-v3-turbo) would sit behind the same `Recognizer` protocol if it is
    needed.
  - The clip already shows the mishearings the glossary is for ("Shikha" heard as
    "Shikta", "data bricks"). Correcting them is the notes agent's job, with engagement
    memory (B77), not ASR's.

### B79 — A meeting transcript is a citable document, and a run can be built from it alone
- **Date:** 2026-11-03
- **Phase / branch:** meeting step 9 (`v2/integration`)
- **Status:** active
- **Context:** B78 turns a recording into `runs/<run>/meeting/transcript.json`. To build
  notes or a deck from it, what was said has to be evidence that A1 can resolve and A3 can
  check, and a run has to work when the project has no paper corpus at all: a client meeting
  is often the only source. Before this, `prepare_planning` and `validate` refused a project
  without ingested documents (exit 2).
- **Decision:**
  - **The transcript is a `Document`.** `autodeck/ingest/transcript_source.py` writes
    `runs/<run>/source/transcript--<run slug>.json`. Page N is the Nth non-empty segment;
    each page has exactly one `text` element (`t{N}-e1`) with the whole-page box, as the
    conversation document does (B55). The A1 resolver, the validator and the audit report
    need no new path.
  - **No time, speaker label or audio identity inside the Document (A6).** Times and
    speakers go to the sidecar `runs/<run>/meeting/segments.json` (page → start, end,
    speaker). The same words always give a byte-identical Document; a re-timed or
    re-diarized transcript does not change a single quote hash.
  - **A new source class, `transcript`** (`TRANSCRIPT_DOC_PREFIX = "transcript--"`), read
    off the doc id like the others. It is **allowed in strict mode**: a meeting transcript
    is a record of what was said, held to the same strictness as a paper, not the person's
    own typing (which strict refuses). In A3 it sits in the document pool: it can support
    and contradict, like the corpus.
  - **Labels:** the audit report reads "from the meeting, mm:ss" (h:mm:ss past the hour),
    with the time taken from the sidecar at render time; slide flags gain the advisory
    `from_meeting`. Like "from you", it proves the slide says what was said, not that it is
    true.
  - **Meeting-only runs.** A run whose folder holds `meeting/settings.json` is a
    run-source run, like a redesign (B41). `_redesign_planning` is generalised into one
    run-source branch inside `prepare_planning` (`RunSourcePlanning`, with
    `RedesignPlanning` and `MeetingPlanning`), and `validate` takes the same branch. The
    store is the run's `source/` folder plus the project's papers only when the settings'
    `check_papers` is on; **the default is off**, as for a redesign (B49), so a project
    with no corpus works and a meeting deck is checked against the meeting unless the
    person asks for the papers too. The conversation document is never indexed (A3).
  - **The whole transcript goes in the writer's pack when it is under about 20k tokens**,
    never trimmed; above that, retrieval alone.
  - **Engagement memory Terms are shown to the validator as context, never as evidence.**
    The claim batch opens with a block headed "Engagement terms (context, not evidence)",
    and `prompts/validation.md` says that only a listed spelling and mishearing pair
    ("APLD" heard as "APID") counts as the same word. What was passed is snapshotted to
    `runs/<run>/validation-terms.json` (A6).
  - **A6 hashes:** `run_source_hashes` also hashes `meeting/*.json` (transcript, settings,
    segments) and the Terms snapshot.
- **Rationale:**
  - Reusing the `Document` model is the whole point: one resolver, one validator, one audit
    trail. A second "transcript citation" type would be a second A1.
  - Keeping times out of the Document follows the conversation document (B55): time is
    presentation, words are evidence.
  - Strict mode exists to keep unchecked human assertion out of MLR decks. A transcript is
    not that: it is a verbatim record, and the validator checks claims against it.
  - Terms as context, not as a rewrite of the transcript: the quote stays what was heard
    (A1 is verbatim), and the validator is told which differences are mishearings.
- **Consequences:**
  - A validate that reuses a verdict (B44) does not re-judge it when only the Terms
    changed. Re-validating from scratch is the remedy if a new Term should rescue a claim.
  - The UI shows "from the meeting · turn N" without a time until step 12.
  - `draft --agent` falls back to one-shot on a meeting run until step 11 joins the deck
    tools to the notes session.

### B80 — Meeting notes are written by an agent through tools, every item cited, read cold before finishing
- **Date:** 2026-11-04
- **Phase / branch:** meeting step 10 (`v2/integration`)
- **Status:** active
- **Context:** Step 9 (B79) made the transcript a citable document. The owner wants notes
  that people act on, with judgement in the agent and its skills, not in a fixed pipeline of
  LLM stages ("too much harness, very little agent"). The original spec had a fixed
  "verify" call and a separate glossary file; both are replaced here.
- **Decision:**
  - **A notes session, like the deck session (B71).** `agents/notes_agent.py` runs
    `session.run_session` with a closed tool vocabulary (B72): `read_transcript`,
    `search_transcript` (the transcript only, never the papers), `notes_set_section`,
    `notes_add_item`, `notes_edit_item`, `notes_remove_item`, `show_notes`,
    `finish_notes`, `ask_advisor`, the memory tools (B77) and `load_skill`. It runs on the
    `composer` role; the advisor on `advisor`.
  - **The workspace decides nothing about content.** `agents/notes_workspace.py` holds seven
    fixed sections (Summary, Attendees, Themes, Decisions, Key dates, Action items, Open
    questions and risks). The sections are fixed because readers look for decisions and
    actions in the same place every time; what goes in them is the agent's judgement,
    guided by the `meeting-notes` skill. Two sections have structured fields: an action's
    owner (absent reads "Owner TBD", never a guess) and due date; a key date's date as said
    and its precision (`day`, `week`, `month`, `quarter`, `year`, `relative`, `unclear`).
  - **Every item is cited (A1).** An item carries one or more citations into the
    transcript, one verbatim quote per turn. A point made across several turns cites each
    turn; a quote never crosses a turn boundary, because that would be a splice. Citations
    resolve through `content._resolve_citation`, the deck's own resolver, against the turns
    the session has shown (B75). The page the agent names is a hint that disambiguates a
    short quote; a quote found on another turn is refused with the right turn named.
  - **The item's words may be corrected; the quote may not.** Engagement memory's Terms give
    the right spelling of a misheard name; the item uses it, and the quote keeps what the
    transcript says. An unsure spelling becomes an open question.
  - **The whole transcript is preloaded when it is under about 20k tokens**, and every turn
    is then citable from the start. Above that, the agent reads it in ranges.
  - **The advisor's cold read replaces a fixed verification call.** `finish_notes` is
    refused until `ask_advisor` with `whole_notes` has run: the advisor sees the notes,
    each item's quotes and the transcript, and nothing else (B73, B76).
  - **Output:** `render_notes` writes `meeting/notes.md` (times from the sidecar, item ids
    as `<!-- nX -->` tags), `meeting/notes.json` (pages and quotes with hashes, no times)
    and `meeting/notes.rendered.md`. Both are deterministic in the workspace and the time
    map. The session lives in `runs/<run>/session/`, hashed by `session_record` (B74).
- **Rationale:**
  - One resolver for slides and notes: A1 means the same thing in both.
  - A wrong owner or a firmed-up decision is the notes' version of an overclaim, and the
    most expensive error they can make; the prompt, the skill and the advisor all say so,
    and the workspace makes "Owner TBD" the default rather than a failure.
  - A cold read by a second model is judgement; a fixed verify stage would be harness.
- **Consequences:**
  - The validator (A3) does not yet judge notes items; the advisor's read and A1 are the
    checks. Running the claim validator over notes is a candidate for step 11 or later.
  - Step 11 continues the same session with the deck tools; turns it read stay citable.

### B81 — Confidential environments, and how the person corrects notes
- **Date:** 2026-11-04
- **Phase / branch:** meeting step 10 (`v2/integration`)
- **Status:** active
- **Context:** Recordings are client-confidential (B78). Transcription is local, but every
  LLM call on a meeting run sends transcript text to a provider. The owner does not
  maintain a glossary (B77) but will correct the agent.
- **Decision:**
  - **`confidential_ok` per environment** in `config/models.yaml`, default false when
    absent. Every LLM command on a meeting run (`meeting notes`, `meeting revise-notes`,
    and `clarify`, `draft`, `revise`, `validate` on a run with `meeting/settings.json`)
    refuses an environment without it. **The owner flagged dev-mistral, sit and prod on
    2026-11-04.** A new environment must be flagged deliberately.
  - **Two ways to correct notes**, both resuming the same session (B74):
    - `meeting revise-notes RUN --say "..."`: the person's words, logged to
      `revisions.jsonl` as an `instruction` (so in `normal` mode they are citable as
      "from you", B55).
    - `meeting revise-notes RUN --apply-edits`: the person edits `notes.md`; the unified diff
      against `notes.rendered.md` goes to the session, and the item tags tell the agent
      which items changed. It is logged as `edits`, not as an `instruction`: a diff of
      generated text is not the person's own typing.
  - The agent turns a correction of a term into an engagement memory Term (`remember`), so
    the next meeting, and the validator (B79), spell it right.
- **Rationale:** the flag fails closed, so a newly added provider cannot receive a
  transcript by accident. Editing the file is how people actually correct notes; sending
  the diff keeps the session, not the person, responsible for keeping every item cited.
- **Consequences:**
  - The UI for both (an editor with "Apply my edits", a chat box) is step 12.

### B82 — The meeting deck continues the notes session by reseeding it
- **Date:** 2026-11-05
- **Phase / branch:** meeting step 11 (`v2/integration`)
- **Status:** active
- **Context:** Step 10 (B80) writes meeting notes in an agent session. The plan says the deck
  is built "from the same session": the agent that read the meeting and wrote its notes
  should not start from nothing. The deck agent (B71) and the notes agent use different tool
  vocabularies, and the deck agent's fresh draft used to delete the session transcript,
  which the two now share (`runs/<run>/session/`).
- **Decision:**
  - **`draft --agent` on a meeting run reseeds the run's session** (the mechanism
    `resume_deck_agent` already uses past its token budget, B74): a new deck transcript in
    the same session folder, whose opening message carries the meeting (every turn when
    under about 20k tokens, else a map of it), the notes with the turns each item cites, the
    agent's note to the person, memory, and the usual deck context. It does not append deck
    turns to the notes transcript: a history of calls to tools the provider is no longer
    offered is fragile across providers, and the notes' tool results would crowd the deck
    turns for no gain.
  - **The citable set carries over (B75):** every turn the notes session showed is citable
    from the deck's first turn; above the preload cap, any other turn must be found or read
    first. The papers join only when the meeting's `check_papers` is on (B79).
  - **The notes are context, never evidence.** Slides cite turns, not notes
    (`prompts/agent_meeting.md`). The deck agent's system adds that section and the
    `meeting-readout` skill.
  - **Files:** the notes session keeps notes-specific names (`notes_transcript.jsonl`,
    `notes_system.md`, `notes_workspace.json`, `notes_meta.json`); a step-10 layout is
    renamed to them on first use. The deck keeps the deck agent's names, so `revise`
    resumes it unchanged. A fresh meeting deck archives an earlier deck transcript as
    `transcript.N.jsonl` instead of deleting it. Both sets are hashed by `session_record`
    (A6).
  - One-shot stays the default on dev-mistral (`--agent` opt-in, owner decision 2026-10-23).
- **Rationale:** continuity is in what the agent knows and may cite, not in the literal
  message list. Reseeding is already how a long deck session continues, so a meeting deck
  adds no new continuation path.
- **Consequences:**
  - Notes and deck can be revised independently (`meeting revise-notes`, `revise`).
  - A note corrected after the deck was drafted does not change the deck; the person revises
    the deck, which can re-read the turns.

### B83 — The meeting UI: streamed upload outside the repo, deleted after transcription
- **Date:** 2026-11-05
- **Phase / branch:** meeting step 12 (`v2/integration`)
- **Status:** active
- **Context:** Steps 9–11 made meetings work from the terminal. The owner works in the UI.
  A recording is client-confidential and large: the real one is 74 minutes, and an
  uncompressed WAV of that length is several hundred megabytes. The existing upload route
  reads the whole body into memory and caps it at 50 MB.
- **Decision:**
  - **A separate audio route**, `POST /api/meeting/upload`, with the same cross-site guard as
    the deck upload (the `X-AutoDeck-Upload: 1` header). Suffix, length and the 1 GB cap are
    checked before a byte of the body is read; the body is copied to disk in 1 MiB chunks.
  - **Outside the repo folder:** `~/.autodeck/uploads/<run>/` (or `AUTODECK_UPLOADS_DIR`),
    never `runs/`, so no audio can be committed by accident (B78).
  - **Deleted when transcription ends, whatever the result.** The transcript keeps the file
    name and sha256 (B78), which is what pins the recording. The deletion is a job feature
    that refuses any path outside the uploads folder.
  - **The UI runs the CLI** (B42): `CHAINS["meeting"]` is `meeting transcribe` then `meeting
    notes`; "Apply my edits" and the chat box are `meeting revise-notes --apply-edits` and
    `--say`; "Make a deck from this meeting" is the ordinary `clarify` → answers → `draft`
    path on the same run. Nothing in the UI decides content or approves anything (A7).
  - Agent or one-shot follows the environment's existing default, as for any draft.
- **Rationale:** streaming keeps a large upload from exhausting memory; keeping audio out of
  the repo and deleting it after use limits how long confidential audio exists on disk to
  the minutes transcription takes.
- **Consequences:**
  - A failed transcription needs the file uploaded again.
  - Step 13 (the real recording) can now run from the UI on the owner's Mac.

### B84 — Phase 4 starts before GATE 3c; the audit report is reviewed only for strict decks
- **Date:** 2026-11-05
- **Phase / branch:** Phase 4 (`v2/phase-4-workflow`, cut from `v2/integration` at `1b5e38c`)
- **Status:** active
- **Context:** `docs/phases/PHASE-4.md` lists GATE 3 approved as a precondition. GATE 2/3
  moved to GATE 3c (B46), which has not been approved in writing; `STATUS.md` still names
  GATE 1 as the last gate passed. Open question Q4 asked who reads the audit report.
- **Decision:**
  - **Phase 4 is built now, on its own branch**, at the owner's instruction (2026-11-05).
    Nothing merges into `v2/integration` until the owner approves GATE 3c and then GATE 4 in
    writing (BRANCHING.md rule 3). The owner asked for all eight tasks, not one at a time;
    they are still built and committed task by task.
  - **Q4, answered by the owner:** the audit report is internal. It is a reviewed document
    only for **strict** decks (MLR, anything going for approval), where someone signs off
    on the claims. In **normal** use nobody has time to review it; it is still written, as a
    log (Markdown report and manifest, A6), but nothing produces a PDF of it or asks the
    person to read it. Task 4.6 is therefore a PDF for strict decks only.
  - The phase's tasks are re-scoped to what exists since the phase was written: 4.4's
    `build` runs the draft-first flow (B43), whose four approvals are on the draft.
- **Consequences:**
  - The branch carries work whose gates are pending; `STATUS.md` says so.
  - A normal-mode deck's audit trail is complete but unread by default; a strict deck's is
    the review surface.

### B85 — A run belongs to one client; knowledge files may not link out of their folder
- **Date:** 2026-11-05
- **Phase / branch:** Phase 4, task 4.5 (`v2/phase-4-workflow`)
- **Status:** active
- **Context:** The first run of the multi-client regression (task 4.5) found eight
  cross-client leaks, two root causes. This is the phase's top escalation trigger: stop,
  fix, regression test, record.
  1. **`--client` could re-bind a run.** `_draft_setup` took `--client` before the client
     the run recorded, and `clarify` never compared them. `draft r --client beta-co` on an
     alpha-co run sent alpha's request (and, on a meeting run, alpha's transcript and notes)
     together with beta's client knowledge.
  2. **Symlinks bypassed the guard.** `KnowledgeLoader` read `client.md`, `value_prop.md`,
     `style/headers.yaml` and the project's files directly, not through `ClientNamespace`;
     a symlink inside alpha's folder (or the shared project) pointing at beta's file loaded
     beta's text into alpha's context.
- **Decision:**
  - **A run is bound to the client and project its own files record** (`ui.json`,
    `clarify.json`, `redesign.json`, `meeting/settings.json`, the latest IR).
    `planning.require_run_binding` refuses any other client or project (exit 1) before
    anything is read or sent, and refuses a run whose files disagree. It runs in
    `prepare_planning` (so in clarify, draft, revise, the notes commands and the UI's
    planning sessions) and in `meeting transcribe` and `redesign`.
  - **Every knowledge file the loader reads must resolve inside its own folder**
    (`loader._contained`): a client file inside that client's folder, a project file inside
    that project's folder, and the folders themselves not links to another. A path that
    resolves into another client's folder raises `ClientIsolationError`.
  - The eight tests that found the leaks are now ordinary passing tests in
    `tests/test_multi_client_regression.py`, plus one for `meeting transcribe`.
- **Consequences:** to build a run's material for another client, the person starts a new
  run; nothing carries over.
  - Next free id: **B86**.

