# Phase 2a — Planning agent & outline

**Branch:** `v2/phase-2a-plan-outline` · **Gate:** GATE 1 · **Estimate:** ~2 weeks
**Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 2 tasks 1–3, §6.13

> Split from Phase 2 per decision B5 — the source plan already places GATE 1 mid-phase,
> so the branch boundary sits on the gate.
>
> The point of this phase: **evidence gaps surface in conversation, before a single slide
> is written.** Everything else here serves that.

## Preconditions

- GATE 1a approved; `docs/handovers/PHASE-1.md` read.
- Corpus ingested with verified provenance; `claims.md` loading.

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 2a.1 | `DeckBrief` model — objective, audience, key_messages, must_include, must_avoid, length_target, header_style, layout_pins, reference_deck, open_risks | **Opus** | `autodeck/ir/models.py` | A7 | Round-trips to `brief.yaml` in the run dir; versioned like the IR |
| 2a.2 | `prompts/planner.md` — interview behaviour, storyline proposal, iteration | **Opus** | `prompts/planner.md` | — | Own commit with rationale (plan §0.5) |
| 2a.3 | Interactive `autodeck plan` session — conversational CLI per D7; transcript stored in the run | **Sonnet** | `autodeck/agents/planner.py`, `autodeck/cli.py` | A7 | Session ends **only** on explicit human sign-off of `brief.yaml`; transcript persisted for audit |
| 2a.4 | **Evidence-gap check** — each proposed key message probed against `claims.md` + corpus during the session | **Opus** (accuracy-critical) | `autodeck/agents/planner.py` | **A1, A8** | Unsupported message triggers in-conversation challenge: *"no source currently supports X: soften it, add a source, or drop it?"* Accepted gaps land in `open_risks` |
| 2a.5 | Layout pins — human can pin a communication mode or component to a message | **Sonnet** | `autodeck/agents/planner.py` | — | Pins persist in the brief and are readable by outline + art direction |
| 2a.6 | `prompts/outline.md` | **Opus** | `prompts/outline.md` | — | Own commit with rationale |
| 2a.7 | Outline agent — DeckBrief + knowledge folder + audience → IR skeleton (narrative roles, component assignments, slide intents). **No prose yet** | **Sonnet** | `autodeck/agents/outline.py` | A4 | Produces a valid IR v0; honours layout pins; deviations from pins are flagged, not silent |
| 2a.8 | Brief sign-off wired as the **first of the four runtime approvals** (A7) | **Sonnet** | `autodeck/pipeline/orchestrator.py` | **A7** | No code path proceeds to outline without a recorded brief approval |
| 2a.9 | GATE 1 review surface — diff the outline against the brief for human review | **Sonnet** | `autodeck/ir/store.py` | A7 | Reviewer can see outline-vs-brief side by side |

## Accuracy focus

The evidence-gap check (2a.4) is the phase's reason for existing. Plan §6.13:

> so evidence gaps surface before a single slide is written, not at validation.

A gap caught here costs one conversational turn. The same gap caught at GATE 2 costs a
rewrite of every slide built on it.

## Milestone

An `autodeck plan` session produces a signed-off `brief.yaml` and an IR v0 skeleton whose
structure demonstrably follows the brief.

## GATE 1 — exit criteria

**The owner approves the outline skeleton *against the brief*.** Plan §6.13 notes this is
what gives the gate objective criteria instead of vibes — the question is not "is this a
good outline" but "does this outline deliver the brief's key messages in the brief's
order, honouring its pins?"

Checkable:
- Every `key_message` in the brief maps to at least one slide.
- Every `must_include` appears; no `must_avoid` does.
- Every `layout_pin` is honoured, or its deviation is explicitly flagged.
- Length is within the brief's target.
- `open_risks` are carried into the IR, not dropped.

## Escalation triggers

- The planner cannot probe evidence because retrieval coverage is too thin — that is a
  Phase 1 gap surfacing late; return to it rather than lowering the bar.
- The owner wants to proceed with a key message that has no support. That is allowed —
  record it in `open_risks`, which resurfaces in the audit report (A8). It is not allowed
  to disappear.

## Notes for the implementer

- v1's `outline_agent.py` (`generate_outline`, `refine_outline`) is prompt-logic reference
  only. Its contract is topic + audience + slide count; v2's is a signed brief and a
  knowledge folder — a different problem.
- The planner is the **first** place a human touches the pipeline. Its conversational
  quality sets whether the system feels like a colleague or a form. Worth Opus attention
  on the prompt (2a.2) even though the harness around it is Sonnet work.
