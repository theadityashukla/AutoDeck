# Phase 1 — Ingestion & knowledge

**Branch:** `v2/phase-1-ingest-knowledge` · **Gate:** GATE 1a · **Estimate:** 3–4 weeks
**Source:** `docs/AUTODECK_V2_PLAN.md` §7 Phase 1, §§6.3–6.5

> This phase builds the provenance chain. Every citation the system will ever produce
> resolves through what is built here — if provenance breaks, A1 is unenforceable no
> matter how good the agents are.

## Preconditions

- GATE 0 approved; `docs/handovers/PHASE-0.md` read.
- Deck IR and provider abstraction merged and stable.
- Owner answer to Q2 (which project + client seed the build; real or anonymised).

## Tasks

| id | Task | Model | Files | Invariants | Done when |
|---|---|---|---|---|---|
| 1.1 | Docling runner → structured document (reading-order text, tables as tables, figures with captions, formulas), each element with page + bbox | **Sonnet** | `autodeck/ingest/docling_runner.py` | A1 | A real PDF produces elements whose page/bbox match the source visually |
| 1.2 | `document_store` — every element keyed by `doc_id`, verbatim text stored so citations hash-verify, plus a normalised form | **Sonnet** | `autodeck/ingest/document_store.py`, `provenance.py` | **A1** | `quote_sha256` verifies against stored text; mutating stored text makes the check fail |
| 1.3 | Figure/table extraction; VLM figure descriptions via the `ingest_vlm` role, stored as element metadata | **Sonnet** | `autodeck/ingest/docling_runner.py` | A1 | Descriptions are retrievable **and structurally cannot be cited as fact** — enforce in the store's citation resolver, not by convention |
| 1.4 | Table cell structure preserved so `ChartSpec`s can cite a specific cell | **Sonnet** | `autodeck/ingest/document_store.py` | A1, D10 | A table cell resolves to a citation with its own bbox |
| 1.5 | Knowledge folder structure + `loader.py` validating required files, failing loudly on malformed folders | **Sonnet** | `autodeck/knowledge/loader.py` | D8 | A malformed fixture folder raises with a message naming the missing file |
| 1.6 | **`context_assembler.py` with A4 isolation** — curated markdown loaded fully; any cross-client reference raises `ClientIsolationError` | **Opus** (invariant-critical) | `autodeck/knowledge/context_assembler.py` | **A4** | Two-client fixture: assembling client B during a client A build **raises**. Cover the non-obvious paths — cached retrieval indices and `clients/<c>/decks/`, not just the markdown load |
| 1.7 | `claims.md` pre-verified claim cache format + loader | **Sonnet** | `autodeck/knowledge/loader.py` | A1, A3 | Claims load with citations attached; cached claims are still **flagged for re-validation** (A3 applies — the cache is a head start, not a bypass) |
| 1.8 | Hybrid retrieval (BM25 + embeddings) returning spans **with** provenance; provenance-less chunks rejected | **Sonnet** | `autodeck/retrieval/hybrid.py` | **A1** | A chunk without resolvable provenance is unusable for a citation — assert this, do not merely document it |
| 1.9 | Seed one real project + one real (or anonymised) client | **Haiku** | `knowledge/projects/`, `knowledge/clients/` | A4 | Folders validate; corpus ingests end to end |
| 1.10 | Grobid adapter **stub only** — not in the critical path | **Haiku** | `autodeck/ingest/` | — | Stub exists with a docstring explaining when it would be needed; no implementation |

## Accuracy focus

> Provenance is unbroken from PDF element → store → any citation; hash check catches drift.

## Milestone

Ask a factual question against the corpus; get answers with correct page/bbox citations
that hash-verify.

## GATE 1a — exit criteria

**The owner spot-checks 10 citations against the source PDFs. All 10 must resolve
exactly** — correct page, bbox pointing at the right region, quote verbatim.

This gate is deliberately manual and deliberately unforgiving. A citation system that is
90% right is worse than none, because it manufactures unearned confidence.

## Escalation triggers

- **Docling provenance gaps on messy PDFs** (a named risk in plan §9). Do not paper over
  with approximate bboxes — flag low-provenance documents at ingest for human review and
  make their content unusable for claims.
- **Any path that produces a citable fact without provenance** — stop; that is an A1 hole.

## Notes for the implementer

- v1's ingestion is fully retired (`legacy/v1/LEGACY.md`): PyMuPDF parsing, agentic
  chunking, ChromaDB. Do not consult it for approach — its chunks structurally cannot
  carry `(doc_id, page, bbox)`, which is exactly why it is being replaced.
- Retrieval is a **fallback**, not the primary knowledge path (D8). The curated
  `claims.md` library is the main road; hybrid search is the long tail.
- Figure descriptions from `ingest_vlm` are metadata. The temptation to let a good VLM
  description back a claim will recur in Phase 2b — the store should make it impossible
  rather than relying on the writer's discipline.
