# First live run of the draft-first build — findings and handover

**Date:** 2026-10-03 · **Branch:** `v2/integration` (all work below is uncommitted)
**Run examined:** `runs/Xls`, project `oral-semaglutide`, environment `dev-mistral`
**Scope:** Phase 3c (draft-first) and 3d (redesign) had never met a real model before this run.
This document records what was observed, what was changed, and what is open. It states facts;
anything not yet confirmed is listed separately in section 6.

---

## 1. Provider access

| Provider | Observed |
|---|---|
| Gemini free tier | 20 requests/day per model (the 429 body said `limit: 20`); intermittent 503 "high demand". `gemini-3.6-flash` and `gemini-3.5-flash` could not complete a run. |
| Mistral key | Valid. `GET /v1/models` returned 200. |
| Mistral per-model limits on this account (`x-ratelimit-limit-req-minute`, 2026-10-03) | `ministral-14b-2512`: 30 · `ministral-8b-2512` / `open-mistral-nemo`: 188 · `codestral-latest`: 125 · **0 (every call returns 429):** `mistral-small-2603`, `mistral-small-latest`, `mistral-medium-latest`, `mistral-medium-2604`, `mistral-medium-3-5`, `magistral-small-latest`, `magistral-medium-latest`, `mistral-vibe-cli-latest`. |
| Mistral capabilities | `ministral-14b-2512` and `ministral-8b-2512`: 262,144-token context, vision, function calling. |
| Mistral pricing (third-party listings) | about $0.20 per million tokens for Ministral; Small $0.15 in / $0.60 out; Medium 3.5 $1.50 in / $7.50 out. |
| Owner's allowance | $10/month included API usage, $0 used (console screenshot). |
| Hugging Face hosted inference | $0.10/month free credit. |
| Free tiers with small per-request input caps | Groq 6k–12k tokens/min on large models; GitHub Models 8,000 input tokens per request; Cerebras 8k–64k context on free tier. A compose call sends an evidence pack of up to 24,000 estimated tokens plus the prompt. |
| Local model | `gemma-3-12b-mlx` (4-bit) is on disk. This Mac: M1 Pro, 16 GB. Installed `mlx_lm.server` has no JSON-schema constrained output. Decision D2 ("no local models") applies. |

## 2. Defects found and fixed in this session

| # | Defect | Evidence | Fix | Files |
|---|---|---|---|---|
| 1 | Gemini rejected the compose schema with HTTP 400 | Full `ComposeDraft` schema failed; removing `maxItems` alone made it acceptable (live bisect against the API). Message: "produces a constraint that has too many states for serving". | `maxItems` added to the keywords stripped from the Gemini dialect. Pydantic still enforces the cap. | `autodeck/ir/schema.py` |
| 2 | No Mistral adapter | — | New adapter (strict schema dialect, `max_tokens`, image part as a data-URL string, chunked-reply handling); `dev-mistral` environment; decision B51. | `autodeck/providers/mistral.py`, `registry.py`, `config/models.yaml`, `DECISIONS.md` |
| 3 | 10 of 12 citations dropped as "not verbatim" | Compared each cached quote against the paper's text: 3 had a trailing period added, 1 lacked `[50, 51]` reference markers, 1 differed by a PDF extraction space (`( p = 0.76)`), 2 were splices of two sentences, others were near copies. | `snap_span`: a quote not found exactly is matched to one passage among the evidence that slide was shown (≥85% of the quote in order, within 1.5× its length, ≥20 characters); the citation is built from that passage's verbatim text and hash. Same rule for the validator's quotes. Each snap is listed under `corrections`. Decision B52; note under A1 in `docs/INVARIANTS.md`. Re-run on the same cached reply: dropped blocks 12 → 6; 11 quotes snapped. | `autodeck/ingest/provenance.py`, `agents/content.py`, `agents/compose.py`, `audit/verdicts.py` |
| 4 | `preview` crashed (`RenderStageError: ChartFocusContent.'chart' has no block filling slot`) | Occurs when a required slot is emptied by a dropped block. | Slide is drawn as a labelled placeholder; `preview` lists placeholders. | `autodeck/render/draft.py`, `cli.py` |
| 5 | UI could not see a key added to `.env` | Running UI (started 19:32) held `GEMINI_API_KEY` but not `MISTRAL_API_KEY`; AutoDeck never read `.env` itself. | CLI loads `./.env` at startup, never overriding the shell; tests set `AUTODECK_NO_DOTENV=1`. | `autodeck/dotenv.py`, `cli.py`, `tests/conftest.py`, `ui/static/app.js` |
| 6 | A failed draft in the UI had no recovery | "Try again" appeared only while the job was held in memory; the UI always started on `dev`. | "Try again" shows from saved stage status; a model picker (environments with a missing key disabled) sits beside it; the choice is saved to `~/.autodeck/settings.json` and restored at start; `ui --env` is optional. | `autodeck/ui/api.py`, `ui/static/app.js`, `app.css`, `cli.py` |

New tests: `tests/test_snap.py` (10), `tests/test_dotenv.py` (3), `tests/test_ui_settings.py` (4), plus 4 Mistral adapter tests in `tests/test_providers.py`.
**Suite:** 1,633 passed with `AUTODECK_FONT_DIRS` pointing at a temporary copy of Liberation Sans. Without it, 131 tests fail with `FontNotFoundError: Liberation Sans` (not installed on this Mac); those failures predate this session. The JavaScript passes a syntax check only (no Node installed); the new UI controls have not been exercised in a browser.

## 3. The `Xls` draft as the owner reviewed it (UI screenshots)

Source: `runs/Xls/llm_cache/51/510ceac5…txt` (compose reply from `ministral-14b-2512`), IR `runs/Xls/ir/v6.json`.

| Slide | Component | What is on it | Cause where known |
|---|---|---|---|
| s1 | `title` | Title wraps to three lines and overprints the subtitle. | Rendering (section 4a). |
| s2 | `section_divider` | Section number "1" and "Glycemic Control: HbA1c Reduction", in a deck of 6 slides. | The model chose the component; no prompt rule limits dividers. |
| s3 | `chart_focus` | Placeholder: "could not be drawn". | Chart block dropped: its quotes were two splices of two sentences each (HbA1c at weeks 26 / 52 / 78). |
| s4 | `chart_focus` | Headline, chart frame, axes and legend; **no bars**. Values 0.3 / 2.5 etc. print to the right of the category labels. | Data in the IR is correct (`-2.5, -2.5, -2.6, -2.5` vs `-0.2, -0.6, -0.1, -0.3`). Cause not diagnosed. |
| s5 | `bullets_supporting` | Headline only. | The model wrote 3 bullets (92, 132 and 101 characters). All three were dropped by the budget check; the log reports `132 characters does not fit (points (each item): at most 1 line(s), roughly 88 characters, at 16pt Inter)` for each. |
| s6 | `callout_takeaway` | Takeaway wraps to four lines and overprints the support line. | Rendering (section 4a); takeaway text is 120 characters. |

The model's own output for this deck:
- 6 slides; `narrative_role` values: title, situation, complication, complication, complication, resolution.
- Headlines are topic labels ("Body Weight Reduction Across PIONEER Trials", "Safety and Tolerability of Oral Semaglutide").
- After citation resolution the IR holds 2 claim blocks in total. Key-message evidence after the B52 re-run: km1 thin, km2 supported, km3 supported, km4 thin, km5 unsupported.
- The s6 takeaway states "superior glycemic control and weight reduction compared to active comparators and placebo". The A3 validator's verdict on the s4 claim about weight versus sitagliptin and empagliflozin was `contradicted`, citing the paper's "Body-weight reductions were found to be similar for oral semaglutide compared with empagliflozin".
- Coverage: 3 of 6 requested topics covered, 3 `left_out`.

## 4. Open defects (not fixed)

**a. Preview fonts.** The draft PPTX names `Inter` and `Inter Display`. Those files are in `~/.local/share/fonts` and are listed by `fc-list`. `~/Library/Fonts` and `/Library/Fonts` contain no Inter. The preview shows a wide, heavy bold face on titles. `scripts/install-dev-fonts.sh` installs to `fonts/` and `~/.local/share/fonts` only. The font check (`autodeck fonts check`) searches `~/.local/share/fonts` as well, so it reports Inter present.

**b. Charts with negative values draw no bars** (slide 4).

**c. Content dropped, not repaired.** A block that fails the budget check or whose quote cannot be matched is removed. The slide is left without it (s3, s5). Nothing returns the failure reason to the writer.

**d. Headline form and storyline are not specified in the prompts.** `prompts/compose.md` asks for `intent` to be "what it must accomplish, not a topic label" and for the situation → complication → resolution order. `prompts/content.md` → "Headers" covers only that an asserting header must be cited. Neither states: that a headline is a full-sentence statement of the slide's point; when a section divider is appropriate; or how `narrative_role` values should progress. (Per-slot character budgets are given to the model in the prompt, and `content.md` → "Budgets are hard constraints" says to write to fit on the first pass; s5's three bullets still exceeded them.) `prompts/outline.md` was not re-read for this document.

**e. Mistral Small / Medium / Magistral return 429 with a limit of 0** on this account (section 1). Cause not determined.

## 5. Owner's stated position on model quality

The owner disagrees that slide quality should be attributed to the model. Position, as stated: **prompts must be detailed enough that basic quality is consistent across model classes.** The consequence for the open items: 4c and 4d are to be addressed in the prompts and in code checks that apply regardless of the model, and 4e is not a precondition.

## 6. Not yet established

- Which font LibreOffice actually substituted for Inter in the preview (the PDF's embedded fonts have not been inspected).
- Why negative-value bars are not drawn (renderer code and chart XML not examined).
- Whether the 3 bullets on s5 would pass the budget check if written at ≤88 characters (not tried).
- Why the overflow log reports the same 132-character figure for all three bullets.
- Output quality on any model other than `ministral-14b-2512` / `ministral-8b-2512`; no other model has been run.
- The `dev` (Gemini) and `dev-gemini` environments have not completed a draft-first run.
- Cost per draft run (not measured; token usage is available in provider responses).

## 7. State of the working tree

- Everything above is uncommitted on `v2/integration`, together with the earlier Phase 3c/3d work.
- `config/models.yaml` contains a local-only `dev-gemini` environment that was not to be committed (composer-role lines may be); `dev-mistral` is new and belongs with B51.
- Decisions added: B51 (Mistral `dev-mistral`), B52 (snap near-verbatim quotes). B49 and B50 remain provisional.
- `docs/handovers/README.md` indexes phase handovers only; this file is not listed there.
- `.env` line 6 (`MISTRAL_API_KEY`) now loads without error; the key value is not recorded here.
