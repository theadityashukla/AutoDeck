# AutoDeck v2

**Consulting deliverables from source documents, where every factual statement on a slide
is traceable, verified, and auditable.**

The overriding design value is **accuracy**. Beauty is second. Speed is third. That
ordering is not a slogan — it decides arguments, and it is why this system has blocking
validation, a numeric linter that re-executes arithmetic, and four mandatory human
approvals per deck.

> **This document is the durable half of the picture.** It carries context that does not
> change phase to phase. For where the build actually *is*, read `STATUS.md` and the
> latest document in `docs/handovers/`. Those two together are the design:
> **README (why and what) + latest handover (current state) = the full picture.**

---

## Status

Planning scaffold complete; **Phase 0 not started.** No v2 package code exists yet.
See `STATUS.md`.

## Repository map

| Path | What it is |
|---|---|
| `README.md` | This file — durable context |
| `STATUS.md` | Where the build is right now |
| `DECISIONS.md` | Append-only decision log (D1–D13, B1–B7, and everything since) |
| `docs/AUTODECK_V2_PLAN.md` | **The specification. Source of truth.** |
| `docs/BRANCHING.md` | Branch topology, gate protocol, PR and commit conventions |
| `docs/MODEL_ROUTING.md` | Which model does what — build-time and runtime |
| `docs/INVARIANTS.md` | A1–A8 made checkable, with a coverage tracker |
| `docs/phases/` | Eight phase briefs — the executable task lists |
| `docs/handovers/` | One document per completed phase |
| `docs/reference/slide-geometry/` | Vendored skill seeding the diagram engine |
| `legacy/v1/` | **Frozen** v1, with `LEGACY.md` salvage map |

---

## Why v2 exists

AutoDeck v1 (2025) was a Streamlit multi-agent system: PyMuPDF parsing → agentic chunking
(local Gemma 3 12B via MLX) → ChromaDB RAG → outline agent → content agent → python-pptx
rendering into template placeholders → a DesignAgent that screenshotted slides, critiqued
them with Gemini Vision, and applied fixes until a target score.

It stalled, and the root cause is specific:

> **python-pptx has no layout engine**, so v1 was hand-building one and using a vision
> model as a measuring instrument.

The EMU math, the overflow whack-a-mole, the fix loop — all symptoms of that one cause.
Secondary causes: the local MLX stack (quality and platform lock-in), Streamlit state
management, and a ~3-layout vocabulary that made every deck look the same.

v1 lives in `legacy/v1/` as reference. Read `legacy/v1/LEGACY.md` before reusing anything
from it — the salvage list is shorter than it looks, and it flags one place where the
spec overstates what is reusable.

### What v2 changes

- A **Deck IR** becomes the central, versioned, auditable artifact. Agents read and write
  IR; renderers consume it.
- **Docling** replaces PyMuPDF plus agentic chunking; its element-level provenance
  (page + bbox) powers claim citations.
- **Constraint-first layout**: components declare text budgets from real font metrics
  *before* content is written. Overflow becomes rare by construction, and residual checks
  are deterministic arithmetic rather than vision-model judgment.
- **Native-only rendering.** Components are designed *and* rendered in the final medium —
  python-pptx over a real OOXML theme and slide master, authored against a fast
  render-preview loop. **No HTML→PPTX conversion exists anywhere in the system.**
- **Cloud-only models** behind a provider abstraction. The MLX/Gemma layer is deleted.
- **Two-tier knowledge folders** (project + client), curated markdown loaded fully into
  context, with retrieval reserved for large paper corpora.
- **Validation and audit promoted from afterthought to load-bearing wall.**

---

## The accuracy invariants

**These are the contract.** Code, prompts, tests, and CI enforce them. Every phase's
acceptance criteria implicitly include "no invariant violated."

**A1 — Universal citation.** Every factual assertion in rendered slide content *or speaker
notes* carries ≥1 citation resolving to a source span: `(doc_id, page, bbox,
verbatim_quote, quote_sha256)`. Only `framing` blocks are exempt.

**A2 — Numbers are copied or derived, never invented.** Every number, percentage, unit,
and date traces to a cited source span — directly, or through a declared **derivation**.
Derivations are first-class: the content agent may compute percentages, deltas, growth
rates, and unit conversions from cited raw numbers, provided the IR records the formula
and the cited inputs. The numeric linter extracts all numerals, normalises them, matches
each to a cited span or derivation, and **re-executes every derivation formula**. Zero
unmatched numerals to pass.

**A3 — Blocking validation.** Every claim gets a verdict: `supported |
partially_supported | unsupported | contradicted`. A deck cannot reach final render while
any block is `unsupported` or `contradicted`. **The validator re-retrieves independently**
— it checks the cited span *and* searches the corpus for contradicting spans. It never
merely trusts the writer's citation.

**A4 — Client isolation.** A build loads exactly one client namespace. Any cross-client
reference in context assembly is a build **error**, not a warning.

**A5 — Fact/framing separation.** Positioning language is typed `framing` and is
citation-exempt, but must pass a deterministic "no fabricated fact" lint: no numerals, no
named studies, no comparative superlatives carrying factual content. Violations are
**demoted to `claim`**, which then requires citation.

**A6 — Reproducibility and audit.** Every deck ships the frozen IR, an audit report
(slide → claim → verdict → doc/page → verbatim quote), and a build manifest (model IDs,
prompt hashes, knowledge git commit, component library version). Same manifest + IR
re-renders byte-comparable output.

**A7 — Human gates.** Four mandatory approvals per deck: planning brief, outline,
post-validation claims table, final render. **The pipeline never auto-approves.**

**A8 — Honest uncertainty.** Where sources conflict or evidence is `partially_supported`,
hedge in the slide text or notes — **never average, round, or silently pick one.**
Conflicts appear in the audit report.

> **The rule that matters most** (plan §0.4): never weaken an invariant to make a test
> pass or a demo work. If an invariant blocks progress, stop and surface the conflict with
> options. Quietly relaxing one produces a system that looks finished and is untrustworthy
> — the only failure mode this project cannot recover from.

`docs/INVARIANTS.md` turns each into a checkable item with an owning phase and a coverage
tracker.

---

## Locked decisions

Do not relitigate without owner sign-off. Full rationale in `DECISIONS.md`.

| # | Decision |
|---|---|
| D1 | Deliverables are fully editable native PPTX on a real slide master/theme XML |
| D2 | Cloud APIs for everything; no local models |
| D3 | Ingestion via Docling; provenance preserved end to end |
| D4 | Deck IR is the single source of truth; renderers are downstream |
| D5 | PPTX is the medium end to end; **no HTML→PPTX conversion anywhere** |
| D6 | Provider abstraction with structured outputs; Gemini first, Claude added |
| D7 | CLI/pipeline-first, headless core; review UI deferred |
| D8 | Knowledge = curated markdown folders loaded fully; retrieval only for corpora |
| D9 | Accuracy invariants are blocking, not advisory |
| D10 | Charts are native editable PowerPoint charts with data provenance |
| D11 | Icons are vectors end to end; raster icons forbidden |
| D12 | Header voice is a learnable per-client profile; headers with facts are claims |
| D13 | Text/icon/diagram balance enforced by deterministic lints, not model taste |

**Rejected, do not revisit:** runtime HTML→PPTX conversion; design-time HTML with
hand-porting; PptxGenJS or other JS generators; Office.js add-ins or macro-enabled files.

---

## Architecture

```
                          ┌────────────────────────────────────────────┐
                          │              knowledge/                    │
                          │  projects/<p>/  (papers, claims, assets)   │
                          │  clients/<c>/   (context, framing, theme)  │
                          └───────┬────────────────────┬───────────────┘
                                  │ curated md (full)  │ corpus (retrieval)
                                  ▼                    ▼
  PDFs ──► [Ingest: Docling] ──► Document Store (elements + provenance)
                                  │
                                  ▼
        [Planning Agent ⇄ human] ──► DeckBrief (objective, key messages,
                                  │     evidence-gap check, layout pins)
                                  │            ◄── brief sign-off (first approval)
                                  ▼
        [Outline Agent] ──► Deck IR v0 (skeleton: roles, layouts, intents)
                                  │            ◄── GATE 1: human approves outline vs brief
                                  ▼
        [Content Agent] ──► Deck IR v1 (blocks + claims + citations,
                                  │          written INSIDE component budgets)
                                  ▼
        [Validation Agent] ──► verdicts + audit table
                                  │            ◄── GATE 2: human approves claims
                                  ▼
        [Art Direction pass] ──► deck-level rhythm, component swaps
                                  ▼
        [Native Renderer: theme master + component renderers
                          + charts + diagrams + icons]
                                  ▼
        [QA loop: LibreOffice render → deterministic checks →
         vision aesthetic critique (bounded IR actions) → re-render]
                                  │            ◄── GATE 3: human approves final
                                  ▼
        deck.pptx  +  audit_report.md/pdf  +  build_manifest.json
```

All intermediate artifacts live under `runs/<run_id>/` — inspectable, diffable, resumable.

---

## Roadmap

Eight branches, six gates. Each phase merges into the integration branch via PR; the PR is
the gate review surface. Full protocol in `docs/BRANCHING.md`.

| Phase | Delivers | Gate |
|---|---|---|
| **0 — Foundations** | Repo skeleton, Deck IR, provider abstraction, orchestrator, **three de-risking spikes** | **GATE 0** — go/no-go on the entire rendering strategy |
| **1 — Ingestion & knowledge** | Docling → document store with provenance; knowledge folders; A4 isolation; retrieval | GATE 1a — owner spot-checks 10 citations against source PDFs |
| **2a — Planning & outline** | `autodeck plan` session → signed DeckBrief with **evidence-gap check**; outline agent → IR skeleton | GATE 1 — outline approved *against the brief* |
| **2b — Content & validation** | Content agent within budgets; numeric + framing linters; independent validator; audit report | GATE 2 — claims table approved |
| **3a — Design system** | Theme/master, `layout_kit`, 15 components, charts, diagram engine, icons, header voice, grammar lints | internal review |
| **3b — Renderer & QA** | `renderer.py`, deterministic QA, bounded aesthetic loop, art direction, post-render re-lint | GATE 3 — owner verifies editability **in PowerPoint** |
| **4 — Consulting workflow** | Client onboarding, reference-deck ingestion, end-to-end build, multi-client regression | GATE 4 — a real deck used for real |
| **5 — Evals & hardening** | Eval harness, regression CI, adversarial tests | ongoing |

**Phase 2b is the heart of the system.** Its milestone is a *correct, fully-audited,
deliberately ugly* deck. Ugly is fine; wrong is not.

---

## Model routing

Build-time work is tiered, and the tiering is structural rather than left to per-task
judgment — every task row in every phase brief carries a `model` tag, and path guardrails
override tags. Full policy in `docs/MODEL_ROUTING.md`.

| Tier | Owns |
|---|---|
| **Opus** | Architecture and contracts — IR schema, provider protocol, all of `prompts/`, everything under `autodeck/audit/`, spike design, gate reviews, decisions, handovers |
| **Sonnet** | Implementation against a settled interface — the bulk of the build |
| **Haiku** | Mechanical high-volume work — fixtures, golden files, batch refactors, eval runs |

Guardrails: Haiku never edits `autodeck/ir/`, `autodeck/audit/`, `prompts/`, `DECISIONS.md`,
or `docs/handovers/`. Sonnet does not author prompts or the IR schema. Tasks escalate a
tier when they turn out to touch an interface, an invariant, or a locked decision;
established patterns de-escalate.

Within Sonnet work, the **docstring-delegation pattern** applies: Sonnet writes the
signature, docstring, and contract; Haiku fills the body — scoped by how completely the
docstring specifies behaviour, never by function length.

### Runtime bindings — three environments

AutoDeck's **own** model bindings are environment-tiered (decision B8):

| Env | Providers | Purpose |
|---|---|---|
| `dev` | Gemini + Groq (free tiers) | Day-to-day build and iteration |
| `sit` | Claude | Pre-production verification |
| `prod` | Claude | Real client deliverables |

**A3 and A8 are model-sensitive**, so accuracy measured on `dev` does not transfer to
production — headline eval metrics must be measured on `sit`. The deterministic invariants
(A1, A2, A4, A5, A6) are code and transfer unchanged. Bindings live in
`config/models.yaml`, never in code; the manifest records the environment and every
resolved model ID, so a dev-built deck is never mistaken for a production one.

---

## Working on this

**Resuming after a context reset — read in this order:**

1. `README.md` — this file.
2. `STATUS.md` — where the build is.
3. `docs/handovers/PHASE-<latest>.md` — what the last phase left behind.
4. `docs/phases/PHASE-<current>.md` — the task list.

If those four do not let you start work, the handover was inadequate; fix the template
rather than working around it.

**Standing rules** (plan §0):

- Work phase by phase, task by task. Every task lands with tests.
- **Stop at every gate and wait for explicit human approval. Do not self-approve.**
- Never weaken an accuracy invariant. Surface conflicts instead.
- All LLM prompts live in versioned files under `prompts/` — never inline in Python.
  A prompt change is its own commit with rationale.
- Maintain `DECISIONS.md` and `CHANGELOG.md`. When the plan is ambiguous, make the
  smallest reasonable decision, record it, and flag it in the phase handover.
- Engineering standards: Python 3.11+, pydantic v2, typer, pytest, full type hints checked
  with pyright, ruff for lint and format. No Streamlit. No notebooks in the package.
