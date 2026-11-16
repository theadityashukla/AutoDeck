# Provenance — normal

This deck is in **normal** mode: everything is still fact-checked, and every claim still says
where it came from, but two sources beyond the documents are allowed. The person sees each
one labelled in review.

## 1. What the person told you — "from you"

The evidence pack has a section **"What you told us"**: the person's own words from this
conversation, as a document whose id begins `conversation--`. When the person has stated
something — how their system is built, what their team decided, a figure from their own
business — and it belongs on a slide, cite it from that section exactly as you would cite a
paper: a `claim` block whose quote is copied verbatim from what they typed.

- Quote only what the person actually typed there. Never quote your own earlier suggestions
  back as theirs.
- Stay faithful to what they said: no extra detail, no stronger wording, no added numbers.
- Prefer a document when one says the same thing; use "from you" for what only they know.

## 2. General knowledge — `unsourced`

When a slide needs a piece of widely known, **qualitative** background that no document in
the pack states — what a class of drug does, what a common architecture pattern is for — you
may write it as a block of kind `unsourced`, with its sentence in `text` and no citation.

- **No numbers, dates, or named studies, trials, authors or organisations' findings.** Any of
  those needs a citation; an unsourced block containing one is rejected.
- **No appeals to evidence** — "studies show", "research confirms", "experts agree". If the
  evidence exists, cite it; if it does not, the sentence is not general knowledge.
- Use it sparingly, for context and mechanism, never for the slide's main point. A slide whose
  headline rests on an unsourced block is resting on nothing anyone can check.
- The validator checks every unsourced sentence against the documents; one they contradict
  blocks the deck, and one they neither support nor contradict is shown as *uncorroborated*.
- The headline rule is unchanged: a talking header's specific facts must be stated by a
  **cited** block on the same slide.
