---
name: reworking-decks
summary: Rebuilding or reusing a deck that already exists — keeping the client's story, the wording modes (keep my words / light rewording), lifting slides into a new deck, reshaping a lifted slide for a new audience
use_when: a redesign of the client's deck; any deck whose evidence includes an existing deck; mixing old slides with new ones
---

# Reworking existing decks

Much real deck work starts from a deck that already exists: a client's deck to restyle and
sharpen, or an old engagement deck whose best slides should reappear in a new one. The
existing deck is evidence. Its facts are cited verbatim from the slide they appear on, exactly
like a paper's. It is also an **argument someone already made**, and that deserves respect.

## Keep the client's story

- **Their argument is theirs.** Keep each slide's purpose and the deck's order, unless the
  person allowed you to merge, split or reorder.
- **One slide in, one slide out** is the default in a redesign. Merge only slides that make the
  same point; split only a slide carrying two. Do either only when the person allowed it.
- **Never add a fact the deck does not state:** not a number, a date, a name or a comparison.
  If a slide would read better with a figure the deck does not contain, it goes without. If the
  person allowed a check against the project's papers, a paper passage may *support* what the
  deck already says. It may not add to it.

## The wording modes

The person's settings say how freely you may reword.

**Keep my words.** Reuse the client's sentences as they are. You may only shorten them, and
only by deleting words: no substitutions, no re-ordering, no new words. Titles stay theirs,
shortened the same way. Code checks this; a reworded sentence is rejected. This is the
**lift** transformation applied to the whole deck. Your craft goes into layout and component
choice, not words.

**Light rewording.** Tighten and restructure sentences for the slide, while each still says
exactly what the original said, with every condition and number intact. Rewrite a topic-label
title as a talking header, using only what that slide says (see `headlines`). Here the
**condense**, **visualise** and **reframe** transformations apply (see
`from-source-to-slide`), within the facts the deck already states.

## Change the layout only where it helps

When layouts may change, pick the component that shows each slide's point best: one headline
figure → `big_number`; two options compared → `two_column_compare`; dated steps → `timeline`;
ordered stages → `framework_diagram`; values in a table → `chart_focus` if every value is in
the deck's text. When the original layout already works, keep its equivalent. A clean restyle
is a legitimate outcome. When layouts may not change, map each slide to its closest component
and change nothing else.

## Lifting slides into a new deck

When an old deck's slides become part of a new one:

- **The facts transfer exactly; the framing is rebuilt.** A slide made for an operations
  review gets a headline, emphasis and component that serve the new audience's decision.
- **Re-check the headline against the slide's own content.** Old decks often have headlines
  stronger than their bodies. The lifted slide's header is no stronger than what it carries.
- **Dates and scope travel with the facts.** "2023 pilot" stays "2023 pilot", even if the new
  deck is about 2025.
- **Make old and new consistent:** one name per concept, one headline style, and one figure
  for one thing. Where the old deck and a newer source disagree, show both with their dates.
  Never quietly keep the one that suits.
- **Note what you lifted** in the draft's `notes` or `changes`, so the person knows which
  slides came from where.

## What a client deck's text can and cannot support

- Text on a slide supports what it says on that slide. A **framing** sentence in the client's
  deck (*"our market-leading platform"*) is value language. Carrying it into a factual claim
  turns their marketing into your assertion. It stays framing, fenced as `citations` requires.
- A key message the deck asserts but supports only with framing, never with a citable
  statement, gets empty `citations`. That is a finding to surface, not something to paper
  over.
- If the deck contradicts itself (two slides giving different figures for the same thing),
  record it in `coverage` as a `gap`, with both.
