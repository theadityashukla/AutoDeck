# Phase 3d — Redesign an existing deck

**Status:** PROPOSED 2026-10-03 — started on the owner's request ("can you start work on the
existing deck implementation part as well?"). Implements B41 on top of Phase 3c's draft-first
flow. Ingestion (3d.1–3d.2) is under way; the rest waits for the owner's review of this plan.
**Branch:** with Phase 3c until 3c lands, then its own · **Gate:** GATE 3d ·
**Estimate:** 1–2 weeks after 3c
**Source:** `DECISIONS.md` B41; the "Redesign an existing deck" design on the UI canvas.

> The person hands AutoDeck a finished deck. AutoDeck keeps the story and rebuilds each
> slide in the client's brand, choosing a better layout where one helps, and every statement
> on a redesigned slide cites the original slide it came from.

## How it fits draft-first

Redesign is the draft-first flow with a different evidence source:

| Draft-first (3c) | Redesign (3d) |
|---|---|
| Evidence pack = curated claims + retrieved paper passages | Evidence pack = **every text element of the uploaded deck**, in slide order (a deck is small enough to send whole) — optionally plus the project's papers |
| Clarify asks about gaps in the evidence | Clarify asks about the deck: wording freedom, layout changes, slides to merge or drop |
| Compose writes brief + outline + slides | Compose writes the same, with the original deck's argument as the starting outline and a **why** per changed layout |
| Validator checks claims against the papers | Validator checks the redesigned wording is **faithful** to the original slide (A3), and A8 surfaces places the deck contradicts itself |
| Citations: paper, page, quote | Citations: `client-deck--<name>`, slide number, the original text — labelled **"client-supplied deck"** in the audit report |

Everything else — the A1 resolver, the A2 linter, A5 framing, approvals on the draft, DRAFT
previews, scoped revise — is Phase 3c's, unchanged.

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 3d.1 | **Deck as a source document** — read a `.pptx` with python-pptx into the existing `Document` model: one page per slide, one element per text frame paragraph group, table cell and speaker-notes block, bbox from the shape's position normalised to the slide; `doc_id` `client-deck--<stem>`; non-text shapes (pictures, charts without data) recorded as non-citable | **Sonnet** | `autodeck/ingest/deck_source.py` | **A1**, A4 | Every text on every slide resolves through `DocumentStore.resolve_quote`; same file → same document |
| 3d.2 | **Run-local source store** — the deck is stored under `runs/<run>/source/`, never in the project corpus or another run (B41: a source for that run only, inside the client's namespace) | **Sonnet** | `autodeck/ingest/deck_source.py` | **A4** | A test shows the deck is invisible to every other run and to the project corpus |
| 3d.3 | **Provenance label** — citations to a client-supplied deck are labelled as such in the audit report and the review UI, so a reader can tell them from research | **Sonnet** | `autodeck/audit/report.py` | A6 | The audit report's citation lines read "client-supplied deck, slide N" |
| 3d.4 | **`prompts/redesign.md`** — keep the story; wording modes ("keep my words, trim only to fit" / "allow light rewording"); layout changes with a one-line why; never add a fact the deck does not state | **Opus** | `prompts/redesign.md` | A1, A2, A8 | Own commit with rationale |
| 3d.5 | **Redesign evidence pack + compose mode** — the whole deck as the pack; compose in redesign mode returns the 3c `ComposeDraft` plus a per-slide `why`; optional papers in the pack when the person asks to check figures | **Sonnet** | `autodeck/agents/evidence_pack.py`, `autodeck/agents/compose.py` | A1, A2 | A fake-provider redesign of a fixture deck cites only original slides; a number not in the original fails A2 |
| 3d.6 | **Faithfulness validation** — the validator's independent retrieval runs over the run-local store; its prompt framing is "does the new wording say what the original slide said" | **Opus** (prompt), **Sonnet** | `autodeck/agents/validation.py` | **A3** | A reworded claim that changes a number or drops a condition is `partially_supported` or worse |
| 3d.7 | **Upload** — `autodeck redesign <run> --client C --deck path.pptx`; in the UI an upload route that takes the file as a raw body with a required custom header (forces a CORS preflight the server never grants, like the JSON-only rule) and a size cap | **Sonnet** | `autodeck/cli.py`, `autodeck/ui/server.py` | A4 | Upload refused from another origin; files over the cap refused |
| 3d.8 | **UI** — the canvas's Redesign screen (upload, wording and layout settings, "your deck is the source" panel) and a side-by-side original/proposed view in the draft review | **Sonnet** | `autodeck/ui/static/` | — | The canvas flow works end to end on a fixture deck |
| 3d.9 | **Docs** | **Haiku** | `docs/OWNER-GUIDE.md` | — | |

## GATE 3d — exit criteria

The owner redesigns a real deck of theirs: every statement on the new deck cites its original
slide, figures match the original exactly, the audit report labels those citations as the
client's own deck, and the four approvals are given on the draft as in 3c.

## Open questions for the owner — provisionally answered (B49, confirm or reverse)

- May a redesign **merge or split** slides? *Provisional:* one-for-one by default; the
  checkpoint may ask to merge or split when the deck plainly needs it.
- "Also check figures against project papers": *Provisional:* off unless the person turns it on.
