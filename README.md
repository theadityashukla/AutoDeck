# AutoDeck

AutoDeck makes consulting decks as native, editable PowerPoint files. This repository holds
two generations of it, side by side:

| | v2 | v3 |
|---|---|---|
| **What it is** | An accuracy-first pipeline. Every factual statement on a slide is traceable to a source passage, checked, and auditable. | A conversational studio. You build a deck by talking to it; the system designs the slides; every change can be undone. Strict traceability is meant to return as an overlay. |
| **Where** | `autodeck/` (everything except `studio/`), `prompts/`, `config/models.yaml`, `tests/` | `autodeck/studio/`, `prompts/studio/`, `config/studio*.yaml`, `tests/studio/`, `bench/`, `mockups/v3/` |
| **State** | Built through the draft-first pipeline, the deck agent, memory and the meeting UI. Two owner gates (GATE 2, GATE 3) and the live checks of the newest work are still open. Not under development. | Phases 0 to 3 built and verified, on scripted models and in one real-model run. About half the plan is not built (see below). **Development is paused** as of 2026-11-15. |
| **Direction** | Kept, and reused by v3 (parsing, knowledge folders, renderer, layout checks, providers). | **The direction of travel.** |
| **Start with** | This file, then `STATUS.md` | `STATUS.md`, then `docs/AUTODECK_V3_PLAN.md` |

v2 was built strict-first: accuracy first, beauty second, speed third, with blocking
validation and four human approvals per deck. Every later feature (draft-first, free layout,
an agent session, meeting notes) was strict with exemptions, and the owner's use of the
product had moved on. v3 turns that round: **the base is a plain deck built in conversation;
strict is an overlay.** The reasoning is in `docs/AUTODECK_V3_PLAN.md` §1.

The state of everything, on one screen, is in `STATUS.md`. This file is the front door and
the durable context.

---

## What v3 is, in three paragraphs

The studio is a local web application. You open an **engagement** (one client and one
project, backed by the existing `knowledge/` folders), start a **thread** (one disposable
chat), and say what deck you want. A **lead** model writes the argument and, for each slide,
a *brief in words*: what it must prove and what goes on it. It never writes coordinates or
picks colours. A **system layer** turns a design direction into a palette that code checks for
contrast. A **designer** designs each slide in its own call, within that palette. A **router**
and a **mechanic** handle small edits ("retitle slide 2 to ...") without troubling the lead.
Layout checks run on every slide in code.

Every edit goes into a **change log** with the layer and model that made it, and can be undone
and redone exactly. A new thread never replays an old one: it starts from the deck's state,
its change log (including what was rejected) and memory, and opens with a short recap. When a
brief or the chosen design changes, the slides built from the old one are computed to be
**stale**, and you ask for them to be recomposed. Every turn shows which layers and models ran
and an estimated cost.

What it does not do yet: strict mode, meeting notes on the new core, a reviewer layer, a
propose-first setting, an export button, selection as scope, several threads editing at once,
and a richer drawing vocabulary. The full list is under "What is not built".

---

## Running v3

Setup, once (LibreOffice and the Carlito font, which LibreOffice bundles, are needed to draw previews; `uv` runs everything):

```bash
./scripts/setup-dev-env.sh        # libreoffice-impress, poppler-utils, optional Inter fonts; proves a render
uv sync
```

**The scripted walkthrough: no key, no cost.** A scripted stand-in plays every model role,
so you can click through the whole flow:

```bash
uv run python -m autodeck.studio \
    --script tests/studio/fixtures/scripts/design_flow.json \
    --workspace /tmp/studio-walkthrough
# then open http://127.0.0.1:8765/
```

The script is consumed in order across threads, so use a fresh `--workspace` each time. Step
by step instructions are in `docs/STUDIO-GUIDE.md`.

**A real model.** `config/studio.yaml` binds one model per layer, per environment:

| Environment | Models | Needs | Status |
|---|---|---|---|
| `dev-openai` | lead and system `gpt-5.6-terra`, designer `gpt-5.6-luna`, router and mechanic `gpt-5.4-mini` | `OPENAI_API_KEY` | **The only environment run live**: one session on 2026-11-14 (`gpt-5.4-mini` alone, Phase 1) and one on 2026-11-15 (the layered bindings shown). Provisional tiering. |
| `dev-mistral` | `ministral-14b-2512` for every role | `MISTRAL_API_KEY` | The file's default. Never run live with the studio (no key was available). |
| `sit`, `prod` | `claude-opus-5` for every role | `ANTHROPIC_API_KEY` | **Never run against a live API.** The model id is unverified, as `config/models.yaml` says. |

```bash
export OPENAI_API_KEY=...         # or put it in .env (gitignored)
uv run python -m autodeck.studio --env dev-openai --workspace /tmp/studio-live
```

Other options: `--port`, `--no-render` (never call LibreOffice), `--knowledge`, `--corpus`,
`--owner-memory`, `--prices`. The server binds to 127.0.0.1 only.

**Costs are estimates, never charges.** Every cost shown anywhere in the studio or in these
documents is computed from assumed prices that were set deliberately high and never confirmed
against the provider's real price list (`config/studio_prices.yaml`,
`bench/slides/prices.yaml`). The estimated total spent building and testing v3 was about
$39.50 against a $50 session limit; that figure is an estimate too.

## Running v2

v2 is a command-line pipeline, with a local review window over the same commands.

```bash
uv run autodeck --help                    # every command
uv run autodeck ui                        # the review UI (v2); `--browser` to skip the native window
uv run autodeck knowledge ingest llm-inference-efficiency    # parse the seed papers (Docling; heavy)
# the draft-first path, for a run named RUN (see the guide for each command's options):
uv run autodeck clarify RUN --client C --project P --prompt "..."
uv run autodeck answer RUN --accept-all
uv run autodeck draft RUN
uv run autodeck validate RUN        # then gate2, render, gate3
```

The click-by-click procedure, with the approvals, is `docs/OWNER-GUIDE.md`. v2's default
environment is `dev-mistral` (`MISTRAL_API_KEY`); `sit` and `prod` use Claude.

## Running the tests

Observed on 2026-11-16 in the build container (fonts and LibreOffice installed):

| Command | Result |
|---|---|
| `uv run pytest -q -p no:cacheprovider tests/studio` | 564 passed, 8 deselected |
| `uv run pytest -q -p no:cacheprovider -m render tests/studio` | 8 passed (need LibreOffice and fonts) |
| `uv run pytest -q -p no:cacheprovider bench/slides/tests` | 70 passed, 1 deselected |
| `uv run pytest -q -p no:cacheprovider` (full default suite) | 2696 passed, 1 failed (the known one below), 6 skipped, 60 deselected |

The one known failure, present before any v3 work, is
`tests/test_design.py::test_a_missing_face_is_as_loud_as_a_missing_family` (a font in the
container's environment). Tests that draw need the Carlito font and skip without it.
Tests marked `render` need LibreOffice and are deselected by default; `live` tests call real
providers and are deselected by default. No test makes a paid call.

---

## Repository map

| Path | What it is |
|---|---|
| `README.md` | This file: the front door |
| `STATUS.md` | Where things are right now, on one screen |
| `DECISIONS.md` | Append-only decision log: D1 to D13, B1 to B83 (v2), V0 onward (v3) |
| `CHANGELOG.md` | What changed, newest first |
| `docs/AUTODECK_V3_PLAN.md` | **The v3 plan**: principles, decisions, build order, with what actually happened |
| `docs/phases/V3-PHASE-0.md`, `V3-PHASE-1.md`, `V3-PHASE-2-3.md` | The detailed record of each v3 phase: design choices, results, real-run notes, fixes, carried items |
| `docs/STUDIO-GUIDE.md` | How to use the studio, in plain steps |
| `docs/handovers/V3-STUDIO.md` | The v3 handover: how to resume cold |
| `docs/AUTODECK_V2_PLAN.md` | The v2 specification |
| `docs/phases/PHASE-*.md`, `docs/handovers/` (other files) | v2's phase briefs and handovers |
| `docs/OWNER-GUIDE.md` | The v2 owner's guide, click by click |
| `docs/INVARIANTS.md` | A1 to A8 made checkable, with the coverage tracker (v2; scoped in v3) |
| `docs/MODEL_ROUTING.md` | Which model does what: build-time, v2 runtime, and v3 layers |
| `docs/BRANCHING.md` | v2 branch topology and gate protocol; notes on the v3 branch |
| `autodeck/studio/` | **v3**: the engagement, plain deck model, change log, conversation loop, layers, design system, web server and `static/` front end |
| `autodeck/` (other packages) | **v2**: `ingest`, `retrieval`, `knowledge`, `ir`, `agents`, `audit`, `design`, `render`, `pipeline`, `providers`, `meeting`, `ui`, and `cli.py`. v3 imports from several of these |
| `prompts/` | Every LLM prompt, as files. `prompts/studio/` is v3's (lead, system, designer, mechanic, router); the rest is v2's |
| `config/studio.yaml`, `config/studio_prices.yaml` | v3 model bindings per layer and environment; assumed prices |
| `config/models.yaml`, `config/tokens/`, `config/palettes/` | v2's role bindings; design tokens (v3 renders with `dev.json`); palettes |
| `bench/slides/` | The slide bench: tests one slide's design in isolation. `SPEC.md`, prompts, cases, concepts, `results/` |
| `mockups/v3/` | The clickable mock-up that preceded the build (accepted as the direction). Throwaway; a visual reference |
| `tests/`, `tests/studio/` | v2's tests; v3's tests |
| `knowledge/` | Curated project and client folders (D8): the seed corpus and two fictional clients. Becomes the v3 engagement container |
| `scripts/` | `setup-dev-env.sh`, `install-dev-fonts.sh`, `studio_demo.py` (the Phase 0 demo) |
| `workspace/` | v3's working state (git-ignored; created on first run unless `--workspace` is given) |
| `legacy/v1/` | **Frozen** v1, with `LEGACY.md` |

---

## What is not built (v3)

In the order the plan puts them, with what is known:

| Not built | Plan reference | Note |
|---|---|---|
| The **reviewer** as a product layer | §6.1 | Tested twice on the bench: precise (no wrong send-backs in 40 reviews), weak at spotting uneven or crowded layouts. Bound as a reserved role, unused. |
| Trimming the lead's context | | The lead resends about 14k tokens on every call. |
| **Phase 4**: selection as scope, propose-first setting, export confirmation, several threads on one artifact, undo from the middle of the history | §12 | Staleness and recomposition were pulled forward into Phases 2 and 3 and are built. |
| **Phase 5**: meeting notes on the new core, source notes, the on-demand fact-check tool | §10, §12 | v2's meeting notes still exist, strict-only, in v2's code. |
| **Phase 6**: the strict overlay | §9 | Until it exists, traceable decks are made with v2. |
| **Phase 7**: routing benchmark | §12 | Every change records its layer and model, so the data is accumulating. |
| A **vocabulary phase**: styled charts, curved and diagonal lines, emphasis inside a line of text, more fonts, a proper fix for the two base theme colours that v2's theme writer emits as system colours | `docs/phases/V3-PHASE-2-3.md`, "Layout vocabulary gaps" | Not in the original plan; found by the bench. |
| Any run against an Anthropic model | | The `sit` and `prod` bindings are untested against a live API. |

---

## What v3 does with v2's decisions and invariants

v2's locked decisions (D1 to D13) and invariants (A1 to A8) still describe v2 exactly. v3
re-scopes some of them (decision records in `DECISIONS.md`, entries V0 onward):

| v2 | In v3 |
|---|---|
| D1 editable native PPTX, D3 Docling, D5 no HTML conversion, D10 native charts, D11 vector icons | **Kept** |
| D2 cloud models only | **Kept**, with the exception for local transcription (B78) |
| D4 Deck IR is the source of truth | **Kept, reshaped**: a plain base model (`autodeck/studio/models.py`); assurance annotations move to the overlay (not built) |
| D6 provider abstraction | **Kept.** Bindings move from pipeline roles to layers |
| D7 CLI-first, UI deferred | **Reversed.** The chat interface is the product |
| D8 curated knowledge folders | **Kept.** They become the engagement container |
| D9 invariants are blocking | **Scoped to strict mode** |
| D12 header voice per client | **Kept** as craft guidance |
| D13 balance by deterministic lints | **Demoted** to advisory findings; layout checks (overflow, overlap, safe area, minimum size, contrast) still run on every slide in every mode |

| Invariant | v2 | v3 base | v3 strict overlay (not built) |
|---|---|---|---|
| A1 citation, A2 numbers, A3 validation, A5 framing, A8 uncertainty | Enforced | Not enforced: text is text. A fact-check will be a tool, never a gate (not built) | As written |
| **A4 client isolation** | Enforced | **Enforced, in every mode** | Enforced |
| A6 reproducibility | Enforced | Not required; the change log is a product feature, not an audit record | As written |
| A7 human gates | Four approvals | One export confirmation (not built) | Four approvals |

A consequence worth stating plainly: **a v3 deck in the base has no traceability.** A figure
on a slide may be wrong, and nothing in the studio checks it. The owner accepted this trade
(plan V8). Where a deck must be traceable, use v2 until Phase 6 exists.

---

## v2 in brief

### The accuracy invariants

These are v2's contract: code, prompts, tests and CI enforce them.

**A1 Universal citation.** Every factual assertion in slide content or speaker notes carries at
least one citation resolving to a source span `(doc_id, page, bbox, verbatim_quote,
quote_sha256)`. Only `framing` blocks are exempt.

**A2 Numbers are copied or derived, never invented.** Every number, percentage, unit and date
traces to a cited span, directly or through a declared derivation whose formula the numeric
linter re-executes.

**A3 Blocking validation.** Every claim gets a verdict (`supported`, `partially_supported`,
`unsupported`, `contradicted`); a deck cannot reach final render with an unsupported or
contradicted block. The validator re-retrieves independently.

**A4 Client isolation.** A build loads exactly one client namespace; any cross-client
reference is an error, not a warning.

**A5 Fact/framing separation.** Positioning language is typed `framing`, is citation-exempt,
and must pass a deterministic "no fabricated fact" lint; violations are demoted to `claim`.

**A6 Reproducibility and audit.** Every deck ships its frozen IR, an audit report and a build
manifest. The same manifest and IR re-render to normalised-comparable output (wording
corrected 2026-09-27, B29).

**A7 Human gates.** Four mandatory approvals per deck: planning brief, outline, post-validation
claims table, final render. The pipeline never auto-approves.

**A8 Honest uncertainty.** Where sources conflict or evidence is only partly supporting, hedge
in the text; never average, round or silently pick one.

> **The rule that matters most** (v2 plan §0.4): never weaken an invariant to make a test pass
> or a demo work. If one blocks progress, stop and surface the conflict with options. In v3
> the invariants are *scoped to strict mode by decision*, which is a recorded owner decision
> and not a quiet relaxation; the base does not claim them.

`docs/INVARIANTS.md` makes each checkable, with an owning phase and a coverage tracker.

### Locked decisions

Do not relitigate without owner sign-off. Rationale in `DECISIONS.md`.

| # | Decision | v3 |
|---|---|---|
| D1 | Deliverables are fully editable native PPTX on a real slide master/theme XML | Kept |
| D2 | Cloud APIs for everything; no local models | Kept (local transcription excepted, B78) |
| D3 | Ingestion via Docling; provenance preserved end to end | Kept |
| D4 | Deck IR is the single source of truth; renderers are downstream | Kept, reshaped |
| D5 | PPTX is the medium end to end; no HTML to PPTX conversion anywhere | Kept |
| D6 | Provider abstraction with structured outputs | Kept; per layer |
| D7 | CLI/pipeline-first, headless core; review UI deferred | **Reversed (v3)** |
| D8 | Knowledge = curated markdown folders loaded fully; retrieval only for corpora | Kept |
| D9 | Accuracy invariants are blocking, not advisory | **Scoped to strict mode (v3)** |
| D10 | Charts are native editable PowerPoint charts with data provenance | Kept |
| D11 | Icons are vectors end to end | Kept |
| D12 | Header voice is a learnable per-client profile | Kept as craft guidance |
| D13 | Balance enforced by deterministic lints, not model taste | **Demoted to advisory (v3)** |

**Rejected, do not revisit:** runtime HTML to PPTX conversion; design-time HTML with
hand-porting; PptxGenJS or other JS generators; Office.js add-ins or macro-enabled files.

### v2 pipeline

```
 PDFs ──► [Ingest: Docling] ──► Document Store (elements + provenance)
                                  │
        [Planning Agent ⇄ human] ──► DeckBrief            ◄── approval 1
        [Outline Agent] ──► Deck IR v0                    ◄── approval 2
        [Content Agent] ──► Deck IR v1 (claims + citations, inside component budgets)
        [Validation Agent] ──► verdicts + audit table     ◄── approval 3
        [Art direction] ──► [Native renderer] ──► [QA loop]
                                                          ◄── approval 4
        deck.pptx  +  audit_report  +  build_manifest.json
```

Everything lives under `runs/<run_id>/`. Since the original plan v2 also has a draft-first path
(one compose call, then validation: B43 to B48), a deck agent session (B71 to B76), memory
(B77), and a meeting-notes path with local transcription (B78 to B83). The v2 roadmap
(`docs/phases/PHASE-*.md`) records Phases 0 to 3b as merged; the handover index (`docs/handovers/README.md`) lists v2's
Phases 4 and 5 as not started.

### v2 state in one paragraph

GATE 0, GATE 1a and GATE 1 are approved (`DECISIONS.md` G0, G1a, G1). GATE 2 and GATE 3 are
open. The draft-first build (3c), redesign (3d) and the deck agent were verified on scripted
models and in some live runs on `dev-mistral`; the meeting path was built through plan step
12 (the UI), and its step 13, a live check on the real recording, is the owner's and not
recorded as done. See `STATUS.md` for what could not be confirmed.

---

## Model routing

Two layers, both in `docs/MODEL_ROUTING.md`:

- **Build-time:** which model implements which task. Opus owns architecture, contracts, all of
  `prompts/` and the decision log; Sonnet implements against settled interfaces; Haiku does
  mechanical work. Path guardrails override tags.
- **Runtime:** which model AutoDeck itself calls. v2 binds *pipeline roles* in
  `config/models.yaml` (three environments: `dev-mistral`, `sit`, `prod`). v3 binds *layers*
  (lead, system, designer, mechanic, router, and a reserved reviewer) in
  `config/studio.yaml`. No model id appears in code in either.

v2's A3 and A8 are model-sensitive: accuracy measured on a dev model does not transfer to
production. v3 shares the lesson in another form: **the tiering of layers only means
something where the tiers differ**, so the `dev-openai` bindings are provisional and the
`sit`/`prod` bindings are untested.

---

## Resuming

**Read in this order:**

1. `README.md`: this file.
2. `STATUS.md`: where things are.
3. `docs/handovers/V3-STUDIO.md`: the v3 handover (what shipped, what did not, how to resume).
4. `docs/AUTODECK_V3_PLAN.md`: the plan, with a "What actually happened" section.
5. `docs/phases/V3-PHASE-2-3.md`, then `V3-PHASE-1.md` and `V3-PHASE-0.md`: the detailed record,
   most recent first. Each has a result section, real-run notes and a carried-items list.
6. `bench/slides/SPEC.md` and `bench/slides/results/README.md`: the slide bench and what it
   found.
7. For v2 work: `docs/handovers/AGENT-MEETING-1.md` (the latest v2 handover) and
   `docs/OWNER-GUIDE.md`.

**Standing rules** (carried from v2's plan §0 and still in force):

- Every task lands with tests. All LLM prompts live as files under `prompts/`, never inline,
  and a prompt change is its own commit with its rationale.
- Never weaken an invariant to make a test pass. Surface the conflict.
- Maintain `DECISIONS.md` (append-only) and `CHANGELOG.md`. When the plan is ambiguous, make
  the smallest reasonable decision, record it, and flag it.
- v3 code does not modify v2 files; it imports from v2. If a v2 change is needed, say so and
  decide it separately.
- Engineering standards: Python 3.11+, pydantic v2, typer, pytest, full type hints checked
  with pyright, ruff for lint and format. No Streamlit. No notebooks in the package.

**Branch.** All v3 work is on `claude/autodeck-principles-review-zp7nsm`, built on top of
`v2/integration`. The plan recommended a `v3/integration` branch; that was not possible in the
session that did the work, so the owner may want to rename it or rebase. See
`docs/BRANCHING.md`.
