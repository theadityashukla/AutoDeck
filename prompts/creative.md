# Creative mode: you design each slide

In this run there is no component catalog. You write each slide's blocks exactly as you
would anywhere else (talking header, cited claims, charts, diagrams, framing), and then you
**place them yourself** in the slide's `layout`. The `slide-design` skill is how to design
well. This file is the contract: what you may write and what code checks.

## What stays exactly the same

- **Every word on the slide is a block.** Claims carry citations, framing is framing, the
  header is a `section_header`. A1, A2 and the validator see your blocks exactly as they
  would in a structured deck. The layout holds no text at all.
- The content slide's talking header is the block with `kind: section_header` and
  `slot: "headline"`. The title slide's line is `slot: "title"`. A callout's point is
  `slot: "takeaway"`. Other blocks may use any short descriptive slot name (`body`,
  `figure_label`, `takeaway_1`, `kicker`); it names the block's job, nothing more.
- The source line is drawn by code at the bottom of the safe area on every slide that
  cites something. Never write one, and keep the reserved band shown in **The master**
  clear.

## The layout

Set `component` to `free_layout` and give the slide a `layout`:

- `background`: a colour token (default `lt1`).
- `elements`: drawn back to front, so put panels and bands first and the text that sits on
  them after.
  - **`text`**: `block_id`, `frame`, `role` (`display`, `title`, `heading`, `body`,
    `caption`, `label`), optional `size_pt` (only for a deliberate big number or a
    one-line statement), optional `bold`, `color` (a token), `align` (`left`, `center`,
    `right`) and `anchor` (`top`, `middle`, `bottom`).
  - **`chart`**, **`diagram`**, **`figure`**, **`icon`**: `block_id`, `frame`, `accent`
    (a token), and for a chart, `emphasis`: the categories to draw in the accent, copied
    exactly from the chart. Everything else is drawn in a neutral.
  - **`shape`**: `shape` (`rect`, `rounded_rect`, `ellipse`, `line`), `frame`, `fill`
    and/or `line` (tokens), `line_pt`, and `tint` (0 to 0.95, which mixes the fill toward
    the background; 0.85 to 0.92 makes a quiet panel). A shape has no text.
- `rationale`: one sentence on why the slide is designed this way. It is never shown on
  the slide; the person and the gold exemplars read it.

A `frame` is `x`, `y`, `w`, `h` in **percent of the slide's width and height**, from the
top-left corner. `{"x": 5, "y": 8, "w": 60, "h": 12}` is a box starting 5% in and 8% down,
60% of the width wide and 12% of the height tall.

**Every face block must be placed exactly once**, as what it is: text blocks in `text`
elements, a chart block in a `chart` element, and so on. A block you do not place is
removed from the slide, and you will be told. Speaker notes are never placed.

## What code checks, on the real render

Your layout is drawn in the client's real fonts and measured. These fail the slide and
come back to you to fix:

- text that does not fit its frame at its size (make the frame bigger or the text shorter;
  text is never shrunk for you);
- text outside the master's safe area (shapes may run to the edge; text may not);
- a text frame overlapping another text frame or a visual, or two visuals overlapping;
- anything in the reserved source band;
- text smaller than the master's minimum;
- text with too little contrast against what is beneath it: 4.5:1, or 3:1 at 24pt and
  above. The palette in **The master** gives each token's colour so you can judge this.

## A worked example

A big-number slide, for an invented drug A. The header sits top-left, the number dominates
the left half, and what it measures sits beside it over a quiet panel:

```json
{
  "id": "s6",
  "narrative_role": "risk",
  "component": "free_layout",
  "intent": "show that cardiovascular risk was not raised, and that no benefit was shown",
  "message_ids": ["km3"],
  "blocks": [
    {"id": "h1", "kind": "section_header", "slot": "headline",
     "text": "Heart risk wasn't raised, but a benefit wasn't shown either"},
    {"id": "b1", "kind": "claim", "slot": "figure",
     "claim": {"text": "HR 0.81", "citations": [{"doc_id": "alpha-review", "quote": "…(HR 0.81; 95% CI 0.60-1.09)…"}]}},
    {"id": "b2", "kind": "claim", "slot": "body",
     "claim": {"text": "Hazard ratio for major cardiovascular events against placebo in ALPHA-6; the interval crosses 1", "citations": [{"doc_id": "alpha-review", "quote": "…"}]}}
  ],
  "speaker_notes": [],
  "layout": {
    "background": "lt1",
    "elements": [
      {"type": "shape", "shape": "rect", "frame": {"x": 56, "y": 34, "w": 38, "h": 40}, "fill": "accent1", "tint": 0.9},
      {"type": "text", "block_id": "h1", "frame": {"x": 5, "y": 8, "w": 80, "h": 16}, "role": "title"},
      {"type": "text", "block_id": "b1", "frame": {"x": 5, "y": 32, "w": 48, "h": 44}, "role": "display", "size_pt": 150, "color": "accent1", "anchor": "middle"},
      {"type": "text", "block_id": "b2", "frame": {"x": 59, "y": 40, "w": 32, "h": 28}, "role": "body", "anchor": "middle"}
    ],
    "rationale": "One number is the whole point, so it gets half the slide; the panel ties its explanation to it without a border."
  }
}
```

The big number is a cited claim like any other. A number on the face is never framing.
