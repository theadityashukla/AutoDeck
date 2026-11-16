# Phase 1 — Ingestion & knowledge — Handover

> This phase built the provenance chain. Every citation the system will ever produce
> resolves through what is here.

---

## 1. Identification

| | |
|---|---|
| **Phase** | 1 — Ingestion & knowledge |
| **Branch** | `v2/phase-1-ingest-knowledge` |
| **PR** | not yet opened |
| **Started / completed** | 2026-08-01 → 2026-08-02 |
| **Gate** | GATE 1a |
| **Gate status** | **approved** (DECISIONS.md G1a) |
| **Approved by / when** | Owner, 2026-08-02 |
| **What the owner actually checked** | `spikes/gate1a/index.md` — the worksheet listing all ten citations with claim, verbatim quote, bbox, sha256 prefix and hash status — plus **four of the ten** rendered pages (dettmers p1, kwon p2, frantar p2 ×2). The other six were generated and referenced but not sent inline. All ten reported `hash ok`. Recorded at this precision deliberately: the sample skews toward three of the five papers, and G1a names which two are least inspected. |

## 2. What shipped

| Path | What it does | Tests |
|---|---|---|
| `autodeck/ingest/document_store.py` | The A1 chokepoint. Verbatim `text` vs generated `description`, `CITABLE_KINDS`, `resolve_quote`, `resolve_cell`, `verify_citation` | `tests/test_ingest.py` |
| `autodeck/ingest/provenance.py` | Tolerant-but-not-approximate matching: ligatures, curly quotes, line-break hyphens. Returns offsets into the *verbatim* string | `tests/test_ingest.py` |
| `autodeck/ingest/docling_runner.py` | PDF → `Document`. Split at the ML seam: `run_docling` needs weights, `document_from_docling` is pure and holds every provenance decision | `tests/test_ingest.py` |
| `autodeck/ingest/figure_describer.py` | VLM figure descriptions via `ingest_vlm`, written to `description` only, with the invariant re-asserted after each write | `tests/test_figure_describer.py` |
| `autodeck/ingest/grobid.py` | Deliberate stub. Raises, documenting the three triggers that would justify building it | — |
| `autodeck/knowledge/loader.py` | Two-tier folder loading, `claims.md` parsing, fails naming every missing file at once | `tests/test_knowledge.py` |
| `autodeck/knowledge/context_assembler.py` | A4 enforcement. One namespace per build, guarded reads, foreign-index refusal | `tests/test_knowledge.py` |
| `autodeck/retrieval/hybrid.py` | BM25 + optional embeddings, RRF fusion. Elements are the chunks — there is no chunker | `tests/test_retrieval.py` |
| `autodeck/audit/spotcheck.py` | Renders a citation's bbox onto its source page for GATE 1a. Produces no verdict | `tests/test_spotcheck.py` |
| `autodeck/cli.py` | `knowledge validate` / `ingest` / `ask` / `spotcheck` | `tests/test_cli_knowledge.py` |
| `knowledge/projects/llm-inference-efficiency/` | Seed corpus: 5 CC BY 4.0 papers, 16 curated claims, all hash-verified | `tests/test_cli_knowledge.py` |
| `knowledge/clients/{northwind-retail,contoso-health}/` | Two fictional clients. Two, because A4 is not demonstrable with one | `tests/test_cli_knowledge.py` |

342 tests, 10 live-marked and deselected in CI.

## 3. What did not ship

| Task (brief id) | Why deferred | Now owned by |
|---|---|---|
| — | Every task 1.1–1.10 is complete | — |
| Live VLM description run | The generation path is built and unit-tested against a fake, but has never been executed against Gemini on a real figure. Needs a run with `generate_picture_images=True`, which re-converts the corpus (~16 min) | Phase 2b, first time a figure matters |
| Real project + client | Q2 answered "synthetic seed now, real one later". The seed is public papers and fictional clients | Whenever the owner supplies real material — the folder structure does not change |
| Embeddings in retrieval | `Embedder` is a Protocol with a test fake; no cloud embedder is wired. D2 forbids local models, so this is a provider-layer call that nothing needs yet | Phase 2b, if BM25 alone proves insufficient |

## 4. Decisions made this phase

- **B13** — `DerivationInput` carries the value, not just the citation (Phase 0, exercised here).
- **B19** — `.gitignore` patterns are anchored. Supersedes B18. Cost seven CI runs.
- **B20** — Seed corpus selects on **licence first**, topic second. CC BY 4.0 only.
- **B21** — `doc_id` is a readable slug, not an arXiv ID, because it appears in every citation a human reads.
- **B22** — `corpus/` and `spikes/gate1a/` are gitignored as derived data; `spikes/gate0/` stays tracked.

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | tested (schema) | **tested (end to end)** | `test_ingest.py::test_a_mutated_document_fails_verification`, `test_retrieval.py::test_a_retrieved_figure_description_cannot_be_cited`, `test_figure_describer.py::test_a_described_figure_is_still_not_citable` |
| A2 numbers | partial | partial | unchanged — `DerivationInput` exists; nothing computes yet |
| A3 validation | not-started | partial | `test_knowledge.py` — cached claims load `unverified`; the validator itself is Phase 2b |
| A4 isolation | not-started | **tested** | `test_knowledge.py::test_a_foreign_reference_deck_raises`, `test_cli_knowledge.py::test_the_seed_clients_are_isolated_from_each_other` (real folders, not a fixture) |
| A5 framing | not-started | partial | `value_prop.md` is typed as framing and loaded separately; nothing yet *enforces* that a claim cannot trace to it |
| A6 reproducibility | partial | partial | unchanged |
| A7 gates | enforced | enforced | `test_orchestrator.py`; `spotcheck` deliberately emits unticked boxes |
| A8 uncertainty | not-started | partial | `FigureDescription.legible`; `low_provenance` flagging. Not yet enforced on deck copy |

## 6. Spike and experiment findings

**The bbox bug — the most valuable thing in this handover.** Docling reports bounding boxes
with a `BOTTOMLEFT` origin; AutoDeck uses top-left. My first conversion swapped `t` and `b`,
which produces a *well-formed rectangle that is still in bottom-left space* — so nothing
crashed, nothing looked wrong, and every citation was vertically mirrored. A heading at the
top of an A4 page read as y≈690 instead of y≈137. My own docstring had warned about this
exact failure while the code below it did the wrong thing.

It was caught only by running a real PDF and looking at the box. Not by a unit test, not by
a hash check — **a mirrored bbox hash-verifies perfectly**, because the quote is unchanged
and only its location is wrong. That is the entire reason `autodeck/audit/spotcheck.py`
exists and why its worksheet says so in as many words.

**Descriptions fail closed harder than expected, and that is worth knowing.** I wrote a test
asserting that citing a figure description raises `UncitableSourceError`. It raises
`QuoteNotFoundError` instead — the broad resolver filters to citable elements *before*
matching, so a description is not a rejected candidate, it is not a candidate at all. The
test was wrong and the code was right. Both entry points are now asserted separately,
because they fail differently and a reader of one error should not infer the other path is
open.

**A4's backstop caught me.** `contoso-health/client.md` explained why the folder existed by
naming `northwind-retail` — in a file that gets loaded into prompts. `check_text` fired on
the real seed corpus. The explanation moved to `knowledge/README.md`. This is exactly the
case the backstop was written for (a client name pasted into curated markdown, which no
path check can see), and it fired on its author within a day.

**`.gitignore` cost seven CI runs.** An unanchored `tokens/` matched `config/tokens/` at any
depth. Local tests passed because the files existed on disk; CI failed every time since the
first Phase 0 push. I had asserted in B18 that the pattern "cannot swallow them" without
running `git status`. Recorded as B19.

**Negative result — no CC BY for the obvious papers.** *Attention Is All You Need*, *Scaling
Laws*, *FlashAttention* and *Chinchilla* all carry arXiv's default perpetual non-exclusive
licence, which grants **arXiv** distribution rights, not third parties. None can be
committed. The corpus topic was chosen *after* filtering on licence, not before —
`papers/SOURCES.md` records this so the next person does not re-derive it.

**Environment findings.** `arxiv.org` is reachable but `export.arxiv.org` is not, so licences
were scraped from abstract pages rather than the API. HuggingFace weights need `*.hf.co`,
not just `huggingface.co` — the API host redirects weight bytes to a CDN whose name never
mentions HuggingFace. Ingestion runs ~190s per 16–20 page paper on this container's CPU.

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| Six of ten spot-check renders unexamined | The gate's sample covers 3 of 5 papers. `leviathan-*` and `pope-*` are least inspected — check those first if a citation later looks wrong | Phase 2a, on first suspicion |
| VLM descriptions never run live | The prompt is untested against a real model; the structured-output schema may need repair-retry in practice | Phase 2b |
| A5 is not enforced, only structured | A claim could trace to `value_prop.md` and nothing would stop it | Phase 2b (validator) |
| Retrieval has no embedder | BM25 alone on a 5-paper corpus is fine; on a 50-paper one it will miss paraphrases | Phase 2b |
| `_element_id_for` is duplicated | Two modules derive element ids independently. If they drift, figures silently go undescribed with no error anywhere | Guarded by `test_figure_ids_match_the_runner` — keep it |
| Claude adapter still unexercised live | Carried from Phase 0. First `sit` run is its first real call | Phase 2a |
| Aptos prerequisite | Carried from Phase 0, unchanged | Phase 2b |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| 1.1–1.4 ingestion | Sonnet | Sonnet | — |
| 1.5, 1.7 loader | Sonnet | Sonnet | — |
| 1.6 context assembler | Opus | Opus | Guardrail path, as briefed |
| 1.8 retrieval | Sonnet | Sonnet | — |
| 1.9 seed corpus | **Haiku** | **Opus** | Escalated. The brief scoped this as file-shuffling. It is not: licence filtering, choosing what may be cited, and writing 16 claims whose quotes must be verbatim are all accuracy-critical judgement. `claims.md` is an A1 surface and Haiku was the wrong tier for it |
| 1.10 Grobid stub | Haiku | Haiku-appropriate | Written as a documented refusal |
| `spotcheck` (unbriefed) | — | Opus | `autodeck/audit/` is an Opus guardrail path |

**The brief's tier for 1.9 is wrong and should be corrected if this phase is ever re-run.**
Anything writing `claims.md` is writing citations.

## 9. Preconditions for the next phase

1. ~~**GATE 1a judged.**~~ **Done** — approved 2026-08-02, DECISIONS.md G1a.
2. **Decide whether the seed stays synthetic.** Phase 2a writes decks *for* a client; a
   fictional one is fine for building, but the first real deliverable needs real folders.
3. `ANTHROPIC_API_KEY` for the `sit` environment — still outstanding from Phase 0.
4. Nothing else. The corpus rebuilds from a clean clone with one command.

## 10. Verifying this phase from a cold start

```bash
uv sync
uv run ruff check . && uv run ruff format --check .   # All checks passed
uv run pyright                                        # 0 errors
uv run pytest -q -m "not live"                        # 342 passed, 10 deselected

uv run autodeck knowledge validate
# project  llm-inference-efficiency     16 claim(s), 5 paper(s)
# client   contoso-health               required files only
# client   northwind-retail             headers, tokens, 1 engagement(s)

# ~16 minutes; needs huggingface.co AND *.hf.co reachable
uv run autodeck knowledge ingest llm-inference-efficiency
# five papers, each "coverage 100%", none flagged LOW PROVENANCE

uv run autodeck knowledge ask llm-inference-efficiency \
    "KV cache memory waste limits serving throughput" --client northwind-retail
# three hits from kwon-2023-pagedattention-vllm, each ending VERIFIED

uv run autodeck knowledge spotcheck llm-inference-efficiency
# ten renders + spikes/gate1a/index.md, every line "hash ok"
```

## 11. Reading notes for the next implementer

**Read `document_store.py` first.** Everything else in this phase is arranged around it. The
one distinction that carries the whole invariant is `text` (verbatim, from the document,
what the resolver searches) versus `description` (generated, metadata, never searched). If
you only remember one thing, remember that they are separate fields on purpose and that a
single `content` field would eventually be searched by something that did not know the
difference.

**The store is the authority, always.** Cached claims re-resolve through it. Retrieval hits
re-resolve through it. The spot-check re-verifies through it. Anything holding a `(page,
bbox)` pair it did not just get from the store is holding a guess — `claims.md` records
bboxes for human readability, and `CachedClaim.to_citation` ignores them.

**What looks wrong but is deliberate:**

- `BM25Index` is hand-written rather than a dependency. Forty lines of well-specified
  arithmetic, and owning it means the tokenizer is shared with the citation resolver —
  which is what stops text being findable but uncitable.
- There is no chunker. Elements *are* the chunks. v1 chunked into windows that structurally
  could not carry `(doc_id, page, bbox)`, which is why it is being replaced. If you find
  yourself writing a chunker, re-read `legacy/v1/LEGACY.md` first.
- `claims.md` quotes contain odd spacing (`2-4 ×`). That is the PDF's kerning as Docling
  extracted it. Tidying it makes the quote stop resolving. That is correct behaviour.
- The Grobid module raises unconditionally. It is a decision made visible in code, not an
  unfinished file.

**What I would do differently.** I asserted a `.gitignore` pattern was safe without running
`git status`, and it cost seven CI runs and a hotfix on two branches. I wrote a bbox
conversion that my own docstring warned against. Both failures share a shape: I reasoned
about what the code would do instead of running it and looking. In a phase whose entire
output is "coordinates that point at the right part of a page", the only real test is
rendering the page and looking at the box. Do that early and often — `autodeck knowledge
spotcheck` exists so it costs one command.

**The seed corpus is real evidence, not fixtures.** Five genuine papers, sixteen claims with
verbatim quotes and verified hashes. If you need a citation to test something against, take
one from there rather than inventing `doc-1 / page 1 / "some text"` — the real ones have
awkward extraction artefacts, second-hand attributions and configuration-bound numbers, and
code that works on invented data often does not survive them.
