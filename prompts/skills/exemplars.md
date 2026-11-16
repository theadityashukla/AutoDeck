---
name: exemplars
summary: "Three finished gold decks, a clinical evidence review, an architecture decision and a question-led research assessment, with their briefs, headline outlines, worked slides and what to copy from each"
use_when: "before writing a deck, to see what a finished one looks like; when unsure how dense a slide should be, or how a slide sentence relates to its quote"
---

# Exemplars

These decks were written by hand from the same corpora this system uses, and every one
passes the checks your drafts face: each quote resolves verbatim, each block fits its slot in
the real font, and the number, framing and header checks are clean. They are the standard.
**Do not copy their facts into another deck**: those facts belong to their papers. Copy how
they are built. (When you write about one of these papers, its own exemplar is withheld, so
the deck you write is your own.)

Look first at three things:
- **Every content slide has a body of 35 to 70 words.** Three to five points, each a complete
  short sentence with its number and its condition.
- **Every headline is a sentence a reader could repeat,** and every number and name in it
  sits in a cited point on the same slide.
- **The slide sentence is never the quote.** The sentence is short and written for the
  audience; the quote is the source's exact words, often three times longer.

<!-- project: oral-semaglutide -->
## Exemplar 1: oral semaglutide, for a hospital P&T committee (answer-first)

**Brief.** Objective: decide whether to list the drug, and for which patients. Audience:
clinicians and pharmacists who know the drug class. Source: one review article.
**Governing thought:** a credible tablet option whose limit is dosing, not efficacy.

| # | Role | Component | Headline |
|---|---|---|---|
| 1 | title | title | A tablet GLP-1 option, if fasting dosing fits |
| 2 | context | bullets_supporting | Oral semaglutide matches or beats common options, at the price of strict dosing |
| 3 | problem | bullets_supporting | Guidelines favour GLP-1RAs, but reluctance to inject holds their use back |
| 4 | mechanism | bullets_supporting | An absorption enhancer gets the peptide through the stomach, but only when fasting |
| 5 | evidence | chart_focus | At 14 mg, HbA1c fell more than on empagliflozin or sitagliptin; liraglutide matched it |
| 6 | evidence | bullets_supporting | At 14 mg, HbA1c fell 0.8% to 1.2% more than placebo, from diet-only to insulin |
| 7 | comparison | bullets_supporting | Weight fell more than on sitagliptin or liraglutide, but only matched empagliflozin |
| 8 | risk | bullets_supporting | Strict fasting dosing is the main practical limit, and no other schedule is tested |
| 9 | risk | bullets_supporting | Side effects were mostly gastrointestinal and early; severe hypoglycemia was rare |
| 10 | risk | big_number | Cardiovascular risk was noninferior to placebo; a benefit was not shown |
| 11 | recommendation | callout_takeaway | (takeaway) List it as a tablet GLP-1RA for patients who can dose fasting on waking |
| 12 | next_steps | closing_cta | Decide on listing now, and revisit when real-world adherence data are published |

Read the headlines alone: they are the argument. Slide 2 is the executive summary: the answer
and its four supports, before any detail. Three of the twelve slides are `risk`, because a
committee decides on limits as much as on benefits.

**Worked slide 7: a comparison that keeps the tie.**

| Slot | Slide sentence (yours) | Quote (theirs, verbatim) |
|---|---|---|
| headline | Weight fell more than on sitagliptin or liraglutide, but only matched empagliflozin | (none; carried by the points) |
| points | vs sitagliptin 100 mg (PIONEER 3): 0.6 to 2.5 kg more lost by week 26, by dose | All three doses of oral semaglutide were associated with significantly greater reductions in body weight compared with sitagliptin (100 mg) [ETD - 0.6 kg (3 mg) to - 2.5 kg (14 mg); p < 0.05 for all doses] at week 26 |
| points | vs liraglutide 1.8 mg (PIONEER 4): 1.2 kg more lost at 14 mg, week 26 | Oral semaglutide (14 mg) also provided a significantly greater body weight reduction compared with placebo (ETD - 3.8 kg; p < 0.001) and liraglutide (1.8 mg) at week 26 in a global population [ETD - 1.2 kg; p < 0.001 (PIONEER 4)] |
| points | vs empagliflozin (PIONEER 2): similar weight loss at weeks 26 and 52 | Body-weight reductions were found to be similar for oral semaglutide compared with empagliflozin [ETD - 0.1 kg ( p = 0.76) and - 0.2 kg ( p = 0.62) at weeks 26 and 52, respectively] |
| points (framing) | Implication: weight loss alone does not separate the tablet from an SGLT2i | (none; a labelled inference with no number or name) |

Notice:
- A 230-character quote becomes an 80-character point that keeps the comparator, the dose,
  the week and the magnitude.
- The headline says "only matched" because the third point is a tie. It does not say
  "superior".
- The implication is the writer's own reading. It is labelled as such and adds no fact.

**Worked slide 10: one figure, with its hedge beside it.**

- **figure** "HR 0.79".
- **figure_label** "MACE hazard ratio vs placebo, PIONEER 6, high CV risk". This label
  is a cited claim, not framing, because it names a trial.
- **support** "MACE occurred in 3.8% vs 4.8% of patients (95% CI 0.57-1.11). Noninferior
  (p < 0.001) but not superior (p = 0.17); the trial was not powered to show superiority."
  It cites three passages.
- The headline states exactly what the trial showed (noninferior, no benefit shown), so the
  large number does not imply a benefit.

<!-- end project -->

<!-- project: transformer-attention -->
## Exemplar 2: Attention Is All You Need, for a CTO (answer-first, bounded ask)

**Brief.** Objective: decide whether to build our next sequence models on the Transformer.
Audience: technical leadership, not specialists. Source: one 2017 paper.
**Governing thought:** strong enough to pilot, not yet to migrate everything.

| # | Role | Component | Headline |
|---|---|---|---|
| 1 | title | title | Build new sequence models on the Transformer |
| 2 | context | bullets_supporting | The Transformer translated better than recurrent models and trained in a fraction of the time |
| 3 | problem | bullets_supporting | Recurrent models compute one position at a time, which caps how far training can parallelise |
| 4 | mechanism | framework_diagram | Attention scores each query against every key, then averages the values by those scores |
| 5 | comparison | bullets_supporting | Self-attention shortens paths between distant words, and is cheaper only for shorter sequences |
| 6 | evidence | chart_focus | On English-German, both Transformer sizes beat every earlier model, ensembles included |
| 7 | evidence | bullets_supporting | Training took 12 hours for the base model and 3.5 days for the big one, on 8 GPUs |
| 8 | evidence | bullets_supporting | With little tuning, it reached 92.7 F1 on English parsing, near the best reported 93.3 |
| 9 | risk | bullets_supporting | The evidence is from 2014 benchmarks, and long inputs remain unsolved in the paper |
| 10 | recommendation | callout_takeaway | (takeaway) Implication: pilot it on our own sequence tasks before migrating |
| 11 | next_steps | closing_cta | Approve a pilot that rebuilds one production sequence model on the Transformer |

**What to copy:**
- **Slide 4 is the only diagram**, because the four steps of attention really happen in
  order. Every step label is four words or fewer, and every step carries a cited claim.
- **Slide 5 keeps the fence:** self-attention is faster "only when sequence length is below
  the representation size". The paper's own condition goes on the slide, not in the notes.
- **Slide 7 shows a source that disagrees with itself.** The abstract gives English-French as
  41.8 BLEU and the results text gives 41.0. The slide states both, each cited, and does not
  pick one:
  - *"The paper gives that English-French score as 41.8 (abstract) and 41.0 (results)"*
- **Slide 8's headline uses numbers from the slide,** 92.7 and 93.3, instead of "close to the
  best", which nobody could check.

<!-- end project -->

<!-- project: lejepa-ssl -->
## Exemplar 3: LeJEPA preprint, for a CTO (question-led)

**Brief.** Objective: decide whether to pilot self-supervised pretraining on our own images
instead of relying on frontier models. Source: one preprint by the method's authors.
**This deck is question-led,** because one preprint whose evidence is all the authors' own
cannot carry a firm "adopt". The title asks the question, slide 2 says what the evidence
does and does not show, and the ask is a pilot.

| # | Role | Component | Headline |
|---|---|---|---|
| 1 | title | title | Should we pretrain on our own images? |
| 2 | context | bullets_supporting | A new method makes in-domain pretraining simpler, but all its evidence is the authors' own |
| 3 | problem | bullets_supporting | Today's self-supervised recipes are brittle, so specialised teams fall back on labels |
| 4 | mechanism | before_after | One regulariser replaces all the heuristics |
| 5 | evidence | chart_focus | On galaxy images, in-domain LeJEPA beat frontier transfer with a frozen backbone |
| 6 | evidence | bullets_supporting | The in-domain lead is largest with a frozen backbone and narrows with full fine-tuning |
| 7 | comparison | bullets_supporting | On transfer benchmarks it edged out I-JEPA with a smaller model, but trailed I-JEPA + STOP |
| 8 | evidence | bullets_supporting | Training needs one hyperparameter and gives a label-free signal for picking models |
| 9 | risk | bullets_supporting | The evidence is the authors' own, and the galaxy result used small models only |
| 10 | recommendation | callout_takeaway | (takeaway) Implication: pilot in-domain pretraining on our images before buying more labels |
| 11 | next_steps | closing_cta | Approve a pilot comparing in-domain LeJEPA with our current transfer setup |

**Worked slide 7: checking the authors' claim against their own table.** The authors write
*"We observe that we consistently outperform IJEPA"*. Their table shows that this holds
against I-JEPA (79.48 vs 78.50 average) but not against I-JEPA + STOP (80.70). The slide
reports both, and its last point attributes the claim and marks its limit:
- *"The authors say it consistently outperforms I-JEPA; that holds against the base
  version"*. This one point cites the authors' sentence and all three table rows.

**Worked slide 6: a computed gap, declared as a derivation.**

| Slide sentence | How it is grounded |
|---|---|
| Full fine-tuning, all labels: 83.28 vs 81.60 for DINOv3, a lead of 1.68 percentage points | Two table rows cited. `derivation`: formula `a - b`, a = 83.28 (row 1), b = 81.60 (row 2), result 1.68, unit "percentage points". The sentence uses the derivation's unit word for word |
| One label per class, frozen backbone: accuracy 31.08 vs 30.17 for DINOv3 | The same two rows. The table prints these numbers without "%", so the sentence does not add one |

Notice:
- **The headline says where the advantage narrows,** not just where it is largest.
- **Units follow the source exactly.** Where a table gives a bare number, the sentence names
  the measure ("accuracy 31.08") instead of adding a "%" the source did not print.
<!-- end project -->
