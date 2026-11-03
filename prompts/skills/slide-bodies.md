---
name: slide-bodies
summary: What goes under the headline — one idea per slide, matching the claim to the component, a body recipe for every component, writing to fit on the first try, splitting instead of shrinking, speaker notes
use_when: choosing a component and writing the blocks of any content slide
---

# Slide bodies

The headline makes the claim; the body proves it. A content slide with a headline and no body
is an assertion with nothing behind it, and it is the most common way a draft fails: the body
blocks were written too long, or as copies of the source, or with quotes that did not
resolve, and they were dropped. This skill is about writing bodies that survive.

## Rules that apply to every slide

1. **One idea per slide.** The headline states it; every body block supports it. A block that
   supports a different point belongs on a different slide.
2. **Every content slide has a body, and the body is substantial.** A slide whose headline
   has no cited block beneath it is never an acceptable output. A pre-read slide must stand
   alone, so a content slide normally carries **35 to 70 words of body**: three to five
   points, each a complete short sentence with its number and condition, or the equivalent in
   a figure, label and support text. Two points is the floor, not the target. If the evidence
   honestly has only one point, use `big_number` or `callout_takeaway`, and fill their
   `support` slot. If you cannot write an honest body at all, change the component, merge the
   slide, or remove it and record why in `coverage`. The `exemplars` skill shows the
   density.
3. **The body carries the headline's facts.** Every number, name and comparator in the
   headline appears in a cited body block on the same slide (see `headlines`).
4. **Choose the component for the claim's shape,** not for variety (table below).
5. **Write to the target on the first pass.** Each slot shows a target (*"aim ≤ N
   characters"*) and a ceiling (*"at most L lines, roughly M characters"*). The ceiling is
   measured in the real font, and a block over it is **rejected, not shrunk**. Write to the
   target. Count the characters of every list item before you answer. Long words fill a line
   faster than the average suggests.
6. **Split, don't shrink.** When an honest sentence will not fit: split it into two items,
   move a condition into the label, or pick a component with more room. Never drop the
   qualifier, the population or the comparator to save characters.
7. **Keep the hedge beside the number.** A qualifier goes in the same block as the figure, or
   in the label right next to it. Not in a footnote, not in the notes alone.
8. **Leave optional slots empty rather than pad them.** An empty optional slot is fine. A
   sentence written to fill space is not.

## Match the claim to the component

| The slide's point is… | Use | Not |
|---|---|---|
| One well-supported figure that carries the whole point | `big_number` | …when the evidence behind the figure is thin: a giant number claims certainty |
| Several parallel metrics, none dominant | `data_card_grid` | …when each metric needs a long condition to be honest |
| A pattern in values across groups or time, all stated in the evidence | `chart_focus` | …when you would have to read values off a figure, interpolate or round |
| Two options or arms on the same dimensions | `two_column_compare` | …when the two sides are not comparable point for point |
| A change from one state to another | `before_after` | …when there is no real "before" |
| Three to eight parallel supporting points | `bullets_supporting` | …when one point dominates, or the points happen in order |
| Steps whose order is the point | `timeline` (dated) / `framework_diagram` | …when the steps could be shuffled; that is a list |
| Three or four ideas to remember as a set | `icon_pillars` | …when each idea needs evidence beside it to be true |
| One implication that must stand alone | `callout_takeaway` | …when it would repeat the previous headline |
| Someone's exact words carry the weight | `quote` | …when it is just a sentence from a paper; that is a claim |
| A figure in the source is itself the argument | `evidence_with_figure` | — |

**Vary the rhythm because the content varies.** Three `bullets_supporting` slides in a row
usually means three slides of content that has a more specific shape: a comparison, a number,
a sequence. Look again.

## Body recipes, component by component

The numbers below are the current theme's budgets, for orientation. **The budget list you are
given is authoritative.** Slot kinds follow the `citations` skill: a fact is a `claim`, a name
or label is `framing`.

### `bullets_supporting`
- `headline`: talking header, ≤ 88 characters.
- `points`: **3 to 5 claim blocks**, one per item, **each ≤ 90 characters, one line**. Each
  is one short, complete, cited statement: subject, verb, number with its condition. No
  sub-clauses, no "and also".
- Aim for 3 to 5 points. Use 2 only when the evidence has no more. With only 1, use
  `big_number` or `callout_takeaway` instead.
- A comparison works well here as one point per comparator: *"vs comparator C (ALPHA-3):
  0.8 to 2.1 kg more lost by week 24, by dose"*.

### `big_number`
- `headline`: ≤ 88 characters.
- `figure`: **one claim, ≤ 26 characters**: the number and its sign or unit only (*"−1.3%"*,
  *"29 ms"*, *"3.2×"*), cited.
- `figure_label`: ≤ 66 characters: what the number measures, for whom, when (*"HbA1c change
  at week 24, 10 mg, adults on metformin"*). If the label contains a number or a named study,
  it is a **cited claim**, not framing.
- `support` (optional, but fill it): ≤ 543 characters. The comparator, the hedge, the
  second figure. A big number without its support text is a number without its meaning.
- With `supporting_points`, everything narrows: `figure` ≤ 12, `figure_label` ≤ 31, points
  ≤ 42 each.

### `data_card_grid`
- `headline`: **≤ 43 characters, one line**: a 6- to 7-word talking header.
- `card_value`: 2 to 6 claim blocks, **each ≤ 8 characters** (*"−1.6%"*, *"24 wk"*).
- `card_label`: one per card, same order, **each ≤ 33 characters**. A label that names a dose,
  a week or a study is a cited claim.
- Use it only when each metric's condition fits in 33 characters. Otherwise use
  `bullets_supporting`.

### `chart_focus`
- `headline`: ≤ 88 characters: what the shape of the data shows.
- `chart`: one `chart` block (see `charts-and-diagrams`). Every value is stated in the
  evidence and cited in `source_citations`.
- `takeaway` (optional): one line, ≤ 90 characters. The hedge or the scope (*"24-week
  trials; adults on metformin; doses as labelled"*).

### `two_column_compare`
- `headline`: ≤ 88 characters: the verdict of the comparison.
- `left_title`, `right_title`: ≤ 27 characters each: the two things compared (framing).
- `left_points`, `right_points`: **up to 6 each, ≤ 37 characters each**. That is very short:
  *"HbA1c −1.6% at wk 24"*, not a sentence. Put matching dimensions in the same order on both
  sides. Each point is a cited claim.
- **Every point names its side.** The column title is drawn above the point, but the claim
  is checked, quoted and audited on its own, without the title. "No fasting requirement"
  under "Subcutaneous" reads, alone, as a claim about the drug the deck is about. Open the
  point with a short label (*"s.c.: no fasting rule"*, *"Oral: −1.4% HbA1c, wk 26"*) or put
  the subject in the sentence. A point the evidence states only for one side is never written
  for the other side by inference: "the oral form needs fasting" does not prove "the
  injection does not".
- **Use it only when every point really fits in about 37 characters with its condition.**
  Live run XLP forced this layout onto a drug comparison and got fragments like "Weight loss:
  less", which no reader or validator could interpret. A comparison whose points need
  conditions belongs in `bullets_supporting`, with one "vs X:" point per comparator.
- Single `left_point` / `right_point` slots exist for one-line sides.

### `before_after`
- `headline`: **≤ 43 characters, one line**.
- `before_label`, `after_label`: ≤ 31 characters.
- `before_text`, `after_text`: ≤ 477 characters each. Room for a short paragraph with its
  conditions. Each is a cited claim, or framing if it states no fact.

### `callout_takeaway`
- **No headline slot.** `label`: ≤ 106 characters, a short framing tag (*"What this means for
  the formulary"*).
- `takeaway`: ≤ 80 characters, large type: the one point. A cited claim, or a labelled
  implication (framing beginning "Implication:") when it is your inference.
- `support` (optional): ≤ 820 characters: the evidence behind it, cited.

### `icon_pillars`
- `headline`: **≤ 43 characters, one line**.
- `pillar_label`: 3 or 4 items, ≤ 16 characters each (framing).
- `pillar_point` (optional): one per pillar, ≤ 34 characters, two lines.
- Use it when the pillars are names to remember, not findings to prove.

### `evidence_with_figure`
- `headline`: **≤ 43 characters, one line**.
- `supporting_text`: ≤ 555 characters: the claim and its conditions, cited.
- `figure` (optional): ≤ 558 characters, italic: what the source figure shows, as a cited
  claim that quotes the source's own text about it. Never quote a generated figure
  description.

### `timeline` / `framework_diagram`
- `headline`: ≤ 88 characters.
- `diagram`: one `diagram` block, 2 to 6 steps, **labels and transitions ≤ 4 words**. A
  longer label drops the whole diagram.

### `quote`
- `headline`: ≤ 88 characters: why the quote matters.
- `quote`: ≤ 67 characters: the person's exact words, cited to where they said them.
- `attribution`: who said it, in what role (framing).

### Structure slides
- `title`: `title` ≤ 47 characters (the deck's answer or question); `subtitle` ≤ 41.
- `agenda`: `headline` plus up to 5 `items`, ≤ 88 characters each.
- `section_divider`: `section_name` only, a few words.
- `closing_cta`: `headline` ≤ 88 characters (the ask); `cta` ≤ 64 characters (the action, as
  framing).

## Worked failure: Xls, slide 5 (live run 1)

The model chose `bullets_supporting` under the topic label *"Safety and Tolerability of Oral
Semaglutide"* and wrote three bullets of 92, 132 and 101 characters, each a near-copy of a
source sentence. The ceiling was one line of about 88 characters. All three were rejected and
the slide shipped as a headline alone.

The same evidence written to the recipe:

| Rejected (132 characters) | Written to fit (≤ 90) |
|---|---|
| "Gastrointestinal adverse events (nausea, vomiting, diarrhea) are the most prevalent, but generally transient and decrease over time." | "Nausea, vomiting and diarrhea were the most common side effects, usually transient" (82) |

The rewrite keeps what was measured (the three side effects), the ranking ("most common") and
the hedge ("usually transient"). It drops nothing that changes the meaning. The headline
becomes a talking header the bullets carry: *"Side effects were mostly gastrointestinal and
usually transient"*.

## Speaker notes

Notes are where the presenter's depth goes: the configuration that did not fit, the second
number, the full caveat, the answer to the obvious question. Every fact in them is a cited
claim block, exactly like the face.

Notes **add**; they never hold a slide's only qualifier. If a limit changes what the face
claims, it goes on the face. Most readers never open the notes.
