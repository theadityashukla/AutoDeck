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
