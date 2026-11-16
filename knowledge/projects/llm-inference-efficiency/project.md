# LLM inference efficiency

The cost and latency of *serving* a large language model, as distinct from training one.
The corpus covers the four technique families that dominate the published work, and the
measurements that justify each.

## Why this project exists

Inference is the recurring cost. Training is paid once; serving is paid per request,
forever, and at production volume it is the line item that decides whether a
language-model feature has a business case. The literature here is unusually good for
consulting work: the claims are quantitative, the baselines are stated, and the papers
report the hardware they ran on — which means a deck built from this corpus can put a
number on a slide and cite the sentence it came from.

## The four technique families

1. **Quantization** — store and multiply weights (and sometimes activations) at lower
   precision. `dettmers-2022-llm-int8` for 8-bit inference without degradation at scale;
   `frantar-2023-gptq` for one-shot post-training quantization down to 3–4 bits.
2. **Memory management for the KV cache** — `kwon-2023-pagedattention-vllm`. The
   observation is that serving throughput is bounded by wasted KV-cache memory rather than
   by compute, and that paging fixes it.
3. **Speculative execution** — `leviathan-2023-speculative-decoding`. Draft cheaply,
   verify in parallel, accept a prefix. Output distribution is preserved exactly, which is
   the property that makes it deployable.
4. **Partitioning and hardware scaling** — `pope-2022-efficiently-scaling-transformer-inference`.
   How to shard a large model across chips, and the Pareto frontier between latency and
   model-FLOPS utilisation.

## How to use this corpus accurately

- **The stated setup is part of the number.** Almost every headline figure here is
  conditional on a batch size, a sequence length, a chip generation and a model size. A
  throughput number lifted without its configuration is not a smaller truth, it is a
  different and false one. Cite the sentence that carries the condition, or state the
  condition alongside.
- **These are the authors' own measurements.** A paper reporting its method beating a
  baseline is evidence, not an independent benchmark. When a claim matters to a
  recommendation, say whose measurement it is.
- **Publication dates matter more than usual here.** The corpus is 2022–2023. Hardware and
  serving stacks have moved; a 2022 chip-generation figure is a historical data point, not
  a current one. Deck copy should carry the year.
- **Percentages compound badly.** Two techniques each claiming "2× throughput" do not
  compose to 4×, and the papers do not measure them together. A2 forbids inventing the
  combined number; if a deck needs one, it needs a source or a stated assumption.

## Open questions this corpus does not answer

- Cost per served request in currency. The papers report throughput, latency and memory —
  not price. Any monetary figure in a deck must come from the client's own billing data or
  a stated, labelled assumption (A8).
- How these techniques interact. Each paper isolates its own.
- Quality impact on the specific downstream task. The papers measure perplexity and
  standard benchmarks; whether a client's task tolerates 4-bit weights is an empirical
  question about that task.
