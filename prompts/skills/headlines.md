---
name: headlines
summary: Writing talking headers — a full sentence stating the slide's bottom line, carried by the slide's own evidence, never stronger than it; weak-to-strong rewrites
use_when: writing or checking any content slide's headline; building the ghost deck
---

# Headlines

A content slide's headline is a **talking header**: one full sentence that states the slide's
bottom line first (BLOT, bottom line on top). It is the most-read sentence on the slide, and
read in order the headlines alone must tell the deck's whole argument.

## The rules

1. **A sentence, not a label.** It has a subject and a verb, and it says something a person
   could disagree with. *"Safety and tolerability"* is a label. *"Side effects were mostly
   gastrointestinal and eased within weeks"* is a header.
2. **The conclusion, not the topic.** Say what the slide's evidence adds up to: the "so
   what". It can be a direct assertion (*"Weight loss matched comparator B, it did not beat
   it"*) or a synthesis of several blocks (*"Across four head-to-head trials, drug A held its
   own against established comparators"*).
3. **Carried by this slide.** The header has no citation of its own. Instead, **every
   specific fact in it must be stated by a cited block on the same slide**: a number, a named
   trial or study, a named comparator or product, a direction of effect. A number in the
   header is copied exactly as the slide's claim or chart has it. If the slide does not carry
   a fact, the header cannot say it. Code checks the numbers and names; the validator checks
   the meaning.
4. **Never stronger than the slide.** A header summarises the blocks under it, so it is no
   more certain than the weakest of them. If one comparator was a tie, the header does not say
   "beat all comparators". If the evidence is one study, the header says so or hedges
   (*"In the one trial that measured it…"*). If the result holds for a population, the header
   keeps the population.
5. **One idea.** Two independent claims joined by "and" are two slides, or one claim and a
   different header. "And" is fine when it joins two halves of a single point (*"Weight loss
   beat comparator C but only matched comparator B"* is one comparison).
6. **Short enough to read at a glance.** Aim for 8 to 16 words and stay inside the headline
   slot's target. Sentence case. No final period. No "Topic: point" constructions with a
   colon.
7. **Spoken, not written.** Say it aloud as the first sentence you would say to this
   audience. If it sounds like a caption, rewrite it until it sounds like a person talking.
   Watch for tails bolted on after a comma (*"…beat every earlier model, ensembles
   included"* → *"Even the small model beat everything before it, ensembles too"*), noun
   piles with no verb doing the work, and "A, but B" with no subject. Contractions and
   "we" or "our" are fine when the audience would hear them that way.
8. **Part of a chain.** Each header follows from the one before, by consequence, contrast
   or addition. If you cannot put "so", "but" or "and" between two headers, a step is
   missing. A mechanism or a number needs an earlier header that set up the problem it
   answers. The validator reads the headers in order and flags breaks, repeats and
   unspeakable lines.

## Fit the header to the component

Most components give the headline up to 88 characters. Some give it **one line of about 43
characters**: `evidence_with_figure`, `data_card_grid`, `icon_pillars`, `before_after`. A
talking header in 43 characters is six or seven words. Write it that short (*"Weight loss
matched comparator B"*), or pick a component whose headline has room for the sentence the
point needs. Never write a long header into a short slot and hope.

`callout_takeaway` has **no headline slot**. Its `takeaway` *is* the point, and its `label` is
a short framing tag.

## Synthesis headers

Most good headers are syntheses: they say what several blocks add up to. That is legitimate
when:

- each block it summarises is on the slide and cited;
- the summary is entailed by those blocks taken together; and
- it does not add a fact none of them states (a total nobody computed, a trend from two
  points, a cause nobody tested).

If a synthesis needs a computed number, such as a difference, a total or a ratio, that number
must be a declared derivation in a block on the slide (see `citations`). Otherwise, state the
synthesis without the number.

## When the evidence cannot carry the header you want

Do one of these, in order of preference:

1. **Re-scope:** add the population, setting or condition that makes it true. *"…in adults
   already on metformin"*.
2. **Weaken the verb:** *"was associated with"*, *"reported"*, *"suggests"*, *"matched"*.
3. **Name the evidence:** *"One trial found…"*, *"The authors' own benchmark shows…"*.
4. **Ask:** a question header, when the slide lays out evidence on an open question. *"Does
   the margin gain survive without the competitor closures?"*
5. **Remove the slide** and say so in `coverage`.

Never solve it by keeping the strong header and putting the qualifier in the notes.

## Weak and strong

| Weak (label or overreach) | Talking header | Why |
|---|---|---|
| HbA1c reduction across ALPHA trials | Drug A lowered HbA1c more than two of its three active comparators | States the result, and its limit |
| Body weight reduction | Weight loss beat comparator C but only matched comparator B | Keeps the tie |
| Drug A demonstrates superior efficacy | Drug A lowered HbA1c more than comparators B and C at 24 weeks | Names what was measured, against what, when |
| Serving memory | Most of model M's serving memory goes to weights and the key-value cache | States the finding |
| Routing layer overview | Model M's routing layer sends each token to two of its eight experts | Says what it does |
| Model M performance | Model M matched the best published score at a quarter of the training cost | A result, carried by the slide's numbers |
| Q3 financial performance | Q3 revenue fell 4%, driven by delayed shipments in two regions | The deduction, not the period |
| Dynamic pricing boosts margins | In an 8-week Ontario pilot, dynamic-pricing stores saw margin rise against controls | Keeps scope, design and duration |
| Strategic recommendations | Start the European launch with the two markets that share our supply chain | A recommendation is a sentence too |
| Key takeaways and limitations | Drug A is a credible first injection-free option, within trial populations | The close, with its limit on the surface |
| Next steps | Approve a payer briefing by March and a real-world adherence study | The ask |

## Structure slides

- **Title slide:** the title states the deck's answer or question in a sentence (see
  `storyline`).
- **Agenda:** the headline names the journey (*"Three questions decide the formulary
  case"*). The items are the section names.
- **Section divider:** `section_name` names the section in a few words. It is `framing`.
- **Closing slide:** the headline states what is asked. The `cta` is the action, as
  framing.
