# Slide bench results

Assumed prices throughout (deliberately high, unconfirmed): see `../prices.yaml`.

## Round 1 (2026-11-14): Luna and Sol, eight slides, concept vs none, QA feedback only

`2026-11-14-round1/`: `sol.png`, `luna.png` (left column Demand curve, right column no
concept), `opus-reference.png` (three slides designed by hand inside the same vocabulary),
`summary.csv`.

- Sol: 14 of 14 completed slides clean, 1-2 attempts, about $0.42-$1.05 a slide. Two
  trials were cut by the budget guard.
- Luna: 14 of 16 clean, 2-4 attempts, about $0.08-$0.40 a slide.
- Both models design real slides (colour fields, hero numbers, emphasised charts) even
  with no concept. With a concept the eight slides read as one deck; without one, each
  slide is good and they do not match each other.
- `gpt-5.4-mini` failed layout QA on all five slides it attempted with the same brief
  (harness development runs, not in this folder).
- Estimated $14.55 against a $13 cap: the guard checks before each call and four parallel
  workers overshot it.

## Round 2 (2026-11-14): Luna, eight slides, Demand curve, visual feedback

`2026-11-14-round2-visual/`: `before-after.png`, `summary.csv`. Estimated $2.40.

- 7 of 8 clean. Shown its own render, Luna revised 2 of the 7 and declined the rest.
- Both revisions only put a wrapped headline on one line. A visible flaw (a figure sitting
  on a line marker) was left alone.
- Conclusion: a model reviewing its own slide with a one-line question adds little. A
  separate reviewer with a real critique brief is untested.

## Reviewer tests (2026-11-15): a separate model reviews the rendered slide

`2026-11-15-reviewer/`. Reviewer `gpt-5.6-terra` with `prompts/review.md`, reasoning
medium. Designer `gpt-5.6-luna`. The studio's new layout rules were active in the loop.

**Review-only, 32 existing slides** (`review-only-p1..p4.png`, `review-only-summary.csv`),
estimated $2.46, about $0.08 a slide.

- 6 sent back, 26 passed. No good slide was sent back.
- Four of the six are line-type flaws the new layout rules now catch on their own (a rule
  through UNMEASURED, a timeline into a band, a line across a chart, a rule through
  "$310k"). Two are judgement calls only a reviewer can make: date labels sitting beside
  their timeline markers, and the accent colour on two competing elements against the
  concept's rule.
- Missed, against the prompt author's predictions: labels floating far from their figures
  (real run, slide 2); labels sitting unevenly along a line (Luna s3); two large figures
  crowding each other (Luna s5).

**Full loop, eight cases, Demand curve** (`loop-luna-reviewed-by-terra.png`,
`loop-summary.csv`), estimated $2.85: designer $2.07, reviewer $0.78.

- 8 of 8 clean under the new layout rules; one attempt was refused for a line through
  text and corrected.
- 6 passed first review. 2 were sent back, each with one blocking finding (a rule through
  a small label; an unlabelled fourth timeline marker). The designer fixed both in one
  revision and both passed second review.
- The reviewer passed s3-techniques, whose labels and figures are scattered above and
  below the line: the same kind of flaw it missed in the review-only test.

**Conclusion.** The reviewer is precise (no wrong send-backs in 40 reviews), its findings
are specific enough that the designer fixes them, and it costs about a third on top of
the designer. Its recall on composition flaws (uneven, scattered or crowded layouts) is
weak. It is worth having as a cheap extra pass; the layout rules remain the main defence,
and the owner still has to look.
