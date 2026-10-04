# Deep research prompt: the craft of building a deck

Paste everything below the line into the deep research tool. It is written to stand alone:
the tool cannot see this repo, so the context it needs is inside the prompt.

Notes for the owner, not part of the prompt:

- The output is meant to be turned into a system instruction afterwards, so the prompt asks
  for findings shaped as rules, tests and anti-patterns, not as an essay.
- The Winston section lists ideas I recall as hypotheses for the researcher to verify against
  primary sources. Treat none of them as confirmed until the report cites a transcript or
  video timestamp.
- Section 6 is my addition beyond your brief (evaluation, accessibility, LLM failure modes).
  Delete it if you want a narrower run.

---

## Prompt

### 1. What I am building and why I need this research

I am building AutoDeck, a system that turns a corpus of source documents (research papers,
client files, call notes) into a consulting-grade slide deck, using LLM agents in a pipeline:
planner (agrees a brief with a consultant), outline (storyline and slide roles), content
(writes each slide), art direction and aesthetic critique (deck-level visual decisions).

The pipeline already has strong mechanical safeguards: every factual claim carries a citation
to a verbatim source span, every number is copied from a source or declared as a re-executable
derivation, an independent validator re-searches the corpus, and a human approves at four
gates. What it lacks is **craft**: a principled account of how a good deck is built, how it is
made beautiful, and how it stays faithful to its source in meaning rather than in wording. I
want to write a long, detailed system instruction that gives the agents that craft. This
research is the evidence base for it.

I need you to find, verify and synthesise the best available thinking on the topics below,
and to return it in a form I can convert into instructions for a model.

### 2. Hard constraints the research must respect

The craft guidance must fit inside these, so tell me where established advice conflicts with
them and how to resolve each conflict:

- **Fidelity.** Slide prose must preserve the core idea of the source, not copy its wording.
  But numbers, units and dates must stay exactly as in the source (or be a declared
  derivation), and citations stay verbatim. So "paraphrase freely" applies to prose only.
- **Hedges travel with the number.** A qualifier (configuration, what was measured, "reported
  by X citing Y", single-source) must sit on the same surface as the figure. This pulls
  against the minimalism most design advice recommends.
- **Headers that assert are claims** and need a citation that supports them as written.
  This pulls against the "action title" convention.
- **The visual agents cannot change words.** Art direction works only through fixed levers:
  choose a layout component from a catalog, set type scale (compact/standard/spacious), pick
  one theme accent, emphasise one block, assign icons from a fixed concept list. No free
  positioning, no arbitrary colours or font sizes. Craft advice must be expressible through
  levers like these.
- **Layout catalog (fixed):** title, section divider, agenda, big number, two-column compare,
  bullets with support, evidence with figure, chart focus, quote, framework diagram,
  timeline, before/after, data card grid, callout takeaway, icon pillars, closing call to
  action. Slides are classed by what they draw: diagram-led (60 words or fewer), icon-anchored
  (50 or fewer), text-led (90 or fewer).
- **Priority order when goals conflict:** truth, then the audience's decision, then clarity,
  then beauty. Say if research suggests a different order.

### 3. Research thread A: Patrick Winston (MIT, 1943-2019)

I want his teaching on communication carried into the system instruction. Work from primary
sources first: the MIT "How to Speak" lecture (IAP) and its video and transcript, his MIT
OpenCourseWare 6.034 lectures, his textbook *Artificial Intelligence*, and any talks or
interviews where he describes his method. Secondary summaries are acceptable only to locate
primary material, and every claim about what he said needs a pointer (title, date, timestamp
or page).

Verify, correct or discard each of these, which I recall but have not checked:

- the **empowerment promise**: open by saying what the audience will be able to do or know
  by the end
- **cycles**: returning to the key idea several times, with deliberate repetition
- **verbal punctuation** and the use of a **fence** to separate your idea from similar ones
- the **"star"** for getting an idea remembered: symbol, slogan, surprise, salient idea,
  story
- **near-miss** examples to teach a concept by contrast
- the **Rumpelstiltskin principle** (naming an idea gives you power over it) and the "right
  representation" principle from his AI work
- his advice on **how to start** (what not to open with), **how to end** (contributions
  rather than a thank-you or questions slide), and on **slides versus the board**, slide
  density and not reading slides aloud
- his framing of the three kinds of talk (informing, inspiring, persuading) and what each
  requires, including the vision / steps / contribution structure for a persuasive or job talk
- his claim about what determines success (speaking, writing, quality of ideas) and the
  order he gave them
- his teaching on **how to explain** and on **how to tell a story**, including anything on
  story structure in his AI/cognition research (the "strong story" hypothesis)

For each idea that survives, I need: what he actually said, why he said it works (his
mechanism, not only the rule), how it translates to a **static consulting deck read by a busy
executive**, since he mostly taught live speaking, and where it does not translate. Do not
force every idea into the deck. Tell me which ones to leave out.

### 4. Research thread B: how to build a deck

Survey the established methods and tell me where they agree, where they disagree, and which
you would pick for an LLM that must also stay faithful to sources:

- storyline construction: the Minto pyramid / governing thought, SCQA, "ghost decks" and
  storyboarding as practised at top consulting firms, question-led versus answer-led decks
- slide-level logic: one idea per slide, action titles and the assertion-evidence structure
  (Alley and others), the "so what" test, MECE grouping
- deck-level tests: reading only the titles should give the argument; how long a deck should
  be for its purpose; appendix versus body; what belongs in speaker notes
- audience modelling: designing for the decision the audience must make, executives versus
  technical readers, pre-read decks versus presented decks (these differ and the research
  should say how)
- evidence from cognitive science and learning research on what works on slides: cognitive
  load, multimedia learning (Mayer), the split-attention effect, redundancy of reading text
  aloud, what the literature really says about words per slide

Where a popular rule has weak evidence behind it (for example specific word-count limits, the
10-20-30 rule, "no more than three bullets"), say so.

### 5. Research thread C: how to make it beautiful

I need principles a model can apply through the lever-based interface in section 2, and
tests it can run on a rendered slide. Cover:

- visual hierarchy and focal point; alignment, proximity, grid and whitespace; consistent
  type scale and why few sizes work; contrast and legibility at presentation distance
- colour: restraint, one accent, colour as meaning, colour-blind safety, brand-theme limits
- charts and data: Tufte (data-ink, lie factor, small multiples), Few, Knaflic, Cleveland and
  McGill on perceptual accuracy; chart choice by question asked; direct labelling; honest axes
- diagrams: when structure or sequence justifies one, and the common failures (decorative
  diagrams, SmartArt-style effects)
- icons and imagery: consistency of style, when icons help comprehension and when they are
  decoration
- rhythm across a deck: density variation, section breaks, avoiding runs of identical layouts
- the most common marks of a deck that looks machine-made or template-made, and what to do
  about each

For every principle give a concrete, checkable test where possible (for example a squint
test, a three-second test, a grayscale test), and say which can be done on a rendered image
by a vision model.

### 6. Research thread D: staying true to the source (meaning, not wording)

This is the most important thread. I want a rigorous account of what it means for a slide to
be faithful to a source when it is not a quotation:

- what must be preserved in a paraphrase of a research finding: subject, quantity measured,
  magnitude, direction, scope and population, conditions or configuration, modality ("can"
  versus "does"), causal versus correlational language, attribution (the authors' own result
  versus a result they cite)
- what may legitimately be dropped or moved to notes, and what may never be dropped
- the common ways summaries distort sources: overgeneralisation, upgrading hedges to claims,
  cherry-picking the most quotable sentence, losing the source's own emphasis, false balance,
  mixing results measured under different conditions
- how to decide what the source's core idea is, as opposed to its most quotable line
- the research literature on faithfulness, factual consistency and attribution in LLM
  summarisation and on how it is measured (for example claim decomposition and entailment
  approaches, FActScore, SummaC, attribution evaluation), and which methods could be run as
  an automated "does this slide say what the source means" check that is separate from a
  "is this quote present" check
- a practical round-trip test: given only the slide, what would a reader believe, and would
  the source's authors endorse it

### 7. Research thread E: additions I did not ask for

Use judgement here and tell me what you find most valuable:

- how decks are actually evaluated: rubrics used by consulting firms, design educators and
  research on presentation quality; anything that could become an automated rubric
- known failure modes of LLM-generated presentations and writing (generic phrasing, filler
  openers, uniform bullet structure, inflated adjectives), with before and after examples
- accessibility: contrast ratios, reading order, alt text for charts and diagrams
- consistency of terminology across a deck, naming concepts once and keeping the name
- anticipating the audience's hardest questions and where that belongs
- anything else a serious practitioner of consulting or scientific decks would say is
  missing from this list

### 8. Source standards

- Prefer primary sources: the person's own lectures, books and papers, then peer-reviewed
  research, then practitioner books, then reputable practitioner blogs. Avoid listicles.
- Quote sparingly and exactly, with a pointer. Never attribute a statement to a person
  without a source you have actually seen. If you cannot verify, say "unverified".
- Mark every finding with a confidence level (strong evidence, practitioner consensus,
  single source, or folklore) so I can weight the rules I derive from it.
- Note disagreement between authorities instead of picking one silently.

### 9. Output format

Structure the report so it converts directly into a system instruction:

1. A one-page executive summary: the ten rules you would put first, in priority order.
2. For each thread, a table of **principles**, each with: the rule in one imperative
   sentence, the mechanism (why it works), the source, the confidence level, how it
   translates to a static executive deck, and a **checkable test**.
3. A **conflicts section** covering each tension in section 2 (and any others you find) with
   a recommended resolution and the reasoning.
4. A catalogue of **anti-patterns**: named failure modes, how to recognise each, and the fix.
5. A set of **before/after examples** showing a faithful versus an unfaithful paraphrase of
   a research finding, and a weak versus strong slide, written out in full.
6. A short list of **open questions** where the evidence is thin or the authorities disagree,
   so I know what needs a decision from me.
7. A bibliography with every source used.

Length is not a constraint. Completeness and verifiability are.
