# Phase 4 — Consulting workflow

**Branch:** `v2/phase-4-workflow` · **Gate:** GATE 4 · **Estimate:** 3–4 weeks
**Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 4, §§6.12, 6.11.1

> The system works on one deck. This phase makes it work as a **practice** — multiple
> clients, real onboarding, knowledge that improves after each engagement.
>
> GATE 4 is the only gate that tests the system against reality: a real deck, used for real.

## Preconditions

- GATE 3 approved; `docs/handovers/PHASE-3B.md` read.
- Owner answer to Q4 (audit report audience — internal only or client-facing; determines
  how much polish 4.6 needs).
- A second client available for the isolation regression (4.5).

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 4.1 | Client onboarding command — extract theme from brand assets/past decks → `tokens.json` + master; register client-supplied icon sets; per-client font licensing check | **Sonnet** | `autodeck/cli.py`, `autodeck/design/theme/extract.py` | D11 | One command takes a brand folder to a working client namespace |
| 4.2 | **Reference deck ingestion** — parse PPTX (titles, body, notes, geometry, images, fonts, colours) and derive four profiles | **Sonnet** | `autodeck/ingest/deck_ingest.py` | **A1** | See the four profiles and the accuracy rule below |
| 4.3 | `plan --like reference.pptx` — StorylineProfile seeds the planner and outline agent | **Sonnet** | `autodeck/agents/{planner,outline}.py` | — | Outline flow demonstrably follows the reference deck's arc |
| 4.4 | `build --project P --client C --audience A` end-to-end with **all four runtime approvals** (A7) | **Sonnet** | `autodeck/cli.py`, `autodeck/pipeline/orchestrator.py` | **A7** | No path bypasses any of the four approvals; **no `--yes` flag exists for gates** |
| 4.5 | **Multi-client regression** — same project, two clients → correct isolation, per-client framing, per-client theme. Automated | **Opus** (invariant-critical) | `tests/` | **A4, A5** | Automated test; a cross-client leak fails the build. Cover cached retrieval indices and reference decks, not just markdown |
| 4.6 | Audit report polish — client-presentable PDF | **Haiku** | `autodeck/audit/report.py` | A6 | Renders to PDF; polish level set by the Q4 answer |
| 4.7 | `update_proposer.py` — post-engagement knowledge diffs for human approval, including approved-header additions to the style profile | **Sonnet** | `autodeck/knowledge/update_proposer.py` | A7, D12 | Emits a **git diff for human approval; never auto-writes** |
| 4.8 | Catalog gap analysis — recurring reference-deck layouts the catalog cannot express, flagged as candidate components | **Haiku** | `autodeck/ingest/deck_ingest.py` | — | Produces a ranked list of gaps |

## The four reference-deck profiles (4.2)

| Profile | What it derives | Feeds |
|---|---|---|
| **StorylineProfile** | Narrative arc as inferred slide roles (context → problem → evidence → implication → ask), section rhythm, density patterns | `plan --like` outline seeding (4.3) |
| **HeaderStyleProfile** | Style, case, length, voice, exemplars, banned patterns — derived from titles | Header voice system (§6.11.1). **This is the canonical path** for title-style learning |
| **VoiceProfile** | Register, sentence length, terminology used and avoided | Augments `client.md` vocabulary guidance |
| **DesignProfile** | Observed layouts mapped to nearest catalog components, spacing and colour habits | Theme extraction (§6.8), art-direction defaults, gap analysis (4.8) |

### The accuracy rule for reference decks

> Reference decks teach **style and structure, never truth.**

Any factual content lifted or paraphrased from a past deck is still a `claim` requiring a
corpus citation (A1). Plan §6.12 puts it plainly: *a slide that shipped before is not
evidence that it was ever right.*

This is a real leak path — a deck-derived sentence carries no provenance but reads
authoritative. Enforce it in `deck_ingest.py`: deck-derived text must be structurally
incapable of satisfying a citation, the same way VLM figure descriptions are (Phase 1).

## Accuracy focus

> A4 isolation and A5 framing correctness proven across real multi-client builds.

## Milestone

Two real client decks from one project, each correct, isolated, on-brand, editable, with
clean audit reports.

## GATE 4 — exit criteria

**The owner runs a real consulting deck through the system for actual use.**

This is the gate that cannot be gamed. Checkable alongside it:
- Two clients from one project build cleanly with zero cross-client references.
- Per-client framing and theming visibly differ.
- All four runtime approvals fire in both builds.
- Audit reports clean for both.
- The knowledge update proposal from the real engagement is reviewable as a diff.

## Escalation triggers

- **Any cross-client leak** — a confidentiality failure, the most serious non-accuracy
  risk in the system. Stop, fix, add a regression test, record in `DECISIONS.md`.
- Onboarding cannot extract usable tokens from a real brand → fall back to mode (b)
  (generate from supplied tokens) and record the limitation.
- A reference deck's fact appears in output without a corpus citation → an A1 hole in
  4.2; fix structurally.

## Notes for the implementer

- 4.5 is tagged Opus despite being "just a test" because it is the **proof of A4**, and
  A4 protects client confidentiality. Its coverage design matters more than its code.
- `update_proposer.py` never auto-writes (D8, A7). Knowledge drift without human approval
  is how a curated knowledge base silently degrades into an uncurated one.
- Basic title extraction may already exist from Phase 3a's header work; the full
  four-profile derivation lands here.
