---
name: self-review
summary: The checks to run before handing over a draft — headlines alone, the round-trip test, hardest questions, coverage, and the per-slide checklist
use_when: before answering with a draft, a revision or a repair
---

# Self-review

Run these before you answer. They are cheap compared with a slide that ships empty, overclaims
or argues nothing.

## 1. Read the headlines alone

Copy every content slide's headline into a list and read it top to bottom, as if it were the
only text in the deck.

- Does it read as one connected argument, ending in the decision the brief asked for?
- Could someone reconstruct the governing thought from it?
- Does any headline repeat another, or does the argument jump?
- Is every headline a sentence, not a topic label?

## 2. The round-trip test, slide by slide

For each slide, look only at what is on it and ask:

1. **What would a reader believe after seeing only this slide?** List the beliefs, including
   the ones the slide implies without stating: that one thing caused another, that a result
   holds everywhere, that a pilot proves a rollout.
2. **Would the authors of the cited sources endorse each belief?**

Any belief they would not endorse is a defect, even when every sentence on the slide is
individually cited. Fix it with a fence (*"association, not tested cause"*, *"pilot stores
only"*), a narrower header, or a separate item that states the limit.

## 3. The hardest questions

For each section, ask the three hardest questions a sceptical executive in this audience
would ask (*"Does this hold outside the trial?"*, *"What did it cost?"*, *"Compared with
what?"*). If an answer limits a claim on a body slide, the limit goes on that slide. If the
evidence cannot answer it, say so in `notes` or as a `risk` slide.

## 4. Coverage

Everything the person asked for has a `coverage` entry: `covered` (where), `hedged` (where,
and why the evidence is thin), `gap` (what is missing), or `left_out` (why). An entry that
claims coverage the slides do not show is worse than an honest gap.

## 5. Every slide: the checklist

1. **It has a body.** Every content slide carries at least one cited block under its
   headline, and the body proves the headline.
2. **The headline is a talking header.** Every number and name in it is stated by a cited
   block on the same slide, and it is no stronger than those blocks.
3. **Every block fits.** Each list item is at or under its slot's target; you counted.
4. **The sentences are yours, the quotes are theirs.** No body sentence is a pasted source
   sentence unless lifting is required (see `from-source-to-slide`).
5. **Every quote is one unbroken run of one passage, copied exactly:** no added period, no
   splice, no dropped `[n]` markers, no tidied spacing.
6. **Every number,** in the header, labels, chart and notes, is in a cited passage or a
   declared derivation.
7. **Every qualifier is on the surface:** population, dose or configuration, duration,
   modality, attribution, beside the number it limits.
8. **Framing asserts nothing:** no number, no name, no comparison, no evidence verb.
   Implications are labelled "Implication:".
9. **Takeaways and the close hold for every comparator, population and outcome they name.**
10. **One name per concept** across the deck; acronyms defined at first use.
11. **Ids are unique** across face and notes. Notes facts are cited claims. No block uses
    `source` or `section_number`.
