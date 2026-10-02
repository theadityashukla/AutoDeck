# Phase 2a — Planning agent & outline — Handover

> The phase's reason for existing, in the plan's own words: *evidence gaps surface in
> conversation, before a single slide is written.*

---

## 1. Identification

| | |
|---|---|
| **Phase** | 2a — Planning agent & outline |
| **Branch** | `v2/phase-2a-plan-outline` |
| **PR** | not yet opened |
| **Started / completed** | 2026-08-02 → 2026-08-02 |
| **Gate** | GATE 1 |
| **Gate status** | **pending** — no outline has been put to the owner |
| **Approved by / when** | — |
| **What the owner actually checked** | Nothing yet. GATE 1 asks whether an outline delivers the brief's argument; `autodeck outline` produces the artifact and the report, and neither has been reviewed. **This handover does not claim the gate passed.** |

## 2. What shipped

| Path | What it does | Tests |
|---|---|---|
| `autodeck/ir/models.py` | `DeckBrief`, `KeyMessage`, `OpenRisk`, `LayoutPin`; `Slide.intent` / `.message_ids` / `.pin_deviation` | `tests/test_deck_brief.py` |
| `autodeck/ir/store.py` | Briefs versioned like the IR, stored as YAML (a human signs this one) | `tests/test_deck_brief.py` |
| `autodeck/ir/schema.py` | `gemini` flavor collapses nullable unions to `nullable: true` (B26) | `tests/test_ir_schema.py` |
| `autodeck/agents/evidence_gap.py` | The gap check: deterministic retrieval, model judgement, and a ceiling on the judgement | `tests/test_evidence_gap.py` |
| `autodeck/agents/planner.py` | The session. Ends only on human sign-off, which is A7 approval 1 of 4 | `tests/test_planner.py` |
| `autodeck/agents/outline.py` | Signed brief → IR skeleton. No prose; pins honoured or flagged | `tests/test_outline.py` |
| `autodeck/audit/gate1.py` | GATE 1's mechanical checks. Reports, decides nothing, fixes nothing | `tests/test_outline.py` |
| `prompts/planner.md`, `prompts/outline.md` | Own commits per plan §0.5 | — |
| `autodeck/cli.py` | `autodeck plan` (conversational), `autodeck outline` | — |

432 tests, 10 live-marked and deselected, 15 skipped for missing local tooling.

## 3. What did not ship

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|
| — | Every task 2a.1–2a.9 is complete | — |
| An interactive `autodeck plan` run by a human | The session is exercised end to end programmatically against live models, but nobody has typed into the REPL. The loop is thin; the risk is in ergonomics, not correctness | Owner, first real use |
| Probe-on-demand for a single message | `probe_messages` re-probes every message. Wasteful on a 20-requests-per-day tier | Phase 2b, if it bites |

## 4. Decisions made this phase

- **B23** — Dev model IDs re-resolved. `gemini-2.5-pro` is retired; no pro model exists on the free tier.
- **B24** — Evidence spans truncated to 500 chars before classification.
- **B25** — Dev roles spread across different Gemini models — quota, and A3 independence.
- **B26** — Gemini drops nullable nested arrays. Fixed in the schema exporter and the planner model.

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | tested | tested | unchanged. The planner is forbidden from writing citations; `supporting_claims` are leads |
| A2 numbers | partial | partial | unchanged |
| A3 validation | partial | partial | unchanged — the validator is Phase 2b. B25 gives it a different model from the writer |
| A4 isolation | tested | tested | `autodeck plan` binds one namespace and passes the index through `use_index` |
| A5 framing | partial | partial | unchanged |
| A6 reproducibility | partial | partial | unchanged |
| A7 gates | enforced | **tested (first real gate)** | `test_planner.py::test_the_model_cannot_sign_its_own_brief`, `::test_signing_off_records_the_a7_gate`; `test_outline.py::test_an_unsigned_brief_is_refused` |
| A8 uncertainty | partial | **enforced** | `test_deck_brief.py::test_a_weakly_supported_message_needs_a_recorded_risk`; `test_evidence_gap.py::test_a_model_cannot_claim_support_that_retrieval_did_not_find` |

**A8 is the phase's real delivery.** A key message the gap check calls `thin` or
`unsupported` cannot reach a signed brief without a matching `OpenRisk` naming who accepted
it — a schema constraint, not a checker anyone can forget to call. Carrying a gap is free;
carrying it silently is impossible.

## 6. Spike and experiment findings

**Gemini silently drops nullable nested arrays — the most valuable finding here.** The
first live planning sessions produced genuinely good briefs, entirely as prose, and
recorded nothing. My first instinct was that the prompt was wrong, and I rewrote it twice:
hoisted the instruction to the top of `planner.md`, then added a positional reminder after
the context. Both improved the prose. Neither changed a single field.

Reading the raw HTTP response instead settled it in one look: scalar fields present,
`key_messages` / `layout_pins` / `open_risks` — every `list[Model] | None` — absent from the
JSON entirely. No error. And it is **non-deterministic**: the same model on the same prompt
populated the arrays once and omitted them on the next call, which is why two prompt
rewrites each appeared to help briefly.

The lesson generalises: **when an agent's output reads right in prose and lands empty in the
artifact, read the raw response before touching the prompt.** Prompt-shaped explanations for
schema-shaped bugs are very easy to believe.

**The A8 schema rule caught this, and that is worth noticing.** The failure surfaced as
`BriefIncomplete: audience string too short; key_messages list too short` at sign-off —
which is task 2a.1's validation doing exactly its job at exactly the right moment. Without
it the session would have written an empty brief and the outline agent would have failed
three steps later with something far less legible.

**My own GATE 1 check was too strict, and the live run proved it.** Two legitimate
`must_include` entries — long requirement sentences — blocked an outline that covered both,
because no slide intent contains a sentence like that verbatim. A gate that blocks on almost
every real run trains its reviewer to click past blocking findings, which costs more than the
check is worth. A missing `must_include` is now advisory and a present `must_avoid` stays
blocking: a substring *found* is reliable evidence, a substring *missing* is not.

**The free tier is smaller than it looks.** 20 requests per day **per model**. A two-turn
planning session probing four messages spends one model's entire day. The roles are now
spread across five models (B25), which is also better for A3 independence, but dev capacity
is genuinely about twenty planner turns a day.

**Negative result — no pro model on the free tier at all (B23).** `gemini-2.5-pro` still
appears in the models listing and 404s on every call, "no longer available to new users".
`gemini-3.1-pro-preview` and `gemini-pro-latest` return 429 with no free-tier quota. Four
dev roles were bound to a dead model. A listing is not availability, which is what B15's
"resolve, never recall" has to mean in practice: call it.

**What the gap check actually does, on real evidence.** Two cases worth recording, both run
against the real seed corpus with a live model:

- *"Quantisation cuts inference cost in half"* → **thin**, with the reasoning naming the
  exact mismatch: the corpus measures memory, not cost. This is the trap the whole design
  targets, and it caught it unprompted.
- *"Our assistant handles 40,000 conversations per day"* → **unsupported**, despite
  retrieval returning six topically-noisy spans (a SQuAD reference, a results table). The
  ceiling was not needed; the classifier declined on its own.

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| **GATE 1 unjudged** | No human has reviewed an outline against a brief | **Owner, next** |
| Nobody has typed into `autodeck plan` | The REPL is thin but unexercised by a human; ergonomics unknown | Owner, first real use |
| Evidence probing re-probes every message | Burns the daily quota fast | Phase 2b |
| `pin_deviation` gets misused by the model | On one run the model wrote risk-handling prose into a slide's `pin_deviation`. Harmless — the code writes real deviations regardless — but it makes the field noisy | Phase 2b prompt pass |
| A5 still structured, not enforced | A claim could trace to `value_prop.md` | Phase 2b validator |
| Claude adapter still unexercised live | Carried from Phase 0 | Phase 2b / first `sit` run |
| Aptos prerequisite | Carried from Phase 0 | Phase 2b |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| 2a.1 DeckBrief | Opus | Opus | `autodeck/ir/` guardrail |
| 2a.2 planner prompt | Opus | Opus | `prompts/` guardrail |
| 2a.3 plan session | Sonnet | Opus | Escalated. The session is where A7 is either real or theatre, and "the model cannot approve its own work" is an invariant decision, not harness code |
| 2a.4 evidence-gap check | Opus | Opus | Accuracy-critical, as briefed |
| 2a.5 layout pins | Sonnet | Sonnet-appropriate | Folded into 2a.3 |
| 2a.6 outline prompt | Opus | Opus | `prompts/` guardrail |
| 2a.7 outline agent | Sonnet | Sonnet-appropriate | — |
| 2a.8 brief sign-off | Sonnet | Opus | Same reason as 2a.3; it is the same code path |
| 2a.9 GATE 1 surface | Sonnet | Opus | `autodeck/audit/` guardrail |

The pattern: anything deciding *what counts as approved* or *what counts as supported* ran
Opus regardless of the brief's tag. That matches the guardrail rule and is worth keeping.

## 9. Preconditions for the next phase

1. **GATE 1 judged** on a real outline. `autodeck outline <run> --client <c> --project <p>`
   after a planning session, then read the intents in order and decide.
2. **Decide whether the seed stays synthetic.** Carried from Phase 1, still open, and Phase
   2b writes actual slide copy — the point where a fictional client starts to matter.
3. `ANTHROPIC_API_KEY` for `sit`. Outstanding since Phase 0, and B23 makes it more
   pressing: dev now runs reasoning roles on flash models, so an A3/A8 result here is a
   smoke test on a small model.
4. Re-resolve model IDs before Phase 2b calls a provider. They went stale inside a week.

## 10. Verifying this phase from a cold start

```bash
uv sync
uv run ruff check . && uv run ruff format --check .   # All checks passed
uv run pyright                                        # 0 errors
uv run pytest -q -m "not live"                        # 432 passed

uv run autodeck models --env dev                      # five distinct Gemini models (B25)
uv run autodeck knowledge ingest llm-inference-efficiency   # ~16 min, needs *.hf.co

uv run autodeck plan demo --client northwind-retail --project llm-inference-efficiency
# conversational; /brief shows the draft, /sign <name> approves, /quit leaves unsigned.
# Expect: an evidence line per key message after a probe turn, and a refusal to sign while
# any message is thin or unsupported without a recorded risk.

uv run autodeck outline demo --client northwind-retail --project llm-inference-efficiency
# Without a signed brief: blocks with GATE 'brief' requires human approval (exit 3).
# With one: 10-ish slides, then the GATE 1 report.
```

## 11. Reading notes for the next implementer

**Read `evidence_gap.py` first, then `planner.py`.** The gap check is the phase; the session
is scaffolding around it.

**The shape to copy is the ceiling.** `EvidenceProbe` splits deterministic retrieval from
model judgement and then bounds the judgement by what retrieval found: zero citable spans is
`unsupported` and the classifier is never even called; a single non-curated hit is capped to
`thin`. The bound is applied to the model's answer *afterwards*, not requested in the prompt,
so a model that ignores the instruction still cannot produce the wrong answer. Phase 2b's
validator wants the same shape.

**`thin` matters more than `unsupported`.** Unsupported is easy — everyone agrees it needs
handling. `thin` is the message that reads as solid and collapses when the client asks what
hardware it was measured on, and it is the one a hurried planner rounds up. It carries the
same consequence as `unsupported` (a recorded risk) specifically so rounding up is the only
way to make it disappear, and the ceiling and the prompt are both built to resist that.

**What looks wrong but is deliberate:**

- Every fake classifier in `test_evidence_gap.py` returns `supported`. That is the failure
  being guarded against, and the tests assert the module produces the right answer anyway.
- `PlannerAction.ready_for_signoff` exists and is never read by `sign_off`. The model may
  hold the opinion; it has no route to act on it (A7).
- `PlannerAction`'s brief fields are required with empty meaning "unchanged". That reads
  like a modelling mistake and is a workaround for B26 — read that entry before changing it.
- `gate1.py` returns `mechanical_checks_pass`, not `passed`. The naming is load-bearing:
  every key message can map to a slide while the deck still fails to make the argument.

**What I would do differently.** I spent two prompt rewrites on a schema bug. The prose
improved each time, which felt like progress and was not. The Phase 1 handover's lesson was
"run it and look" and I ran it — but I looked at the *output* rather than the *response*.
When the artifact is empty and the prose is good, the next thing to read is the raw HTTP
body, before any theory about what the model was thinking.
