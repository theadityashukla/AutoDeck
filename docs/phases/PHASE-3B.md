# Phase 3b — Renderer, QA & art direction

**Branch:** `v2/phase-3b-render-qa` · **Gate:** GATE 3 · **Estimate:** ~3 weeks
**Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 3 tasks 8–10, §6.9

> Split from Phase 3 per decision B5. Phase 3a built the vocabulary; this phase assembles
> it into decks and defends the result.
>
> **The defining constraint: the aesthetic loop may never edit claim text or citations.**
> This must be structural — enforced by the action space's type system — not a prompt
> instruction. A vision model that can rewrite a verified claim is a silent accuracy
> corruption channel (plan §9).

## Preconditions

- Phase 3a merged; component catalog, diagram engine, icons, grammar lints available.
- Phase 2b's audited deck available as the regression subject.

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 3b.1 | `renderer.py` — IR → pptx via theme master + component renderers + native charts | **Sonnet** | `autodeck/render/renderer.py` | A6 | The Phase 2b deck renders end to end into the client theme |
| 3b.2 | `qa/deterministic.py` — overlap, margin/safe-area, min font size, WCAG-style contrast. **Pure arithmetic, no model** | **Sonnet** | `autodeck/render/qa/deterministic.py` | — | Every failure is fixable via a token or slot adjustment; no vision model involved |
| 3b.3 | `qa/libreoffice.py` — headless render to images, productionised from the 0.5 spike | **Sonnet** | `autodeck/render/qa/libreoffice.py` | — | Deterministic image output suitable for the aesthetic pass |
| 3b.4 | `prompts/aesthetic_critique.md` | **Opus** | `prompts/aesthetic_critique.md` | — | Own commit with rationale |
| 3b.5 | **`qa/aesthetic.py` — bounded IR-action critique loop.** Vision reviews true renders; output is a closed action set (adjust type scale, swap component, change emphasis, rebalance columns, swap glyph/colour token) — **never free-form geometry** | **Opus** | `autodeck/render/qa/aesthetic.py` | **A1, A3** | **The action type system makes editing claim text or citations unrepresentable.** Max iterations + target score; test asserts a critique attempting a text edit is rejected |
| 3b.6 | `prompts/art_direction.md` | **Opus** | `prompts/art_direction.md` | — | Own commit with rationale |
| 3b.7 | Art-direction pass — deck-level rhythm (density variation, section dividers, promote one number to `big_number`), component swaps, communication-mode decisions | **Sonnet** | `autodeck/agents/art_direction.py` | D13 | Assigns `text_led`/`icon_anchored`/`diagram_led` per slide, human-overridable; honours brief layout pins |
| 3b.8 | **Numeric linter re-run post-render** on extracted rendered text | **Opus** | `autodeck/audit/numeric_linter.py`, `renderer.py` | **A2** | Text is extracted from the *rendered* PPTX and re-linted; a number altered during rendering is caught |
| 3b.9 | Header horizontal-flow QA wired into the render pipeline | **Sonnet** | `autodeck/design/headers/` | D12 | Header sequence read in isolation; storyline breaks, banned patterns, and repeated syntax flagged |
| 3b.10 | GATE 3 review surface — rendered deck + final audit pass | **Sonnet** | `autodeck/cli.py` | A7 | Owner gets deck, audit report, and manifest together |

## Accuracy focus

> Rendering and the aesthetic loop are proven unable to alter verified facts; numeric
> linter re-runs on final rendered text; headers carrying claims are validated like any claim.

Task 3b.5 and 3b.8 are the two halves of this: **prevention** (the loop structurally
cannot touch facts) and **detection** (post-render re-lint catches anything that did).
Build both — neither alone is sufficient.

## Milestone

The same Phase 2b deck, now **beautiful, in the client theme, fully editable in
PowerPoint** — including at least one native diagram and theme-recolourable icons — with
the audit report still clean.

## GATE 3 — exit criteria

The owner approves the visual result and a final audit pass, **and verifies in PowerPoint**:

1. A **diagram node** can be selected and recoloured.
2. An **icon** can be selected and recoloured from the theme palette.
3. A **chart's underlying data** can be edited.
4. Theme colours and fonts appear in PowerPoint's own Design UI.
5. Adding a new slide by hand inherits the master's look.
6. The audit report is clean and the numeric linter passes **post-render**.

Items 1–5 are hands-on-keyboard checks in PowerPoint, not screenshots. D1, D10, and D11
all fail silently if verified any other way.

## Escalation triggers

- **The aesthetic loop proposes an action outside its bounded set** — that is a design
  hole in the action type system, not a prompt tuning problem. Fix the types.
- **The post-render numeric linter catches a discrepancy** — stop and find the mechanism.
  A number changing between IR and render means something in the pipeline is rewriting
  content, which is a class of bug that will recur.
- **Deterministic QA cannot fix a failure via token or slot adjustment** — that is a
  component design gap; return it to the 3a catalog rather than special-casing the renderer.

## Notes for the implementer

- v1's `design_agent.py` `ACTION_CATALOG` is the **conceptual** ancestor of 3b.5: closed
  vocabulary proposed by the model, deterministic execution. v1's version acted on
  geometry; v2's acts on IR. Salvage the idea, not the code (`legacy/v1/LEGACY.md`).
- The aesthetic loop judges **true renders only** (D5). Never a mock-up, never a proxy.
- Deterministic checks are the safety net; component budgets (§6.7) are the primary
  mechanism. If deterministic QA is catching overflow routinely, budgets are wrong —
  fix them upstream instead of tuning the net.
