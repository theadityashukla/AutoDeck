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
  prompts/review.md       the slide reviewer's system prompt        (prompt author)
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

`--feedback qa` stops after step 5. `--feedback review` is described under "The reviewer".

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
- `--feedback review` and review-only mode add a reviewer model; see "The reviewer" below.
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

## The reviewer

The hypothesis under test: a separate model that looks at the rendered slide cold, with a
critique brief, catches flaws the deterministic checks cannot (a rule through a word, a
timeline running into a colour band, a label drifting from its figure) and says it specifically
enough for the designer to fix it. A designer shown its own render changes almost nothing.

### Contract (fixed)

- **One call per slide.** System prompt: `prompts/review.md`, read and sent exactly as it is
  (no placeholders). The reviewer sees neither the slide's JSON, nor the layout rules, nor
  earlier attempts.
- **User message**, one message, text then one image:
  1. `# Slide brief`: `Talking header:`, `Intent (...)`, `Content:` (Points, Key figures,
     Chart with series and emphasis), then, if the brief has any, `Notes from the brief's
     author:` (so the reviewer does not flag intended choices).
  2. `# Design concept`: Name, Concept, Rules, and the palette (every slot with its hex and,
     where given, its role). `None given.` when the concept is `none`. For a studio deck the
     design system's palette is listed and the slide brief's own notes are used.
  3. `# The rendered slide`: one sentence, then the image.
- **The image** is the slide render as a PNG, resized to 1600 pixels wide, sent as an
  `image_url` data URL (Chat Completions) or `input_image` (Responses). Same provider
  routing, `--reasoning`, `--max-output-tokens`, `prices.yaml` and budget-guard rules as for a
  designer; `--reviewer-reasoning` sets the reviewer's effort separately (default: `--reasoning`).
- **The answer** is one call to the tool `report`: `verdict` (`pass` | `revise`), `findings`
  (list of `{severity: blocking | minor, where, problem, fix}`, empty for a pass), `summary`
  (one sentence). A `revise` with no blocking finding is treated as a `pass` and recorded
  (`downgraded: true`, `raw_verdict: "revise"`). A `pass` that lists a blocking finding stays a
  pass and is flagged (`pass_with_blocking`). No call, or a call that fails validation: one
  nudge, then the review is recorded as `failed` (never as a pass). Only the first `report`
  call in a reply is read.
- The reviewer must not be the designer's model unless `--allow-self-review` is given.

### Mode 1: review-only

Reviews slides that already exist; nothing is designed. Input, any mix:

- `--review-dir DIR` (repeatable): every directory under DIR holding a `slide.png` (the final
  render; `slide.before.png` is ignored). The case and concept are recovered from
  `review-input.json` there (case and concept written out) or else from the bench
  `trial.json` (`case` and `concept` ids, looked up in `cases/` and `concepts/`). A directory
  from which neither can be recovered is an error. Unclean trials have no `slide.png` and are
  skipped.
- `--review-item image,case,concept` (repeatable): an explicit triple, ids from the bench.
- `--studio-deck current.json --studio-images s1.png s2.png ...` (one render per slide, in
  order; `--studio-slides 1,4` keeps only some): the converter writes
  `<out>/inputs/studio/<deck>-<nn>-<slide>/{slide.json, slide.png, review-input.json}`. The
  brief is the slide's `brief` (header, intent, content, notes); the concept is the deck's
  `design_system` palette (and `design_concept` if present).

Output under `--out`: `<reviewer>/<slide>/review.json` and `review.transcript.json` per
slide, `summary.json`, `summary.csv` (one row per slide: verdict, counts, summary, findings,
tokens, seconds, cost) and `sheet-review-<reviewer>.png`: each slide beside its verdict,
summary and findings as wrapped text, ten slides per page (`-p1`, `-p2`, ... when more).
The reviewer is refused if it is the model that designed a slide it is given (the
`trial.json` model) unless `--allow-self-review`.

### Mode 2: `--feedback review` in a full trial

After the designer produces a clean slide and it is rendered, the reviewer is called.

- `pass`: stop.
- `revise`: the designer's next message (text only, no image) is the reviewer's summary and
  its findings, formatted plainly and verbatim: `BLOCKING findings (fix these)` then
  `MINOR findings (optional)`, each as Where / Problem / Fix. The designer revises under the
  same validation and layout QA, one retry, exactly as `visual` does. If the revision is clean
  and renders, the revised slide is rendered and reviewed once more; the second verdict is
  recorded and the loop ends there, whatever it says. If the revision fails or the designer
  does not revise, the earlier slide stays and there is no second review.
- A failed review or a budget stop before a review leaves the (clean) slide and the trial
  status untouched; the review is recorded as `failed` or `budget_stopped`.

Options: `--reviewer provider:model` (required), `--allow-self-review`,
`--reviewer-reasoning`. The reviewer needs a price in `prices.yaml` (or `--allow-unpriced`).

Per trial, under `<out>/<model>/<case>/<concept>/review/r<n>/`: the usual files, plus
`slide.before.png` and `slide.before.json` when revised, and for each review
`review-1.json` / `review-1.transcript.json` (and `review-2.*`). `review-N.json` holds the
verdict, findings, summary, tokens, seconds, estimated cost and the raw tool call; the
transcript has the image replaced by its file name.

`trial.json` gains `review` (`first_verdict`, `revised`, `revision_clean`, `second_verdict`,
and the full `first` / `second` summaries) and, separate from the designer's `cost_usd`:
`review_cost_usd`, `review_calls`, `review_input_tokens`, `review_output_tokens`,
`review_seconds`, and `total_cost_usd`. `summary.json` and `summary.csv` carry the same
(`review_cost_usd`, `total_cost_usd`, `review_first`, `review_revised`,
`review_revision_clean`, `review_second`; per model a `reviews` block with counts of first and
second verdicts, downgrades, failures and budget stops). The budget guard counts designer and
reviewer spend together; skipped reviews are listed in `summary.json` under
`budget.reviews_skipped`.

Contact sheets: the usual `sheet-<model>.png` (its cells say `review: revise > revised >
pass`), and `sheet-reviewed-<model>.png`: one row per trial, before and after side by side
when a revision happened, the first verdict with its findings, the designer revision
outcome, the second verdict, all as wrapped text at a readable size.

### Running it

```
# review-only, all existing slides (round-1 bench trials and the studio deck)
python bench/slides/run.py --reviewer openai:gpt-5.6-terra --budget 6 --out <dir> \
  --review-dir <round1> \
  --studio-deck <current.json> --studio-images <7-final-s1.png> ... <7-final-s4.png>

# the full loop, eight cases, one concept
python bench/slides/run.py --env-model openai:gpt-5.6-sol --reviewer openai:gpt-5.6-terra \
  --cases all --concepts demand-curve --feedback review --budget 10 --out <dir>
```
