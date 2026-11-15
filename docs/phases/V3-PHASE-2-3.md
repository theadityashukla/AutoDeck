# v3 Phase 2–3 — Layers, routing and the design layer

**Branch:** `claude/autodeck-principles-review-zp7nsm` · **Source:** `docs/AUTODECK_V3_PLAN.md`
P4, P5, P7, V5, §4, §6, §7, §8.3, §12 Phases 2 and 3; the slide bench
(`bench/slides/`, results in `bench/slides/results/README.md`).

(Draft written early so an interruption leaves the task table on disk; the full document
follows below as it is completed.)

## Tasks (draft)

| id | Wave | Model | Files owned | Depends on |
|---|---|---|---|---|
| 23.1 | 1 | sonnet | `design.py` (functions below the marker) | none |
| 23.2 | 1 | haiku | `design_render.py` | 23.1 |
| 23.3 | 1 | sonnet | `responses.py` | none |
| 23.4 | 1 | haiku | `usage.py` (functions below the marker) | none |
| 23.5 | 1 | haiku | `edits.py` (Phase 2–3 functions) | none |
| 23.6 | 1 | haiku | `designer_prompt.py` | none |
| 23.7 | 2 | sonnet | `designer.py` | 23.1, 23.2, 23.6 |
| 23.8 | 2 | sonnet | `system_layer.py` | 23.1 |
| 23.9 | 1 | sonnet | `routing.py` | none |
| 23.10 | 2 | sonnet | `views.py`, `context.py` additions | 23.1 |
| 23.11 | 3 | sonnet | `compose.py` | 23.5, 23.7, 23.8 |
| 23.12 | 3 | sonnet | `tools.py` | 23.5, 23.11 |
| 23.13 | 2 | sonnet | `loop.py` additions, `mechanic.py` | none |
| 23.14 | 4 | sonnet | `session.py` | all above |
| 23.15 | 5 | sonnet | `api.py`, `__main__.py` | 23.14 |
| 23.16 | 1–5 | sonnet | `static/*` | the contract |
| 23.17 | 6 | lead | verification | all |
