# Phase 0 — Foundations & de-risking

**Branch:** `v2/phase-0-foundations` · **Gate:** GATE 0 · **Estimate:** 2–3 weeks
**Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 0

> The riskiest assumptions live here; prove them before building on them. Three of the
> seven tasks are **spikes whose failure changes the architecture**, not tasks that can
> be worked around.

## Preconditions

- Scaffold merged on the integration branch (this document exists).
- Read: `README.md`, `docs/AUTODECK_V2_PLAN.md` §§1–6, `legacy/v1/LEGACY.md`.
- Owner answers to open questions Q1 and Q3 below (they determine CI packaging and what
  the font spike measures).

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 0.1 | Repo skeleton per plan §5; `pyproject.toml` (Python 3.11+, pydantic v2, typer, pytest, ruff, pyright); CI running lint + types + tests | Opus scaffolds, **Haiku** fills boilerplate | `pyproject.toml`, `.github/workflows/`, package tree | — | CI green on an empty test suite; `ruff` and `pyright` clean |
| 0.2 | **Deck IR v1** — pydantic models per §6.1, JSON-schema export, `store.py` with versioning + diff | **Opus** | `autodeck/ir/{models,schema,store}.py` | **A1** | Golden-file round-trip test on a hand-authored sample IR; **a `claim` block with zero citations raises `ValidationError`** |
| 0.3 | **Provider abstraction** — protocol, `complete_structured` with schema enforcement and repair-retry (N attempts then hard-fail, never silent field drop), **Gemini + Groq + Claude** adapters, environment-tiered role registry (`dev`/`sit`/`prod`, decision B8) | **Opus** | `autodeck/providers/*`, `config/models.yaml` | — | Structured output validated against a trivial schema on **all three** providers; malformed JSON triggers repair then hard-fails; `--env` selects bindings; **backoff + resumability** proven against a free-tier rate limit; resolved model IDs recorded in `DECISIONS.md` |
| 0.4 | **SPIKE — font/theme.** One real brand → tokens → theme XML + one slide master. Confirm PowerPoint shows palette/fonts natively; confirm a TTF measures correctly; confirm embedding + fallback | **Opus** | `autodeck/design/theme/*`, `fonts/` | — | Owner opens the PPTX and sees the palette in PowerPoint's own colour UI; measured text height matches rendered height within tolerance; findings in `DECISIONS.md` |
| 0.5 | **SPIKE — native design.** `layout_kit` v0 (stacks, grids, gutters, baseline spacing) + watch-render preview gallery (render → headless LibreOffice → PNG). Design **`big_number`** and **`two_column_compare`** to a high visual bar, natively | **Opus** | `autodeck/design/layout_kit.py`, `autodeck/design/components/renderers/`, `autodeck/render/qa/libreoffice.py` | — | Two components meet the owner's visual bar; **iteration loop is fast enough to sustain a 15-component library** (record the actual edit→preview seconds) |
| 0.6 | **SPIKE — icon vector.** One library SVG → DrawingML `custGeom` → placed in a themed PPTX | **Opus** | `autodeck/design/icons/` | — | Owner confirms **in PowerPoint** the icon is selectable, losslessly scalable, and recolours from the theme palette; converter edge cases (arcs, compound paths, fill rules) documented in `DECISIONS.md` |
| 0.7 | Orchestrator skeleton — run dirs under `runs/<run_id>/`, resumability, gate stubs | **Sonnet** | `autodeck/pipeline/orchestrator.py`, `autodeck/cli.py` | **A7** | Empty pipeline runs end to end on a stub, producing a versioned IR and a blank manifest; gate stubs **block** rather than log |

## Accuracy focus

> IR carries citations structurally from day one; schema forbids a `claim` block without
> ≥1 citation.

Task 0.2 is where this lands, and it is structural rather than a runtime check — the
cheapest possible enforcement of A1 and the reason IR comes first.

## Milestone

Empty pipeline runs end to end on a stub, producing a versioned IR and a blank manifest.

## GATE 0 — exit criteria

> Plan §7: *"This is the go/no-go for the whole rendering strategy."*

The owner reviews the three spike outputs and confirms, by opening files in PowerPoint —
not by reading a report:

1. **Theme (0.4)** — the brand palette and fonts appear in PowerPoint's own Design UI;
   a new slide added by hand inherits the look.
2. **Components (0.5)** — `big_number` and `two_column_compare` meet the visual bar, and
   the recorded iteration time makes a 15-component library credible.
3. **Icon (0.6)** — the converted icon is selectable, scales losslessly, and recolours
   from the theme palette.

Plus: CI green, IR round-trip test passing, structured output working on **all three**
providers (Gemini, Groq, Claude) with environment tiers selectable via `--env`.

### Watch items in 0.3 (from decision B8)

- **Structured-output parity.** JSON-mode and tool-use support varies by provider, and
  within Groq by the open model being served. Where a provider is weaker the repair-retry
  path carries more load — test it deliberately here rather than discovering it in
  Phase 2b, where structured output is load-bearing for every claim.
- **Free-tier rate limits.** They bite first at Phase 1 ingestion (`ingest_vlm` over a full
  corpus) and Phase 5 eval batches. Build backoff and resumability into the provider layer
  now; retrofitting under a live rate limit is painful.

## Escalation triggers — stop and return to the owner

- **0.5 fails on quality** — native authoring cannot reach the visual bar. D5 is in
  question; the rendering architecture needs re-planning *before* Phase 3. Do not
  substitute an HTML path (§6.6 rejects it) — escalate.
- **0.5 fails on speed** — quality is reachable but iteration is too slow to sustain 15
  components. Invest further in the preview loop before Phase 3, and say so at the gate.
- **0.6 fails** — D11 is in question. Fall back to `svgBlip` + PNG embedding as §9
  allows, but flag it: it weakens "icons are vectors end to end".
- **0.4 shows the brand font cannot be licensed or embedded** — resolve with the owner
  before Phase 3 depends on the metrics.

## Open questions carried from plan §11

| Q | Question | Starts blocking |
|---|---|---|
| Q1 | Deployment target — local dev only, or containerised for a team? | **Phase 0** — determines CI and packaging in 0.1 |
| Q2 | Which project + client seed the build? Real or anonymised? | Phase 1 |
| Q3 | Are brand fonts available and licensed for the seed client, or design against a safe default? | **Phase 0** — determines what 0.4 measures |
| Q4 | Audit report audience — internal only, or client-facing? | Phase 4 |
| Q5 | Any client with a mandated corporate template to target as mode (a)? | Phase 3a |

Q1 and Q3 block GATE 0. The rest are tracked and re-surfaced by the phase that needs them.
