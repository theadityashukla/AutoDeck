---
name: from-source-to-slide
summary: Turning dense source material into slides that communicate — the five transformations (lift, condense, visualise, synthesise, reframe), the sentence-vs-quote mechanic, finding the core idea, reusing slides from existing decks
use_when: writing or rewriting any content slide from documents, notes or an existing deck
---

# From source to slide

The source was written for a different reader, at a different length, for a different
purpose. Your job is to carry its facts across to this audience **intact in meaning and
reshaped in form**. A slide that copies the source is not faithful, it is just long. A slide
that drops the source's conditions is not clear, it is wrong. The craft is in between.

## The key mechanic: your sentence, their quote

Every factual block has two parts, and they are different on purpose:

- **`claim.text`: the slide sentence.** Yours. Written for the audience, as short as the
  slot's target, in plain words, carrying every condition that makes it true.
- **`citations[].quote`: the proof.** The source's words, copied exactly: the shortest
  unbroken run of one passage that says what your sentence says.

The checker resolves the quote in the source. The validator then reads your sentence against
the source and asks whether it says the same thing at the same strength. Paraphrase is
expected: **a different wording is not a fidelity problem; a different meaning is.**

> **Source passage** (invented, like every example in these skills): *"In ALPHA-2, drug A
> 10 mg was superior to comparator B in reducing HbA1c at week 24 (−1.6% vs −1.1%), while
> reductions in body weight were similar between groups."*
>
> **Copying it** (wrong): a 210-character bullet into a 90-character slot. Dropped. The slide
> has a headline and nothing under it.
>
> **Two slide sentences** (right), each with its own short quote:
> - `claim.text`: *"At week 24, HbA1c fell 1.6% on drug A 10 mg vs 1.1% on
>   comparator B"* · quote: *"in reducing HbA1c at week 24 (−1.6% vs −1.1%)"*, a run long
>   enough to contain every number the sentence states.
> - `claim.text`: *"Weight loss was similar between the two"* · quote: *"reductions in body
>   weight were similar between groups"*

Notice: the numbers are copied exactly. The dose, the comparator and the week are kept. The
word "superior" was not needed. The tie on weight survived as its own point.

## The five transformations

Choose one deliberately for each block. Most slides use condense or visualise; most decks use
all five somewhere.

### 1. Lift: stay near-verbatim

**When:** the exact words carry weight a paraphrase would lose, or someone requires them:

- a **quotation** from a person (the `quote` component), where the words are the evidence;
- the **client's own wording**, when they asked to keep it (see `reworking-decks`);
- **regulated claims**: an approved indication, a label statement, a safety warning, a
  contractual or legal term, a definition someone will hold you to. In a strict
  (MLR-reviewed) deck, wording that defines what may be claimed stays as the source has it;
- a **definition** the rest of the deck depends on.

**What may change:** only trimming at the edges, and only by deleting words, never by
substituting them. **What may not:** everything else.

Lifting is the exception. If you notice that most of your blocks are lifted, you are
transcribing, not communicating.

### 2. Condense: same claim, fewer words

**When:** almost always. Source sentences run 30 to 60 words; a bullet target is 37 to 90
characters.

**How:** keep the subject, the measured quantity, the number and unit, the direction, the
comparator, the population or setting, and the hedge. Cut everything else: method detail that
does not change the meaning, restated context, adjectives, "it was observed that", "notably".

> Source: *"In a cohort of 400 enterprise clients, those who implemented the automated
> reporting module experienced an average reduction in weekly hours spent on compliance tasks
> of roughly 15%, though results varied significantly depending on legacy infrastructure."*
> (illustrative)
>
> Condensed: *"Clients using automated reporting spent ~15% fewer weekly hours on
> compliance"* plus a second item, *"Results varied with legacy infrastructure"*. Or, as a
> big number: figure *"−15%"*, label *"weekly compliance hours, 400 enterprise clients,
> average"*, support *"Varied with legacy infrastructure; an association, not a tested
> cause"*.

If a condensed sentence will not fit with its conditions, **split it** into two items, or move
the condition into a label or a second block. **Never drop the condition to make it fit.**

### 3. Visualise: from prose to a picture of the point

**When:** the point is a number, a comparison, a change, a trend, a sequence or a structure,
and the source states it in a paragraph. A slide is not a page; if the claim is quantitative
or structural, show it.

| The source says, in prose… | The slide shows… |
|---|---|
| One headline figure with its conditions | `big_number`: the figure large, its label and conditions beside it |
| Three to six parallel metrics | `data_card_grid`: one card per metric |
| Two options or arms weighed on the same dimensions | `two_column_compare`, or a bar chart |
| Values across groups or over time, all stated in the text | `chart_focus` with a bar, column or line chart |
| A state before and a state after | `before_after` |
| Steps in a fixed order | `timeline` or `framework_diagram` |
| Three or four parallel ideas to remember as a set | `icon_pillars` |

The words do not disappear when you visualise. They move into the labels, the takeaway and
the scope tag, and they get shorter. A chart's values must all be stated in the evidence: you
may not read values off a figure, interpolate, or round (see `charts-and-diagrams`).

### 4. Synthesise: several passages, one point

**When:** the slide's point is a pattern across several findings: four trials, three
benchmarks, two quarters.

**How:**

- **One block per finding**, each cited to its own passage. The header states the pattern.
  This is the safest form, and usually the clearest.
- **One block with several citations** when one sentence genuinely rests on several passages
  (*"Both ALPHA-2 and ALPHA-3 ran 24 weeks in metformin-treated adults"*). Each citation
  is its own unbroken quote.
- **A declared derivation** when the synthesis is a computed number (a difference, a total, a
  ratio). Show the working (see `citations`). Never compute in prose.

What synthesis may never do: average two sources that disagree, widen a range to cover both,
or state a trend the sources do not state. If two sources disagree, show both, each with its
conditions.

### 5. Reframe: for this audience, this decision

**When:** always, in some measure. The same finding is told differently to a payer, a
clinician, an engineer and a CFO. Not different facts: a different emphasis, vocabulary,
order and "so what".

- **Lead with what this audience decides on.** A payer reads cost and population first; a
  clinician reads efficacy, dose and safety; an executive reads the decision and the risk.
- **Use their vocabulary.** Replace the source's jargon with the audience's word when the two
  mean the same thing. Define a necessary technical term once, at first use. Keep a term of
  art the audience already uses.
- **State the implication, and label it as yours.** The source says what was found; the
  audience needs to know what it means for them. When the "so what" is your inference rather
  than the source's statement, write it as a separate `framing` block beginning
  **"Implication:"** (see `fidelity`). Never fold your inference into the cited sentence.
- **Choose the level of detail by the decision.** If a detail would not change what the
  audience does, it goes to the notes or the appendix, unless it is a qualifier that limits
  a claim on the slide. Qualifiers stay.

> Same finding, two audiences (invented, about a fictional model M):
> - **Engineering lead:** *"Sharing one key-value cache across heads cut model M's serving
>   memory enough to run 8× larger batches on the same chips"* (mechanism and capacity).
> - **CFO:** *"The same hardware served far more requests at once after one architectural
>   change"*. Careful: "far more" must still be carried by a cited number on the slide, and
>   "cost" must not appear if the paper measured memory, not cost.

## Find the core idea, not the most quotable line

The most striking sentence in a source is often not its main finding. It is a secondary
result, an aside in the discussion, or the authors' most optimistic phrasing. Before
building a slide from a source:

1. Find the source's **own summary statements**: abstract, conclusion, stated limitations.
2. Identify the **primary outcome** and what the authors conclude about it. Treat exploratory
   or secondary results as such, and say so if you use them.
3. Write the core idea to yourself as: *who/what, measured how, how much, which direction,
   under what conditions, how certain, according to whom*.
4. Check your slide sentence against **that**, not against the quotable line. If your
   sentence is broader than the source's own conclusion, it is wrong, however well it
   matches some line in the text.

## Reusing slides from an existing deck

Consulting decks are often part old, part new: a few slides lifted from an earlier deck, the
rest built fresh. When the evidence includes an existing deck:

- **Its facts are evidence like any other,** cited verbatim from the slide they appear on.
  Its *structure* (what each slide was for, how the argument ran) is a strong suggestion, not
  a rule.
- **Reshape a lifted slide for the new audience.** A slide that worked for an operations
  review may need a different headline, emphasis or component for a board. The facts stay
  exactly as stated; the framing is new. If the old slide's headline was a topic label, give
  it a talking header from what that slide states.
- **Never let an old slide's claims grow.** If the old deck said "pilot", the new slide says
  "pilot". If its figure was from 2023, the new slide says so.
- **Make old and new consistent.** One name per concept across both (see `writing-style`),
  one style of headline, and the same figure everywhere for the same thing. If the old deck
  and a newer source disagree, show both, with dates.

## Signs you are copying, not communicating

- A body sentence is nearly identical to its quote.
- Bullets run past their target and end mid-thought.
- The slide uses the source's section headings as its headlines.
- Every slide is `bullets_supporting`.
- The audience would need to have read the source to follow the slide.

When you see one, go back to the core idea and write the slide sentence fresh, for the
reader.
