# Knowledge folders

Two tiers (D8): a **project** base holding evidence, and a **client** overlay holding
context, framing and brand. One project serves several clients; a client's material never
enters another client's build (A4).

```
knowledge/
  projects/<project>/
    project.md      required — what the project is about, for the writer's context
    claims.md       required — the pre-verified claim cache (task 1.7)
    papers/         source PDFs; ingested into the document store
    assets/         optional — charts, data files
  clients/<client>/
    client.md       required — who they are, what they care about
    value_prop.md   required — positioning language. A5: this is FRAMING, never fact
    engagements/    optional — dated notes from the engagement
    style/          optional — headers.yaml and other writing-style profiles
    theme/          optional — tokens.json, template.pptx, icons/
    decks/          optional — past decks, read for STYLE only (§6.12)
```

## Why `claims.md` is the main road

Curated markdown is loaded *fully* into context. Retrieval (`autodeck/retrieval/`) is the
long tail — for questions the curated library does not already answer. This is the OKF
principle behind D8, and it is why `claims.md` is a required file even when empty: an
absent one usually means somebody forgot, and an empty one says so on purpose.

The cache is a head start, not a bypass. A claim loaded from `claims.md` arrives
`unverified` like any other and is re-resolved through the document store, because the
store is the authority on where text is *now* and a re-ingest can move a span.

## The seed corpus

`projects/llm-inference-efficiency/` is the seed committed by task 1.9. Its papers are
real, public and CC BY 4.0 — see `papers/SOURCES.md` for attribution. Its clients are
fictional (`northwind-retail`, `contoso-health`), so nothing here is confidential and the
whole thing can live in the repo.

Two clients, not one, because A4 is only *demonstrable* with two: `contoso-health` exists
so that a `northwind-retail` build reaching for it raises `ClientIsolationError` against
real folders rather than only against a test fixture.

## Adding a client

1. `mkdir -p knowledge/clients/<name>` and write `client.md` and `value_prop.md`. The
   loader fails naming every missing required file at once, so it is safe to start empty.
2. Keep facts out of `value_prop.md`. A5 separates fact from framing: anything in there is
   typed as framing and cannot back a claim. If a number belongs to the client, it needs a
   citable source like any other number.
3. Never paste another client's name into curated markdown.
   `ContextAssembler.check_text()` fires on it.
