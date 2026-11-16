---
name: charts-and-diagrams
summary: Choosing and filling a chart or a diagram honestly — chart type by question, perceptual accuracy, honest scales, direct labels, one focal series, diagrams only for real order; the chart and diagram block formats
use_when: any slide with a chart_focus, timeline or framework_diagram component, or when deciding whether a slide should be a chart
---

# Charts and diagrams

A chart is a dense set of factual claims, drawn. A diagram is a claim about how things relate.
Both are powerful, because the eye reads them before it reads a word, and dangerous for the
same reason: a misleading picture misleads faster than a misleading sentence.

## When a chart earns its place

Use `chart_focus` when **the shape of the data is the argument**: a trend, a ranking, a gap
between groups. **Every value must be stated in the evidence as text or a table.** You may
not:

- read values off a figure or image,
- interpolate a point between two that are stated,
- round values to make them tidy,
- combine values from sources with different conditions into one series as if comparable.

If you cannot fill every value honestly, use `bullets_supporting` or `data_card_grid` with the
values you do have.

## Chart type by question

People judge **position on a common scale** most accurately, then length, then angle and area
much less accurately. Choose the encoding that makes the slide's comparison easiest to read.

| The question | Chart | Avoid |
|---|---|---|
| How do these groups compare? | `bar` (horizontal, for long category names) or `column` | `pie` |
| How did this change over time? | `line` (many points) or `column` (few periods) | `area` for a single series |
| What share of the whole? | `stacked_bar`, or `pie` **only for 2–3 slices** | `pie` with many slices |
| Do two measures move together? | `scatter` | Implying cause from it |

## Honest scales

- **Bars and columns start at zero.** A truncated axis exaggerates differences: a 3% gap drawn
  as a doubling. The size of the effect in the picture should match its size in the data.
- **No 3D, no decorative depth,** no area used for a linear quantity.
- **Negative values are real values.** A reduction (−1.3%) is plotted as negative, not flipped
  to positive, unless the axis label says "reduction" and every value is converted the same
  way, as stated in the source.
- **One unit per axis.** Do not put percent and percentage points, or two different metrics,
  on one axis.

## Labels and emphasis

- **Label the data directly.** Name series and categories so the reader does not hunt in a
  legend. Keep category names short.
- **One focal series.** If the headline is about one series (drug A vs the comparators),
  that series is the point. Name the others plainly and keep them secondary. Colour is
  applied in rendering; your job is to make the focal series obvious from the names and the
  headline.
- **Axis labels carry the unit and the measure** (*"HbA1c change from baseline, %"*), not just
  a word.
- **The takeaway carries the scope** (*"Week 24; 10 mg; adults on metformin"*).

## The chart block

```json
{"id": "b2", "kind": "chart", "slot": "chart", "text": "", "claim": null, "diagram": null,
 "chart": {"chart_type": "column", "title": "",
   "categories": ["ALPHA-2", "ALPHA-3", "ALPHA-4"],
   "series": [{"name": "Drug A 10 mg", "values": [-1.6, -1.4, -1.5]},
              {"name": "Comparator", "values": [-1.1, -0.8, -1.2]}],
   "x_axis_label": "", "y_axis_label": "HbA1c change at week 24, %",
   "source_citations": [{"doc_id": "...", "quote": "..."}]}}
```

(Shape illustration only; drug A, the ALPHA trials and the values are invented.) Every value appears in a passage cited in
`source_citations`. Cite enough passages to cover every value, each its own verbatim run.

## Diagrams: only for real order

A diagram claims that its boxes relate as drawn. Use one **only when the relationship is real
and stated in the evidence**: a sequence of steps, stages over time, a process. If the items
could be shuffled without losing anything, they are a list. Use `bullets_supporting` or
`icon_pillars`, not a diagram that implies order or flow that is not there.

Today the system draws **process flows**: two to six steps that happen in order.

```json
{"id": "b2", "kind": "diagram", "slot": "diagram", "text": "", "claim": null, "chart": null,
 "diagram": {"relationship": "sequence", "title": "",
   "steps": [
     {"id": "n1", "order": 1, "label": "Screen eligible patients", "transition": "",
      "status": "framing", "claim": null, "framing_reason": "stage_name"},
     {"id": "n2", "order": 2, "label": "Start at 3 mg", "transition": "",
      "status": "claim", "framing_reason": "",
      "claim": {"text": "Treatment starts at 3 mg once daily for 30 days.",
                "citations": [{"doc_id": "...", "quote": "..."}]}}
   ]}}
```

- **Every step says what kind of label it is, in `status`, first.** Use `status: "claim"`
  when the label asserts something about the world: fill `claim` exactly as for a claim block,
  and set `framing_reason` to `""`. Use `status: "framing"` when the label only names
  something: set `framing_reason` to `stage_name`, `actor_name`, `artefact_name`,
  `category_name` or `question`, and set `claim` to `null`.
- **Framed labels, the title and every `transition` are fenced like framing blocks:** no
  numbers, no named studies, no comparisons. Declaring "40% cheaper" a `category_name` does
  not make it one.
- **Labels are at most four words. `order` runs 1, 2, 3… with no gaps.** `transition` names
  what happens on the arrow, or is `""`.
- **A diagram is all or nothing.** If one step's citation fails to resolve, or one label is
  too long, the whole diagram is dropped. Keep it small and check every step.
