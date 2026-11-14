# Slide bench — spec

A slide-level test of design ability. One trial gives a model **one slide** to design and
gets back one rendered slide. It exists because the slide is the unit: if a model cannot
design one good slide, it cannot design a deck. Research, storyline and the studio's tool
loop are deliberately out of the picture.

It is a measuring tool, not product code. It may import from `autodeck.studio` and v2, and
must not change either.

## Layout

```
bench/slides/
  SPEC.md                 this file
  prompts/slide.md        the slide designer's system prompt        (prompt author)
  cases/<id>.yaml         one slide brief each                       (prompt author)
  concepts/<id>.yaml      one design direction each                  (prompt author)
  run.py                  the harness                                (harness author)
  prices.yaml             assumed price per model                    (harness author)
  tests/                  harness tests, no network                  (harness author)
```

Results are written outside the repository, to the directory given by `--out`.

## A case (`cases/<id>.yaml`)

The content is already written; the model designs, it does not research.

```yaml
id: s4-quantisation            # file name without extension
title: Quantisation alone cuts serving cost by 38%   # the slide's talking header
intent: >                      # what the slide must make the audience conclude
  The single biggest saving comes from one technique.
content:                       # everything the model may put on the slide
  points:                      # short text items, may be empty
    - "Monthly serving cost falls from $412k to $255k"
  figures:                     # key numbers, each with a label, may be empty
    - {value: "38%", label: "lower serving cost"}
  chart:                       # optional data for one chart
    kind: bar                  # bar | column | line
    categories: ["Before", "After"]
    series:
      - {name: "Monthly cost ($k)", values: [412, 255]}
    emphasis: ["After"]        # optional
notes: ""                      # optional hints about what matters; not rendered
```

## A concept (`concepts/<id>.yaml`)

A design direction, the stand-in for Phase 3's design concept and design system.

```yaml
id: shelf-price
name: Shelf price
concept: >                     # one or two sentences: the visual idea
  ...
rules:                         # three to five short statements
  - "..."
palette:                       # hex per theme slot; omitted slots keep the default
  dk1: "#0B2A22"
  lt1: "#FFFFFF"
  dk2: "..."
  lt2: "..."
  accent1: "..."
  # accent2 .. accent6
roles:                         # what each slot is for, shown to the model
  accent1: "the price ticket"
```

`concepts/none.yaml` has `id: none`, an empty concept, no rules and no palette: the
default tokens (`config/tokens/dev.json`) and no stated direction. It is the control.

A concept changes colours only. Fonts stay those of the default tokens, because only
installed fonts can be measured and rendered.

## What the model is given

1. **System:** `prompts/slide.md`, with these placeholders filled by the harness:
   `{{MASTER}}` (slide size, safe area, the type roles with their point sizes, the minimum
   type size, the source band if any), `{{PALETTE}}` (each theme slot's name and hex, with
   the concept's role for it where given), `{{VOCABULARY}}` (the elements and fields the
   layout accepts, generated from the models, not hand-written).
2. **User:** the case (title, intent, content, notes) and the concept (name, concept,
   rules), rendered as plain text.
3. **One tool, `write_slide`,** whose argument is one studio `Slide` (blocks and a free
   layout). The model must call it.

## One trial

For a `(model, case, concept, feedback)`:

1. Call the model. If it does not call `write_slide`, nudge once, then fail the trial.
2. Validate the slide. A validation error is returned to the model as the tool result.
3. Run layout QA (`autodeck.studio.render_adapter.check_slide`) with the concept's tokens.
   Findings are returned to the model as the tool result.
4. Repeat 1–3 up to `--attempts` model calls in total (default 4). The trial is **clean**
   if a slide passes validation and QA.
5. Render the last slide to PNG if it is clean. An unclean trial records its findings and
   renders nothing.
6. **Visual feedback** (`--feedback visual` only, and only for a clean slide): send the
   rendered PNG back to the model with the question "This is the rendered slide. If it can
   be clearly improved, call write_slide once more; otherwise reply DONE." One revision at
   most, itself subject to steps 2–3 with one retry. Keep both renders (before and after).

`--feedback qa` stops after step 5.

## Harness (`run.py`)

```
python bench/slides/run.py \
  --env-model openai:gpt-5.4-mini [--env-model ...] \
  --cases all | id,id \
  --concepts none,shelf-price \
  --feedback qa | visual \
  --attempts 4 \
  --budget 5.00 \
  --out <dir> \
  [--repeat 1] [--dry-run]
```

- Models are named `provider:model` and resolved through v2's provider classes. The key
  is read as the provider adapter reads it.
- **Budget guard:** before every model call, estimate the spend so far from recorded token
  counts and `prices.yaml`; refuse to start a call once the estimate has reached
  `--budget`, finish cleanly, and say what was skipped. A model missing from `prices.yaml`
  is refused unless `--allow-unpriced` is given.
- `--dry-run` builds every request and writes it to `--out` without calling a model.
- Output per trial, under `<out>/<model>/<case>/<concept>/<feedback>/r<n>/`:
  `slide.json`, `slide.png` (and `slide.before.png` for a visual revision),
  `trial.json` (attempts, each attempt's validation error or QA findings, model calls,
  input and output tokens, seconds, estimated cost, clean or not, element counts by type),
  and `transcript.json` (the messages, with images replaced by their file names).
- Output per run: `summary.json` and `summary.csv` (one row per trial), and one contact
  sheet per model, `sheet-<model>.png`: rows are cases, columns are
  concept × feedback, each cell labelled; an unclean cell shows its findings as text.
- No response cache: every trial is a fresh call.
- Never print or store a key.

## What a result means

The bench does not score. The lead looks at the contact sheets. Numbers it does report:
clean rate, attempts to clean, tokens and cost per slide, and element counts (how many
text, shape and chart elements), which show whether a model used the layout or stayed
with text on white.
