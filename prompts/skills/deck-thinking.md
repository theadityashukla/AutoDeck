---
name: deck-thinking
summary: What a deck is and how to build one — the priorities, the working order, and which skill to reach for at each step
use_when: always; read first, before any other skill
---

# Deck thinking

## A deck is an argument, not a collection of sentences

A deck exists to move a particular audience to a particular decision or understanding. It
is a means of communicating an idea. It is **not** a corpus of sentences copied out of the
source documents and arranged under headings.

The sources are where the facts come from. The deck is where those facts are *used*:
selected, ordered, condensed, turned into a picture, put next to each other so a comparison
becomes obvious, and phrased for the person who has to act on them. A consultant building a
deck for a client does exactly this. Some slides come from an earlier deck, some are new, and
all of them must be accurate. Almost none of them repeat the source word for word, because the
source was written for a different reader, at a different length, for a different purpose. A
forty-page clinical review is dense and hedged and text-heavy. The slide built from it has to
be short, visual and high level, and still true.

So every slide does two jobs at once:

- **It is grounded.** Every fact on it can be traced to a passage in the evidence, and it
  says no more than that passage says. The citation is the proof: a short verbatim quote from
  the source, attached to the sentence it supports.
- **It communicates.** The sentence the audience reads is *yours*. It is written for them,
  as short as it can be while still true, in their vocabulary, and placed where it does the
  most work in the argument.

These do not compete. The slide sentence and the quote are two different things with two
different jobs, and the system keeps them apart for you:

| | The slide sentence (`claim.text`, `text`) | The quote (`citations[].quote`) |
|---|---|---|
| Who it is for | The audience | The checker and the auditor |
| Whose words | Yours | The source's, exactly |
| Length | As short as the slot's target allows | The shortest run that proves the sentence |
| May you rephrase it? | Yes, and you should | Never |
| What it must do | Say what matters, truthfully, at the right strength | Say what your sentence says |

The most common way a draft fails is to blur the two: pasting a long source sentence onto the
slide as the bullet, because then it obviously "matches". It does not fit the slot, it does not
read as a slide, and it does not communicate. It gets dropped, and the slide is left with a
headline and nothing under it. **A headline with nothing under it is the worst outcome a
content slide can have.** Load `from-source-to-slide` and `slide-bodies` before writing a
single body block.

## The order of priorities

When two goals pull in different directions, the earlier one wins:

1. **Truth.** This means what the reader *ends up believing*, not only whether each sentence
   can be matched to a passage. A slide whose every sentence is cited can still mislead: a
   true number, a true chart and a causal-sounding headline can together imply something no
   source said. A slide is true when a reader who sees only that slide comes away believing
   only what the sources support.
2. **The audience's decision.** Every slide earns its place by moving the reader toward the
   decision or understanding the deck exists for. Interesting but irrelevant goes to the
   appendix or goes away.
3. **Clarity.** One idea per slide, stated in the headline and shown by the body, in words
   the audience uses.
4. **Beauty.** A calm, consistent, well-proportioned slide earns attention. It never comes at
   the cost of the three above. A qualifier is never cut to make a slide look cleaner.

## The working order

Build a deck the way a good consultant does: argument first, slides second, polish last.
Reordering sentences is cheap; reordering finished slides is not.

1. **Understand the brief.** Who is the audience, what do they already know, and what must
   they decide or be able to do afterwards? Write the objective as that decision.
2. **Read the evidence for its core ideas,** not for its most quotable lines. What does each
   source actually conclude, about whom, under what conditions, and how sure is it?
   (`fidelity`)
3. **Decide the governing thought.** This is the one sentence the whole deck argues. If the
   evidence supports one answer, lead with it. If it does not, the deck is question-led.
   (`storyline`)
4. **Write the ghost deck.** Every slide's headline, in order, before any body. Read them top
   to bottom as a paragraph. Fix the argument here. (`storyline`, `headlines`)
5. **Check every headline against the evidence** before writing the body. A headline the
   evidence cannot carry is weakened, re-scoped or turned into a question now, not after the
   slide is built. (`headlines`, `fidelity`)
6. **Choose each slide's evidence form.** A number, a comparison, a trend, a sequence or a
   set of parallel points each has a component that shows it best. (`slide-bodies`,
   `charts-and-diagrams`)
7. **Write each body.** Short, grounded sentences that fit their slots on the first try, each
   with the shortest quote that proves it. (`from-source-to-slide`, `citations`,
   `writing-style`)
8. **Review.** Read the headlines alone, run the round-trip test on every slide, and walk the
   checklist. (`self-review`)

## The skills

Each skill is a short, specific guide. The ones you need for a full draft:

| Skill | Use it for |
|---|---|
| `storyline` | The governing thought, the deck's shape, the ghost deck, opening and closing, dividers, length, what goes to the appendix |
| `headlines` | Writing each slide's talking header: a sentence that states the slide's point and that the slide can carry |
| `from-source-to-slide` | Turning dense source material into slides: condense, visualise, synthesise, reframe. When to stay near-verbatim |
| `slide-bodies` | What goes under the headline: one idea per slide, the right component, a body recipe for every component, writing to fit |
| `fidelity` | Saying what the source says at the strength it says it: scope, conditions, modality, causality, tense, attribution. Hedges. Labelled implications |
| `writing-style` | Plain, precise slide prose. The tics to avoid. One name per concept. Acronyms |
| `charts-and-diagrams` | Choosing and filling a chart or a diagram honestly |
| `citations` | The mechanics of grounding: claim blocks, verbatim quotes, numbers and derivations, framing |
| `reworking-decks` | Rebuilding or reusing slides from a deck that already exists |
| `exemplars` | Three finished decks to measure your draft against: their outlines, worked slides and density |
| `self-review` | The checks to run before you hand the draft over |

The rules in these skills hold whatever the subject. Their examples come from clinical
reviews, technology assessments and business cases, so that no rule reads as if it belonged
to one field.

**Examples are never evidence.** Every example in these skills is about an invented subject:
drug A, comparators B and C, the ALPHA trials, model M, a fictional pilot. Their numbers are
made up. Never cite, copy or reuse an example's facts, even when its subject sounds like
yours. The only facts you may use are in the evidence pack. The one exception is
`exemplars`: its decks are real and checked, and they are still about their own papers, not
yours.
