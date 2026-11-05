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

## 3. Grounded, not copied

Normal mode is for getting a good deck made quickly. Every point still rests on a source;
nothing about that is relaxed. What is relaxed is how closely the slide has to echo the
source's words.

- **Write the slide in your own words.** Plain, natural sentences for this audience, at the
  length the slot wants. Condense, combine passages that say related things, reframe for the
  decision. A slide that reads like sentences lifted from the source has failed even if every
  quote resolves. Keep the meaning and the strength: the same subject, conditions,
  comparison and degree of certainty as the source (`fidelity`).
- **A quote points at the passage; it does not have to be a perfect copy.** Give the words of
  the passage your point rests on, as close as you can get them. Code finds the exact words in
  that passage and stores those as the citation. Where a skill says a quote must be copied
  character for character, in this mode close is enough. The passage must still be one you
  were shown, and the quote must come from one passage, not stitch two together.
- **Round figures for readability when it helps.** 33.4% may be "33%" and 1,212 stores "about
  1,200 stores"; the exact figure stays in the citation. Round, never shift: the slide's
  number must be the cited one rounded, in the same unit. A ratio or a change you work out
  yourself is still a `derivation`.
