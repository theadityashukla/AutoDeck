---
name: fidelity
summary: Saying what the source says at the strength it says it — the fields a paraphrase must preserve, the ten ways slides distort, hedges that travel with the number, conflicting sources, thin evidence, and labelled implications
use_when: writing any claim; checking a headline, takeaway or closing slide; whenever the evidence is thin, hedged, second-hand or conflicting
---

# Fidelity

The biggest risk in a deck built from documents is not ugliness or a weak storyline. It is the
slide quietly **saying more than the source did**. Studies of model-written summaries found
them several times more likely than expert summaries to broaden a conclusion, most often by
dropping a qualifier, switching past tense to present, or turning a finding into advice.
Simply being told to "be accurate" did not help; it made things worse. So this skill gives you
**procedures to run**, not a request to be careful.

## What a faithful paraphrase preserves

Treat every source finding as a set of fields. Your slide sentence may change the *words*. It
may not exceed the source in **any field**.

| Field | Keep | Typical distortion |
|---|---|---|
| Subject / intervention | Exactly what was studied (the 14 mg dose, the int8 model, the pilot stores) | Specific → general category ("the drug", "quantisation", "dynamic pricing") |
| Quantity measured | The actual metric | Memory → "cost"; self-reported → measured; a composite endpoint → "heart attacks" |
| Magnitude and unit | The exact number and unit | Rounding; relative ↔ absolute swaps; percent ↔ percentage points |
| Direction | Better or worse, up or down | Sign flips on negatively framed metrics |
| Scope: population, setting, time | Who, where, when | "Participants" → "people"; "in Ontario pilot stores" → dropped |
| Conditions / configuration | Dose, hardware, version, baseline, duration | Mixing numbers from different configurations on one slide |
| Modality | "may", "suggests", "associated with" | Hedge upgrade to "does", "drives", "proves" |
| Causal status | Correlation vs tested cause | Causal verb on observational data |
| Tense of reporting | "reduced… in the trial" (a past result) | "reduces" (a general truth) |
| Descriptive vs prescriptive | A finding | Advice: "should", "must adopt" |
| Attribution | Whose result it is | "X found" when X was citing Y |
| Species / system | Human vs animal; real vs simulated; production vs benchmark | Human claim from animal or synthetic results |
| Emphasis | Primary result vs exploratory | A secondary result presented as the headline finding |

**May move to the notes:** method detail that changes none of the fields above, secondary
outcomes you do not use, affiliations.

**May never leave the slide surface:** any qualifier that changes scope, modality, causality,
attribution, or the conditions of a number that is displayed; the fact that a result comes
from a single source; limitations the authors attach to that specific result.

## The procedure, for every claim

1. Write the source's finding to yourself as the fields above.
2. Write your slide sentence.
3. Compare field by field. Is the scope broader? The verb stronger? A correlation now causal?
   Past now present? A finding now advice? Attribution collapsed? Conditions mixed?
4. Any "yes" is a defect. Fix the sentence, not the source.

## The ten distortions

| Name | How to recognise it | Fix |
|---|---|---|
| **Scope creep** | The subject is broader than the sample ("customers" for "pilot-store customers") | Put the population back in the sentence or its label |
| **Tense inflation** | The source reports a past result; the slide states a present truth ("reduces") | "Reduced… in the trial" |
| **Hedge upgrade** | "May / suggests / associated with" became "does / shows / drives" | Copy the source's level of certainty |
| **Causal leap** | Causal verb ("cuts", "drives", "boosts") on correlational evidence | "Was associated with", plus a fence: "association, not tested cause" |
| **Advice injection** | "Should" where the source only describes | Remove it, or make it a labelled implication (below) |
| **Attribution collapse** | "X found" when X was citing Y | "X reports, citing Y" |
| **Condition mixing** | Numbers from different doses, hardware or periods side by side as if comparable | Separate items or cards, each with its configuration |
| **Quotable-line capture** | The headline uses the most striking line, not the primary conclusion | Re-derive it from the conclusion and the primary outcome |
| **Montage implication** | True pieces placed together imply a link no source states (a true number + a true chart + a causal-sounding header) | Run the round-trip test (`self-review`); add a fence |
| **Hedge exile** | The qualifier is only in the notes or the appendix | Move it to the slide surface, next to the claim |

## Hedges travel with the number

- **Carry the configuration, or do not use the number.** Not *"HbA1c fell 1.6%"* but *"at
  10 mg, drug A lowered HbA1c 1.6% over 24 weeks"*. Not *"41 ms per token"* but *"on 16
  accelerators, the 70B version of model M generated at 41 ms per token"*. If the configuration will not fit the slot,
  the slot is telling you to pick a different number, use a component with a label beside the
  figure, or split the point.
- **Put the scope tag where the eye lands.** On a `big_number`, the conditions go in
  `figure_label` or `support`, directly beside the figure. On a chart, in the `takeaway`. In a
  card grid, in the card's label.
- **Hedge in words, never in arithmetic.** *"About 65%"* against a source reading
  *"approximately 65%"* is fine. *"Roughly 3×"* against *"2-4 ×"* is not: 3 appears nowhere.
  Never round to hedge, never average to reconcile, never widen a range to be safe.
- **If honest hedging needs a number you cannot cite, drop the number and keep the hedge.**
- **Words that look like hedges and are not,** because nobody can check them: *up to, as much
  as, potentially, could deliver, significant* (unless the source means statistically, and
  says so), *dramatically, industry-leading*. Taking one end of a range the source gave as a
  range is overstatement wearing a hedge.
- **Keeping qualifiers costs nothing.** Research on science communication found that caveats
  did not reduce how much attention a finding got. A precise, scoped claim reads as more
  credible to an expert audience, not less.

## Thin evidence

Evidence is **thin** when it is one source, an adjacent measurement, a mismatched
configuration, or a result the source is reporting rather than making. Then:

- do not use *proves, shows, demonstrates, establishes*;
- name the evidence: *"in the one trial that measured this"*, *"in the authors' own
  benchmark"*, *"reported by the review, citing the original trial"*, *"a design goal stated in
  the abstract, not a measured outcome"*;
- do not stake a whole slide on it with a `big_number`, whose giant figure claims certainty;
- where the brief recorded an **open risk** against a message this slide serves, hedge to
  that risk specifically. Someone accepted that gap in writing.

## When sources disagree

Show both numbers, each with its source and its conditions. Do not average them, do not
widen a range to cover both, and do not quietly take the one that suits the story. A
disagreement is often the most useful thing on the slide: say what differs between the two
(population, period, method).

## Takeaways and closing slides

The last slides are where a deck most often says more than its evidence. A takeaway, a callout
or a closing line **summarises claims already made and cited**; it is no stronger than they
were.

- Check it against **each** comparator, population and outcome it names. If the drug beat one
  comparator and matched another, the takeaway says so. Never "superior to active
  comparators" when one of them was a tie. (Live run 1's closing slide did exactly this, and
  the validator found the slide contradicted by its own source.)
- A takeaway that states a fact is a claim citing the same passages the earlier slides used.

## Labelled implications: your inference, marked as yours

The audience needs the "so what". Often the source does not state it; you are inferring it.
That is legitimate and valuable, **as long as it is visibly yours**:

- Write it as a separate **`framing`** block whose text begins **"Implication:"**.
- It contains **no numbers and no named studies, products' results or comparisons**. The
  framing fence applies (see `citations`). It interprets facts that are cited elsewhere on
  the slide; it adds none of its own.
- It may appear on **any slide**, usually as the last body block, a `takeaway`, or a callout.
- It is **never the factual basis of the headline**. The headline must still be carried by
  cited blocks. A headline may state a recommendation only on `recommendation` or
  `next_steps` slides, where the slide's job is to propose.

> *"Implication: a tablet could reach patients who decline injections, if adherence holds
> outside trials"* is a labelled inference. It names no figure, claims no result, and says
> what would have to be true.
>
> *"Implication: the tablet will cut payer costs by 20%"* is not. It contains a number and a
> claim about the world. It needs a citation, or it does not get written.
