# Bench

Measuring tools, not product code. They may import from `autodeck/studio/` and v2 and must
change neither. Results are written outside the repository (`--out`) and the ones worth keeping
are copied into `results/`.

## `slides/`: the slide bench (v3)

Tests design at the level of one slide: one trial gives a model one slide brief (and optionally
a design concept) and returns one rendered slide, checked by the studio's layout QA. It exists
because the slide is the unit of design; research, storyline and the studio's tool loop are
deliberately left out. Added at the owner's suggestion during v3 (it is not in the plan).

| Path | What |
|---|---|
| `SPEC.md` | The contract: cases, concepts, what the model is given, scoring, outputs |
| `run.py` | The harness (designer loop, visual feedback, reviewer modes) |
| `prompts/slide.md`, `prompts/review.md` | The designer's and the reviewer's prompts (the designer's was moved into the product as `prompts/studio/designer.md`) |
| `cases/`, `concepts/` | Eight slide briefs; four design concepts, one of them `none` (the control) |
| `prices.yaml` | **Assumed**, deliberately high prices; never confirmed |
| `results/README.md` | What each round found, with the estimated cost of each |
| `tests/` | Harness tests, no network (70 pass) |

Run it (needs `OPENAI_API_KEY`; every run costs money; the budget guard is an estimate and
parallel workers can overshoot it, as round 1 did):

```bash
uv run python bench/slides/run.py --env-model openai:gpt-5.6-luna --cases all \
    --concepts demand-curve --out /tmp/bench-out --budget 5
uv run python bench/slides/run.py --help      # reviewer and review-only modes, dry run
```

Findings in one paragraph: with a concept, separately designed slides read as one deck, and
without one each is good but they do not match; a model shown its own render adds little; a
separate reviewer is precise and weak on composition flaws; `gpt-5.4-mini` cannot pass layout QA
as a designer. Details and the numbers: `slides/results/README.md`.
