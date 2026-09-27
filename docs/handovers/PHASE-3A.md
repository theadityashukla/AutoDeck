# Phase 3a — Design system — Handover

> The phase's reason for existing, in the plan's own words: components that declare their
> budget before content is written, rendered into a real OOXML theme, with nothing shrinking
> to fit.

---

## 1. Identification

| | |
|---|---|
| **Phase** | 3a — Design system |
| **Branch** | `v2/phase-3a-design-system` — cut from 2b's tip `15f0880` (B27, stacked, unmerged) |
| **PR** | not opened. Nothing merges until the owner works the gate (B27) |
| **Started / completed** | 2026-09-19 → 2026-09-27 |
| **Gate** | PHASE-3A has no owner gate of its own — the owner reviews this work in a rendered deck at GATE 3 |
| **Gate status** | **pending** |
| **Approved by / when** | — |
| **What the owner actually checked** | Nothing yet. |

Suite at tip: **1098 passed, 0 skipped, 10 live deselected** — requires the three
environment dependencies in **B34**.

## 2. What shipped

| Path | What it does | Commit |
|---|---|---|
| `layout_kit.py` | Composition layer: `Frame`, `Stack`, `Box.reserve`, `measure_block`; nothing shrinks text, over-budget raises. Renderers 186→115 and 208→154 lines | 878035e |
| `components/catalog.py` | Registry: `register()` with name, roles, slots, renderer, content class, preview together; variants; `components_missing_previews()` | 6fa845b |
| `ir/models.py` | `DiagramSpec` type system: relationship declared before geometry, typed payloads, `GEOMETRIES`; a node must be exactly one of `claim`/`framing` (unconstructible otherwise, mutation-tested) | 8cd7750, 4294f5d |
| — | Merge of the 2b accuracy fixes, incl. an identity check that verdicts written through a `ClaimSite` reach the stored node; later A2 noun fix | 9aa3218; 80b93c8 |
| `components/preview.py` | Golden-preview loop + `autodeck components preview` | b1e45da |
| 15 components, each with a committed golden PNG | big_number, two_column_compare (spike); quote, bullets_supporting, callout_takeaway; title, section_divider, agenda, closing_cta, before_after, evidence_with_figure, data_card_grid; framework_diagram, timeline, chart_focus | 9247784; 6f2c3ae (+ lint 7d08f8d); scaffold 4e337e9, fill 8f9d52c/eae715f |
| — | Budgets resolve a real face per weight/style; exact integer prediction-vs-render line-count cross-check | cbe85d5, e78d496, 6ad4a9b |
| `theme/` | Mode (b) from tokens with inheritance proven; mode (a) extraction against a synthetic template only | ad62cd0, f4ee72f |
| `icons/` | Licence record first (ISC + MIT carve-out, suitable); semantic library, deck consistency checker, `Frame.icon` | c32a10f; 988efa8 |
| `headers/` | Profile loader, profile in the content prompt, `--header-style` one-flag switch on `autodeck content`, horizontal-flow QA | 1264454, 9cbdd02, 85871bd |
| `charts.py` | Native charts, data in an embedded workbook referenced by formula, no image part ever | 3541c10 |
| `diagrams.py` + `draw.py` | process_flow, two_by_two, layered_stack as ungrouped native shapes with theme colours | d026e07, 46ae31c |
| `grammar.py` | D13 lints: word budget, ≤1 diagram, icon+chart+diagram pileup (blocking); concept count (advisory); icon adjacency (blocking, uncalibrated) | fd346ad, efb9602, 521ef8e, 3d7958c |
| — | `ContentResult.incomplete_slots` split from `rejections` | 5bc499a |
| `scripts/install-dev-fonts.sh`; CI fonts; vendored geometry reference | Infra: installs dev fonts; CI installs fonts; `ISOSCELES` correction to the vendored geometry reference | b1d5544; 3cac30e; e101cad |

## 3. What did not ship

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|
| A dated-axis timeline | Recorded catalog gap; `timeline` renders the sequence as chevrons and refuses any non-sequence geometry | — |
| Theme mode (a) against a real corporate template | Q5 unanswered — synthetic only proves the path runs | Owner (Q5), then a future phase |
| `Stack.icon_row` structural icon+label pairing | Declined twice, so the adjacency lint pairs geometrically instead | — |
| Renderers for 4 of the 7 `GEOMETRIES` | cycle, funnel, pyramid, hub_spoke have no renderer | — |
| The exit criterion "2b's audit report still clean" | Fixture-verified only — no live run exists (PHASE-2B §3, B30) | Owner, at the review session |

## 4. Decisions made this phase

- **B31** — Phase 3a starts with three preconditions unmet, knowingly.
- **B32** — Opus writes the scaffold; Sonnet writes the code.
- **B33** — Registering a component is not a local change.
- **B34** — The environment is part of the project.
- **B28** superseded in part by **B32**, for code (guardrail paths no longer hold Opus for
  implementation; the scaffold/fill split applies there too).

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | tested | **strengthened** | diagram nodes cannot hold an uncited fact by construction; renderers never compose or resolve citations (charts format already-resolved ones); `timeline` takes a `DiagramSpec` precisely so A1 decisions are never made by a renderer |
| A2 numbers | partial | partial | unchanged this phase beyond the A2 quantity-noun fix (80b93c8) |
| A3 validation | tested | tested | diagram-node claims block render (from the 2b merge) |
| A4 isolation | tested | tested | unchanged |
| A5 framing | partial | partial | the headers work found the fence misses plain declaratives (see PHASE-2B §5) |
| A6 reproducibility | partial | partial | unchanged |
| A7 gates | enforced | enforced | unchanged — no new gate this phase |
| A8 uncertainty | enforced | enforced | unchanged |

D10/D11/D13 are enforced by construction and tests: native shapes, zero `grpSp`, zero
`srgbClr`, zero image parts, blocking grammar lints.

## 6. Spike and experiment findings

**Including negative results — most important first.**

1. **Bold budgets were under-predicted by 3–8.5%** (Inter Display 6.1%, Inter 2.8%,
   Liberation Sans 8.5%), because face resolution always returned the regular file. Caught
   only by looking at a golden PNG — a rule struck through a wrapped headline — while every
   automated check stayed green, because `check_overflow` compares a prediction with itself.
   The flag was dropped in two places (`measure_block`, `ComponentSlot`). Fixed, plus an
   exact integer prediction-vs-render cross-check. `RENDER_TOLERANCE` was the wrong *shape*
   (1/N of total height: 36% at one line, 3.3% at six) — replaced by a fraction of one line
   box.
2. `overflow_width` was discarded by `Canvas.measure`: an unbreakable word measured as one
   line and rendered past the edge. `big_number`'s supporting points had no overflow check.
3. Chevron labels were centred on the bounding box, but the preset's filled region starts at
   the notch tip: white text landed in the unfilled notch, invisible on white. Caught only by
   rendering. `construction.md` gives no numbers for any recipe used; every constant in
   `diagrams.py` was derived by render-and-look.
4. The vendored authority was wrong: `ISOCELES_TRIANGLE` is not a python-pptx member.
5. LibreOffice ignores `sysClr`'s `lastClr` (title text stays black whatever `dk1` is) —
   deliberately not patched, since `sysClr` serves a PowerPoint-only behaviour; LibreOffice's
   own re-save drops a chart's embedded workbook. Both are concrete PowerPoint/LibreOffice
   divergences B31 predicted.
6. **Two descriptions of one thing drift — the phase's recurring defect:** catalog slot
   geometry vs renderer arithmetic; `ComponentSlot` vs `TextStyle` (bold); a figure block
   measured one way and drawn another; `DiagramSpec.nodes` as storage (2b) vs derived view
   (3a) across the merge. Prefer deriving one from the other.
7. Registering seven components broke seven citation tests (B33).
8. A test passed for the wrong reason: a 6pt fixture made `split_rows` raise before the label
   path it was named for was reached.
9. Fresh containers lacked Inter, `libreoffice-impress` and `poppler-utils` (B34).

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| **Four PowerPoint-only checks for GATE 3** (no PowerPoint here, B31) | GATE 3 has no evidence for the one engine that matters, unless the owner runs each procedure below in one sitting | Owner, at GATE 3 |
| Aptos visual sign-off | Not installable here; the deliverable default font is unverified visually | Owner |
| `check_overflow`'s sibling-floor policy passes content the renderer then refuses | Each slot's budget assumes siblings take one line; nothing checks both can hold at once | Phase 3b |
| Catalog mirrors renderer arithmetic by hand | A third module is needed to break an import cycle before slot boxes can be derived from a dry-run placement | Phase 3b |
| Diagram and chart labels are protected physically only at render, not by `check_overflow` | A label can overflow without the pre-render check catching it | Phase 3b |
| Icon-adjacency threshold (1.0 × gutter) is uncalibrated | No component places icons yet, so the threshold has never been exercised against a real layout | Phase 3b |
| Owner question: `split_rows`/`split_columns` raise `ValueError` for "does not fit" while `Box.reserve` raises `LayoutOverflowError` | Changing it is a breaking type change pinned by `test_columns_that_cannot_fit_raise` | Owner |
| Kerning is not applied | Width over-predicted by up to 6.7% — safe direction (rejects text that would fit), a quality issue not an accuracy one | Phase 3b |
| `prompts/content.md` "## Headers" is stale about A5's scope | Replacement wording exists (from the headers work) and is a guardrail-path change | Phase 3b |
| The done-when's `build --header-style` names a verb that does not exist | The flag is on `content`, not `build` — anyone testing against the done-when as written will look in the wrong place | — |

**Four PowerPoint-only procedures for GATE 3**, each a numbered check the owner can run in
one sitting:

(a) **Theme.** Open a built deck, Design → Variants shows a named custom theme with the 12
    colours and 2 fonts; right-click → New Slide, type in title and body, confirm fonts AND
    text colour come from the theme (text colour is the unverified part, see §6.5).
(b) **Icons.** Select an icon, change its outline colour; change the theme accent and
    confirm it recolours; each icon part is a native shape, not a picture.
(c) **Charts.** For each chart type, right-click → Edit Data opens an Excel sheet with the
    real numbers; editing a cell updates the chart; Selection Pane lists a Chart, not a
    Picture.
(d) **Diagrams.** Selection Pane lists every node and connector individually; changing the
    theme recolours them.

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| 3a.2 layout_kit + 3a.3 registry | Opus | Opus | not a guardrail path — over-tiered (owner correction, B32) |
| 3a.6a DiagramSpec | Opus | Opus | `ir/` guardrail |
| merge 2b→3a | — | Opus | `ir/` guardrail |
| 3a.4 components 3–5 + preview loop | Sonnet | Sonnet | — |
| bold-metrics fix | — | Opus | not a guardrail path — over-tiered |
| 3a.1 theme · 3a.7 icons · 3a.5 charts · 3a.8 headers | Sonnet | Sonnet | two pairs in parallel |
| 3a.6b diagram renderers | Sonnet→Haiku | Sonnet | — |
| 3a.4 components 6–12 | Haiku | **Haiku** | first Haiku use; craft good, but reported its own 7 test failures as "pre-existing" and skipped the lint gate |
| content regression fix | — | Sonnet | — |
| 3a.9 grammar lints | Opus | **Sonnet** | path decides the tier (owner, 2026-09-20) |
| lint cleanup | — | Haiku | all four gates reported verbatim when told explicitly |
| components 13–15 | — | **Opus scaffold, Sonnet fill** | B32 |

The pattern that forced B32: before the owner's 2026-09-20 correction, the batch had run
10 Opus / 12 Sonnet / 0 Haiku dispatches, two of them Opus work outside any guardrail path,
justified by "foundational" and "accuracy-critical" — which is not the rule.

## 9. Preconditions for the next phase

1. **GATE 2 judged on a live run.** Still pending — B27.
2. ~~B29 answered~~ — **done, 2026-09-27**: A6 promises normalised-comparability, so the
   post-render manifest and render-determinism test compare digests, not bytes.
3. The render stage must call `require_safe_to_render`.
4. **B34's setup run on the machine that renders** — `scripts/setup-dev-env.sh`, not just
   the fonts, must run wherever the render tests are trusted.

## 10. Verifying this phase from a cold start

```bash
uv sync
./scripts/setup-dev-env.sh

uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest -q -m "not live"
# expected: 1098 passed, 10 deselected

uv run autodeck components preview
# regenerates all 15 PNGs; they should be byte-identical to the committed ones.
# --only is repeatable, one name per flag.
```

## 11. Reading notes for the next implementer

**Read `callout_takeaway.py` first** — the simplest component — **then `layout_kit`'s
`Stack`.** The tier is decided by the path, not by how important the task feels: two Opus
dispatches over-tiered themselves on exactly that misjudgement before B32 corrected it.

**Open the PNG.** Three real layout bugs this phase were invisible to every automated
check and visible in one look at a rendered slide: the bold-budget under-prediction (§6.1),
the discarded `overflow_width` (§6.2), and the chevron label sitting in the unfilled notch
(§6.3). A green suite here is necessary and not sufficient.

**What looks wrong but is deliberate:** `sysClr`'s `lastClr` divergence and LibreOffice
dropping a chart's embedded workbook on re-save are not bugs to fix — they are the concrete
form B31 predicted PowerPoint/LibreOffice divergence would take, and both are outside a
headless environment's reach to patch or verify further (§6.5).

**What I would do differently:** the phase's recurring defect (§6.6) is always the same
shape — two descriptions of one thing, kept in sync by hand instead of one deriving the
other. Every instance this phase (catalog vs renderer, `ComponentSlot` vs `TextStyle`,
figure measurement vs drawing, `DiagramSpec.nodes` storage vs derived view) was found by a
test failing or a PNG looking wrong, never by inspection. The next phase that adds a second
description of something the catalog already knows should ask first whether it can be
derived instead.
