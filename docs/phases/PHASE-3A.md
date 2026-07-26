# Phase 3a — Design system

**Branch:** `v2/phase-3a-design-system` · **Gate:** internal review (no owner gate)
**Estimate:** ~4 weeks · **Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 3 tasks 1–7,
§§6.6, 6.8, 6.11

> Split from Phase 3 per decision B5. This phase builds the **vocabulary**; Phase 3b
> assembles and renders it. Everything here was proven possible by the Phase 0 spikes —
> if a spike failed, that must be resolved before this phase, not worked around inside it.

## Preconditions

- GATE 2 approved; `docs/handovers/PHASE-2B.md` read.
- GATE 0 spikes all passed. **If the native design spike (0.5) or icon spike (0.6) failed
  or passed with conditions, resolve with the owner before starting.**
- `design/budgets.py` measurement engine from Phase 2b.
- Owner answer to Q5 (a client with a mandated corporate template, for onboarding mode a).

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 3a.1 | Theme/master builder productionised — both onboarding modes: (a) client corporate template, (b) generate from tokens | **Sonnet** | `autodeck/design/theme/{extract,tokens,master_builder}.py` | D1 | Both modes produce a PPTX whose theme appears in PowerPoint's own UI; new hand-added slides inherit it |
| 3a.2 | `layout_kit` productionised from the 0.5 spike — stacks, grids, gutters, baseline spacing, token-driven type scale | **Opus** (API shape) | `autodeck/design/layout_kit.py` | — | API stable enough that a component renderer is ~50 lines, not ~300 |
| 3a.3 | Component catalog registry — name → role → slots → budgets → renderer → golden preview | **Opus** | `autodeck/design/components/catalog.py` | — | Registry drives lookup; adding a component is a registration, not a code change elsewhere |
| 3a.4 | **First 15 components** authored natively against the preview gallery; budgets declared per slot; golden preview PNG committed each | **Sonnet** (first 3) → **Haiku** (remainder, once the pattern holds) | `autodeck/design/components/renderers/`, `previews/` | — | All 15 render; each has a committed golden PNG; budgets measured, not guessed |
| 3a.5 | Native editable charts from `ChartSpec` with data provenance | **Sonnet** | `autodeck/design/charts.py` | **A1, D10** | Chart opens in PowerPoint with **editable underlying data**; the source table cell is the citation. No image fallback exists |
| 3a.6 | **Diagram engine** — `DiagramSpec` types as native shapes + connectors, theme-coloured. Start `process_flow`, `two_by_two`, `layered_stack` | **Opus** (type system) → **Sonnet** (first types) → **Haiku** (remainder) | `autodeck/design/diagrams.py` | **A1** | Nodes are individually selectable and recolourable in PowerPoint; node labels obey budgets; factual nodes carry citations |
| 3a.7 | **Icon system** productionised from the 0.6 spike — semantic library, concept→glyph picker, SVG→`custGeom` converter, deck-wide consistency | **Sonnet** | `autodeck/design/icons/` | D11 | Icons land as native recolourable shapes; one family, stroke weight, and size scale per deck. **Verify library licences at implementation time** |
| 3a.8 | **Header voice system** — `HeaderStyleProfile` loader, application in content prompts, per-deck style switch, horizontal-flow QA | **Sonnet** | `autodeck/design/headers/` | **A1–A3, D12** | `build --header-style question_led` is a one-flag switch; **headers containing facts are `claim` blocks and validate like any claim** |
| 3a.9 | **Grammar lints** — deterministic balance checks, blocking | **Opus** | `autodeck/design/grammar.py` | D13 | Every icon adjacent to a text label; word budgets per mode (icon_anchored ≤50, diagram_led ≤60, text_led ≤90); ≤5–7 concepts/slide; ≤1 diagram/slide; no icon+chart+diagram pileup |

## The 15 components

`title`, `section_divider`, `agenda`, `big_number`, `two_column_compare`, `quote`,
`bullets_supporting`, `evidence_with_figure`, `framework_diagram`, `timeline`,
`data_card_grid`, `chart_focus`, `before_after`, `callout_takeaway`, `closing_cta`.

`big_number` and `two_column_compare` exist from spike 0.5. Diagram-led components
(`framework_diagram`, `timeline`) **delegate geometry to the diagram engine** (3a.6)
rather than carrying bespoke renderer code.

## Slide-geometry skill — the seed source

`docs/reference/slide-geometry/` is vendored per plan §6.11.2 and seeds `DiagramSpec`
types, art-direction selection rules, and label-placement conventions.

Two standing requirements:

1. **The `python-pptx MSO_SHAPE` column of `construction.md` is authoritative.** Its
   table leads with pptxgenjs presets, which D5 and §6.6(c) rule out. The vendored copy
   carries a header note; read past the leftmost column.
2. **Keep the two in sync.** Any `DiagramSpec` type added beyond the catalog is proposed
   back to the upstream skill, and any upstream change is reflected here.

The skill's own discipline applies to 3a.6: classify the relationship *before* choosing a
geometry, and apply the load-bearing test — if replacing the geometry with a plain list
loses no information, the geometry is decoration.

## Accuracy focus

Headers carrying claims are validated like any claim (D12). Titles are the most-read text
in the deck; they get the **strictest** treatment, not the loosest.

## Exit criteria (internal review — no owner gate)

- All 15 components render with committed golden previews.
- At least three `DiagramSpec` types produce natively editable shapes.
- Icons land as recolourable native shapes.
- Grammar lints blocking and tested.
- Header profile switch works per-deck.
- **Phase 2b's audit report is still clean** — nothing here may alter verified facts.

Phase 3b's GATE 3 is where the owner reviews this work in a rendered deck.

## Escalation triggers

- A recurring layout the catalog cannot express → record as a catalog gap (feeds Phase 4's
  gap analysis); do not bolt a special case onto a renderer.
- A `DiagramSpec` type that cannot be expressed in native shapes → escalate rather than
  falling back to an image. D10/D11's whole point is that pasted pictures are the #1
  client edit request.
- Icon library licence turns out to be unsuitable → resolve before the library is embedded.

## Notes for the implementer

- Components are **authored directly in the final medium** (D5). The loop is: edit code →
  render → headless LibreOffice → PNG → adjust. The committed golden PNG is the design
  artifact of record.
- Do not introduce a second medium at any point, including "just for sketching". Loose
  inspiration (paper, images) is fine; **conversion is not** (§6.6 rejections a–d).
- De-escalation is expected in 3a.4 and 3a.6 — the first few establish the pattern, the
  rest are mechanical. Record the actual split in the handover.
