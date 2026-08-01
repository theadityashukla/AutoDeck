# Sources and licences

Every paper here is redistributed under **Creative Commons Attribution 4.0 International
(CC BY 4.0)**, which is why it can sit in this repository at all. That was the selection
criterion, not an afterthought: arXiv's default "perpetual non-exclusive licence" grants
*arXiv* the right to distribute, not third parties, so a paper carrying it was excluded
however well it fitted the topic. Checked at the arXiv abstract page for each ID on
2026-08-01.

Adding a paper means checking its licence first. If it is not CC BY (or another licence
that permits redistribution), keep the PDF out of the repo and point `claims.md` at a
local path instead — an uningestable corpus is a smaller problem than an unlicensed
redistribution.

| File (`doc_id`) | Paper | arXiv | Licence |
|---|---|---|---|
| `pope-2022-efficiently-scaling-transformer-inference` | Pope et al., *Efficiently Scaling Transformer Inference* | [2211.05102](https://arxiv.org/abs/2211.05102) | CC BY 4.0 |
| `kwon-2023-pagedattention-vllm` | Kwon et al., *Efficient Memory Management for Large Language Model Serving with PagedAttention* | [2309.06180](https://arxiv.org/abs/2309.06180) | CC BY 4.0 |
| `leviathan-2023-speculative-decoding` | Leviathan et al., *Fast Inference from Transformers via Speculative Decoding* | [2211.17192](https://arxiv.org/abs/2211.17192) | CC BY 4.0 |
| `frantar-2023-gptq` | Frantar et al., *GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers* | [2210.17323](https://arxiv.org/abs/2210.17323) | CC BY 4.0 |
| `dettmers-2022-llm-int8` | Dettmers et al., *LLM.int8(): 8-bit Matrix Multiplication for Transformers at Scale* | [2208.07339](https://arxiv.org/abs/2208.07339) | CC BY 4.0 |

The PDFs are unmodified as downloaded from arXiv.

## Why the filenames are slugs and not arXiv IDs

The filename becomes the `doc_id`, and the `doc_id` appears in every citation the owner
reads during a GATE 1a spot-check. `kwon-2023-pagedattention-vllm, p. 7` can be checked
against the right paper without a lookup; `2309.06180, p. 7` cannot. The arXiv ID is the
canonical identifier and lives in the table above, where a machine that needs it can find
it and a human reading a citation is not made to decode it.
