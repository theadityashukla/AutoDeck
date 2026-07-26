# AutoDeck v1 — frozen reference

This directory is the complete AutoDeck v1 tree, moved here by `git mv` when the v2
build began. **History is preserved** — `git log --follow legacy/v1/app.py` traces back
through the original root-level path.

v1 is **reference material only**. Per plan §0.7: *salvage per §8; do not import v1 code
wholesale.* Nothing here is imported by the `autodeck/` package, and nothing here is
maintained. It exists so v2 implementers can read what was tried and why it stalled.

## Why v1 stopped

One root cause, from plan §1.2: **python-pptx has no layout engine**, so v1 was
hand-building one (`text_fitter.py`) and using a vision model as a measuring instrument
(`agents/design_agent.py`). Everything downstream — the EMU math, the overflow
whack-a-mole, the fix loop — is a symptom of that. Secondary causes: the local MLX/Gemma
stack, Streamlit state management, and a ~3-layout vocabulary that made every deck look
the same.

Read that paragraph before deciding to reuse anything here.

---

## Salvage map

What carries into v2, at function level, and where it lands.

| v1 location | What it is | v2 destination | Notes |
|---|---|---|---|
| `autodeck_core/agents/design_agent.py` → module-level `ACTION_CATALOG` | A problem→action lookup table (e.g. *text overflowing* → `body_font_size:small`, `split_slide`) fed to the vision model, with deterministic `apply_fixes` execution | `autodeck/render/qa/aesthetic.py` — the **bounded IR-level action set** (§6.9) | **Salvage the concept, not the code.** The insight worth keeping: the vision model proposes from a closed vocabulary, and execution is deterministic. In v2 the actions operate on IR (swap component, adjust type scale, rebalance columns), never on geometry — and the loop is structurally forbidden from touching claim text or citations. |
| `autodeck_core/agents/validation_agent.py` → `validate_content()`, `validate_coherence()` | Content/coherence checks against source docs | `autodeck/agents/validation.py` (A3) | **Read the caveat below — this is thinner than plan §8 implies.** |
| `autodeck_core/agents/outline_agent.py` → `generate_outline()`, `refine_outline()` | Outline generation with audience and slide-count parameters; `_clean_title()` | `autodeck/agents/outline.py` + `prompts/outline.md` | Prompt logic and narrative-role thinking. Re-implemented against the Deck IR, not ported. |
| `autodeck_core/agents/content_agent.py` → `generate_slide_content()`, `refine_content()` | Per-slide content generation | `autodeck/agents/content.py` + `prompts/content.md` | Same: the prompt shape is the asset. v2's version writes **inside component budgets** (§6.7) with a citation per claim — a different contract. |
| `autodeck_core/session_manager.py` → `save_session()`, `load_session()`, `_cleanup_old_sessions()` | JSON session persistence under `sessions/` | `autodeck/ir/store.py` + `runs/<run_id>/` | The *instinct* — checkpoint everything, make runs resumable — is right and carries forward. v2 versions the IR itself (`ir/v<N>.json`) and makes versions diffable for gate review. |
| `templates/Presentation1.pptx`, template-integrity learnings | What broke when writing into placeholder-based templates | `autodeck/design/theme/master_builder.py` (§6.8) | Informs onboarding mode (a): client supplies a corporate template. |

### Caveat on the validation agent

Plan §8 lists "validation agent structure" as salvage. Inspecting the file shows that
claim is **overstated**, and Phase 2b should be scoped accordingly:

- `validate_image()` — OpenCV blur / brightness / contrast checks. **Image quality, not
  claim validation.** No v2 equivalent; this is not what A3 does.
- `search_replacement_image()` — asset substitution. Not a validation concern in v2.
- `validate_content()`, `validate_coherence()` — the only two methods that are actually
  content validation, and they trust the writer's own retrieval.

**A3's defining behaviours have no v1 ancestor at all:** independent re-retrieval (the
validator retrieves for itself rather than checking the writer's citation), contradiction
search across the corpus, the four-verdict scheme, and blocking the render on
`unsupported`/`contradicted`. Treat Phase 2b's validator as new construction with a
prompt-shape hint from v1, not as an extension.

---

## Retire — do not port

| v1 location | Why it dies |
|---|---|
| `autodeck_core/text_fitter.py` (`chars_per_line()`, `calculate_optimal_font_size()`, `estimate_overflow()`, `SlideConstraints`) | Character-count heuristics standing in for glyph metrics. This is **the single clearest v1→v2 lesson**: v2's `design/budgets.py` measures real wrapped text height from the licensed TTF, hands the budget to the content agent as a hard constraint *before* writing, and makes overflow rare by construction. v1 wrote first and shrank fonts afterwards. |
| `autodeck_core/ingestion/chunker.py`, `parser.py`, `vector_store.py` | Agentic/vision chunking over PyMuPDF + ChromaDB → replaced by Docling with element-level provenance (D3). v1 chunks cannot carry `(doc_id, page, bbox)`, so they can never satisfy A1. |
| `autodeck_core/llm/gemma_client.py` | Local MLX/Gemma stack → deleted (D2). Apple-Silicon-only was a platform lock-in; v2 runs anywhere. |
| `app.py` (57k), `.streamlit/`, `static/material_expressive.css` | Streamlit app + session-state machine → replaced by a headless CLI (D7). |
| `autodeck_core/agents/design_agent.py` — everything except `ACTION_CATALOG` | Geometry-fixing code → replaced by deterministic checks (`render/qa/deterministic.py`) + natively designed components. |
| `autodeck_core/agents/formatting_agent.py` | Bypassed in v1 itself (see commit `d0d5ef8`); superseded by component budgets + grammar lints. |
| `autodeck_core/slide_factory.py`, `slide_processor.py`, `slide_renderer.py`, `ppt_generator.py` | Placeholder-filling render path → replaced by the component-renderer architecture over a real theme/master. |

## What was dropped in the move

Two tracked paths were deleted rather than moved, both build artifacts recoverable from
`main` and from git history:

- `.DS_Store` and `0. Input Data/.DS_Store` — macOS junk, already listed in `.gitignore`,
  tracked by accident.
- `generated_decks/temp_slide_{0..4}.pptx` — render scratch files. Commit `52b2489`
  ("chore: clean up temp files and test artifacts") shows the same intent.

`0. Input Data/AlphaFold.pdf` and `sessions/*.json` were **kept** — the paper is a
plausible Phase 1 ingestion fixture, and the session files show v1's checkpoint shape.

> **Note on the PDF.** `.gitignore` carries a blanket `*.pdf` rule, so `AlphaFold.pdf` is
> tracked only because it was force-added (it predates the rule). It survived the move for
> the same reason — a plain `git add` silently drops it at the new path while staging the
> deletion at the old one. If you move or re-add it again, use `git add -f`, or it
> disappears without an error.
