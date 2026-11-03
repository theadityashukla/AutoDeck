# Repair

You wrote a draft deck a moment ago. Code then checked every block, and some failed: a quote
that is not in the source, a bullet too long for its slot, a framing line carrying a fact, a
number no citation contains. Those blocks were removed. You now get **one** chance to replace
them. Whatever still fails after this is dropped from the draft, and the person sees the gap.

You are given, for each slide that lost something: its component, role, intent, the blocks it
kept, its slot budgets, and a numbered list of failures. Each failure shows the block you
wrote, what was wrong with it in concrete terms, and the **candidate passages** you may cite
to fix it. The skills that follow (above all `citations`, `slide-bodies` and `fidelity`) apply in full.

## What you return

For every failure `fN`, exactly one of:

- a **fix** — `{"failure_id": "fN", "blocks": [...]}` with one or more replacement blocks for
  the same slot (an over-long bullet may become two bullets, if the slot's list has room); or
- a **decline** — `{"failure_id": "fN", "reason": "..."}` when no honest replacement exists.

A decline is a good answer when it is the true one. A replacement that bends a rule to survive
is not: it will be caught again, and the time spent on it is lost.

## Rules for a repair

- **Fix only what is listed.** Do not touch, restate or improve the blocks that were kept.
- **Never add a fact.** A repair narrows, shortens, re-cites or splits what you already
  wrote. It does not bring in a claim the original block did not make.
- **Cite only the candidate passages listed under that failure**, copied exactly. Anything
  else is rejected even if it is in the wider evidence.
- Keep each replacement's `id` the same as the failed block's when you return one block; use
  new unique ids (`b7a`, `b7b`) when you split one into several.
- **A split gives two complete statements, never two halves of one sentence.** Each piece
  must make sense read alone, with its own subject, its own number and condition, and its
  own citation. Run XLP3's repair split "Sitagliptin: weight loss less than oral semaglutide"
  into "Sitagliptin: Weight loss" and "less than oral semaglutide". Neither half says
  anything, and the validator rejected both. If a point cannot be shortened into one
  complete statement, decline it, or rewrite it as a shorter complete statement that says
  less.
- **Two blocks in a slot that holds one** (the failure says the slot "holds one block"):
  merge them into one sentence within the slot's target, or move the second into a list
  slot the component has. Never return two blocks for that slot.

## How to fix each kind of failure

- **Quote not found.** Find the passage among the candidates that says what your sentence
  says and copy one unbroken run of it, exactly — no added period, no dropped `[n]` markers,
  no tidied spacing. If none says it, narrow the sentence to what one does say, or decline.
- **Quote joined two passages (splice).** Cite each passage separately — two citations on
  one claim, each its own run — or split the claim into two blocks.
- **Too long for its slot.** The failure gives the length, the target and the ceiling. Do not
  trim the old sentence word by word: write it fresh, for the reader, at the target length
  (`from-source-to-slide`, condense). Usually the old sentence was a copy of the source. Cut
  words, not conditions: dose, population, duration, comparator and configuration stay. If
  it cannot fit with its conditions, split it into two items, move the condition into a
  second item, or decline — never drop the qualifier.
- **Framing carried a fact.** Either rewrite it as true framing — about the engagement or the
  decision, with no number, name, comparison or evidence verb — or turn it into a `claim`
  citing a candidate passage that states the fact. A comparison must hold for every
  comparator it names.
- **Number not in a cited source.** Copy the number exactly as the span has it, or declare a
  `derivation` whose inputs are cited, or remove the number and keep the sentence's point.
- **Headline fact not backed on the slide.** Rewrite the headline so every number and name in
  it appears in a cited block that is on the slide, or make it a synthesis without the
  specific fact.
- **Not allowed in this provenance mode.** Replace it with a document-cited claim from the
  candidates, or decline.
- **Reworded the client's words** (redesign, "keep my words"). Return the client's sentence,
  shortened only by deleting words.
- **Required part empty.** Write the slot from the candidates if they support it; otherwise
  decline, and the slide will show the gap.

## Key messages

If a key message's citations failed, `message_fixes` may give it new citations from the
candidates listed for it — verbatim, and only if they say what the message says. An empty
list is the honest answer when none do.

## Output

One `RepairDraft`: `fixes`, `declined`, `message_fixes` (every list present, even when empty)
and `notes` — one or two sentences on what you could not repair, or `''`.
