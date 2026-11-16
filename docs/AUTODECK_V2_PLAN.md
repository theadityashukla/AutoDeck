# AutoDeck v2 — Implementation Plan

**Audience of this document:** an implementing AI agent (Claude Opus in Claude Code) working with a human owner (Aditya).
**Primary use case:** consulting deliverables. **The overriding design value is accuracy** — every factual statement on a slide must be traceable, verified, and auditable. Beauty is the second priority; speed is third.

---

## 0. How to use this document (instructions to the implementing agent)

1. Read this entire document before writing any code.
2. Work strictly phase by phase (Section 7). Within a phase, work task by task; every task lands with tests.
3. **Stop at every review gate** (marked `GATE`) and wait for explicit human approval before continuing. Do not self-approve.
4. Never weaken an accuracy invariant (Section 3) to make a test pass or a demo work. If an invariant blocks progress, surface the conflict to the human and propose options.
5. Keep all LLM prompts in versioned files under `prompts/` — never inline in Python. Any prompt change is a commit with rationale.
6. Maintain `DECISIONS.md` (append-only decision log) and `CHANGELOG.md` at repo root. When this plan is ambiguous, make the smallest reasonable decision, record it, and flag it in your phase summary.
7. The v1 repository (`https://github.com/theadityashukla/AutoDeck`) is reference material. Salvage per Section 8; do not import v1 code wholesale.
8. Engineering standards: Python 3.11+, `pydantic` v2 for all data models, `typer` for CLI, `pytest`, full type hints checked with `pyright`, `ruff` for lint/format. No Streamlit. No notebooks in the package.

---

## 1. Background and diagnosis

### 1.1 What v1 was

AutoDeck v1 (2025) was a Streamlit multi-agent system: PyMuPDF parsing → agentic chunking (local Gemma 3 12B via MLX) → ChromaDB RAG → outline agent → content agent → python-pptx rendering into template placeholders → a DesignAgent that screenshotted slides, critiqued them with Gemini Vision, and applied fixes from a bounded action catalog, looping until a target score.

### 1.2 Why it stalled (root-cause diagnosis)

Most v1 engineering pain (TextFitter EMU math, overflow whack-a-mole, "innocent until proven guilty" vision prompts, the fix loop itself) traces to one cause: **python-pptx has no layout engine**, so v1 was hand-building one and using a vision model as a measuring instrument. Secondary causes: the local MLX stack (quality and platform lock-in), Streamlit state management, and a small layout vocabulary (~3 layouts) that made every deck look the same.

### 1.3 What v2 changes

- A **Deck IR** (intermediate representation) becomes the central, versioned, auditable artifact. Agents read/write IR; renderers consume it.
- **Docling** replaces PyMuPDF + agentic chunking, and its element-level provenance (page + bounding box) powers claim citations.
- **Constraint-first layout**: components declare text budgets computed from real font metrics *before* content is written. Overflow becomes rare by construction, and residual geometry checks are deterministic arithmetic, not vision-model judgment.
- **Native-only rendering** for fully editable PPTX: components are designed *and* rendered directly in the final medium — python-pptx renderers over a real OOXML theme/slide-master, authored against a fast render-preview loop (`layout_kit` + headless LibreOffice PNG gallery). No HTML→PPTX conversion exists anywhere in the system. Vision models critique true renders only, with a bounded, IR-level action space.
- **Cloud-only models** behind a provider abstraction (Gemini first, Claude second). The MLX/Gemma layer is deleted.
- **Two-tier knowledge folders** (project + client), curated markdown loaded fully into context (OKF-style), with retrieval reserved for large paper corpora.
- A **validation and audit subsystem** is promoted from afterthought to load-bearing wall (Section 6.10).

---

## 2. Locked decisions (do not relitigate without human sign-off)

| # | Decision | Rationale |
|---|---|---|
| D1 | Deliverables are **fully editable native PPTX** built on a real slide master/theme XML | Consulting clients reuse and extend decks; theme colors/fonts must appear in PowerPoint's own UI |
| D2 | **Cloud APIs for everything**; no local models | Removes MLX complexity; pipeline runs anywhere (laptop, container, CI) |
| D3 | Ingestion via **Docling**; provenance (page, bbox) preserved end to end | Serves auditability directly |
| D4 | **Deck IR** is the single source of truth; renderers are downstream | Auditability, swappability, human review on diffs |
| D5 | **PPTX is the medium end to end**: components are designed *and* rendered natively (python-pptx + `layout_kit`); **no HTML→PPTX conversion exists anywhere**, design-time or runtime | Conversion ports are where fidelity dies (owner's documented experience); designing in the final format makes the preview the truth |
| D6 | Provider abstraction with structured outputs; **Gemini to start, Claude added** behind same interface | Model mobility; judgment-heavy steps benefit most from swaps |
| D7 | **CLI/pipeline-first, headless core**; thin review UI deferred | v1's Streamlit state machine was a documented cost; headless enables automation |
| D8 | Knowledge = **curated markdown folders** (project base + client overlay) loaded fully; retrieval only for paper corpora | Google OKF-style curated context beats blind chunk search for stable knowledge |
| D9 | **Accuracy invariants are blocking**, not advisory | Consulting use case |
| D10 | Charts are **native, editable PowerPoint charts** with data provenance; no pasted chart screenshots | Clients restyle charts; screenshots are the #1 edit request |
| D11 | Icons are **vectors end to end**: rendered into PPTX as native DrawingML shapes, theme-recolorable; raster icons forbidden | Icons are not pictures — clients recolor, scale, and restyle them |
| D12 | Header voice is a **learnable per-client style profile**, switchable per deck; headers containing facts are claims (A1–A3 apply) | Talking headers carry the argument; they are the most-read text in the deck |
| D13 | Text/icon/diagram **balance is enforced by deterministic grammar lints**, not model taste | Prevents both text walls and "hieroglyphics"; consistent with accuracy-first posture |

---

## 3. Accuracy invariants (the contract — enforce everywhere)

These are hard requirements. Code, prompts, tests, and CI must enforce them. Every phase's acceptance criteria implicitly include "no invariant violated."

**A1 — Universal citation.** Every factual assertion in rendered slide content or speaker notes carries ≥1 citation resolving to a source span: `(doc_id, page, bbox, verbatim_quote, quote_sha256)`. Blocks are typed; only `framing` blocks (see A5) are exempt.

**A2 — Numbers are copied or derived, never invented.** Every number, percentage, unit, and date on a slide must trace to a cited source span — either directly, or through a declared **derivation**. Derivations are first-class, not an exception: the content agent is free to compute percentages, deltas, growth rates, ratios, and unit conversions from cited raw numbers, provided the IR records the formula and the cited inputs. The deterministic **numeric linter** then (a) extracts all numerals from rendered content, (b) matches each against a cited span or a derivation result (with a unit/format normalization table: "3.2M" ↔ "3,200,000", "%" ↔ "percent", locale decimal separators), and (c) **re-executes every derivation formula** to confirm the arithmetic. Zero unmatched numerals to pass; the audit report shows the working for every derived figure.

**A3 — Blocking validation.** Every claim gets a verdict: `supported | partially_supported | unsupported | contradicted`. A deck cannot reach final render while any block is `unsupported` or `contradicted`; such blocks must be corrected, retyped as `framing` (only if genuinely non-factual), or removed. The validator re-retrieves independently — it checks the cited span *and* searches the corpus for contradicting spans; it never merely trusts the writer's citation.

**A4 — Client isolation.** A build loads exactly one client namespace. Any cross-client reference in context assembly is a build **error**, not a warning. Client folder contents never enter prompts for other clients' builds. Enforced in the context assembler with tests.

**A5 — Fact/framing separation.** Value-proposition and positioning language from client knowledge is typed `framing`. Framing blocks are citation-exempt but must pass a deterministic "no fabricated fact" lint: no numerals, no named studies/sources, no comparative superlatives with factual content ("proven", "clinically shown"). Violations demote the block to `claim` type, which then requires citation.

**A6 — Reproducibility and audit.** Every final deck ships with: (a) the frozen IR, (b) an **audit report** (claims table: slide → claim → verdict → source doc/page → verbatim quote), (c) a build manifest (model IDs and versions, prompt file hashes, knowledge folder git commit, component library version). Same manifest + IR must re-render byte-comparable output (excluding timestamps).

**A7 — Human gates.** Four mandatory approvals per deck: planning brief (6.13), outline (IR skeleton), post-validation (claims table), final render. The pipeline never auto-approves.

**A8 — Honest uncertainty.** Where sources conflict or evidence is `partially_supported`, the content agent must hedge in the slide text or notes ("reported in one study", "estimates range from…") — never average, round, or silently pick one. Conflicts appear in the audit report.

---

## 4. Target architecture

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

All intermediate artifacts (IR versions, verdicts, renders) are files on disk under `runs/<run_id>/` — inspectable, diffable, resumable.

---

## 5. Repository layout

```
autodeck/
├── DECISIONS.md                # append-only decision log
├── CHANGELOG.md
├── pyproject.toml
├── prompts/                    # ALL llm prompts, versioned, one file each
│   ├── planner.md
│   ├── outline.md
│   ├── content.md
│   ├── validation.md
│   ├── art_direction.md
│   └── aesthetic_critique.md
├── autodeck/
│   ├── ir/                     # Deck IR: pydantic models + schema + versioning
│   │   ├── models.py           # Deck, Slide, Block, Claim, Citation, Derivation, ChartSpec, DeckBrief
│   │   ├── schema.py           # JSON schema export for LLM structured output
│   │   └── store.py            # load/save/version IR under runs/<run_id>/
│   ├── providers/              # model abstraction (D6)
│   │   ├── base.py             # Provider protocol: complete(), complete_structured(), vision()
│   │   ├── gemini.py
│   │   ├── claude.py
│   │   └── registry.py         # per-role model binding from config
│   ├── ingest/                 # Docling pipeline (D3)
│   │   ├── docling_runner.py
│   │   ├── deck_ingest.py      # reference PPTX ingestion → profiles (6.12)
│   │   ├── document_store.py   # elements + provenance, persisted
│   │   └── provenance.py       # (doc_id, page, bbox, quote, sha256) helpers
│   ├── knowledge/              # two-tier folders (D8)
│   │   ├── loader.py           # load + validate folder structure
│   │   ├── context_assembler.py# build prompt context; ENFORCES A4 isolation
│   │   └── update_proposer.py  # post-engagement diff proposals (human-approved)
│   ├── retrieval/              # hybrid search over corpus (paper long-tail only)
│   │   └── hybrid.py           # BM25 + embeddings; returns spans WITH provenance
│   ├── agents/
│   │   ├── planner.py          # interactive planning session → DeckBrief (6.13)
│   │   ├── outline.py
│   │   ├── content.py          # writes within component budgets (Section 6.7)
│   │   ├── validation.py       # A3: independent re-retrieval + verdicts
│   │   └── art_direction.py    # deck-level rhythm and layout assignment
│   ├── design/
│   │   ├── theme/              # OOXML theme + master generation (D1)
│   │   │   ├── extract.py      # tokens from client brand assets / past decks
│   │   │   ├── tokens.py       # DesignTokens model (palette, type, spacing, radii)
│   │   │   └── master_builder.py # write theme XML + slide masters into template
│   │   ├── components/         # THE layout vocabulary (D5)
│   │   │   ├── catalog.py      # registry: name → role → slots → budgets → renderer
│   │   │   ├── renderers/      # python-pptx renderer per component, authored natively
│   │   │   └── previews/       # golden rendered PNGs per component (design artifact of record)
│   │   ├── layout_kit.py       # expressive layout helpers over python-pptx: stacks, grids, baseline spacing
│   │   ├── headers/            # HeaderStyleProfile: learn/apply/switch header voice (6.11.1)
│   │   ├── icons/              # semantic icon library + SVG→DrawingML converter (6.11.3)
│   │   ├── diagrams.py         # DiagramSpec → native shapes + connectors (6.11.2)
│   │   ├── grammar.py          # deterministic text/icon/diagram balance lints (6.11.2)
│   │   ├── budgets.py          # font-metric text budget computation (Section 6.7)
│   │   └── charts.py           # native editable PPTX charts from ChartSpec (D10)
│   ├── render/
│   │   ├── renderer.py         # IR → deck.pptx via theme + component renderers
│   │   └── qa/
│   │       ├── deterministic.py# geometry/contrast/margin/font-min checks
│   │       ├── libreoffice.py  # headless render to images
│   │       └── aesthetic.py    # vision critique → bounded IR actions
│   ├── audit/
│   │   ├── numeric_linter.py   # A2
│   │   ├── framing_linter.py   # A5
│   │   ├── report.py           # A6 audit report generation
│   │   └── manifest.py         # A6 build manifest
│   ├── pipeline/
│   │   └── orchestrator.py     # phase runner, gates, resumability
│   └── cli.py                  # typer entrypoints
├── fonts/                      # licensed font files for metrics + embedding
├── runs/                       # per-build artifacts (gitignored)
├── evals/                      # golden papers + reference decks + rubric (Phase 5)
└── tests/
```

---

## 6. Component specifications

### 6.1 Deck IR (build first — everything depends on it)

Pydantic v2 models. Sketch (implementing agent finalizes fields):

```python
class Citation(BaseModel):
    doc_id: str
    page: int
    bbox: tuple[float, float, float, float]
    quote: str                      # verbatim from source
    quote_sha256: str               # hash of quote; verifies against store
    retrieved_by: Literal["writer", "validator"]

class Derivation(BaseModel):        # for A2 derived numbers
    formula: str                    # e.g. "(a - b) / b * 100"
    inputs: dict[str, Citation]     # each input cited
    result: float
    unit: str

class Claim(BaseModel):
    text: str
    citations: list[Citation]
    derivation: Derivation | None = None
    verdict: Literal["unverified","supported","partially_supported",
                     "unsupported","contradicted"] = "unverified"
    verdict_notes: str | None = None
    contradicting_spans: list[Citation] = []

class Block(BaseModel):
    id: str
    kind: Literal["claim","framing","chart","figure","section_header",
                  "diagram","icon"]
    slot: str                       # which component slot this fills
    text: str | None = None         # for claim/framing/section_header
    claim: Claim | None = None      # when kind == claim
    chart: ChartSpec | None = None  # when kind == chart
    figure_ref: str | None = None   # when kind == figure (asset id + citation)
    diagram: DiagramSpec | None = None  # when kind == diagram (6.11.2)
    icon: IconRef | None = None     # when kind == icon: {concept, glyph_id, color_token}

class Slide(BaseModel):
    id: str
    narrative_role: str             # e.g. "problem","evidence","big_number"...
    component: str                  # catalog component name
    blocks: list[Block]
    speaker_notes: list[Block] = [] # notes are ALSO claims/framing, A1 applies

class Deck(BaseModel):
    run_id: str
    project: str
    client: str
    audience: str
    version: int
    slides: list[Slide]
    theme_ref: str
    component_lib_version: str
```

Requirements: JSON-schema export for structured LLM output; `store.py` saves each version as `runs/<id>/ir/v<N>.json` and supports diffing two versions for gate review.

### 6.2 Provider abstraction

`Provider` protocol: `complete_structured(prompt, schema, ...) -> validated pydantic object` (enforce schema; retry-with-repair on invalid JSON up to N times, then hard-fail — never silently drop fields). `vision(images, prompt, schema)`. Per-role binding in config, e.g.:

```
roles:
  outline:     {provider: gemini, model: <pro-tier>}
  content:     {provider: gemini, model: <pro-tier>}
  validation:  {provider: claude, model: <opus/strong>}   # judgment-critical
  aesthetic:   {provider: claude, model: <vision-strong>}
  ingest_vlm:  {provider: gemini, model: <flash-tier>}     # figure description
```

Do not hardcode model version strings in code; read from config, record resolved IDs in the manifest (A6). At implementation time, look up current model identifiers rather than assuming.

### 6.3 Ingestion (Docling)

- Run Docling to produce a structured document: reading-order text, tables as tables, figures with captions, formulas — each element with page + bbox provenance.
- Persist to `document_store`: every element keyed by `doc_id`, with provenance and a normalized text form. Store the verbatim text so citations can be hash-verified (A1).
- Figure/chart images extracted with provenance; VLM (via provider `ingest_vlm`) generates a description stored as element metadata for retrieval — **descriptions are metadata, never a citable source of fact**.
- Tables: preserve cell structure so the content agent can propose `ChartSpec`s from real data (D10) with the table cell as the citation.
- Keep a Grobid adapter stub *only* if rigorous bibliographic metadata is later needed; not in the critical path.

### 6.4 Knowledge folders

Structure:

```
knowledge/
  projects/<project>/
    project.md          # canonical description; each factual line cites a paper
    claims.md           # curated, pre-verified claim library (text + citation)
    papers/*.pdf        # source corpus → document_store
    assets/             # figures approved for reuse, with provenance
  clients/<client>/
    client.md           # context, priorities, sensitivities, vocabulary do/don't
    value_prop.md       # framing for THIS client (typed framing at load)
    style/headers.yaml  # HeaderStyleProfile (6.11.1) — learned header voice
    theme/tokens.json   # design tokens
    theme/assets/       # logo, fonts, brand refs
    theme/icons/        # (optional) client-supplied icon set, SVG source (6.11.3)
    theme/template.pptx # (optional) client's corporate template
    decks/              # past client decks → reference-deck ingestion (6.12); teach style/structure, never facts
    engagements/*.md
```

- `loader.py` validates structure and required files; fails loudly on malformed folders.
- `context_assembler.py` loads curated md **fully** into context (OKF principle) and **enforces A4**: one client namespace per build; assembling any other client's content raises `ClientIsolationError`. Unit-tested with a two-client fixture.
- `claims.md` is a **pre-verified claim cache**: claims used from it still get re-validated (A3) but start from a known-good citation, improving accuracy and speed.
- `update_proposer.py`: after an engagement, propose additions (new objections, refined framing) as a git diff for human approval. Never auto-writes.

### 6.5 Retrieval (long-tail only)

Hybrid BM25 + embedding search over the Docling corpus, used when the curated claim library lacks coverage. **Every returned chunk carries provenance**; a chunk without resolvable provenance is unusable for a citation (A1). Retrieval is a fallback, not the primary knowledge path.

### 6.6 Component catalog (the design vocabulary)

Target ~15 components in v1, ~25–30 by Phase 4. Each entry:

```
name, narrative_role(s), slots[{name, type, budget_ref}], 
renderer, golden_preview_path, theme_token_usage
```

First 15 (initial catalog — refine in Phase 3):
title, section_divider, agenda, big_number, two_column_compare, quote,
bullets_supporting (3–5 claims), evidence_with_figure, framework_diagram,
timeline, data_card_grid, chart_focus, before_after, callout_takeaway,
closing_cta.

Each component is **authored directly in the final medium** (D5): a python-pptx renderer written against `layout_kit` (a small internal layout API — stacks, grids, gutters, baseline spacing, token-driven type scale — that gives component code the expressiveness CSS used to provide, without introducing a second medium). The design loop is: edit code → render → headless LibreOffice → PNG preview gallery → adjust. The committed golden preview PNG is the design artifact of record, and the vision critique always judges true renders, never mock-ups. All renderers draw exclusively from DesignTokens. Diagram-led components (`framework_diagram`, `timeline`, process layouts) delegate their geometry to the diagram engine (6.11.2) rather than carrying bespoke renderer code.

**Alternatives considered and rejected (do not revisit):** (a) runtime HTML→PPTX conversion — produces low-fidelity "nonsense ports" (owner's direct experience with such pipelines); (b) design-time HTML references with one-time hand-porting — a proxy medium invites designs the target format cannot honor; (c) PptxGenJS or other JS generators — same category of tool as python-pptx in another language, changes nothing about fidelity; (d) Office.js add-ins or macro-enabled files — scripting lives in the PowerPoint application or requires .pptm; a .pptx deliverable is static XML and contains no executable code, and client IT policies make macro files a non-starter. Deliverables are plain, script-free .pptx.

### 6.7 Text budgets (kills v1's overflow problem)

`budgets.py`: given the licensed TTF, a slot's box width/height, font size, and line spacing, measure wrapped text height accurately (real glyph metrics, e.g. via `fonttools`/`Pillow` measurement, not character-count heuristics). Each component slot declares a budget: max chars/lines/words that fit at the theme's type scale. **The content agent receives budgets as hard constraints in its prompt** and writes to fit. Post-write, a deterministic budget check rejects overflowing blocks before render. This makes overflow rare by construction; the render-time geometry check (6.9) is the safety net, not the primary mechanism.

### 6.8 Theme & master (native editability)

`design/theme/`: extract tokens from brand assets/past decks (or accept `tokens.json`); write **real OOXML theme XML** (color scheme, font scheme) and **slide masters/layouts** into the template so edits and new slides in PowerPoint inherit the look (D1). Two modes: (a) client supplies corporate template → use their masters for title/divider, register content components against their theme; (b) brand assets only → generate clean master from tokens. **Font spike required in Phase 0**: confirm brand-font availability for measurement + embedding + fallback stacks + licensing.

### 6.9 Rendering + QA

- `renderer.py`: IR → pptx using theme master + per-component native renderers + native charts.
- `qa/deterministic.py`: from IR geometry + rendered shapes, check overlap, margin/safe-area, min font size, contrast ratio (WCAG-style) — pure arithmetic, no model. Any failure is fixable via token/slot adjustment.
- `qa/libreoffice.py`: headless LibreOffice renders slides to images for the aesthetic pass.
- `qa/aesthetic.py`: vision model reviews rendered images for hierarchy, balance, consistency, "looks cheap." Output is a **bounded set of IR-level actions** (adjust type scale, swap component, change emphasis, rebalance columns) — never free-form geometry. Loop with max iterations and a target; **the aesthetic loop may never edit claim text or citations** (A1/A3 protected).

### 6.10 Audit subsystem (load-bearing)

- `numeric_linter.py` (A2): extract all numerals from rendered content + notes; normalize; match to cited spans or declared derivations; re-execute derivation formulas to confirm the arithmetic; zero unmatched to pass.
- `framing_linter.py` (A5): ensure framing blocks contain no smuggled facts; demote violators to `claim`.
- `validation` agent (A3): independent verdict per claim via re-retrieval + contradiction search.
- `report.py` (A6): audit report — per slide, a claims table (claim → verdict → doc/page → verbatim quote → any contradictions), plus a conflicts section (A8). Export md + pdf.
- `manifest.py` (A6): model IDs/versions, prompt hashes, knowledge git commit, component lib version, IR hash. Enables reproducibility check.

### 6.11 Visual grammar: headers, icons, diagrams (the beyond-template layer)

A template supplies a background and a logo; this layer supplies authorship. It is what separates a generated deck from a consultant's deck, and it has three subsystems.

#### 6.11.1 Header voice system (`design/headers/`)

In consulting decks the headers *are* the argument — the horizontal-story test is that reading only the headers, in order, delivers the entire storyline. Headers therefore get their own model rather than being an afterthought of the content agent.

`HeaderStyleProfile` (YAML), one per client plus a personal default for the owner:

```yaml
style: assertion            # assertion | topical | question_led | metric_led
case: sentence
length_words: [8, 14]
voice: active, present-tense, claim-first
horizontal_story: true      # headers alone must read as a coherent argument
exemplars: [...]            # real approved headers from delivered decks
banned_patterns: ["Overview", "Background", "Introduction", "Next steps"]
```

- **Precedence:** per-deck flag (`build --header-style question_led`) > client profile > owner default. Switching styles is a one-flag operation.
- **Learning loop:** onboarding parses the client's past decks (extract every title via python-pptx), classifies and clusters the style, derives the initial profile. After each delivered deck, *approved* headers are appended to `exemplars` through `update_proposer` — a human-approved diff, never silent drift (consistent with A7).
- **Horizontal-flow QA:** after content generation, a check reads the header sequence in isolation and flags storyline breaks, topical placeholders from `banned_patterns`, and repeated syntactic structure on consecutive slides.
- **Accuracy:** headers containing factual assertions are `claim` blocks — A1–A3 apply to titles (D12). Titles are the most-read text in the deck; they get the strictest treatment, not the loosest.

#### 6.11.2 Visual grammar & diagram engine (`design/diagrams.py`, `design/grammar.py`)

Balance principle: **text carries the meaning, icons index it, diagrams carry structure.** An icon never bears meaning alone — deleting every icon from a well-balanced slide must lose no information, only scanning speed. This redundancy rule is what prevents both text walls and hieroglyphics.

- **Communication mode** is an explicit per-slide decision made by the art-direction pass and overridable by the human: `text_led | icon_anchored | diagram_led`, chosen from the shape of the content (process → diagram-led; capability pillars → icon-anchored; nuanced argument → text-led with strong hierarchy).
- **Grammar lints** (`grammar.py`, deterministic and blocking, like budgets): every icon adjacent to a text label; word budgets per mode (icon_anchored ≤ ~50, diagram_led ≤ ~60, text_led ≤ ~90); ≤ 5–7 distinct concepts per slide; ≤ 1 diagram per slide; no icon + chart + diagram pileups; one icon family, stroke weight, and size scale per deck (D13). Taste is encoded as checkable rules wherever possible; the vision model judges only what rules cannot reach.
- **DiagramSpec** — the ChartSpec pattern applied to concepts instead of data. Typed, parameterized diagram schemas: `process_flow` (with decision branches), `cycle`, `funnel`, `pyramid`, `two_by_two`, `hub_spoke`, `layered_stack`. Rendered as **native PowerPoint shapes and connectors**, theme-colored, fully editable. Node labels and support lines obey text budgets (6.7); factual nodes carry citations (A1). This is the mechanism by which "how the algorithm works" becomes a slide instead of a paragraph or a pasted screenshot. The relationship→geometry catalog in the owner's **`slide-geometry` skill** is the seed source for DiagramSpec types, art-direction selection rules, and label-placement conventions — keep the two in sync as either evolves.

#### 6.11.3 Icon system (`design/icons/`) — icons are vectors, not pictures

- **Curated semantic library:** one permissively licensed family (Lucide/Phosphor/Tabler-class — verify current licenses at implementation time) as the default, stored as SVG source with semantic tags so an icon-picker step maps concept → glyph deliberately. Client-supplied icon sets register per client under `theme/icons/` and take precedence.
- **Native conversion (the load-bearing piece):** SVG paths are converted to DrawingML freeform shapes (`custGeom`) at render time, so icons land in the PPTX as genuine PowerPoint shapes — theme-recolorable, losslessly scalable, individually selectable (D11). Raster icons are forbidden. Fallback for unsupported SVG edge cases (complex arcs, fill rules): OOXML native SVG embedding (`svgBlip` with PNG fallback), which modern PowerPoint can convert to shapes on demand.
- **IR representation:** `icon` blocks carry `{concept, glyph_id, color_token}` — icon choices are reviewable and diffable like everything else. The aesthetic loop may swap a glyph or its color token, but (as everywhere) never touches text or citations.
- **Phase 0 spike:** one icon must round-trip SVG → `custGeom` → open in PowerPoint as a recolorable native shape before Phase 3 depends on the converter.

### 6.12 Reference deck ingestion (`ingest/deck_ingest.py`)

Existing decks — the owner's or the client's — are a first-class knowledge source. Given a PPTX, parse it (python-pptx: titles, body text, speaker notes, shape geometry, images, fonts and colors in use) and derive four profiles:

- **StorylineProfile** — the narrative arc as a sequence of inferred slide roles (e.g. context → problem → evidence → implication → ask), plus section rhythm and density patterns. Used to seed outlines: `plan --like reference.pptx` tells the planner and outline agent to flow like that deck.
- **HeaderStyleProfile** (6.11.1) — derived from the titles; this replaces the narrower "parse past deck titles" mechanic and is the canonical path for it.
- **VoiceProfile** — register, sentence length, terminology used and avoided; augments the vocabulary guidance in `client.md`.
- **DesignProfile** — observed layouts mapped to the nearest catalog components, spacing and color habits; informs theme extraction (6.8) and art-direction defaults. Recurring layouts the catalog cannot express are flagged as candidates for new components (catalog gap analysis).

**Accuracy rule:** reference decks teach *style and structure, never truth*. Any factual content lifted or paraphrased from a past deck is still a `claim` requiring a source citation from the corpus (A1) — a slide that shipped before is not evidence that it was ever right.

### 6.13 Planning agent & DeckBrief (`agents/planner.py`)

Before any outline is generated, an interactive planning session (`autodeck plan`, a conversational CLI session per D7) between the human and the planning agent produces a **DeckBrief** — a versioned artifact in the run:

```yaml
objective: ...              # the decision or action this deck should produce
audience: ...
key_messages: [...]         # the argument, in the human's words
must_include: [...]         # claims/figures/topics that must appear
must_avoid: [...]           # sensitivities, banned framings
length_target: ...
header_style: ...           # optional override (6.11.1)
layout_pins: [...]          # human-pinned communication modes/components per message
reference_deck: ...         # optional, routes through 6.12
open_risks: [...]           # evidence gaps acknowledged at planning time
```

- The agent interviews, proposes a storyline, and iterates; the session ends only on explicit human sign-off of `brief.yaml` — this is the **first of the four approvals (A7)**. The transcript is stored in the run for auditability.
- **Evidence-gap check (accuracy-critical):** during the session, each proposed key message is probed against `claims.md` and the corpus. Messages without support are flagged *in conversation* — "no source currently supports X: soften it, add a source, or drop it?" — so evidence gaps surface before a single slide is written, not at validation. Gaps the human accepts anyway are recorded in `open_risks` and resurface in the audit report.
- Content **and layout** are both in scope: the human can pin a communication mode or component to a message ("the algorithm gets a diagram-led slide"); pins are honored by the outline agent and art direction, and deviations require flagging at GATE 1.
- The outline agent consumes brief + knowledge folder; GATE 1 review checks the outline *against the brief*, which gives that gate objective criteria instead of vibes.

---

## 7. Phased roadmap

Each phase lists **tasks**, an **accuracy focus**, a **milestone**, and its **exit GATE**. Do not enter the next phase until the gate is approved.

### Phase 0 — Foundations & de-risking (2–3 weeks)

The riskiest assumptions live here; prove them before building on them.

1. Repo skeleton (Section 5), `pyproject.toml`, ruff/pyright/pytest CI, `DECISIONS.md`.
2. **Deck IR v1** models + JSON-schema export + `store.py` with versioning and diff. Golden-file tests round-tripping a hand-authored sample IR.
3. **Provider abstraction** with `complete_structured` schema enforcement + repair-retry; Gemini and Claude adapters; role registry from config. Test structured output against a trivial schema on both providers.
4. **Font/theme spike (highest risk):** take one real brand, extract tokens, write theme XML + one slide master, confirm PowerPoint shows the palette/fonts natively; confirm a TTF measures correctly in `budgets.py`; confirm embedding + fallback. Record findings in `DECISIONS.md`.
5. **Native design spike (highest risk):** build the minimal design loop — `layout_kit` v0 (stacks, grids, baseline spacing over python-pptx) plus a watch-render preview gallery (render → headless LibreOffice → PNG) — and use it to design **two** components (`big_number`, `two_column_compare`) to a high visual bar, directly in the final medium. **This proves D5** — that beauty is achievable authoring natively and that iteration is fast enough to sustain a 15-component library. If either fails, escalate before Phase 3.
6. **Icon vector spike (new):** convert one library SVG icon to a DrawingML freeform shape (`custGeom`), place it in a themed PPTX, and confirm in PowerPoint that it is selectable, losslessly scalable, and recolorable from the theme palette. **This proves D11.** Document converter edge cases (arcs, compound paths, fill rules) in `DECISIONS.md`.
7. Orchestrator skeleton with run dirs, resumability, and gate stubs.

**Accuracy focus:** IR carries citations structurally from day one; schema forbids a `claim` block without ≥1 citation.
**Milestone:** empty pipeline runs end to end on a stub, producing a versioned IR and a (blank) manifest.
**GATE 0:** human reviews the three spike outputs (theme, natively designed components, icon shape) and signs off that native authoring can be beautiful and vector-true. *This is the go/no-go for the whole rendering strategy.*

### Phase 1 — Ingestion & knowledge (3–4 weeks)

1. Docling runner → document_store with provenance; hash-verifiable verbatim text (A1).
2. Figure/table extraction; VLM figure descriptions as metadata; tables preserved for charts.
3. Knowledge folder structure; `loader.py` validation; **`context_assembler.py` with A4 isolation enforced and tested** (two-client fixture must raise on cross-load).
4. `claims.md` pre-verified claim cache format + loader.
5. Hybrid retrieval with provenance-carrying results; reject provenance-less chunks.
6. Seed with **one real project + one real (or anonymized) client**.

**Accuracy focus:** provenance is unbroken from PDF element → store → any citation; hash check catches drift.
**Milestone:** ask a factual question against the corpus; get answers with correct page/bbox citations that hash-verify.
**GATE 1a:** human spot-checks 10 citations against source PDFs — all must resolve exactly.

### Phase 2 — Narrative, content & validation (4–5 weeks) — *accuracy core*

This is the heart of the consulting use case. Spend the time here.

1. **Planning agent (6.13):** interactive `autodeck plan` session → signed-off `DeckBrief`, including the evidence-gap check against `claims.md` + corpus and layout pins. Brief sign-off is the first of the four approvals (A7).
2. **Outline agent:** consumes DeckBrief + knowledge folder + audience → IR skeleton (roles, component assignments, slide intents). No prose yet.
3. **GATE 1 (outline):** human approves the skeleton *against the brief*.
4. **Content agent:** for each slide, writes `claim`/`framing`/`chart` blocks **within component budgets (6.7)**, each claim with a citation drawn from `claims.md` or retrieval; derived numbers declared as derivations (A2). Speaker notes are blocks too (A1 applies). Honest-uncertainty behavior (A8) prompted and tested.
5. **Numeric linter (A2, including derivation re-execution)** and **framing linter (A5)** wired in as blocking pre-validation checks.
6. **Validation agent (A3):** independent re-retrieval per claim; assigns verdicts; searches for contradicting spans; writes the claims table. Blocks final render on `unsupported`/`contradicted`.
7. **GATE 2 (claims):** human reviews the audit claims table; approves, or sends specific claims back for correction.
8. Audit report + manifest generation (A6); `open_risks` from the brief resurface in the report.

**Accuracy focus:** the entire invariant set (A1–A8) is live and enforced here.
**Milestone:** a **correct, fully-audited, deliberately ugly** deck — every claim verified, every number traced, audit report clean. *Ugly is fine; wrong is not.*
**GATE 2 sign-off** required to proceed.

### Phase 3 — Design system & native rendering (6–7 weeks)

1. Theme/master builder productionized (both onboarding modes, 6.8).
2. First **15 components** authored natively via `layout_kit` against the preview gallery (6.6); budgets declared per slot; golden preview PNG committed per component.
3. Native editable charts from `ChartSpec` with data provenance (D10).
4. **Diagram engine (6.11.2):** DiagramSpec types rendered as native shapes + connectors, theme-colored, budget- and citation-aware. Start with `process_flow`, `two_by_two`, `layered_stack`; add the rest incrementally.
5. **Icon system (6.11.3):** semantic library + picker + SVG→`custGeom` converter productionized from the Phase 0 spike; deck-wide consistency enforcement.
6. **Header voice system (6.11.1):** profile loader, application in content prompts, per-deck style switch, horizontal-flow QA check.
7. **Grammar lints (6.11.2):** communication-mode assignment in art direction + deterministic balance checks wired in as blocking.
8. `renderer.py` IR → pptx.
9. QA: `deterministic.py` (geometry/contrast/margins/min-font), `libreoffice.py` render-to-image, `aesthetic.py` bounded-action critique loop — **forbidden from touching claim text/citations**.
10. Art-direction pass: deck-level rhythm (density variation, section dividers, promote one number/section to `big_number`), component swaps, communication-mode decisions.

**Accuracy focus:** rendering and the aesthetic loop are proven unable to alter verified facts; numeric linter re-runs on final rendered text (post-render, not just pre-render); headers carrying claims are validated like any claim (D12).
**Milestone:** the same Phase 2 deck, now **beautiful, in the client theme, fully editable in PowerPoint** — including at least one native diagram and theme-recolorable icons — audit report still clean.
**GATE 3 (final render):** human approves visual + a final audit pass, and verifies in PowerPoint that a diagram node and an icon can be selected and recolored.

### Phase 4 — Consulting workflow (3–4 weeks)

1. Client onboarding command: extract theme from brand assets/past decks → `tokens.json` + master; register any client-supplied icon set (6.11.3).
2. **Reference deck ingestion (6.12) productionized:** Storyline/Header/Voice/Design profiles derived from past decks during onboarding; `plan --like reference.pptx` outline seeding; catalog gap analysis. (Basic title extraction may land earlier wherever onboarding needs it; the full four-profile derivation lands here.)
3. `build --project P --client C --audience A` end-to-end command with all four approvals (A7).
4. `update_proposer.py`: post-engagement knowledge-diff proposals (human-approved), including approved-header additions to the style profile.
5. Multi-client regression: same project, two clients → correct isolation (A4), correct per-client framing, correct per-client theme. Automated test.
6. Audit report polish (client-presentable PDF).

**Accuracy focus:** A4 isolation and A5 framing correctness proven across real multi-client builds.
**Milestone:** two real client decks from one project, each correct, isolated, on-brand, editable, with clean audit reports.
**GATE 4:** human runs a real consulting deck through the system for actual use.

### Phase 5 — Hardening & evals (ongoing)

1. **Eval harness (`evals/`):** 3–5 golden source papers with reference decks; rubric scoring on **faithfulness, citation coverage, numeric accuracy, contradiction-catch rate, design consistency**, plus two grammar checks: the **headers-only storyline test** (do the titles alone tell the story, in the active profile's voice?) and the **icon-redundancy test** (strip all icons — is any meaning lost?). Faithfulness and numeric accuracy are the headline metrics.
2. Regression suite: every prompt/model change re-runs evals; accuracy metrics must not regress to merge.
3. Adversarial accuracy tests: inject a subtly wrong number, a miscomputed derivation, an unsupported claim, a fact lifted from a reference deck without a corpus source, a cross-client leak, a fabricated study in framing, an unlabeled icon, and a topical placeholder header — the system must catch each.
4. Deferred niceties revisited only now: thin review UI, local-model option (if a client contract ever requires it), performance/parallelism tuning.

**Accuracy focus:** accuracy is measurable and defended by CI, not vibes.

---

## 8. Salvage / retire from v1

**Salvage (as reference, re-implement cleanly):**
- Outline/content prompt logic and the narrative-role thinking.
- Validation agent structure (extend heavily for A3 independent re-retrieval).
- The DesignAgent **action-catalog concept** — reused as the bounded IR-action set for `qa/aesthetic.py`.
- Session/checkpoint instincts → IR versioning + resumable runs.
- Template-integrity learnings → theme/master builder.

**Retire (do not port):**
- TextFitter EMU math → replaced by font-metric budgets (6.7).
- AgenticChunker / vision-chunking → replaced by Docling.
- MLX / Gemma local stack → deleted (D2).
- Streamlit app + session-state machine → replaced by headless CLI (D7).
- DesignAgent geometry-fixing code → replaced by deterministic checks + native components.

---

## 9. Cross-cutting risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Native authoring in python-pptx hits a taste or iteration-speed ceiling (D5) | Components look generic, or design work stalls | **Phase 0 native design spike is go/no-go**; invest early in `layout_kit` + instant preview gallery; vision critique runs on true renders; loose sketches (paper, image, anything) allowed for inspiration but **never converted** — the renderer is the only design artifact |
| Brand font licensing/embedding | Can't match client brand / legal risk | **Phase 0 font spike**; fallback stacks; per-client licensing check in onboarding |
| Validator misses a subtle wrong claim | Accuracy failure in front of client | Independent re-retrieval + contradiction search (A3); adversarial evals (Phase 5); human GATE 2 as backstop |
| Number generated not copied (A2) | Wrong figure on a slide | Deterministic numeric linter, blocking; derivations must show working |
| Cross-client leak (A4) | Confidentiality breach | Hard error in context assembler; multi-client regression test; one namespace per build |
| Docling provenance gaps on messy PDFs | Uncitable content | Reject uncitable content from claims; flag low-provenance docs at ingest for human review |
| SVG→DrawingML converter edge cases (arcs, compound paths, fill rules) | Icons degrade to pictures, breaking D11 | **Phase 0 icon spike**; `svgBlip`+PNG-fallback embedding as the fallback path; constrain default library to stroke-simple glyph families |
| Model API changes (versions/pricing) | Build breaks or drifts | Provider abstraction; model IDs in config + manifest; look up current IDs at implementation time |
| Aesthetic loop edits a fact | Silent accuracy corruption | Loop structurally forbidden from touching claim text/citations; numeric linter re-runs post-render |

---

## 10. Definition of done (v2 MVP)

- `build --project P --client C --audience A` produces: `deck.pptx` (editable, on-brand, beautiful), `audit_report.pdf` (every claim traced), `build_manifest.json` (reproducible).
- All accuracy invariants A1–A8 enforced and covered by tests.
- Decks pass the headers-only storyline test in the active style profile; contain at least one native diagram and themed icons, all selectable and recolorable in PowerPoint (D11–D13).
- Two real client decks from one shared project demonstrate isolation, per-client framing, and per-client theming.
- Eval harness green on faithfulness, citation coverage, and numeric accuracy.
- Four human approvals (planning brief, outline, claims table, final render) operational; no path bypasses them.

---

## 11. Open questions for the human (resolve early)

1. Deployment target for the pipeline — local dev only for now, or containerized for a small team? (Affects Phase 0 CI/packaging.)
2. Which one project + one client seed the build in Phase 1? Real or anonymized client for development?
3. Are brand fonts available/licensed for the seed client, or design against a safe default and swap later?
4. Audit report audience — internal-only, or ever shown to clients? (Affects report polish priority in Phase 4.)
5. Any client with a mandated corporate template we should target as the "mode (a)" reference in Phase 3?

*(These are not blocking to start Phase 0, but answers sharpen Phases 1–4.)*
