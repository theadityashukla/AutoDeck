# Pre-verified claims — LLM inference efficiency

The curated claim library (task 1.7, D8). Each fenced `yaml` block is one `CachedClaim`;
prose between blocks is commentary for humans and is ignored by the parser.

**The cache is a head start, not a bypass.** A claim loaded from here arrives `unverified`
like any other and its quote is re-resolved through the document store, because the store
is the authority on where text is *now* and a re-ingest can move a span. What the cache
saves is the search, not the validation (A3).

Every `quote` below is verbatim from the PDF as Docling extracted it, and every one was
resolved against the store and hash-verified before being written down. Copy the quote
exactly — a fixed typo or a smoothed hyphen makes it unresolvable, which is the intended
behaviour and not a bug to route around.

## Status — partially curated

Only `dettmers-2022-llm-int8` has curated claims. The other four papers are ingestable and
searchable via `autodeck knowledge ask`, but their claims have not been hand-verified yet.
Writing them from memory rather than from the resolved text is exactly the failure A1
exists to prevent, so they are absent rather than plausible. GATE 1a's ten-citation
spot-check runs against what is here plus live retrieval hits.

---

## Quantization — LLM.int8()

The headline: 8-bit inference at 175B parameters with no measured degradation. Note the
scope — this is about *memory*, not latency, and the paper is explicit that its Int8
matrix multiplication is not faster than fp16 at small batch sizes.

```yaml
claim: >-
  LLM.int8() halves the memory required for inference while retaining full-precision
  performance.
doc_id: dettmers-2022-llm-int8
page: 1
quote: "cut the memory needed for inference by half while retaining full precision performance"
bbox: [143.9, 317.5, 469.8, 522.4]
tags: [quantization, memory, headline]
note: >-
  The authors' own measurement, from the abstract. "Full precision performance" means task
  performance, not speed — this claim says nothing about latency or throughput, and a deck
  that reads it as a speedup is misusing it (A2).
```

```yaml
claim: >-
  A 175B-parameter checkpoint can be converted to Int8 and used for inference immediately,
  without a post-quantization tuning step.
doc_id: dettmers-2022-llm-int8
page: 1
quote: >-
  a 175B parameter 16/32-bit checkpoint can be loaded, converted to Int8, and used
  immediately without performance degradation
bbox: [143.9, 317.5, 469.8, 522.4]
tags: [quantization, deployment, integration-cost]
note: >-
  This is the operationally interesting part for a client with an existing deployment: no
  retraining and no calibration pass. It is the claim that makes quantization a candidate
  for a first phase rather than a project.
```

```yaml
claim: >-
  The method keeps more than 99.9% of values in 8-bit, isolating only outlier feature
  dimensions into 16-bit.
doc_id: dettmers-2022-llm-int8
page: 1
quote: "more than 99.9% of values are multiplied in 8-bit"
bbox: [143.9, 317.5, 469.8, 522.4]
tags: [quantization, mechanism]
note: >-
  Use when explaining *why* the memory saving is nearly the full 2x rather than eroded by
  the mixed-precision fallback.
```

## Where inference cost sits

Useful for framing the problem before naming a technique — it says which parts of the
model are worth attacking.

```yaml
claim: >-
  In transformer language models at and beyond 6.7B parameters, feed-forward and attention
  projection layers account for 65-85% of all computation.
doc_id: dettmers-2022-llm-int8
page: 1
quote: "65-85% of all computation"
bbox: [108.0, 568.8, 505.7, 686.5]
tags: [cost-structure, framing]
note: >-
  Careful — this is Dettmers et al. *citing Ilharco et al. (2020)*, not measuring it. The
  citation resolves to this paper because that is where the sentence is; a deck asserting
  it as this paper's finding would be wrong about provenance even though the quote is
  verbatim. Attribute it as reported.

  The adjacent parameter figure in the same sentence extracts as "95% 2" because a footnote
  marker sits against the number. That is why it is not quoted here: the verbatim span is
  the one thing A1 will not let us tidy, so a span that reads badly is a span to avoid, not
  to edit.
```
