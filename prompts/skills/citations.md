---
name: citations
summary: The mechanics of grounding — blocks and slots, claim vs framing, verbatim quotes and the seven ways they break, numbers and derivations, the framing fence, what never to cite
use_when: writing any block; fixing a rejected block; whenever a quote, number or framing line is involved
---

# Citations: how grounding works

Everything you write is read twice: once by the audience, and once by machinery that does not
read prose at all. A resolver looks up every quote in the source. A numeric linter re-executes
your arithmetic. A framing linter checks that uncited text asserts nothing. A budget check
measures your text in the real font. And a separate validator re-searches the sources and
takes none of your citations on trust. **This skill is how you write for the machinery.**
`from-source-to-slide` is how you write for the audience. You need both, on every block.

## The blocks are the slide. Your prose is not.

Your output is a list of blocks. Each carries its own payload: a `claim` with its `citations`,
a `chart` with its `source_citations`, a `diagram`, or plain `text` for headers and framing.
Speaker notes are a second list of blocks beside the first.

**Anything you write outside those structures does not exist.** If you catch yourself typing
*"(Andersen et al., p.11)"* inside a block's text, stop. The parenthesis is not a citation;
the `citations` entry is. The same goes for derivations: explaining a calculation in prose
while leaving `derivation` empty produces a number with nothing behind it. Fill the
structures first.

## Which block goes in which slot

Every block names the `slot` it fills, using the slot names in the component's budget list.

| Slot | Block kind | What it holds |
|---|---|---|
| `headline` | `section_header` | The talking header (see `headlines`) |
| `title` (title slide) | `section_header` | The deck's answer or question, as a sentence |
| `subtitle`, `presenter`, `date` | `framing` | Audience, occasion, names. Never a fact |
| `points`, `support`, `supporting_points`, `supporting_text`, `left_point(s)`, `right_point(s)`, `pillar_point`, `before_text`, `after_text`, `takeaway` | `claim` (or `framing` when it states no fact) | The evidence |
| `figure`, `card_value` | `claim` | The figure, cited |
| `label`, `left_title`, `right_title`, `figure_label`, `card_label`, `pillar_label`, `before_label`, `after_label`, `attribution`, `section_name`, `cta`, `items` | `framing`, **or `claim` when the label states a fact** (a dose, a week, a named study) | Names a thing |
| `quote` | `claim` | The person's exact words, cited to where they said them |
| `chart` | `chart` | One chart block |
| `diagram` | `diagram` | One diagram block |
| `source`, `section_number` | — | **Never write these.** Code fills them |

- **A slot described as a LIST takes one block per item.** Five bullets are five `claim`
  blocks with `slot: "points"`, in display order. Never join two items in one block, and never
  put a list inside one block's text.
- **Block ids are unique across the whole slide, face and notes together.** `b1, b2, …` on the
  face and `n1, n2, …` in the notes is a safe habit.

## Every factual assertion carries a citation (A1)

A block that asserts something about the world is a `claim`, and a `claim` cannot exist
without at least one citation. The one exception, where the provenance section allows it, is
the explicitly labelled `unsourced` block. If the provenance section does not offer it, it
does not exist.

**Speaker notes are blocks too.** If a note states a fact, it is a cited claim. If it cannot
be, do not write it. A chart is a set of factual assertions, so every value traces to a cited
passage. A diagram step whose label asserts a fact carries a claim. No block type is a
loophole.

## Quotes are selected, not written

A citation is `{"doc_id": ..., "quote": ...}`. The quote is **copied exactly** from a passage
in the evidence, character for character, including whatever the PDF extraction produced. The
corpus is full of spans that read oddly (`2-4 ×`, `( p = 0.76)`, `HbA 1c`) because that is how
extraction spaced the source's typesetting. Copy them as they are.

Tidying a quote makes it stop resolving, **and that is correct behaviour.** An edited quote and
a fabricated one look the same downstream. If the only quote supporting your sentence reads
badly, change your sentence or find another passage. Never improve the quote.

**The quote is not the slide sentence.** Your `claim.text` is short and written for the reader
(see `from-source-to-slide`). The quote is the shortest run of the source that proves it. They
will usually differ, and that is how it should be.

### The seven ways quotes break: check every one before you answer

These are the failures from real drafts. Each one cost a slide its evidence.

1. **Adding punctuation.** Cutting a quote mid-sentence and adding a period. If the passage
   continues *"…by 1.3% versus placebo in"*, the quote ends at `in` or earlier, never with a
   `.` the source did not put there.
2. **Splicing.** Joining the end of one sentence to the start of another, or two passages, into
   one quote. **One quote is one unbroken run of one passage.** If the claim needs two
   sentences, give it two citations.
3. **Dropping reference markers.** The source says *"…as previously reported [50, 51]."* Keep
   `[50, 51]`, or end the quote before it. Never delete it from the middle.
4. **Tidying extraction spacing.** `( p = 0.76)` stays `( p = 0.76)`. `10 ×` stays `10 ×`.
5. **Changing case or fixing typos.** Starting mid-sentence does not license a capital letter.
   A misspelling stays misspelled.
6. **Quoting the note instead of the source.** In `claims.md` evidence, only the line after
   `quote:` is citable. The claim summary and the `note:` are someone's description of the
   source.
7. **Quoting too much.** Use the shortest run that supports your sentence. Long quotes cross
   line breaks, table cells and footnotes that extraction laid out differently from how they
   read.

The quote must actually **support** the sentence. A passage on the same topic is not
support. The validator re-retrieves the evidence itself precisely to catch that.

## Numbers are copied or derived, never computed in prose (A2)

Every numeral, percentage, unit and date in your output, in headers, labels, charts and notes
alike, is either **verbatim in a cited passage** or **a declared `derivation`** with its
formula, its named inputs, each input's value and each input's citation.

You are free to compute. Differences, ratios, percentages and unit conversions are
first-class. The only rule is that the working goes in the structure, not in a sentence:

> HbA1c fell 1.3% on the drug and 0.8% on the comparator. *"A larger reduction, by 0.5
> percentage points"* is legitimate as a derivation: `formula: "a - b"`, both inputs cited,
> `result: 0.5`, `unit: "percentage points"`. The same words as plain text, with no
> derivation, are a fabricated number.

The numeric linter extracts every numeral, normalises it (`3.2M` against `3,200,000`, `%`
against `percent`), matches it to a cited passage or a derivation, and **re-executes every
formula**. It runs twice: on your text, and again on the text of the rendered deck.

- **Rounding leaks.** If the passage says `29ms` and you write *"about 30ms"*, 30 appears in no
  source.
- **Names with digits are copied exactly** (*ALPHA-7, GLP-1*). When they appear in a header,
  a cited block on that slide should name them too.

### The number traps the linter catches

These caught a hand-written gold deck as well as model drafts. Check each one.

- **Every number in a sentence must be in that block's own quotes.** If the sentence says
  "at week 26" or "25 mg", the quote must contain "week 26" or "25 mg". Choose a longer run
  of the same passage, or add a second citation. A number from a neighbouring sentence you
  did not quote does not count.
- **Keep the source's unit.** If the source writes "- 1.1%", write "1.1%", not "1.1 points".
  If a table prints a bare "79.48" and only its caption says "percent", write "accuracy
  79.48", not "79.48%".
- **A derivation's unit appears in the sentence word for word.** A derivation with
  `unit: "percentage points"` is written "a lead of 1.68 percentage points", not "a
  1.68-point lead".
- **Do not hyphenate a number onto a word.** Write "40K sentences", not "40K-sentence", and
  "6.79 percentage points", not "6.79-point".
- **Signs are not checked; magnitudes are.** "Fell 1.3%" against a source "- 1.3%" matches.
  Say the direction in words.

## Framing is exempt from citation, and therefore fenced (A5)

`framing` blocks are labels, names, the audience and occasion, the question the deck answers,
and labelled implications. They carry no citation, so they may assert nothing checkable.
The framing linter enforces:

- **no numerals**, not even "three";
- **no named studies, papers, trials or authors**;
- **no comparisons or superlatives with factual content**: "the fastest", "the leading",
  "superior", "compared with", "more effective than";
- **no evidence verbs**: "demonstrates", "establishes", "proves".

A framing block that breaks the fence is **demoted to a claim**, and then fails for having no
citation. The test: **if a measurement could falsify it, it is a claim.** *"The question is
whether a tablet can replace the first injection, and for whom"* is framing. *"The tablet
outperforms injectables"* is a claim and needs a citation for each comparator it names.

## What you must never do

- **Invent a source.** A plausible `doc_id` and a plausible quote are worse than no citation.
- **Cite a figure description or any machine-generated text.** Descriptions help find the
  right page; they are never citable. Neither is your own summary of a document.
- **Use a reference deck as a source of fact** unless it is the client's deck supplied as
  evidence (a redesign). Past decks teach structure and voice.
- **Carry material from another client's documents.** One build, one client.
- **Fill a slot to fill it.** An empty optional slot beats a sentence written to occupy space.
- **Write `source` or `section_number`.** Code computes them.
