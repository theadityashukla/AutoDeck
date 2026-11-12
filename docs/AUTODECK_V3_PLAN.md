# AutoDeck v3 — Plan

**Status:** draft for owner review, 2026-11-12. Nothing here is built. This document records
the principles and decisions agreed in the v3 review conversation and proposes the build
order. It does not replace `docs/AUTODECK_V2_PLAN.md` until the owner accepts it.

**Reading order:** §1 (why), §2 (principles), §3 (what was decided). The rest is how.

---

## 1. Why v3

### 1.1 What v2 was built for

v2 was designed for one job: generate a deck for reps from existing, approved material, with
full traceback, so that a new deck would not need a fresh MLR review. Its constitution says
so: accuracy first, beauty second, speed third; eight blocking invariants (A1–A8); four
mandatory approvals per deck.

### 1.2 What AutoDeck is now for

Three applications, in order of importance:

1. **Co-creating a deck in conversation.** The owner and the system design a deck together.
   Two problems with doing this in a general assistant today: the decks look generic
   (recognisable standard templates), and compute is wasted (the strongest model spends its
   time on slide ratios and colour choices a cheaper model could settle).
2. **Meeting notes** from a transcript or recording. Secondary.
3. **Fully traceable decks** (the original job). One mode, for a small group.

### 1.3 Why v2 cannot simply be extended

Since October, v2 has been stretched toward applications 1 and 2: draft-first (B43), a
`normal` provenance mode (B55), free layout (B69), an agent session (B71), memory (B77),
meeting notes (B78–B83). Each was sound. Together they feel jerry-rigged, for one reason:

> **v2 was built strict-first. Everything else is strict with exemptions.**

The symptoms:

| Symptom | Where it shows |
|---|---|
| The run is the container for everything | One run holds the request, the session, the artifact, the approvals and the mode. Notes and a deck share a session folder by reseeding (B82). |
| The transcript is the state | A session resumes by replaying its transcript under deterministic compaction (B74), mainly to satisfy A6. |
| Every sentence pays for assurance | The IR types every sentence as claim or framing; the schema default is `strict`; `normal` still resolves and judges every claim. |
| One model does every layer | The deck agent runs on one role. It sets the brief, writes the copy and places frames in percent of the slide. Routing is by pipeline stage. |
| Design has freedom but no direction | The writer designs each slide as it writes it. No deck-level concept is decided, and the owner is never shown alternatives. |
| Chat wraps commands | The UI runs CLI chains (B42, B83); a chat message is `revise --say`. |

v3 turns the direction around: **the base is a plain deck built in conversation; strict is an
overlay.**

---

## 2. Principles

**P1 — The engagement is the container.** An engagement holds sources (papers, transcripts,
uploaded decks, the owner's own words) and artifacts (decks, notes). Each artifact has
versions. A run is no longer a concept.

**P2 — Chats are disposable threads.** A thread opens from the artifact's current state, its
change log and memory. No transcript is replayed, and no agent persists between threads.

**P3 — The base is a plain deck; strict is an overlay.** In the base, text is text: no claim
typing, no citation resolution, no validator, no gates. Strict adds annotations and rules on
top of the same deck, and only strict decks carry or pay for them.

**P4 — Every decision has a layer, and each layer has the cheapest capable owner.** The lead
model writes intent. Lower tiers and code turn intent into copy, coordinates and files.

**P5 — Design is decided before it is applied.** A deck-level concept and design system
exist as an artifact, chosen from rendered options, and every slide conforms to them.

**P6 — Chat proposes; the owner disposes.** Proposals arrive rendered, changes arrive as
diffs, every change can be undone, and a selection on the slide is the scope of a message.

**P7 — No stages, only state.** The conversation has no fixed order. Any layer may be
missing or provisional, and an upstream change marks downstream work stale without forcing a
rebuild.

---

## 3. Decisions

### 3.1 Settled in the review conversation

| # | Decision |
|---|---|
| V1 | Chat is the centre of the product. Comments and command chains are not. |
| V2 | There is no planning mode and no revision mode: one conversation, one tool set. |
| V3 | Editing is **auto** by default: the model judges whether to talk, propose or change the deck. A **propose-first** setting is the alternative. |
| V4 | Every edit lands in the change log and can be undone. That is what makes V3 safe. |
| V5 | Routing is **automatic by layer, with a manual override**. It will be benchmarked later, so every change records which model made it. |
| V6 | Outside strict mode there is **one confirmation, at export**. No other approvals. |
| V7 | Reproducibility (A6) applies in strict mode only. The change log is universal, as a product feature (undo, thread context, benchmark data), not as an audit record. |
| V8 | Outside strict mode there is no claim typing, citation resolution or validation. A fact-check is a tool the owner or the model may call; it never blocks. |
| V9 | Client isolation (A4) holds in every mode. It protects confidentiality, not accuracy. |
| V10 | Strict mode keeps A1–A8 and its gates as written, as an overlay (§9). |

### 3.2 What happens to v2's locked decisions

| v2 | In v3 |
|---|---|
| D1 editable native PPTX | **Kept.** |
| D2 cloud models only | **Kept**, with the existing exception for local transcription (B78). |
| D3 Docling ingestion with provenance | **Kept.** |
| D4 Deck IR is the source of truth | **Kept, reshaped:** a plain base IR; assurance annotations move to the overlay (§8). |
| D5 PPTX end to end, no HTML conversion | **Kept.** |
| D6 provider abstraction | **Kept.** Bindings move from pipeline roles to layers (§6). |
| D7 CLI-first, UI deferred | **Reversed.** The chat interface is the product. A CLI remains for strict runs and for tests. |
| D8 curated knowledge folders | **Kept.** They become the engagement container. |
| D9 invariants are blocking | **Scoped to strict.** |
| D10 native editable charts | **Kept.** |
| D11 vector icons | **Kept.** |
| D12 header voice per client | **Kept**, as craft guidance in a skill. |
| D13 balance enforced by lints | **Demoted** to advisory findings the model may use. |

### 3.3 What happens to the invariants

| Invariant | Base | Strict overlay |
|---|---|---|
| A1 citation, A2 numbers, A3 validation, A5 framing, A8 uncertainty | Not enforced. Available through the fact-check tool. | As written. |
| A4 client isolation | **Enforced.** | Enforced. |
| A6 reproducibility | Not required. Change log only. | As written. |
| A7 human gates | One export confirmation. | Four approvals, as written. |

---

## 4. Concepts

**Engagement.** One client and one project: today's `knowledge/clients/<c>/` and
`knowledge/projects/<p>/` pair, plus everything made for it. The isolation guard (A4) is the
boundary.

**Source.** Anything the work draws on: ingested documents, a meeting transcript, an
uploaded deck, and the owner's messages. Sources are read through tools.

**Artifact.** A thing being made: a deck or a set of notes. An artifact has a type, a
current version and a change log. An engagement can hold many.

**Change log.** An append-only list of changes to an artifact. Each entry records:

- what changed (an id-keyed diff, reusing `ir/store.diff_decks`);
- the instruction that caused it, in a sentence;
- which thread, layer and model made it;
- whether it has been undone.

**Thread.** One chat. It belongs to an engagement and may touch any of its artifacts. It
holds its own messages for display, but nothing depends on them after the thread closes.

**Memory.** Unchanged from B77: engagement memory under the client, owner memory in the home
folder. Owner memory is where taste accumulates across engagements.

**State markers.** Each part of an artifact is one of:

- `decided` — the owner chose it or accepted it;
- `provisional` — the system filled it in so work could continue (for example a default
  design system when slides were asked for first);
- `stale` — something upstream changed after it was made.

---

## 5. The conversation

### 5.1 What a thread starts with

A new thread is given, built from state and never from an earlier transcript:

1. the engagement context and both memory files;
2. for each artifact in play: a compact view of its current state (argument, design concept,
   slide list with intents and markers);
3. the recent change log, including what was rejected and undone;
4. a list of what is provisional, stale or open.

The first reply in a returning thread is a short recap from items 2–4.

### 5.2 What a turn can be

The lead model chooses, from what the owner said:

| Kind | What happens |
|---|---|
| **Talk** | A reply. Nothing changes. |
| **Propose** | One or more rendered options, or a described change with a preview. Nothing changes until the owner picks. |
| **Change** | The artifact is edited. The reply states what changed and shows the affected slides. |

In auto mode (V3) the model picks among all three. In propose-first mode a change larger
than a trivial edit becomes a proposal. Strict mode forces propose-first, because a change
there voids approvals.

### 5.3 Rules of the conversation

- **Show, do not ask.** A design question is answered with renders, not with a paragraph
  about palettes.
- **Ask only what changes the deck** (carried from B48). At most three questions at once,
  each with a suggested answer.
- **Selection is scope.** When the owner selects a slide or an element, the message is about
  that selection. With no selection it is about the artifact.
- **Undo is always available**, per change and back to any earlier version.
- **No order is imposed** (P7). The owner may start from the argument, a design, one slide,
  or a transcript.

### 5.4 Several threads on one artifact

Allowed. Before a thread edits a part of an artifact that another thread has changed since
it last read it, it is shown the current version and edits on top of that. Sequential
threads never meet this case.

---

## 6. Layers and routing

### 6.1 The layers

| Layer | Decides | Output | Owner |
|---|---|---|---|
| **L1 Direction** | Audience, goal, the argument, the design concept, what each slide must prove | Brief, storyline, concept, slide intents | Lead tier |
| **L2 System** | Palette, type scale, grid, motifs, chart and diagram style | Design system artifact | Senior tier |
| **L3 Composition** | The copy and the visual structure of one slide, within the system | Slide content and a layout sketch | Senior or mid tier |
| **L4 Placement** | Exact frames, sizes, alignment, fit | Free layout | Low tier, or code |
| **L5 Mechanics** | Aspect ratio, export, text fitting, file handling, routing a trivial edit | Files | Code first, low tier otherwise |
| **Review** | Whether the result works, read cold | Findings | A different model from the one that made it (carried from B73) |

Tiers are bound to models in config, per environment, as today. No model id appears in code.

### 6.2 The contract between layers

The rule that saves the compute: **a layer never does the work of the layer below it.**

- L1 writes a slide intent in words: what it proves, and the visual idea ("one large number,
  with the comparison as a quiet footnote"). It never writes coordinates or picks a colour.
- L3 writes the copy and a layout sketch in relative terms (regions, emphasis, order).
- L4 turns the sketch into frames that pass layout QA.

v2's IR already separates words from placement (every word is a block; a layout only
positions blocks). v2's `write_slide` tool demands both from one model in one call. v3
splits the tool, not the IR.

### 6.3 Delegation

The lead works through tools. Three of them hand work down:

- `design_system(concept)` → L2;
- `compose_slides(intents)` → L3, in parallel across slides;
- `place(slide)` → L4, usually called by L3's result handler and not by the lead.

A delegate receives only what its layer needs (the intent, the system, the relevant source
passages), returns a result and its check findings, and keeps no state.

### 6.4 Routing a message

1. A trivial, local edit ("shorten this title", "swap these two slides") goes straight to
   the lowest tier that can do it. The lead is not invoked.
2. Anything about direction, or anything ambiguous, goes to the lead.
3. The owner can override: name the tier for a message, or pin the lead for a thread.

Every change log entry records the layer and the model (V5). That log is the benchmark's
data.

### 6.5 A caveat on environments

Tiering only means something where the tiers differ. In `dev-mistral` every layer binds to
small models, so routing can be built and tested there, and judged only on the production
bindings.

---

## 7. The design layer

This is the answer to "the decks look generic".

### 7.1 Why they look generic

A deck looks generic when design is defaulted slide by slide. Nobody decided what this deck
should look like, so each slide falls back to the most probable layout.

### 7.2 What v3 adds

**A design concept** (L1): one or two sentences, derived from the content and the audience.
It names the visual idea, not the tokens.

**A design system** (L2): the concept made concrete. Palette, type scale, grid and margins,
how emphasis works, chart and diagram style, recurring motifs, and what the deck never does.
It is an artifact with versions, and a client's slide master constrains it where one exists
(carried from B69: the master is the only fixed layer).

**Rendered options.** When the direction is open, the lead states two or three concepts and
the lower tiers render each as a title slide and two content slides using the deck's real
content. The owner picks one, blends them, or describes something else.

**Conformance.** Every composed slide is checked against the system by code where the rule
is mechanical (colours, type steps, margins) and by the reviewer where it is judgement.

**Taste memory.** What the owner chooses and rejects is written to owner memory, within the
existing leak rules, so later decks start closer.

### 7.3 The layout vocabulary

The free-layout IR today offers: text frames in six type roles, charts, diagrams, figures,
icons, and four plain shapes (`rect`, `rounded_rect`, `ellipse`, `line`), in ten theme
colour tokens with a tint. That list is the ceiling on how distinctive a deck can look.

Phase 3 begins with a review of this vocabulary against a set of decks the owner considers
well designed, and extends it where the gap is real. Candidates to examine: images as
full-bleed or cropped elements, more shape kinds, rotation, transparency, gradient fills,
and text-level emphasis inside a block. Each addition must render natively and stay editable
(D1, D5).

### 7.4 What does not change

Deterministic layout QA (overflow, overlap, safe area, minimum type size, contrast) keeps
running on every slide in every mode. A slide that fails is fixed by L4 or reported; it is
not exported broken.

---

## 8. Data model

### 8.1 The plain base

| Object | Holds |
|---|---|
| `Engagement` | client, project, sources, artifacts, threads |
| `DeckArtifact` | brief, storyline, design concept, design system reference, slides, markers |
| `Slide` | intent, blocks, speaker notes, layout, marker, links to the storyline points it serves |
| `Block` | plain text, or a chart, diagram, figure or icon. No claim, no citation, no verdict. |
| `DesignSystem` | tokens and rules, versioned |
| `NotesArtifact` | sections and items in plain text, each optionally linked to transcript turns |
| `ChangeLog` | entries as in §4 |

Carried from v2 unchanged: `ChartSpec`, `DiagramSpec`, `FreeLayout` and its elements,
`Placement`, the theme tokens.

A block may carry an optional **source note**: a pointer to the document and page a
specific fact came from. It is a convenience for the owner and has no rules attached.

### 8.2 The strict overlay

A strict deck is a base deck plus an annotation set keyed by block id:

- the block's type (claim or framing);
- its citations and derivations;
- its verdict;
- the approvals and the fingerprints they cover.

The v2 `Claim`, `Citation`, `Derivation` and verdict models move here as they are. A base
deck with no overlay is valid. A strict deck with an incomplete overlay is not.

### 8.3 Staleness

Each part of an artifact records a fingerprint of what it was made from: a slide records the
storyline points and the design-system version it was composed against. When those change,
the slide is `stale`. This generalises two things v2 already has: approvals bound to
fingerprints (B43), and `Slide.message_ids`.

---

## 9. Strict mode

Strict is the original product, kept whole, for the group that needs it.

- It is chosen when the artifact is created and cannot be removed afterwards.
- It runs on the same engagement, artifact, change log and renderer as the base.
- It adds the overlay (§8.2), the checking code under `autodeck/audit/`, the four approvals,
  the audit report and the build manifest.
- It forces propose-first editing, document-only sources, and the pinned validation
  bindings.
- It is the one place where an order is imposed, because its gates are an order by design.

Whether a strict deck is safe to skip a regulatory review is a judgement for the people
responsible for that review. The system's part is to make every statement traceable and to
refuse to export one that is not.

---

## 10. Meeting notes

Notes are a second artifact type on the same core.

- **Input:** a recording (transcribed locally, B78) or a transcript. Both become a source.
- **Making them:** the same conversation. "Write up this meeting" produces a notes artifact;
  "turn that into a deck" produces a deck in the same engagement, drawing on the same
  source. Nothing is reseeded.
- **Shape:** the seven fixed sections from B80 are kept, because readers look for decisions
  and actions in the same place every time.
- **Links to the transcript:** each item may link to the turns it came from, shown as a
  time. In the base this is a source note; in strict it is a citation.
- **Carried rules that are about notes, not about assurance:** an action with no stated
  owner reads "Owner TBD"; a corrected spelling goes to engagement memory.
- **Confidentiality:** the `confidential_ok` flag per environment (B81) is kept.

---

## 11. Carry-forward map

Judged from module structure and interfaces. Each row is confirmed or corrected when its
phase starts.

| v2 area | Lines | Verdict | Note |
|---|---|---|---|
| `ingest/`, `retrieval/` | 2,800 | Keep | |
| `knowledge/` (folders, isolation guard, memory) | 1,100 | Keep | Becomes the engagement container. |
| `meeting/` (local transcription) | 700 | Keep | |
| `providers/` | 1,600 | Keep; rework the registry | Bindings per layer; routing log. |
| `design/` theme, fonts, charts, diagrams, icons, draw, `layout_kit`, free layout and its QA | about 8,000 | Keep | |
| `design/` component catalog, budgets, grammar lints | about 3,500 | Demote | Vocabulary and small-model fallback. |
| `render/` renderer, previews, deterministic QA | about 2,400 | Keep | Must accept the base IR. |
| `render/qa/aesthetic.py`, `agents/art_direction.py`, `ir/actions.py` | about 1,600 | Retire | Replaced by the design layer and the reviewer. |
| `ir/models.py` layout, chart, diagram models | part of 2,200 | Keep | |
| `ir/models.py` block, claim, citation, deck root | part of 2,200 | Split | Base form plus strict overlay. |
| `ir/store.py` | 400 | Rework | Diff kept; storage becomes the change log. |
| `agents/session.py`, `tools/registry.py` | about 500 | Keep the loop and tool mechanics | Drop transcript-as-state. |
| `agents/workspace.py`, `deck_agent.py`, `notes_agent.py`, `notes_workspace.py`, `meeting_deck.py` | about 2,400 | Rework | Basis for the lead and the artifacts. |
| `agents/advisor.py` | small | Keep | The reviewer. |
| `agents/` planner, outline, content, compose, repair, evidence gap, evidence pack | about 6,500 | Retire as paths | Citation resolution is salvaged into the overlay. |
| `audit/` | 7,100 | Strict overlay | Plus one on-demand fact-check tool for the base. |
| `pipeline/` orchestrator, gates, send-back | 1,900 | Strict overlay | |
| `cli.py` | 4,100 | Shrink | Strict runs and tests. |
| `ui/` | 3,900 + 4,000 static | Replace | Chat-native interface. |
| `prompts/skills/` | 16 files | Keep | Add a design-direction skill. |
| `prompts/` stage prompts | about 15 files | Retire with their stages | |
| Tests | 39,800 | Follow their modules | |

---

## 12. Build order

The build starts with an interactive mock-up, then eight phases. Each phase ends with
something the owner can use and judge. There are no approval gates in the build beyond the
owner saying whether the phase did its job.

### First step — An interactive mock-up (before any phase)

Nothing in Phases 0–7 starts until the owner has used a mock-up and this plan has been
revised from what it showed. The plan describes a conversation; the cheapest way to find
out where it is wrong is to click through one.

**What it is:** a clickable front end with scripted content. No model calls, no rendering
to PPTX, no engine behind it. Slides are static images or simple drawn layouts.

**What it must let the owner try:**

- an engagement's home: its sources, artifacts and threads;
- opening a returning thread and reading the recap built from state (§5.1);
- the three kinds of turn: talk, propose and change (§5.2);
- a design question answered with two or three rendered directions to pick from (§7.2);
- the slide strip with `decided`, `provisional` and `stale` markers (§4);
- selecting a slide or an element and sending a message scoped to it (§5.3);
- the change log, with undo of a single change (§4);
- which layer and model handled a message, and the manual override (§6.4);
- auto and propose-first editing (V3);
- a notes artifact beside a deck in one engagement (§10);
- the single export confirmation (V6), and how a strict deck looks different (§9).

**What it is not:** a prototype to grow into the product. It is thrown away, or kept only as
a visual reference. The interface stack (§14, question 2) is decided after it, not by it.

**Done when:** the owner has walked through it, said what feels wrong or missing, and this
plan has been updated to match. Only then does Phase 0 begin.

### Phase 0 — Foundations

- Engagement container over the existing knowledge folders.
- Plain base IR; layout, chart and diagram models carried over.
- Change log with undo; id-keyed diff reused.
- Renderer and layout QA accept the base IR.

**Done when:** a hand-written base deck renders to PPTX and previews, and an edit to it can
be made, listed and undone.

### Phase 1 — Conversation core

- Thread model; context built from state (§5.1); recap on a returning thread.
- The lead loop with base tools: read state, read sources, edit, propose, undo.
- A minimal chat interface: streamed replies beside live slide previews.
- One model for every layer. No routing yet.

**Done when:** the owner builds a short deck over two separate threads, and the second
thread picks up correctly with no transcript.

### Phase 2 — Layers and routing

- The tool split of §6.2: intent, composition, placement.
- Delegation tools, with slides composed in parallel.
- Bindings per layer; routing of trivial edits; manual override.
- Layer and model recorded on every change.

**Done when:** on the same request, the lead emits no coordinates and no colour choices, and
the log shows the cost per layer beside the Phase 1 single-model cost.

### Phase 3 — The design layer

- Layout vocabulary review and extensions (§7.3).
- Design concept and design system as artifacts.
- Rendered options in the conversation.
- Conformance checks; the reviewer sees renders, not only text.
- Taste notes to owner memory.

**Done when:** for one piece of content the system offers three directions the owner agrees
are distinct and none of which reads as a stock template, and the chosen one holds across
the whole deck.

### Phase 4 — State and refinement

- `decided`, `provisional` and `stale` markers; staleness by fingerprint.
- Selection as scope in the interface.
- Several threads on one artifact (§5.4).
- The propose-first setting; the export confirmation.

**Done when:** the owner changes the argument of a finished deck and sees exactly the
affected slides marked stale, and rebuilds only those.

### Phase 5 — Notes and sources

- Notes artifact; recording and transcript as sources in the conversation.
- Notes to deck in one engagement, with no reseeding.
- Source notes on blocks.
- The on-demand fact-check tool.

**Done when:** a real recording becomes notes and then a readout deck in one thread.

### Phase 6 — The strict overlay

- Annotation set over the base IR; v2's claim, citation and verdict models moved in.
- `audit/`, gates and manifest running against base plus overlay.
- A1–A8 coverage re-established, with v2's invariant tests ported.

**Done when:** a strict deck built in v3 passes every invariant test v2 passes today.

### Phase 7 — Routing benchmark

- Compare layer bindings on cost, time and the owner's judgement of quality, from the change
  log.
- Adjust the default bindings.

### On the order

Phases 0–2 are sequential. Phase 3 is the one that addresses the generic-deck problem and
could move ahead of Phase 2 if the owner would rather see design quality before cost
savings; it would then run on a single model first. Phase 6 depends only on Phase 0 and can
be scheduled whenever the strict group needs it.

---

## 13. Risks

| Risk | Why it matters | What to do |
|---|---|---|
| Preview speed | Rendered options are only useful if they appear in seconds. Previews go through LibreOffice today. | Measure in Phase 0. If slow, render options in parallel and cache by slide content. |
| Delegation loses the idea | A design concept passed down in words may arrive diluted. | The reviewer checks renders against the concept; the lead sees the result and may send one slide back. Judge in Phase 3. |
| Routing overhead | Deciding the layer costs a call. On small edits that can exceed the saving. | Route trivial edits by rule first, by model only when the rule cannot tell. Measure in Phase 7. |
| Vocabulary additions break editability | A new primitive that does not render as a native shape violates D1. | Each addition ships with a native-render test. |
| Two IR shapes drift | Base and overlay could diverge until strict cannot be rebuilt. | The overlay is keyed to base block ids from Phase 0, and Phase 6's exit test is v2's own invariant suite. |
| The plain base states something false | With no checker running, a misquoted figure can reach a client. | The fact-check tool, source notes, and the export confirmation. This is an accepted trade (V8). |

---

## 14. Open questions for the owner

1. **Where v3 is built.** Recommended: a `v3/integration` branch from `v2/integration`, new
   code beside the old, v2-only paths moved to `legacy/v2/` as they are replaced.
2. **The interface stack.** The v2 UI is a standard-library server with plain JavaScript and
   no streaming. Recommended: keep it local and dependency-light, add streaming, and decide
   the front-end approach at the start of Phase 1.
3. **Phase 3 before Phase 2?** See the note on order.
4. **Reference decks for the vocabulary review.** Phase 3 needs a handful of decks the owner
   considers well designed.
5. **When strict is needed.** That sets where Phase 6 falls.

---

## 15. Not in scope

- Any change to how MLR review works, or any claim about when it is required.
- Multi-user collaboration. v3 is built for one owner across isolated clients.
- Containerised or hosted deployment (deferred in B10, still deferred).
- Output formats other than PPTX for decks and Markdown for notes.
