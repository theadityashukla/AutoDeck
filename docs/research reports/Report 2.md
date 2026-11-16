# Craft Evidence Base for AutoDeck: Storyline, Beauty, and Meaning-Level Fidelity

The single most important finding is that the biggest risk in an LLM-built deck is not ugliness or weak storyline. It is the slide quietly saying more than the source did. LLM summaries of scientific texts broaden conclusions far more often than human summaries do, and asking the model to "be accurate" made this worse. So AutoDeck's craft instruction should be built around a meaning-preservation contract, and design and storyline guidance should sit inside it. Your priority order (truth, then decision, then clarity, then beauty) holds up, with one refinement: "truth" should mean the truth of what a reader comes away believing, not only the truth of the words on the slide.

## TL;DR

- **Fidelity first:** Peters and Chin-Yee (Royal Society Open Science, 2025) compared 4,900 LLM summaries with their sources. Three of the ten models tested (DeepSeek, ChatGPT-4o and LLaMA 3.3 70B) overgeneralized in 26–73% of cases, even when explicitly prompted for accuracy. LLM summaries were nearly five times more likely than expert-written NEJM Journal Watch summaries to contain broad generalizations (OR = 4.85, 95% CI 3.06–7.70). The usual mechanism is dropping a qualifier, switching past tense to present, or turning a description into advice. Every slide therefore needs a check, separate from the quote check, that compares what the slide asserts against what the source asserts: scope, modality, causality, attribution and tense.
- **Storyline and slide logic:** answer-first pyramid storylines, sentence headlines and visual evidence are the best-supported structure. Garner and Alley (2013) found better comprehension, fewer misconceptions and lower cognitive load with assertion–evidence slides in a study of 110 engineering students. Specific word counts, the 10-20-30 rule and "three bullets max" are folklore. Treat your 60/50/90 budgets as engineering limits, not science.
- **Winston, translated:** what carries over to a static executive deck is his empowerment promise, the fence (near-miss contrast), verbal punctuation as signposting, naming an idea once and keeping the name, the vision–steps–contributions arc, and ending on contributions. His near-empty slides, deleted titles and board-over-slides advice are about live speaking. They conflict with pre-read decks and should be left out.

---

## Executive summary: the ten rules to put first (in priority order)

1. **Say only what the source says, at the strength it says it.** Keep the subject, population, conditions, magnitude, direction, modality, causal or correlational status, tense of reporting, and attribution. A paraphrase may change words. It may not widen scope, raise certainty, or turn a finding into a recommendation unless the source does so itself. (Strong evidence: Peters and Chin-Yee 2025; Sumner et al. 2014.)
2. **Keep the qualifier on the same surface as the number, always.** Put the scope tag (who, where, when, how measured, single source, "reported by X citing Y") next to the figure, never only in notes. (Strong evidence that dropping qualifiers is the main distortion mechanism; Sumner et al. 2016 found caveats did not reduce news uptake.)
3. **Make every headline a claim the cited evidence entails as written.** If the evidence cannot carry the strongest version, weaken the headline. (Practitioner consensus plus experimental support for sentence headlines: Garner and Alley 2013.)
4. **Build the storyline before any slide: one governing thought, then a pyramid of supporting claims, then a ghost deck of headlines only.** Test it by reading only the titles. (Practitioner consensus: Minto; consulting practice.)
5. **Design for the decision the audience has to make.** Open with what they will be able to decide or do (Winston's empowerment promise). Close with what the deck established and what is being asked (Winston's contributions ending). (Primary source for Winston; practitioner consensus.)
6. **One idea per slide, shown by the strongest evidence form the catalog allows.** Prefer a chart or diagram over bullets when the claim is quantitative or structural. (Strong evidence for the principle: Mayer; Garner and Alley.)
7. **Mark the boundaries of every idea.** Use fences ("this is X, not Y"), near-miss contrasts, and one stable name per concept across the whole deck. (Winston, primary source; terminology consistency is practitioner consensus.)
8. **Make the focal point unmistakable.** Use one emphasised block, one accent colour used only for meaning, and position on a common scale for any comparison that matters. (Strong evidence: Cleveland and McGill 1984; practitioner consensus on emphasis.)
9. **Draw data honestly.** The size of an effect in the graphic should equal its size in the data (Tufte's lie factor of about 1), with zero-based bar axes, direct labels and no decorative dimensions. (Practitioner consensus with perceptual support.)
10. **Make every slide readable and robust.** Text contrast at least 4.5:1 (3:1 for large text), chart marks at least 3:1, meaning never carried by colour alone, and a squint test and grayscale test passed on the rendered image. (Standard: WCAG 2.2.)

---

## Thread A: Patrick Winston

### Primary sources used

The main source is the MIT OpenCourseWare transcript of "How to Speak" (RES.TLL-005, January IAP 2018), which I read in full. Video timestamps are not verified. Pointers give the transcript section in talk order: opening; samples of heuristics; time and place; tools (boards, props, slides); special cases (informing, inspiring, persuading); how to stop. Other sources: the OCW 6.034 Fall 2010 lecture pages (Lecture 1 "Introduction and Scope"; Lecture 15 "Learning: Near Misses, Felicity Conditions", recorded November 3, 2010); his Slice of MIT column "The Rumpelstiltskin Principle" (August 16, 2009); the MIT Press description of *Make It Clear: Speak and Write to Persuade and Inform* (2020, 360 pp.); and his paper "The Strong Story Hypothesis and the Directed Perception Hypothesis" (AAAI Fall Symposium, 2011).

### Verdict on each recalled idea

| Recalled idea | Verdict | What he actually said (pointer) |
|---|---|---|
| Empowerment promise | **Verified** | "start with empowerment promise. You want to tell people what they're going to know at the end of the hour that they didn't know at the beginning of the hour." (opening). *Make It Clear* description: "start with an empowerment promise and conclude by noting you delivered on that promise." |
| Cycling | **Verified** | "cycle on the subject. Go around it. Go round it again." Mechanism: "at any given moment, about 20% of you will be fogged out... you need to say it three times." (heuristics) |
| Fence | **Verified** | "I want to build a fence around it so that it's not confused with somebody else's idea." Example: "my algorithm might seem similar to Jones's algorithm, except his is exponential, and mine's linear." (heuristics) |
| Verbal punctuation | **Verified** | Enumerating seams so people who "fog out" can "get back on the bus": "I'm giving you a sense that there's a seam in the talk, and you can get back on." (heuristics) |
| Winston's star | **Verified** | "something I like to call Winston's star... every one of the items... starts with an S": symbol, slogan, surprise, salient idea, story. "when I say salient idea, I don't mean important. What I mean is an idea that sticks out. Some theses, funnily enough, have too many good ideas." (getting famous). Lecture 15's OCW description: "how to package your ideas better." |
| Near-miss examples | **Verified** | "this is not an arch, but it doesn't miss by much. So it's a near miss." (How to Speak). Lecture 15 OCW description: "a model which evolves through examples and near misses; this is an example of one-shot learning." Verbatim Lecture 15 text not obtained. |
| Rumpelstiltskin principle | **Verified (wording single source)** | 6.034 Lecture 1 transcript excerpt on OCW: "Rumpelstiltskin Principle says that once you can name something, you get power over it." OCW notes it recurs in Lecture 9. The 2009 Slice column applies it to students' names. |
| "Right representation" | **Partly verified** | In How to Speak he uses Papert's bicycle-wheel prop to show "how it's important to look at the problem in the right way." The slogan "right representation" as a 6.034 quote is **unverified**. |
| How to start | **Verified** | "Some people think the right thing to do is to start a talk with a joke. I don't recommend it." The audience is still adjusting to "your vocal parameters." (opening) |
| How to end | **Verified** | The final slide should be labelled "contributions." Collaborators go on the first slide. Questions, "the end" and plain "conclusions" slides waste the slot. "Thank you... is a weak move" because it implies people stayed out of politeness. (how to stop) |
| Slides vs board, density, reading aloud | **Verified** | Board for informing; "slides are good when your purpose is exposing." "There are always too many slides, always too many words." "one of the things you shouldn't do is read your transparencies." Mechanism: "we humans only have one language processor." Minimum font: an audience member suggests "40 or 50"; Winston agrees; 35 "is beginning to get too small... because you're probably using it to get too many words on the slide." Too-heavy test: print the deck and lay it on a table. "Hapax legomenon": at most one deliberately overwhelming slide. (tools) |
| Three kinds of talk | **Corrected** | Not three parallel types. He covers **informing** (start with a promise); **inspiring** as a question about informing (people are inspired by someone who "exhibited passion" or "helped them see a problem in a new way"); teaching people **how to think** through stories; and **persuading**, which "breaks down into several categories, oral exams... shop talks, getting famous", with the job talk as the worked case. |
| Vision / steps / contributions | **Verified** | Show "vision" and that "you've done something" within five minutes. Vision is "a problem that somebody cares about and something new in your approach"; then "listing the steps"; "you conclude by enumerating your contributions." He calls it "a kind of general purpose framework for doing a technical talk." *Make It Clear* formalises "VSN-C (Vision, Steps, News–Contributions)" plus a "broken-glass" outline (publisher description). |
| Success order | **Verified** | "your success in life will be determined largely by your ability to speak, your ability to write, and the quality of your ideas, in that order." Quality depends on knowledge, practice and talent, "and notice that the T is very small." (opening) |
| Story; Strong Story Hypothesis | **Verified** | "we are storytelling animals." Teaching people to think means giving them "the stories they need to know... ways of evaluating how reliable a story is" (informing). Paper: "The Strong Story Hypothesis: The mechanisms that enable humans to tell, understand, and recombine stories separate human intelligence from that of other primates" (Winston 2011; DSpace handle 1721.1/67693). |
| Practice audiences (bonus) | **Verified** | People who know your work "will hallucinate that there's material in your presentation that isn't there." Oral exams most often fail through "failure to situate and a failure to practice." |

### Table A: Winston principles translated for AutoDeck

| Rule (imperative) | Mechanism (his) | Source | Confidence | Translation to a static executive deck | Checkable test |
|---|---|---|---|---|---|
| Open with what the reader will be able to decide or know by the end. | Gives the "reason for being here." | How to Speak, opening; *Make It Clear* | Attribution verified; efficacy practitioner consensus | Executive summary states the decision the deck equips the reader to make; closing slide confirms delivery. | The promise names a decision; the close answers it point for point. |
| Return to the governing thought at each section boundary. | About 20% "fogged out" at any moment (his estimate). | How to Speak, heuristics | Attribution verified; the 20% is folklore-level | Section dividers and callouts restate the governing thought or the section's link to it. Repeat the idea, not the sentence. | The governing thought (or an entailing paraphrase) appears on the executive summary, at least one divider, and the close. |
| Fence every key idea against its nearest neighbour or likeliest misreading. | Stops the audience merging your idea with a similar one. | How to Speak, heuristics | Attribution verified; contrast learning is practitioner consensus | Two-column compare, before/after, or a fence line ("association, not causation"; "pilot stores, not chain-wide"). | Every headline with a plausible misreading has a fence on the slide. |
| Teach concepts with near misses. | One example differing in a single feature teaches that feature (one-shot learning). | How to Speak; 6.034 Lecture 15 description | Attribution verified | Definition and framework slides show a labelled non-example. | The non-example differs on exactly one criterion. |
| Signpost structure with numbered seams. | Lets lost listeners "get back on the bus." | How to Speak | Attribution verified | Agenda, dividers and position marker as navigation. | Every divider matches an agenda item verbatim. |
| Name each concept once and keep the name. | Naming gives "power over" an idea. | 6.034 Lecture 1 (OCW excerpt) | Attribution verified (single source) | Deck glossary; no stylistic synonyms. | A term scan finds no synonym drift. |
| Make the one big idea memorable with the star, selectively. | Symbol, slogan, surprise, salient idea, story make work recognisable. | How to Speak; *Make It Clear* | Attribution verified; efficacy anecdotal | One slogan-like governing thought, one source-supported surprise, one symbol (big number or icon), one SCQA story. | One salient idea is identifiable; not five equally weighted big ideas. |
| End on contributions and the ask. | The last slide stays up longest. | How to Speak, how to stop | Attribution verified | Closing call to action: established claims, decision requested, next steps. | Two or more cited established claims plus one explicit ask; no "thank you" or "questions". |
| State vision, then steps, then contributions. | Evaluators judge vision and achievement within five minutes. | How to Speak; *Make It Clear* VSN-C | Attribution verified | Maps onto SCQA for persuasive decks. | The first three content slides establish the problem and the novelty of the approach. |
| Review heaviness across the whole deck. | Laid out on a table, heavy decks are obvious. | How to Speak, tools | Attribution verified | A vision model reviews a contact sheet. | No more than two consecutive text-led slides at their word ceiling (your threshold). |
| Allow at most one deliberately overwhelming slide. | A "hapax legomenon" makes complexity itself the point, once. | How to Speak | Attribution verified | Only when the claim is "this is too complex", stated in the headline. | At most one slide exceeds its class budget, with an explicit complexity headline. |

### Winston ideas to leave out for a static deck

- **Near-empty slides and deleted titles.** He removes titles because the speaker carries the words. A pre-read has no speaker, and your citation model needs assertive headers.
- **Board over slides, props, empathetic mirroring.** Live-only. He calls the mirror-neuron explanation his "lunatic fringe view"; do not encode it as a mechanism.
- **Time, place, lights, hands, laser pointers, seven-second pauses, closing jokes, salutes.** Not applicable. His "put a little arrow on there" fix carries over as the emphasised block.
- **Font size 40–50.** From a lecture hall; your type-scale lever encodes size. Keep only the point that small fonts invite too many words.
- **"Remembered what they read on the slide."** An informal student experiment with fraternity freshmen as subjects; illustration only, not evidence.

---

## Thread B: How to build a deck

### Where the methods agree and disagree

- **Agreement.** Minto's pyramid, SCQA, ghost decks, action titles and assertion–evidence slides share one move: decide the claim, then show the evidence beneath it. Every tested method points the same way: sentence headlines plus visual evidence beat topic headlines plus bullets (Garner and Alley 2013; Alley and Neeley 2005; Alley et al. 2006).
- **Answer-first vs question-led.** Minto and consulting practice put the answer at the top. Winston opens job talks with vision before contributions. For an executive deciding something, answer-first wins. When the corpus does not support a single answer, question-led is *more faithful*, because a forced governing thought overstates the evidence.
- **Minimal vs self-contained slides.** Winston and Mayer's redundancy principle push text off slides. But redundancy concerns *narration plus identical on-screen text*. Its boundary conditions include learner-paced presentation and the absence of narration (Mayer, *e-Learning and the Science of Instruction*, redundancy chapter), which is the pre-read case. The evidence does not forbid text on pre-reads. It forbids a presenter reading the slide aloud.
- **Titles.** Winston deletes them; Alley and consultants make them carry the claim. For AutoDeck, Alley and consulting practice win.

### Recommendation: an evidence-gated pyramid

1. The planner agrees the decision and audience.
2. The outline agent drafts a governing thought plus three to five key-line claims (SCQA introduction) as a ghost deck of headlines only.
3. Each headline is checked against the corpus for entailment *before* content is written.
4. Unsupported headlines are weakened, re-scoped, or turned into questions.

This keeps Minto's discipline but reverses the usual failure of fixing the answer first and recruiting evidence to fit it.

### Table B: deck-building principles

| Rule (imperative) | Mechanism | Source | Confidence | Translation to static executive deck | Checkable test |
|---|---|---|---|---|---|
| State one governing thought; make every section a reason or step supporting it. | A summary above its supports lets readers predict and file information. | Minto, *The Pyramid Principle* (via practitioner summaries) | Practitioner consensus | Executive summary is the apex; dividers state key-line claims. | Each divider answers "why/how?" about the governing thought. |
| Open with Situation–Complication–Question, then the Answer. | Creates the felt need before the answer. | Minto SCQA | Practitioner consensus | First two to three content slides, or compressed into the executive summary. | The deck's question can be extracted from the opening. |
| Group sibling points without overlap (MECE). | Overlap double-counts; gaps undermine the claim. | Minto; consulting practice | Practitioner consensus ("exhaustive" often unachievable) | Icon pillars, card grid, framework. | An LLM judge lists overlaps; headlines never claim completeness that cannot be shown. |
| Draft a ghost deck of headlines before any body. | Reordering sentences is cheap; reordering slides is not. | Consulting practitioner sources (no primary firm source) | Practitioner consensus | Human gate 2 approves the ghost deck. | Titles read top to bottom form a coherent argument. |
| Write each headline as a full-sentence assertion supported by the slide. | Directs attention to the main point; deeper comprehension. | Garner and Alley 2013, *IJEE* 29(6):1564–1579 (110 engineering students) | Strong evidence (education setting) | Every content slide has a cited assertion header. | Header has a verb; entailment against cited spans passes. |
| Support the assertion with visual evidence where the content allows. | Words plus relevant graphics; bullets fragment logic. | Mayer multimedia principle; Garner and Alley | Strong evidence | Numbers lead to chart focus or big number; sequence to timeline; structure to framework. | Flag bullets used for sequential or quantitative content. |
| One idea per slide. | Limits load; keeps headers entailed. | Mayer coherence; practice | Practitioner consensus with theoretical support | Split two-claim slides. | No "and" joining independent claims in the header. |
| Apply the "so what" test, honestly. | Data without implication shifts work to the reader. | Consulting practice | Practitioner consensus | State the implication only if the source supports it; else label it "Implication (our inference)". | Every implication is cited or labelled as inference. |
| Make the titles alone tell the argument. | Executives skim headlines. | Consulting practice | Practitioner consensus | Deck-level test. | An LLM judge reconstructs the governing thought from concatenated headers. |
| Size the deck to its purpose. | Winston's "80th slide" with "the first of 10 conclusions slides" shows the failure. | Winston anecdote; no empirical length standard found | Folklore for any number | Short body plus appendix for decision pre-reads. | Every body slide sits in the governing thought's tree; the rest go to the appendix. |
| Put proof the decision rests on in the body; other proof in the appendix. | Protects the main line without hiding evidence. | Consulting practice | Practitioner consensus | Methods, sensitivity and tables go to the appendix. **Hedges never do.** | No body-claim qualifier appears only in appendix or notes. |
| Use speaker notes for delivery and depth, never for limits on the claim. | Notes are invisible in most reading modes. | Inference from your constraint | Recommended rule | Talk track, context, full source passage. | Diff body vs notes for scope or modality words found only in notes. |
| Differentiate pre-read and presented decks. | Learner pacing removes the redundancy concern. | Mayer redundancy boundary conditions; Winston | Strong evidence for mechanism; application is inference | Pre-read: self-contained, full scope tags. Presented: lighter body; notes complement rather than repeat. | A mode flag drives word ceilings and notes policy. |

### Cognitive science: what the literature actually says

- **Mayer's principles.** Mayer (2017, *Journal of Computer Assisted Learning*) reports effect sizes for principles that reduce extraneous processing: coherence d = 0.70, signalling d = 0.46, redundancy d = 0.87, spatial contiguity d = 0.79, temporal contiguity d = 1.30. These come mostly from lab studies with novice learners; expect smaller effects with expert executives.
- **Redundancy has boundaries.** Mayer and Johnson (2008, *Journal of Educational Psychology*) found short on-screen text, as opposed to full transcripts, can help alongside narration. The strong reading holds for verbatim duplication only.
- **Spatial contiguity** directly supports direct chart labels and keeping hedges beside numbers.
- **Words per slide.** I found no study establishing an optimal number of words or bullets per slide. Kosslyn et al. (2012, *Frontiers in Psychology* 3:230) found slideshows "on average violate approximately six of the eight principles," with academic slideshows "no better or worse than business slideshows," and observers were poor at spotting violations, which argues for automated checks. The 10-20-30 rule, "6x6" and "max three bullets" have no direct experimental support that I could find: folklore.

---

## Thread C: How to make it beautiful (through levers only)

Your five levers are layout component, type scale, one accent, one emphasised block, and icons from a fixed list. Each principle below is a lever decision plus a test runnable on the rendered image by a vision model (**V**) or computable from structured slide data (**S**).

### Table C: visual principles

| Rule (imperative) | Mechanism | Source | Confidence | Lever / translation | Checkable test |
|---|---|---|---|---|---|
| Give every slide one focal point: the evidence for the headline. | Contrast draws the eye; competing focal points split attention. | Mayer signalling (d = 0.46); design practice | Strong (signalling); consensus ("one") | Emphasise exactly one block, the one carrying the claim. | **V** Squint test: blur the render; the first thing that stands out is the emphasised block. **V** Three-second test: a description after a brief glance matches the headline. |
| Encode important comparisons as positions on a common scale. | Position is decoded most accurately; angle, area, volume, shading less so. | Cleveland and McGill 1984, *JASA* 79(387):531–554; Heer and Bostock 2010 replication | Strong evidence | Bar, dot or line over pie or area; card grid only for a few headline numbers. | **S** Chart type vs question: comparison to bar/dot; trend to line; pie only for two or three slices. |
| Keep the graphic's effect size equal to the data's. | Visual exaggeration misleads even with printed numbers. | Tufte (1983): lie factor = effect in graphic / effect in data; secondary notes report his 0.95–1.05 threshold (not verified in the primary text) | Practitioner consensus | Zero-based bar axes; no 3D. | **S** Compute lie factor from geometry. **V** Flag 3D and truncated baselines. |
| Remove ink that carries no data. | Non-data ink competes for attention. | Tufte data-ink ratio; Mayer coherence (d = 0.70) | Consensus (extreme minimalism contested) | Renderer defaults: light or no gridlines, no borders or backgrounds. | **V** Flag heavy gridlines, shadows, gradients, logo clutter. |
| Label data directly. | Removes look-up and split attention. | Mayer spatial contiguity; Knaflic, *Storytelling with Data* (2015; not re-verified) | Strong (contiguity) | Renderer rule for charts. | **S/V** Legend present with four or fewer series: flag. |
| Use one accent colour, only for meaning. | Colour attracts attention; decoration wastes the signal. | Few, Knaflic (not re-verified); Mayer signalling | Practitioner consensus | Accent = focal series or number; all else neutral. | **V** Accent only on the emphasised element. **V** Grayscale test: focal point still identifiable. |
| Never let colour carry meaning alone. | Colour vision deficiency is common. | WCAG 2.2 SC 1.4.1 | Standard | Pair accent with label, position or icon. | **V** Colour-blind simulation and grayscale: meaning survives. |
| Meet contrast minima. | Legibility at distance and for low vision. | WCAG 2.2 SC 1.4.3 (text 4.5:1; large text 18 pt or 14 pt bold 3:1); SC 1.4.11 (graphics 3:1) | Standard | Theme accent passes against background and under text. | **S** Ratios from theme tokens. **V** Sample pixels where text overlays images. |
| Use few type sizes in a fixed hierarchy. | Consistent scale signals importance reliably. | Design practice | Practitioner consensus | The type-scale lever changes the whole hierarchy, never single sizes. | **S** More than three or four sizes per slide: flag. |
| Align to a grid; group by proximity. | Gestalt proximity and alignment signal relationships. | Gestalt principles | Practitioner consensus | Pick a layout whose grouping matches the logical grouping. | **S** Visual groups = logical groups. **V** Flag misaligned or orphan elements. |
| Split the slide rather than shrink the type. | Crowding raises load; small fonts invite words (Winston). | Winston; design practice | Practitioner consensus | Overflow at "standard": split or move non-limiting detail to notes; "compact" for appendix only. | **S** Overflow flags. **V** Contact-sheet heaviness. |
| Use a diagram only for real structure: sequence, hierarchy, cycle, matrix, flow. | Diagrams help when layout mirrors logic. | Mayer; Kosslyn 2012 | Consensus with theoretical support | Framework or timeline only when relations are stated in the source or a derivation. | **S** Every arrow maps to a cited relation; flag decorative cycles. |
| Use icons as a consistent label system. | Stable mappings aid recognition; decorative icons add load. | Coherence principle; practice | Practitioner consensus | One icon per concept for the whole deck. | **S** One-to-one concept–icon mapping. |
| Vary rhythm across the deck. | Monotony reads as template-made and hides structure. | Practice; Winston table test | Practitioner consensus | Outline-level layout planning; section dividers. | **S** Flag runs of three or more identical layouts or density runs. |

---

## Thread D: Staying true to the source (meaning, not wording)

### What a faithful paraphrase must preserve

Treat each source claim as a structured tuple. The slide's claim must not exceed it in any field.

| Field | Must preserve | Typical distortion | Evidence |
|---|---|---|---|
| Subject / intervention | What was studied, exactly | Specific to category | Practitioner consensus |
| Quantity measured | The metric, not a proxy | "Beliefs" to "behaviour" | Practitioner consensus |
| Magnitude and unit | Exact number and unit | Rounding; relative/absolute swaps | Your constraint |
| Direction | Better or worse | Sign flips on negatively framed metrics | Practitioner consensus |
| Scope / population / setting | Who, where, when | Quantified to generic ("participants" to "people") | **Strong:** most frequent transition in Peters and Chin-Yee 2025 |
| Conditions / configuration | Dose, settings, version, benchmark | Mixing results from different conditions | Practitioner consensus |
| Modality | "Can", "may", "associated with" vs "does" | Hedge upgrade | **Strong:** Sumner et al. 2014 |
| Causal status | Correlational vs causal design | Causal claims from observational data | **Strong:** Sumner et al. 2014 (BMJ 349:g7015) and replications |
| Tense of reporting | Past sample result vs present general truth | "Reduced" to "reduces" | **Strong:** Peters and Chin-Yee 2025 |
| Descriptive vs prescriptive | Finding vs recommendation | Advice injection ("should") | **Strong:** Peters and Chin-Yee; Sumner et al. |
| Attribution | Own result vs cited result | "X found" when X cited Y | Your constraint; consensus |
| Species / model | Human vs animal; real vs simulated | Human claims from animal research | **Strong:** Sumner et al. 2014 |
| Source's emphasis | Primary vs secondary result | Elevating an exploratory result | Practitioner consensus |

**May move to notes:** method detail that changes no field above, unused secondary outcomes, affiliations. **May never leave the slide surface:** any qualifier that changes scope, modality, causality, attribution or the conditions of a displayed number; single-source status; limitations the authors attach to the specific result.

### Documented distortion patterns

1. **Overgeneralisation through generics and tense.** Peters and Chin-Yee give a real example. Source: disinformation exposure "had strong detrimental effects on participants' climate change beliefs (δ = −0.16)". LLM summary: exposure "significantly undermines individuals' beliefs in climate change". A past-tense sample result became a present-tense generic and a small effect lost its magnitude.
2. **Hedge upgrade and correlation-to-causation.** Sumner et al. (2014, BMJ 349:g7015) studied 462 press releases from 20 UK universities. Of these, 40% contained exaggerated advice, 33% exaggerated causal claims and 36% exaggerated inference to humans from animal research. News stories exaggerated far more often when the press release did (58%, 81% and 86% respectively) than when it did not (17%, 18% and 10%). Sumner et al. (2016, PLOS ONE) found caveats did not reduce news uptake, so keeping hedges does not cost attention.
3. **"Be accurate" prompts can backfire.** In Peters and Chin-Yee, the accuracy prompt was *more* likely to produce generalized conclusions than the simple prompt. Temperature 0 cut the odds of generalization by 76% relative to 0.7. Claude-family models had the lowest rates among those tested. Use structural checks and low temperature, not exhortation.
4. **Quotable-line capture, false balance, lost emphasis, condition mixing.** Practitioner consensus; no single LLM study isolates them. Sentence-level checkers catch them poorly.

### Finding the core idea vs the most quotable line

1. Locate the source's own summary statements and stated limitations.
2. Identify the primary outcome and the authors' discussion claim about it; label exploratory results as such.
3. Write the core idea as the tuple above.
4. Check the slide sentence against the tuple, not the quotable sentence. A line broader than the conclusion section fails.
5. Invert Winston's "salient vs important": for fidelity, carry the source's *important* (primary) claim even if a secondary result is more salient.

### Automated "does the slide mean what the source means" check

| Method | What it does | Limits for AutoDeck | Use |
|---|---|---|---|
| FActScore (Min et al. 2023, EMNLP) | Splits text into atomic facts; scores the share supported | Measures support, not strength; splitting can strip qualifiers | Decompose slides, **keeping qualifiers attached** |
| SummaC (Laban et al. 2022, TACL) | Sentence-level NLI entailment, aggregated | Weak on cross-sentence synthesis | Cheap first screen |
| AlignScore (Zha et al. 2023, ACL) | Unified alignment model trained on 4.7M examples across 7 tasks | Consistency, not claim strength | Second screen on header and body vs cited spans |
| AIS (Rashkin et al. 2023, *Computational Linguistics*) | Is the statement interpretable, and would a hearer affirm "According to P, s"? | Human-centred; AutoAIS approximates via NLI | Template for the LLM-judge rubric |
| RARR (Gao et al.) | Researches and revises unattributed output | Can over-edit | Auto-repair after failure |

**Caveat.** Zheng, Lapata and Pan ("Long-Form Information Alignment Evaluation Beyond Atomic Facts", EMNLP 2025) built the MontageLie benchmark from true pieces arranged to imply something false. They report that evaluators are susceptible, with "AUC-ROC scores falling below 65%"; in their tests SummaC-ZS, SummaC-Conv, AlignScore and FActScore scored about 50–57, near chance. Sentence- and fact-level checks miss distortion created by composition, which is the slide-level risk (true number + true chart + causal-sounding headline).

**Recommended layered check, separate from quote presence:**

1. **Claim layer.** Decompose header, body and callout into atomic claims with qualifiers attached. Require "entailed" against cited spans; "neutral" fails for headers.
2. **Strength layer (LLM judge, fixed rubric).** Compare source tuple and slide tuple field by field: broader scope? stronger modality? causal for correlational? present for past? prescriptive for descriptive? attribution collapsed? conditions mixed? Any "yes" fails. This operationalises Peters and Chin-Yee's three generalization types and Sumner's three exaggeration types.
3. **Round-trip layer.** A separate model sees *only the rendered slide* and lists what a reader would believe. A source-grounded judge asks whether the authors would endorse each belief (AIS "according to P"). Any belief they would not endorse fails, even if every sentence passes entailment.

---

## Thread E: Additions

- **Evaluation rubrics.** PPTEval (Zheng et al., PPTAgent, EMNLP 2025) scores content, design and coherence on 1–5 with an MLLM judge grounded in Duarte's principles. It has no fidelity dimension. Kosslyn et al. (2012) offer eight psychological principles usable as a checklist. **Proposed AutoDeck rubric, in priority order:** (1) fidelity: strength-layer and round-trip pass rates; (2) decision fit: promise answered, explicit ask; (3) argument: title-only reconstruction, MECE overlap, entailed headers; (4) clarity: focal-point test, layout–content fit, terminology consistency; (5) craft: contrast, grayscale, colour-blind, rhythm, lie factor.
- **LLM writing failure modes.** Filler opener: "In today's rapidly evolving landscape, organisations face unprecedented challenges" becomes "Three of five regional sites missed their 2025 throughput target." Inflated adjectives: "a robust, transformative solution delivering significant value" becomes "cut changeover time from 42 to 31 minutes in the two pilot lines." Generic tense upgrade: "Remote work boosts productivity" becomes "In the 2023 survey of 1,200 UK firms, managers reported higher productivity among remote staff (self-reported)." Also watch for uniform triplets, "not just X, but Y" titles and vague quantifiers ("many", "significant"). These examples are illustrative. The overgeneralization patterns are strong evidence. The stylistic tics are practitioner consensus, and claims about specific LLM vocabulary are unverified here.
- **Accessibility.** WCAG 2.2 SC 1.4.3, 1.4.11 and 1.4.1 as in Table C. Export reading order: header, evidence, takeaway, source. Chart alt text states the claim and key numbers with scope tags, and must pass the same fidelity check.
- **Terminology.** Build the glossary at the outline stage. The content agent may not introduce synonyms; the validator scans for drift.
- **Hardest questions.** Winston warns that informed reviewers "hallucinate" missing material. Have an adversarial reviewer agent with no access to the planner's intent pose the three hardest executive questions per section. Answers go to the appendix. If an answer limits a body claim, the limit goes on the body slide.
- **Practitioner additions.** A source line in a fixed position on every evidence slide. "Single source" and "derived" badges as a visual convention, so hedges read as part of the deck's visual language. Explicit "Implication (our inference)" labels separating the consultant's reasoning from the source's finding.

---

## Conflicts and resolutions

| Tension | Recommended resolution | Reasoning |
|---|---|---|
| **Hedges vs minimalism** | The hedge is part of the number: a compact scope tag beside the figure. Pay for it by cutting decoration and secondary text, never the qualifier. Consider a capped word allowance for scope tags (your decision). | Dropping qualifiers is the main documented distortion (Peters and Chin-Yee); caveats did not reduce uptake (Sumner et al. 2016); spatial contiguity favours adjacency. |
| **Action titles vs cited headers** | Keep assertion headers but require entailment as written. Multi-source synthesis becomes a declared derivation with listed premises; otherwise weaken or use a question header. | Garner and Alley support sentence headlines; the headline is the highest-risk sentence. |
| **Winston's empty slides vs pre-reads** | Follow him for presented-mode body text and talk tracks; not for titles or density on pre-reads. | His advice assumes a speaker ("condiments to what you're saying"). |
| **Redundancy vs text-led slides** | Allow text on pre-reads; in presented mode notes complement rather than duplicate. | Redundancy concerns narration plus identical text; learner pacing is a boundary condition. |
| **Answer-first vs mixed evidence** | Answer-first only when the corpus supports a governing thought; otherwise question-led, with "what the evidence shows / does not show". | A forced answer is deck-level overgeneralization. |
| **Paraphrased prose vs exact numbers** | Paraphrase structure and verbs; keep numbers, units, dates and scope-defining hedge words ("associated with", "self-reported", "in mice") verbatim or strength-equivalent. | Modality and causal verbs carry meaning like numbers. |
| **Design advice vs fixed levers** | Express each principle as layout, emphasis, accent, type scale or icon mapping; leftovers (gridlines, alignment) are renderer duties tested by a vision model. | Visual agents cannot alter words. |
| **One accent vs multi-series charts** | Accent = focal series; others neutral grey with direct labels. | Colour as meaning; colour-blind safety. |
| **Priority order** | Keep truth, decision, clarity, beauty, with truth defined as the reader's resulting belief, tested by round-trip. | The montage-lie result shows true sentences can create false beliefs. |

---

## Anti-pattern catalogue

| Name | How to recognise | Fix |
|---|---|---|
| **Scope creep** | Subject broader than the sample ("customers" for "pilot-store customers") | Restore population in scope tag |
| **Tense inflation** | Source past, slide present | "Reduced… in the trial" |
| **Hedge upgrade** | "May/associated/suggests" became "does/drives/proves" | Copy the source's modality class |
| **Causal leap** | Causal verb on correlational evidence | "Associated with" plus fence |
| **Advice injection** | "Should" where the source describes | Label "Implication (our inference)" or remove |
| **Attribution collapse** | "X found" when X cited Y | "Reported by X, citing Y" |
| **Condition mixing** | Numbers from different configurations side by side | Separate cards with configuration tags |
| **Quotable-line capture** | Headline uses the most striking line, not the primary conclusion | Re-derive from the conclusion and primary outcome |
| **Montage implication** | True parts juxtaposed to imply an unsupported link | Round-trip test; add a fence |
| **Hedge exile** | Qualifier only in notes or appendix | Move to slide surface |
| **Topic title** | Noun-phrase header ("Market Overview") | Cited assertion header |
| **Ungated synthesis header** | Header supported by no single span | Declared derivation, or weaken |
| **Uniform bullets / symmetric triads** | Every slide has three similar bullets or pillars regardless of evidence | Layout by content type; group count = evidence count |
| **Decorative diagram** | Arrows with no stated relation | Bullets with support |
| **Icon confetti** | Icon on every bullet, unrelated to meaning | One icon per concept |
| **Accent sprawl** | Accent on headers and decoration | Accent only on the focal element |
| **Stock language** | "Unlock value", "robust", "seamless" | Source nouns and numbers |
| **Template monotony** | Runs of identical layouts | Rhythm rule |
| **Polite ending** | "Thank you", "Questions?" | Contributions plus ask |
| **Synonym drift** | Same concept, different names | Glossary enforcement |
| **Lie-factor chart** | Truncated bar axis, 3D, area for linear quantity | Zero baseline, position encoding |

---

## Before/after examples

### Example 1: a real distortion (Peters and Chin-Yee 2025, Table 3)

- **Source:** "While exposure to disinformation had strong detrimental effects on participants' climate change beliefs (δ = −0.16)…"
- **Unfaithful (LLM, as reported):** "exposure to climate disinformation significantly undermines individuals' beliefs in climate change." Fails on population, tense and dropped magnitude.
- **Faithful slide text:** Header: "Disinformation exposure lowered participants' climate-change beliefs in the study (δ = −0.16)". Scope tag: "Experimental participants; effect size as reported by the authors."

### Example 2: illustrative consulting finding (constructed, not a real study)

- **Source (hypothetical):** "Across 14 pilot stores in Ontario, dynamic pricing was associated with a 3.2% increase in gross margin over 8 weeks relative to matched control stores. Three pilot stores experienced a competitor closure during the period, which may account for part of the effect. Ramos et al. (2021), cited by the authors, report similar effects in grocery."
- **Unfaithful:** "Dynamic pricing boosts margins by 3.2% and should be rolled out chain-wide; similar results have been found in grocery." Causal leap, generic present, advice injection, scope creep, dropped confound, attribution collapse.
- **Faithful:** "In an 8-week Ontario pilot, the 14 dynamic-pricing stores saw gross margin rise 3.2% relative to matched controls. The design shows association, not proven cause, and a competitor closed near 3 of the stores. A similar grocery result is reported by the authors, citing Ramos et al. (2021)."

### Example 3: weak vs strong slide (same hypothetical source)

**Weak slide.** Layout: bullets with support. Title: "Dynamic Pricing Overview". Bullets: "Unlocks significant margin upside"; "Robust results across pilot stores"; "Proven in grocery too"; "Recommended for immediate rollout". Icons: rocket, lightbulb, target, checkmark. Notes: "Pilot was 14 stores; 3 had competitor closures." Diagnosis: topic title, hedge upgrade, vague quantifier, attribution collapse, advice injection, icon confetti, hedge exile.

**Strong slide.**

- Layout: big number
- Header (assertion, cited): "Ontario pilot stores using dynamic pricing saw a 3.2% gross-margin gain relative to matched controls"
- Big number (emphasised block, accent): "+3.2% gross margin"
- Scope tag: "14 pilot stores vs matched controls · 8 weeks · Ontario · association, not proven cause"
- Fence: "Not yet evidence for chain-wide effect: competitor closed near 3 of 14 pilot stores"
- Source line: verbatim citation to the pilot report
- Callout: "Implication (our inference): a controlled multi-region test would show whether the gain holds without the closure effect"
- About 60 words: over the icon-anchored budget, within text-led. See open question 1.

---

## Open questions needing your decision

1. **Word budgets vs hedges.** Should scope tags count toward the 60/50/90 limits? No evidence supports specific limits. I recommend a separate capped allowance (e.g. up to 15 words) so the budget never pressures the model to drop qualifiers.
2. **Synthesis headlines.** Allow headers entailed only by combining several spans, as declared derivations? It is the honest form of most action titles but needs a premise list and checker.
3. **Implication labelling.** Allow labelled consultant inferences on body slides, or only in the executive summary and close?
4. **Question-led mode.** Triggered by the planner at gate 1, or automatically when governing-thought entailment fails?
5. **Thresholds.** Entailment cut-offs, layout run length, type-size count and density ceilings have no empirical standard.
6. **Transfer.** Mayer's and Garner and Alley's results come from students; effects on executives may be smaller. Consider small A/B tests with your consultants.
7. **Tufte vs memorability.** The chartjunk debate is unresolved. I recommend no non-data ornament on evidence slides.
8. **Unverified Winston quotes.** The 6.034 "right representation" wording and Lecture 15's felicity-conditions passage need a manual transcript check before being quoted.

---

## Caveats

- **Winston pointers.** Video timestamps are not verified; pointers are transcript sections in talk order. I did not read *Make It Clear* or his textbook *Artificial Intelligence* in full; claims about their contents rely on the publisher's description.
- **Unverified positions.** Positions attributed to Few, Knaflic, Duarte and Reynolds are not re-verified here. Minto is described from practitioner summaries, not the primary book. Ghost-deck practice is documented only in practitioner blogs.
- **Constructed examples.** Examples 2 and 3 are invented for demonstration. Only Example 1 reproduces a real documented distortion.
- **No separate bibliography.** Bibliographic details (author, year, venue, and volume or pages where available) are given inline wherever each source is used.