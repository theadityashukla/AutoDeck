# Phase 3c — Draft-first build

**Status:** APPROVED 2026-10-03 — the owner accepted every proposal below; recorded as
B43–B46 in `DECISIONS.md`. **B47 refines D-PLAN:** a clarify step always runs before the
draft, and a chat mode is available before drafting. **B48 refines B47:** the checkpoint
always appears but asks only questions that would change the deck (and shows its
assumptions); one conversation serves before and after the draft; agreed key messages are
never dropped for weak evidence — kept, hedged and flagged — and anything skipped is called
out in a coverage section.
**Branch:** `v2/phase-3c-draft-first` (cut from `v2/integration`) · **Gate:** GATE 3c ·
**Estimate:** 2–3 weeks
**Source:** the owner, 2026-10-03, after using the B42 review UI: *"It should be able to brief
and outline after the first prompt itself, it is AutoDeck. Whenever it writes something it
should cite it. All of this should happen in the same call. The claim citation is more of an
output contract thing than anything else."* And: *"People really won't want to spend too much
time on brief and outline. They only start to realize what's missing once the pieces start to
assemble."*

> The pipeline today is **gate-first**: a conversation produces a brief, the brief is approved,
> an outline is built and approved, and only then is a word of slide text written. Evidence is
> checked by a separate model call per key message, slides are written one call per slide, and
> claims are re-checked in batches of six. A five-slide deck costs roughly 25–35 model calls and
> four approvals before the owner sees a slide.
>
> This phase makes it **draft-first**: one prompt → one model call that writes the brief, the
> outline and every slide, citing as it writes → deterministic checks in code → one independent
> validation call for the whole deck → a rendered draft. The owner reviews the assembled deck,
> corrects it where they see the gap, and gives the same four approvals **on the draft**.

## Why this is mostly a reshaping, not a rewrite

The parts that make a deck trustworthy already exist and are kept unchanged:

| Kept | What it already does |
|---|---|
| Citation resolution (`agents/content.py`, `DocumentStore.resolve_quote`, `RetrievedSpan.to_citation`, `CachedClaim.to_citation`) | The model names a `doc_id` and a verbatim quote; code resolves them to page, bbox and `quote_sha256`. A quote that does not resolve drops the block. **This is the "output contract" the owner describes — it is already how slides are written; this phase makes it how the brief and outline are written too.** |
| `Citation` schema (A1) | A claim with no citation cannot be constructed. |
| Numeric linter (A2), framing linter (A5) | Deterministic, no model calls. |
| Independent validation (A3: `agents/validation.py`, `audit/verdicts.py`) | Its own retrieval, its own model; already batched. |
| Client isolation (A4: `ContextAssembler`) | Unchanged — the evidence pack is assembled through it. |
| Audit report, manifest (A6), renderer, QA, art direction | Unchanged; the draft renders through the same renderer. |
| Orchestrator fingerprints (A7) | An approval still binds to the bytes it covered. |

What changes is the **shape of the run**: how many calls, in what order, and when the person
is asked.

## The new call flow

```
prompt (+ client, project)
  │
  ├─ 1. Evidence pack ............ code: ContextAssembler + HybridIndex, no model call
  │                                 claims.md + the top spans for the prompt and the project's
  │                                 themes, each with a short id, within a token budget
  │
  ├─ 1b. Clarify ................. ONE short model call (B47): one to four questions the
  │                                 draft depends on, grounded in the pack, each with a
  │                                 suggested answer; the person answers or accepts
  │                                 (or, in chat mode, the planner conversation replaces
  │                                 this step and hands compose a brief)
  │
  ├─ 2. Compose .................. ONE model call (role `composer`)
  │                                 → brief (objective, audience, key messages)
  │                                 → outline (slides: role, component, intent, messages served)
  │                                 → every slide's blocks; every claim cites span id + quote;
  │                                   key messages cite the spans that support them
  │
  ├─ 3. Resolve and lint ......... code: citations resolved (A1), numerals matched (A2),
  │                                 framing linted (A5), budgets checked, key-message evidence
  │                                 status computed from what resolved (the existing `_cap`
  │                                 rule: one non-curated span = thin, none = unsupported)
  │
  ├─ 4. Validate ................. ONE model call (role `validation`, a different model)
  │                                 independent re-retrieval as today (A3), whole deck in one
  │                                 batch while it fits the token budget
  │
  ├─ 5. Draft render ............. code: renderer + LibreOffice previews, marked DRAFT
  │
  └─ the owner reviews the assembled draft
        ├─ "Revise": an instruction → one compose call scoped to what changed → steps 3–5
        │            for the changed slides only (unchanged claims keep their verdicts)
        └─ approvals on the draft (brief, outline, claims), then the final render
           (art direction + critique) and the fourth approval, as today
```

### Call budget, five-slide deck, first draft

| | Today (measured shape, `STATUS.md`) | Draft-first |
|---|---|---|
| Brief | 2–4 planner turns + 1 evidence-probe call per key message per check | 0 (inside compose) |
| Outline | 1 | 0 (inside compose) |
| Slide text | 1 per slide | 0 (inside compose) |
| Validation | 1 per 6 claims | 1 |
| Clarifying questions (B47) | — (part of the planner turns) | 1 |
| **Before the first visible draft** | **~25–35** | **3** |
| Final render (art direction + up to 3 critique looks) | 2–4 | 2–4 (unchanged, after approval) |

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 3c.1 | **Decisions and invariant text** — record the owner's answers to the decisions below; amend `docs/INVARIANTS.md` A3 and A7 wording | **Opus** | `DECISIONS.md`, `docs/INVARIANTS.md` | A3, A7 | Owner-signed entries exist **before** any other task merges |
| 3c.2 | **Evidence pack** — deterministic assembly of the spans one compose call sees: `claims.md` entries, top-k spans for the prompt and for each `project.md` theme, deduplicated, each with a short stable id, capped by a token budget per provider | **Sonnet** | `autodeck/agents/evidence_pack.py` | A1, A4 | Same inputs → same pack (tested); never crosses a client namespace; reports what was cut for budget |
| 3c.3 | **`ComposeDraft` output contract** — brief + outline + per-slide `ProposedBlock`s in one schema; every claim and every key message carries `(span_id, quote)` pairs; required, non-nullable fields (B26) | **Opus** | `autodeck/agents/compose.py` | **A1**, A5 | A claim or key message without a citation pair fails schema validation; round-trips to `DeckBrief` + `Deck` |
| 3c.4 | **`prompts/compose.md`** | **Opus** | `prompts/compose.md` | A1, A8 | Own commit with rationale (plan §0.5); hedges conflicting sources rather than picking one |
| 3c.5 | **Composer agent** — one structured call; resolution through the existing helpers (extract the shared resolver out of `content.py`, do not add a third path); key-message evidence status from resolved citations; budgets via `check_overflow` | **Sonnet** (Opus review) | `autodeck/agents/compose.py`, `autodeck/agents/content.py` | **A1, A2, A5** | A fake-provider test produces a full draft from **one** call; an unresolvable quote drops its block and is reported |
| 3c.6 | **Orchestrator draft mode** — stages may run ahead of approvals to produce a **draft**; the final render and export still require the approvals (see D-A7 below) | **Opus** (invariant-critical) | `autodeck/pipeline/orchestrator.py` | **A7** | Tests: no path produces `deck.pptx` (final) or an export without the four current approvals; a draft never reads as final anywhere (file names, UI, manifest) |
| 3c.7 | **Whole-deck validation** — batch by token budget instead of a fixed 6; independent retrieval unchanged | **Sonnet** | `autodeck/agents/validation.py` | **A3** | A five-slide deck validates in one call on the fake provider; the A3 contradiction test still passes |
| 3c.8 | **Draft render** — previews under `previews/draft/`, every slide marked DRAFT, slides with a blocking verdict flagged on the preview; no art-direction loop for drafts | **Sonnet** | `autodeck/render/`, `autodeck/cli.py` | A3, A6 | A draft render never writes `deck.pptx`; flags match verdicts |
| 3c.9 | **Revise** — an instruction (from the review screen or chat) → one compose call scoped to the slides it touches → resolve, validate the changed claims only, re-render the changed previews | **Sonnet** | `autodeck/agents/compose.py`, `autodeck/pipeline/` | A1–A3, A7 | Unchanged claims keep their verdicts (cache); any change voids the approvals it touches through fingerprints, as today |
| 3c.10 | **CLI** — `autodeck draft <run> --client C --project P "<prompt>"`, `autodeck revise <run> "<instruction>"`; existing commands keep working for the gate-first path until retired | **Sonnet** | `autodeck/cli.py` | A7 | No flag approves anything (the existing bypass test covers the new commands automatically) |
| 3c.11 | **UI** — Home becomes one prompt box; the run screen shows the draft assembling (pack → compose → checks → validation → previews); a draft review screen (slides with their citations and verdicts inline, a revise box); approvals on the draft | **Sonnet** (front end), **Haiku** (copy) | `autodeck/ui/` | A7 | Prompt → visible draft in one action; the four approvals still only via the B42 routes |
| 3c.12 | **Native diagrams from compose** — let compose propose a `diagram` block kind (the GATE 3 criterion-4 debt in `STATUS.md`) | **Sonnet** | `autodeck/agents/compose.py`, `autodeck/design/diagrams.py` | — | A pipeline-made deck can satisfy GATE 3 criterion 4 |
| 3c.13 | **Model routing** — new `composer` role per environment (long context + structured output); planner role kept only for the optional refine chat | **Opus** | `config/models.yaml`, `docs/MODEL_ROUTING.md` | A6 | Each environment binds `composer`; the manifest records it |
| 3c.14 | **Retire or keep** — the evidence-gap probe stays as a library (its `_cap` rule is reused) but leaves the default path; per-slide content writing stays only as the scoped path for 3c.9; the planner conversation becomes optional "refine" | **Sonnet** | `autodeck/agents/` | — | Nothing dead is left reachable; removed paths take their tests with them |
| 3c.16 | **Clarify step** (B47) — `prompts/clarify.md` (Opus) and `autodeck/agents/clarify.py`: from prompt + evidence pack, one to four questions with suggested answers, each tied to what it changes in the draft; answers stored in the run and fed to compose | **Opus** (prompt), **Sonnet** (agent) | `prompts/clarify.md`, `autodeck/agents/clarify.py` | A8 | The draft cannot start without a recorded answer set (accepting every suggestion counts); questions name real gaps in the pack |
| 3c.17 | **Chat mode** (B47) — "Plan in a chat first" runs the existing planner; "Draft the deck" passes its draft brief to compose, which writes outline and slides to it rather than a brief of its own | **Sonnet** | `autodeck/agents/compose.py`, `autodeck/ui/` | A7 | A chat-mode draft keeps the conversation's key messages verbatim |
| 3c.15 | **Docs** — owner guide, status, changelog | **Haiku** | `docs/OWNER-GUIDE.md`, `STATUS.md`, `CHANGELOG.md` | — | The guide describes the draft-first flow end to end |

## Decisions this phase needs (owner)

**D-A7 — When approvals happen.** *Proposed:* the four approvals stay mandatory and stay the
owner's alone, but they are given on the **assembled draft**, not before each stage runs. The
pipeline may build an unapproved draft end to end; it may not produce the final `deck.pptx`,
an export, or anything labelled final without all four approvals current. Approving the brief
after seeing the slides is still approving the brief: its fingerprint binds, and a revision
that changes it voids the approval as today. *Rejected alternative:* dropping to fewer
approvals — the four are what the audit trail records, and the UI already makes each one a
click.

**D-A3 — What "independent" means.** *Proposed:* independence is about **who judges**, not
how many calls: the validator keeps its own retrieval and a different model from the composer,
and judges the whole deck in one batched call. *Not proposed:* letting the composer's own
citations count as validation — that is v1's failure (`legacy/v1/LEGACY.md`).

**D-PLAN — What happens to the planner conversation.** *Proposed:* optional. The first
prompt is enough; the chat becomes a way to revise the draft ("make slide 3 about cost, not
memory"), each message a scoped revise. The brief's fields stay editable directly.

**D-SIZE — Where one call stops being enough.** *Proposed:* one compose call up to a token
budget (roughly 10–12 slides on Gemini flash); longer decks compose the brief and outline in
one call, then slides in section-sized calls, still citing in the same output contract.

**D-GATES — The pending GATE 2 / GATE 3 reviews of the gate-first pipeline.** *Proposed:* do
not run them on the old flow. This phase keeps every component they would judge (validation,
render, QA, audit), and GATE 3c exercises them on the new flow; the owner reviews once.

## Accuracy focus

Draft-first must not become trust-the-model. The line that keeps it honest: **the model
proposes citations; code decides whether they exist (A1, A2, A5); a different model with its
own retrieval decides whether they support the sentence (A3); a person decides whether the
deck ships (A7).** Every one of those checks runs on the draft before the owner sees it, and
the draft shows their results inline — so the first thing the owner looks at is already
verified, which is the point.

## Milestone

From one prompt on the `dev` environment, for `pharma-demo` / `oral-semaglutide`: a rendered
draft deck in which every claim resolves to a verbatim quote on a real page, every numeral
traces, every claim carries a verdict, in **three model calls** (clarify, compose,
validate) before the draft is visible.

## GATE 3c — exit criteria

**The owner gets a usable, cited draft from one prompt, and can take it to a final deck
through approvals given on the draft.**

Checkable:
- First draft in ≤ 3 model calls (clarify, compose, validate) (counted by the fake provider in tests and by
  `provider_calls` on a live run); wall-clock time recorded on `dev`.
- Every claim block resolves (A1); numeric linter clean or every finding shown (A2); framing
  clean (A5); every claim has a verdict from the independent validator (A3).
- Key messages show supported / thin / unsupported computed from resolved citations, with no
  extra calls.
- No code path writes the final `deck.pptx` or an export without four current approvals (A7);
  the existing gate-bypass tests pass unchanged, extended to the new commands.
- A revise touches only the slides it names; unchanged verdicts are reused.
- A3's contradiction test and A8's conflicting-sources fixture pass on the new path.

## Escalation triggers

- One compose call cannot produce a schema-valid draft reliably on `dev` (truncation, null
  arrays — B26). Measure the failure rate; if it is above a few percent, fall back to brief +
  outline in one call and slides in a second, and record it.
- The evidence pack cannot fit enough of the corpus to cite well within the composer's
  context budget. That is a retrieval problem, not a reason to accept uncited text.
- Any design that lets the composer's citation stand in for validation. Stop; that is v1.

## Notes for the implementer

- The content agent's module docstring is the specification for citation resolution. Read it
  first; 3c.5 extracts and reuses it, it does not reimplement it.
- Groq's free tier caps at 8,000 tokens per minute, which a compose call with an evidence pack
  will exceed. On `dev`, `composer` belongs on a long-context Gemini model; Groq stays useful
  for short, latency-sensitive calls such as the revise chat.
- Phase 4's task 4.4 (`build` end to end with four approvals) is largely delivered by this
  phase; Phase 4's plan should be revised to point here when this phase merges.
