# Pre-verified claims — LLM inference efficiency

The curated claim library (task 1.7, D8). Each fenced `yaml` block is one `CachedClaim`;
prose between blocks is commentary for humans and is ignored by the parser.

**The cache is a head start, not a bypass.** A claim loaded from here arrives `unverified`
like any other and its quote is re-resolved through the document store, because the store
is the authority on where text is *now* and a re-ingest can move a span. What the cache
saves is the search, not the validation (A3).

Every `quote` below is verbatim as Docling extracted it, and every one was resolved
against the store and hash-verified before being written down. Copy quotes exactly — a
fixed typo or a smoothed hyphen makes one unresolvable, which is the intended behaviour
and not a bug to route around. Where a quote reads oddly (`2-4 ×`, `10 ×`), that spacing is
what the extractor produced from the PDF's kerning, and it is preserved rather than tidied.

## How to use these on a slide

Almost every number here is conditional on a model size, a chip generation, a batch size
or a sequence length. Lifting one without its configuration does not produce a simpler
truth, it produces a different and false one. Prefer the quote that carries the condition;
where the condition sits in a neighbouring sentence, put it in the slide text yourself.

---

## Where the cost sits

Framing claims. Useful before naming any technique, because they say which part of the
system is worth attacking.

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

```yaml
claim: >-
  For a 13B-parameter model on an A100, roughly 65% of GPU memory holds static model
  weights and close to 30% holds the dynamic KV cache.
doc_id: kwon-2023-pagedattention-vllm
page: 1
quote: "Approximately 65% of the memory is allocated for the model weights"
bbox: [317.6, 548.5, 559.7, 700.7]
tags: [cost-structure, memory, framing]
note: >-
  The 30% KV-cache figure is in the following sentence of the same element, so cite this
  quote and state the second number in slide text, or quote the longer span. Both are
  specific to a 13B model on a 40GB A100 — the split moves with model size.
```

```yaml
claim: >-
  Serving an LLM request can be an order of magnitude more expensive than serving a
  traditional keyword query.
doc_id: kwon-2023-pagedattention-vllm
page: 1
quote: "processing an LLM request can be 10 × more expensive than a traditional keyword query"
bbox: [53.7, 470.8, 295.7, 599.1]
tags: [cost-structure, framing, secondhand]
note: >-
  Reported by Kwon et al. citing an external estimate, not measured here. Good for opening
  framing; do not present it as a measurement. Note the extracted spacing `10 ×`.
```

## Memory management — PagedAttention / vLLM

The strongest fit for a client whose bottleneck is batch size rather than raw compute.

```yaml
claim: >-
  vLLM improves LLM serving throughput by 2-4x over prior state-of-the-art systems with no
  loss of model accuracy.
doc_id: kwon-2023-pagedattention-vllm
page: 2
quote: "vLLM improves the LLM serving throughput by 2-4 × compared to the state-of-the-art systems"
bbox: [317.6, 350.3, 559.7, 514.5]
tags: [kv-cache, throughput, headline]
note: >-
  The headline number for this technique family, and the authors' own measurement against
  baselines they selected. The paper states the gains are larger for longer sequences and
  bigger models — so 2-4x is a range across their workloads, not a figure any single
  deployment should expect. "Without affecting the model accuracy at all" is in the same
  sentence and is worth carrying: it is what makes this a throughput win rather than a
  trade.
```

```yaml
claim: >-
  PagedAttention's design goal is near-zero waste in KV cache memory, borrowing virtual
  memory and paging from operating systems.
doc_id: kwon-2023-pagedattention-vllm
page: 1
quote: "near-zero waste in KV cache memory"
bbox: [53.6, 197.4, 295.7, 433.4]
tags: [kv-cache, mechanism]
note: >-
  Use when explaining the mechanism rather than the result. This is a stated design goal
  from the abstract, not a measured outcome — phrase it as such.
```

## Quantization

Two papers, two different operating points. Both are memory claims; neither is a latency
claim, and GPTQ is explicit that it is not.

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
  The operationally interesting part for a client with an existing deployment: no
  retraining, no calibration pass. It is what makes quantization a candidate for a first
  phase rather than a project.
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
  Use when explaining why the memory saving is nearly the full 2x rather than eroded by the
  mixed-precision fallback.
```

```yaml
claim: >-
  GPTQ compresses models to 3 or 4 bits per parameter in one shot, without retraining and
  without significant loss of accuracy.
doc_id: frantar-2023-gptq
page: 2
quote: "compress such models to 3 or 4 bits per parameter without significant loss of accuracy"
bbox: [108.0, 319.8, 504.0, 383.7]
tags: [quantization, memory, headline]
note: >-
  A more aggressive operating point than LLM.int8(). "Without significant loss" is the
  authors' characterisation of a perplexity delta, not a guarantee about any downstream
  task — and a client's quality bar is an empirical question about their data (A8).
```

```yaml
claim: >-
  GPTQ can quantize a 175B-parameter model in roughly four GPU hours.
doc_id: frantar-2023-gptq
page: 2
quote: >-
  GPTQ can quantize the largest publicly-available models, OPT-175B and BLOOM-176B, in
  approximately four GPU hours, with minimal increase in perplexity
bbox: [108.0, 319.8, 504.0, 383.7]
tags: [quantization, integration-cost]
note: >-
  The one-off cost of adopting the technique. Useful when the question is "how long would
  this take to try", which for a cost-constrained client is usually the second question.
```

```yaml
claim: >-
  A compressed OPT-175B model runs on a single A100 GPU, where the uncompressed model
  requires several.
doc_id: frantar-2023-gptq
page: 2
quote: "we are able to run the compressed OPT-175B model for the first time on a single NVIDIA A100 GPU"
bbox: [108.0, 391.7, 504.0, 475.6]
tags: [quantization, memory, hardware]
note: >-
  The most legible business consequence in the corpus: a hardware count, not a percentage.
```

```yaml
claim: >-
  GPTQ does not speed up the matrix multiplications themselves — mainstream hardware lacks
  support for mixed-precision operands.
doc_id: frantar-2023-gptq
page: 2
quote: >-
  our method currently does not provide speedups for the actual multiplications, due to the
  lack of hardware support for mixed-precision operands
bbox: [108.0, 564.9, 504.0, 627.2]
tags: [quantization, limitation, honest-uncertainty]
note: >-
  Cached deliberately. A8 asks for honest uncertainty, and the fastest way to lose this
  audience is to present a memory technique as a latency technique. Curating the limitation
  next to the headline means the writer meets both at the same time rather than finding the
  headline first and the caveat never. Note it is stated as of 2023 hardware.
```

## Speculative decoding

The one technique here that is provably output-preserving, which changes how it can be
recommended.

```yaml
claim: >-
  Speculative decoding gives a 2-3x latency improvement on T5-XXL with no change to the
  model's outputs.
doc_id: leviathan-2023-speculative-decoding
page: 2
quote: "latency improvement of 2X-3X"
bbox: [55.0, 392.4, 291.1, 508.6]
tags: [speculative-decoding, latency, headline]
note: >-
  Measured on an 11B-parameter T5-XXL against the T5X implementation — quote the
  configuration alongside, because a latency multiplier without a baseline is not a claim.
  This is the corpus's main *latency* result; most of the rest are memory or throughput.
```

```yaml
claim: >-
  Speculative decoding provably preserves the model's output distribution exactly.
doc_id: leviathan-2023-speculative-decoding
page: 1
quote: "an algorithm to sample from autoregressive models faster without any changes to the outputs"
bbox: [75.0, 191.4, 271.2, 439.0]
tags: [speculative-decoding, quality, risk]
note: >-
  The property that makes this deployable where quantization needs an evaluation first: a
  client with a low quality tolerance can adopt it without re-running their quality bar.
  Pair it with the latency claim — on its own it says nothing about speed.
```

## Partitioning and hardware scaling

```yaml
claim: >-
  PaLM 540B with int8 weights on 64 TPU v4 chips generates at 29ms per token and reaches
  76% model-FLOPS utilisation on large-batch input processing.
doc_id: pope-2022-efficiently-scaling-transformer-inference
page: 2
quote: >-
  29ms per token during generation (with int8 weight quantization) and a 76% MFU during
  large-batch-size processing of input tokens
bbox: [307.2, 304.2, 543.2, 468.2]
tags: [partitioning, latency, hardware]
note: >-
  Deeply configuration-bound: 540B parameters, int8 weights, 64 TPU v4 chips, 2048-token
  context. Every one of those conditions matters, and the number is meaningless without
  them. For a client on GPUs this is a reference point about what good looks like, not a
  target they can adopt.
```

```yaml
claim: >-
  On 64 TPU v4 chips, a PaLM 540B chatbot turn — 64 input tokens against a 1920-token
  history, generating 64 tokens — completes in 1.9 seconds.
doc_id: pope-2022-efficiently-scaling-transformer-inference
page: 2
quote: "generate a 64-token response in a total of 1.9 seconds"
bbox: [307.2, 304.2, 543.2, 468.2]
tags: [partitioning, latency, interactive]
note: >-
  The most concrete interactive-latency figure in the corpus, and the closest thing to a
  workload a retail assistant would recognise. Carry the token counts: 1.9 seconds is for
  that specific turn shape, and latency scales with the generated length.
```
