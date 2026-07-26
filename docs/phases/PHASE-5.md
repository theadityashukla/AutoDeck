# Phase 5 — Hardening & evals

**Branch:** `v2/phase-5-evals-hardening` · **Gate:** none (ongoing) · **Estimate:** ongoing
**Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 5

> Everything before this phase makes the system accurate. This phase makes accuracy
> **measurable and defended by CI, rather than by vibes and human vigilance.**
>
> The human gates are a backstop, not a strategy. They catch what they happen to look at.

## Preconditions

- GATE 4 approved; `docs/handovers/PHASE-4.md` read.
- At least two real decks built, available as eval references.

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 5.1 | **Eval harness** — 3–5 golden source papers with reference decks; rubric scoring | **Opus** (rubric design) → **Sonnet** (harness) | `evals/` | **A1–A8** | Scores faithfulness, citation coverage, numeric accuracy, contradiction-catch rate, design consistency. **Faithfulness and numeric accuracy are the headline metrics.** Every result records the environment it ran on (B8) |
| 5.2 | **Headers-only storyline test** — do the titles alone tell the story, in the active profile's voice? | **Sonnet** | `evals/` | D12 | Automated check over the header sequence in isolation |
| 5.3 | **Icon-redundancy test** — strip every icon; is any meaning lost? | **Sonnet** | `evals/` | D13 | If meaning is lost, the icons were carrying meaning alone — a grammar failure (§6.11.2) |
| 5.4 | Regression suite in CI — every prompt or model change re-runs evals; **accuracy metrics must not regress to merge** | **Sonnet** | `.github/workflows/` | **A1–A8** | A prompt change that lowers faithfulness fails the build |
| 5.5 | **Adversarial accuracy tests** — see the table below | **Opus** | `tests/adversarial/` | **A1–A8** | The system catches **every** injected fault |
| 5.6 | Eval batch execution and result tabulation | **Haiku** | `evals/` | — | Runs are cheap enough to execute on every prompt change |
| 5.7 | Deferred niceties, revisited **only now**: thin review UI, local-model option (only if a client contract demands it), performance and parallelism tuning | **Sonnet** | — | D2, D7 | Each is a separate decision recorded in `DECISIONS.md` |

## Adversarial tests (5.5)

Each injected fault must be caught. These are the tests that prove the invariants are real
rather than aspirational:

| Injected fault | Must be caught by |
|---|---|
| A subtly wrong number | A2 numeric linter |
| A miscomputed derivation (formula and stated result disagree) | A2 re-execution |
| An unsupported claim | A3 validator |
| A fact lifted from a reference deck with no corpus source | A1 + §6.12 accuracy rule |
| A cross-client leak | A4 context assembler |
| A fabricated study cited inside a `framing` block | A5 framing linter → demotion → A1 |
| An unlabelled icon | D13 grammar lints |
| A topical placeholder header ("Overview", "Background") | D12 header profile banned patterns |
| Two sources disagreeing on one figure | A8 — must hedge, not average |

**Every one of these is a failure mode the system was designed to prevent.** A test that
does not fail when its defence is removed is not testing anything — verify each by
temporarily disabling its defence and confirming the test goes red.

## Which environment the evals run on (decision B8)

Development runs on free-tier Gemini + Groq; SIT and production run on Claude. That split
has a direct consequence for this phase:

- **A3 (validation) and A8 (honest uncertainty) are model-sensitive.** They are judgment,
  so a weaker model fails them *plausibly* rather than loudly. A contradiction-catch rate
  measured on the dev binding says nothing certain about the production binding.
- **A1, A2, A4, A5, A6 are deterministic** — code, not judgment — so their results transfer
  across environments unchanged.

Therefore:

1. Every eval result records its environment. A faithfulness score without one is unusable.
2. **Headline metrics (faithfulness, numeric accuracy) must be measured on `sit`** before
   any production use. Dev scores are for catching regressions during iteration, not for
   deciding a deck is safe to ship.
3. CI regression gating (5.4) runs on `dev` for cost, with a `sit` run required before a
   release — not on every commit.
4. Adversarial tests (5.5) run on **both**: on dev to keep them cheap and fast, and on
   `sit` to prove the shipped configuration actually catches each fault.

## Accuracy focus

> Accuracy is measurable and defended by CI, not vibes.

## Exit criteria

Phase 5 is ongoing rather than gated. The **v2 MVP definition of done** (plan §10) is the
bar it serves:

- `build --project P --client C --audience A` produces `deck.pptx` (editable, on-brand,
  beautiful), `audit_report.pdf` (every claim traced), `build_manifest.json` (reproducible).
- All invariants A1–A8 enforced and covered by tests.
- Decks pass the headers-only storyline test; contain at least one native diagram and
  themed icons, all selectable and recolourable in PowerPoint (D11–D13).
- Two real client decks from one shared project demonstrate isolation, per-client framing,
  per-client theming.
- Eval harness green on faithfulness, citation coverage, and numeric accuracy.
- Four runtime approvals operational; **no path bypasses them.**

## Escalation triggers

- **An eval metric regresses and the cause is a model change, not a code change** — a
  provider or version drift. Pin it, record in `DECISIONS.md`, and re-baseline
  deliberately rather than accepting the new number.
- **An adversarial test cannot be made to pass without weakening an invariant** — stop.
  Per plan §0.4, surface the conflict with options.
- **A local-model request from a client contract (5.7)** — that reopens D2. Owner decision,
  new `DECISIONS.md` entry; do not implement it quietly as an option flag.

## Notes for the implementer

- A8 (honest uncertainty) is the invariant **least reducible to a deterministic check** —
  it is model behaviour, so the eval is its only real defence. It is also the most likely
  to regress silently on a model swap. Weight it accordingly in 5.1.
- 5.6 is the archetypal Haiku task: high volume, mechanically verifiable, and the thing
  that determines whether evals actually get run on every change or only before releases.
- The deferred niceties in 5.7 have been deferred since Phase 0 **on purpose**. Revisit
  them as fresh decisions against the system that now exists, not as a backlog to clear.
