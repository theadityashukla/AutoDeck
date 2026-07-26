# Model routing

Two independent layers, both governed here (decision B3):

- **Dev-time** — which model implements which build task.
- **Runtime** — which model AutoDeck itself calls for each agent role (plan §6.2).

Do not confuse them. A Sonnet-implemented module can bind an Opus-class runtime role.

---

# Part 1 — Dev-time routing

## The tiers

| Tier | Owns | Why this tier |
|---|---|---|
| **Opus** | Architecture, contracts, and anything whose error propagates across phases | A wrong IR field or a loose invariant costs weeks and may ship an inaccurate deck |
| **Sonnet** | Implementation against a settled interface — the bulk of the build | Interface is fixed, so the work is competent execution with tests |
| **Haiku** | Mechanical, high-volume, low-judgment work | Repetitive, verifiable by inspection or by a test that already exists |

## What lands where

**Opus**
- Deck IR schema and versioning (§6.1) — every downstream contract derives from it
- Provider protocol and structured-output repair semantics (§6.2)
- Invariant enforcement design; anything under `autodeck/audit/`
- **All files under `prompts/`** — prompts are product surface, not glue
- The three Phase 0 spikes' design and their go/no-go readouts
- `layout_kit` API shape; the `DiagramSpec` type system
- Gate reviews, `DECISIONS.md` entries, phase handovers
- Cross-cutting refactors; any change to a public interface already in use

**Sonnet**
- Docling runner, document store, provenance helpers
- Knowledge loader, context assembler, retrieval
- Agent implementations against prompts Opus has written
- Component renderers (after the first two establish the pattern)
- Linters, CLI commands, chart and theme builders
- Tests for specified behaviour

**Haiku**
- Fixture and test-data generation; golden-file regeneration
- Docstring and type-hint passes
- Batch renames, moves, mechanical refactors with a green test suite
- Dependency pinning; config file scaffolding
- Eval batch execution and result tabulation (Phase 5)
- Log triage and failure summarisation
- Repetitive per-component / per-diagram-type scaffolding once the pattern exists

## Enforcement

Routing that relies on per-task judgment decays within a week. It is made structural:

**1. Task tags.** Every task row in every `docs/phases/PHASE-*.md` carries a `model`
column. **A task without a model tag is not ready to start.**

**2. Dispatch.** Delegated work goes through the `Agent` tool with an explicit `model`
parameter matching the tag.

**3. Path guardrails.** Independent of any tag:

| Path | Minimum tier |
|---|---|
| `autodeck/ir/` | Opus |
| `autodeck/audit/` | Opus |
| `prompts/` | Opus |
| `DECISIONS.md`, `docs/handovers/` | Opus |
| any test asserting an invariant (A1–A8) | Sonnet |
| `legacy/v1/` | frozen — no edits |

Haiku never edits the first four. Sonnet does not author or amend `prompts/` or the IR
schema.

**4. Escalation.** A task escalates a tier when it turns out to require:
- changing an interface other code already depends on,
- touching an accuracy invariant,
- relitigating a locked decision (D1–D13),
- resolving genuine ambiguity in the plan.

Escalate rather than improvise, and log it in handover §8. A Haiku task needing a
judgment call escalates to Sonnet.

**5. De-escalation.** Once a pattern is established, remaining instances drop a tier:
the third component renderer, the fourth `DiagramSpec` type, the fifth ingestion fixture.
This is where most of the build's cost saving lives — it is an expectation, not an option.
Record de-escalations in handover §8 too, so the ratio is visible.

**6. Audit.** Each handover reports planned vs actual routing. Systematic deviation means
the tags are wrong; fix the tags.

## The docstring-delegation pattern

A named sub-pattern within Sonnet work: **Sonnet writes the signature, docstring, and
contract; Haiku fills the body.** Adopted deliberately — it is where the largest share of
routine implementation cost sits.

**Scope it by specification completeness, not by function length.** The instinct to send
*lengthy* functions to Haiku gets the axis wrong: length correlates with branching, and
branching is exactly where a cheaper model's errors hide inside a plausible-looking body.
A short function with an ambiguous contract is the riskier delegation.

Delegate the body when the docstring **fully determines** behaviour:

- pure transformation, clear input/output types, no hidden state
- error cases named in the docstring, not left to judgment
- edge-case behaviour specified (empty input, boundary values, unicode, locale)
- a test already exists, or the docstring is precise enough for Haiku to write one

Keep the body with Sonnet when the function carries judgment: retry and repair semantics,
anything where "reasonable behaviour" is doing load-bearing work in the spec, or anything
whose failure mode is silent rather than loud.

**The path guardrails still apply and are not negotiable.** No body under `autodeck/ir/`,
`autodeck/audit/`, or `prompts/` is delegated to Haiku regardless of docstring quality —
in the numeric linter the invariant *lives in* the edge cases, so a docstring that reads
complete is precisely the trap.

### A note on Clean Code and this pattern

The project follows Clean Code, and that discipline is what makes this delegation safe —
but it also cuts against the framing. "Extract till you drop" means a well-factored
codebase should not contain many lengthy functions to hand off. The decomposition does the
work: small, single-purpose functions with honest names and complete contracts are exactly
what a cheaper model executes reliably.

So the pattern's real unit is **a small, fully-specified function**, and the payoff is
volume — dozens of them per phase — rather than length. If a function looks long enough to
be worth delegating on size alone, the first move is to extract it, not to route it.

## Judgment call when tags conflict

If a task's tag and the path guardrail disagree, **the guardrail wins**. If a task
plausibly belongs to two tiers, take the higher one — the cost of over-tiering is money,
the cost of under-tiering is a defect in an accuracy-critical path.

---

# Part 2 — Runtime routing (AutoDeck's provider registry)

Per plan §6.2 and D6. Bindings live in config, **never hardcoded in code**; resolved model
IDs are recorded in the build manifest (A6).

## Environment tiers (decision B8)

Three environments, because the cost profile of development and the accuracy requirement
of production pull in opposite directions:

| Env | Providers | Purpose |
|---|---|---|
| **dev** | Gemini + Groq (free tiers) | Day-to-day build and iteration. Low cost, low risk, high call volume |
| **sit / uat** | Claude | Pre-production verification on the bindings production actually uses |
| **prod** | Claude | Real client deliverables |

Gemini and Claude do not overlap — they occupy disjoint stages rather than competing for
the same role.

### The accuracy consequence — read this before relying on a dev-environment result

Two invariants are **model-sensitive**: A3 (independent re-retrieval, contradiction
search) and A8 (honest uncertainty). Both are judgment, not arithmetic, so a weaker model
fails them *plausibly* rather than loudly.

That means **an accuracy result obtained on the dev binding does not transfer to prod.**
A validator that catches every planted contradiction on Gemini tells you nothing certain
about Claude, and vice versa. The deterministic invariants — A1 citation structure, A2
numeric linting and derivation re-execution, A4 isolation, A5 framing lints, A6 manifest
reproducibility — are model-independent and *do* transfer; they are code, not judgment.

Two rules follow, and the SIT tier exists to serve them:

1. **Phase 5 eval numbers are only meaningful on the binding they were measured on.** The
   eval harness records the environment; a faithfulness score from dev is a dev score.
   Headline metrics (faithfulness, numeric accuracy) must be measured on **sit** before
   any production use.
2. **GATE 2's claims table should be produced on the sit binding** at least once before a
   deck ships, even if development iterated on dev. The gate is the last automated line
   before a client sees the deck.

This is what the SIT/UAT stage buys, and it is why the instinct to add one is right.

## Role bindings

Tier is the *capability class* the role needs; the concrete model per environment is
resolved in config.

| Role | Capability needed | dev | sit / prod |
|---|---|---|---|
| `planner` | Strong interactive judgment; evidence-gap probe (§6.13) | Gemini pro-tier | Claude strong-tier |
| `outline` | Structural reasoning; runs once per deck | Gemini pro-tier | Claude strong-tier |
| `content` | High volume, tightly constrained by budgets and citations | Groq fast-tier | Claude mid-tier |
| `validation` | **Judgment-critical** (A3) | Gemini pro-tier | Claude strong-tier |
| `aesthetic` | Vision over true renders (§6.9) | Gemini vision-tier | Claude vision-tier |
| `ingest_vlm` | High-volume figure description; **metadata only, never citable** | Gemini flash-tier | Gemini flash-tier |

`ingest_vlm` stays on Gemini in all environments — its output is metadata that can never
back a claim (enforced structurally in the document store), so there is no accuracy reason
to pay for it.

Shape of `config/models.yaml`:

```yaml
default_env: dev

environments:
  dev:
    planner:    {provider: gemini, model: <resolved-at-P0>}
    outline:    {provider: gemini, model: <resolved-at-P0>}
    content:    {provider: groq,   model: <resolved-at-P0>}
    validation: {provider: gemini, model: <resolved-at-P0>}
    aesthetic:  {provider: gemini, model: <resolved-at-P0>}
    ingest_vlm: {provider: gemini, model: <resolved-at-P0>}
  sit:
    # same role keys, Claude bindings
  prod:
    # same role keys, Claude bindings
```

Selected with `--env`, defaulting to `dev`. **The manifest records the environment and
every resolved model ID** (A6) — so an audit report always states which bindings produced
it, and a dev-built deck is never mistaken for a production one.

**Model IDs are looked up at implementation time, not recalled from training.** Plan §6.2
is explicit about this and §9 lists model API change as a live risk. Phase 0 resolves the
actual IDs and records them in `DECISIONS.md`.

## What this adds to Phase 0

Task 0.3 now builds **three** provider adapters (Gemini, Groq, Claude), not two, and the
environment-tier config above. Two things to verify in that task, because they are the
likely friction:

- **Structured output parity.** `complete_structured` must work on all three. JSON-mode
  and tool-use support varies by provider and by model within a provider; Groq's varies by
  the open model being served. Where a provider is weaker, the repair-retry path carries
  more load — test it deliberately rather than discovering it in Phase 2b.
- **Free-tier rate limits.** They will bite first at Phase 1 ingestion (`ingest_vlm` over a
  full corpus) and Phase 5 eval batches. Build backoff and resumability into the provider
  layer in Phase 0 rather than retrofitting under a rate limit.

## Cost posture

`content` and `ingest_vlm` dominate token volume; `validation` dominates cost per call.
Within an environment, do not cheapen `validation` to save money — it is the last automated
line before GATE 2, and A3 is the invariant most likely to fail silently. If cost needs
cutting, cut `ingest_vlm` batch size or `content` retry budget first.
