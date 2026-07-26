# Accuracy invariants — the enforceable checklist

The invariants are stated in full in `README.md`. This file turns them into something
**checkable**: for each one, what enforces it, which phase owns it, and what test proves
it. Every phase handover updates the coverage table at the bottom.

Per plan §0.4 and D9: **invariants are blocking, not advisory.** Never weaken one to make
a test pass or a demo work. If an invariant genuinely blocks progress, stop, surface the
conflict to the owner, and propose options. Silently relaxing an invariant is the single
worst failure mode available to this build — it produces a system that looks finished and
is untrustworthy.

---

## Which invariants can be verified on the dev binding (decision B8)

Development runs on free-tier Gemini + Groq; SIT and production run on Claude. That split
divides the invariants in two, and the division decides where a verification result is
worth anything.

| | Invariants | Verify on |
|---|---|---|
| **Deterministic** — enforced by code | A1, A2, A4, A5, A6 | any environment; results transfer unchanged |
| **Model-sensitive** — enforced by judgment | **A3, A8** | `sit` before any production reliance |

A1's citation structure is a schema constraint. A2's linting and derivation re-execution
is arithmetic. A4, A5, A6 are lints, guards, and hashes. None of them care which model
produced the text they inspect, so a green result on `dev` is a green result everywhere.

A3 and A8 are different in kind. "Did the validator find the contradicting span?" and
"did the writer hedge honestly where sources conflict?" are judgments, and a weaker model
fails them **plausibly rather than loudly** — you get a clean-looking claims table that
happens to have missed something. A contradiction-catch rate measured on Gemini is
evidence about Gemini.

**The operational rule:** a dev-environment pass on A3 or A8 is a smoke test, not a
verification. Phase 5 records the environment on every eval result, and headline metrics
are measured on `sit`. A7 sits slightly apart — the gate *mechanism* is deterministic and
verifiable anywhere, but what a human approves at those gates depends on A3's output.

---

## A1 — Universal citation

> Every factual assertion in rendered slide content or speaker notes carries ≥1 citation
> resolving to a source span `(doc_id, page, bbox, verbatim_quote, quote_sha256)`. Only
> `framing` blocks are exempt.

- **Enforced by:** the IR schema (a `claim` block with zero citations must fail pydantic
  validation — structural, not a runtime check); `ingest/provenance.py`; hash
  verification of `quote_sha256` against the document store.
- **Owning phases:** Phase 0 (schema forbids it), Phase 1 (provenance chain), Phase 2b
  (writer produces them).
- **Proves it:** a test constructing a `claim` block with `citations=[]` and asserting
  `ValidationError`; a test mutating a stored quote and asserting the hash check fails.
- **Watch for:** speaker notes are blocks too. A1 applies to notes, not just slide faces.

## A2 — Numbers are copied or derived, never invented

> Every number, percentage, unit, and date traces to a cited span — directly, or through
> a declared `Derivation` whose formula is recorded with cited inputs. The numeric linter
> extracts all numerals, normalises, matches, and **re-executes every derivation formula**.
> Zero unmatched numerals to pass.

- **Enforced by:** `autodeck/audit/numeric_linter.py`, blocking, run **twice** —
  pre-validation on IR text, and again post-render on extracted rendered text.
- **Owning phases:** Phase 2b (linter + derivations), Phase 3b (post-render re-run).
- **Proves it:** adversarial tests injecting (a) a numeral with no cited source, (b) a
  derivation whose stated result does not match re-executing its formula, (c) a format
  variant (`3.2M` vs `3,200,000`) that must still match.
- **Watch for:** the normalisation table is where this invariant leaks — locale decimal
  separators, `%` vs `percent`, scale suffixes. Test it directly, not only end to end.

## A3 — Blocking validation

> Every claim gets `supported | partially_supported | unsupported | contradicted`. No
> final render while any block is `unsupported` or `contradicted`. The validator
> **re-retrieves independently** and searches for contradicting spans; it never merely
> trusts the writer's citation.

- **Enforced by:** `autodeck/agents/validation.py` + an orchestrator guard that refuses
  to enter the render phase on a failing verdict.
- **Owning phase:** Phase 2b.
- **Proves it:** a test where the writer's citation is valid but a contradicting span
  exists elsewhere in the corpus — the validator must find it and return `contradicted`.
  A test asserting the orchestrator raises rather than renders.
- **Watch for:** v1's validator trusted the writer (`legacy/v1/LEGACY.md` records this).
  Independent re-retrieval is the whole point and has **no v1 ancestor** — build it new.
- **Model-sensitive (B8):** a dev-binding pass is a smoke test. Verify on `sit`.

## A4 — Client isolation

> A build loads exactly one client namespace. Any cross-client reference in context
> assembly is a build **error**, not a warning.

- **Enforced by:** `autodeck/knowledge/context_assembler.py` raising `ClientIsolationError`.
- **Owning phases:** Phase 1 (assembler), Phase 4 (multi-client regression).
- **Proves it:** a two-client fixture; assembling client B's content during a client A
  build must raise. Phase 4 adds a full two-client build regression.
- **Watch for:** leaks via cached retrieval indices and via reference decks
  (`clients/<c>/decks/`), not just the obvious markdown load path.

## A5 — Fact/framing separation

> Value-proposition language is typed `framing` and is citation-exempt, but must pass a
> deterministic "no fabricated fact" lint: no numerals, no named studies, no comparative
> superlatives with factual content. Violations demote the block to `claim`.

- **Enforced by:** `autodeck/audit/framing_linter.py`, blocking.
- **Owning phases:** Phase 2b (linter), Phase 4 (proven across real client framing).
- **Proves it:** adversarial test — a `framing` block containing "clinically shown to cut
  costs 40%" must be demoted to `claim` and then fail A1 for lack of citation.
- **Watch for:** demotion must be a real state change that re-triggers A1/A3, not a
  logged warning.

## A6 — Reproducibility and audit

> Every deck ships the frozen IR, an audit report (slide → claim → verdict → doc/page →
> verbatim quote), and a build manifest (model IDs, prompt hashes, knowledge git commit,
> component library version). Same manifest + IR re-renders byte-comparable output.

- **Enforced by:** `autodeck/audit/report.py`, `autodeck/audit/manifest.py`.
- **Owning phases:** Phase 2b (report + manifest), Phase 3b (render determinism),
  Phase 4 (client-presentable PDF).
- **Proves it:** render twice from one manifest+IR and diff, excluding timestamps.
- **Watch for:** PPTX zip entry order and embedded creation timestamps will break naive
  byte comparison — normalise before comparing, and record the normalisation.

## A7 — Human gates

> Four mandatory approvals per deck: planning brief, outline, post-validation claims
> table, final render. The pipeline never auto-approves.

- **Enforced by:** `autodeck/pipeline/orchestrator.py` gate stops.
- **Owning phases:** Phase 0 (gate stubs), Phase 2a/2b, Phase 4 (all four wired).
- **Proves it:** a test asserting no code path reaches final render without four recorded
  approvals — including `--yes`-style flags, which must not exist for gates.
- **Watch for:** these are the deck's four runtime approvals. They are **distinct** from
  the six build-time GATEs in `docs/BRANCHING.md`. Do not conflate the two.

## A8 — Honest uncertainty

> Where sources conflict or evidence is `partially_supported`, hedge in slide text or
> notes — never average, round, or silently pick one. Conflicts appear in the audit report.

- **Enforced by:** `prompts/content.md` behaviour + a conflicts section in the audit
  report; partly model behaviour, so it is eval-defended rather than lint-defended.
- **Owning phases:** Phase 2b (behaviour), Phase 5 (eval).
- **Proves it:** a fixture corpus with two sources giving different values for one figure;
  the deck must hedge and the report must show both.
- **Watch for:** the only invariant not fully reducible to a deterministic check. It needs
  an eval, and it is the most likely to silently regress on a model swap.
- **Model-sensitive (B8):** a dev-binding pass is a smoke test. Verify on `sit`. Note that
  moving between `dev` and `sit` **is itself a model swap** — exactly the event this
  invariant is most likely to regress on.

---

## Coverage tracker

Status values: `not-started` · `partial` · `enforced` (code exists) · `tested` (a test
proves it). Updated in every phase handover — §5 of `docs/handovers/TEMPLATE.md`.

| Invariant | P0 | P1 | P2a | P2b | P3a | P3b | P4 | P5 |
|---|---|---|---|---|---|---|---|---|
| A1 citation | not-started | | | | | | | |
| A2 numbers | not-started | | | | | | | |
| A3 validation | not-started | | | | | | | |
| A4 isolation | not-started | | | | | | | |
| A5 framing | not-started | | | | | | | |
| A6 reproducibility | not-started | | | | | | | |
| A7 gates | not-started | | | | | | | |
| A8 uncertainty | not-started | | | | | | | |

Fill each cell as its phase completes. A phase whose brief claims an invariant cannot
close its gate with that cell below `enforced`.
