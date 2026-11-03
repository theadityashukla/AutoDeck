# Agent session, memory, meeting recordings (part 1) — Handover

> Written 2026-11-04 to move the work from the owner's Mac to a remote environment. It
> covers Phase 4c (the deck agent session), the memory layer, and the first half of the
> meeting-recording feature. Read `README.md`, then this, then `DECISIONS.md` B71–B78.

---

## 1. Identification

| | |
|---|---|
| **Phase** | 4c (agent session) + memory + meeting Stage A |
| **Branch** | `v2/integration` (everything since `2ac1bec` was uncommitted until this push, including the earlier 4a/4b/design work in `CRAFT-4A-4B.md`) |
| **PR** | none yet |
| **Started / completed** | 2026-10-23 → 2026-11-04 (paused at plan step 9 of 13) |
| **Gate** | none; no gate may be altered by this work |
| **Gate status** | n/a |
| **Approved by / when** | The plan was approved by the owner on 2026-10-23. Two later owner decisions (2026-10-23): keep one-shot as the dev-mistral default with `--agent` opt-in, and test the agent on Claude later. |
| **What the owner actually checked** | Saw both live XLP5-agent runs compared with XLP4 (tables in §6). Supplied the 74-minute real recording and saw the timing and speaker-separation numbers; no transcript text was shown. They have not opened the Memory tab or the agent timeline in the UI themselves. |

## 2. What shipped

**Phase 4c, the deck agent session** (B71–B76):

| Path | What it does | Tests |
|---|---|---|
| `autodeck/agents/session.py` | The `converse` loop: tool dispatch, step and token caps, nudge then stall, `TranscriptLog` (JSONL), pure `compact()`, `timeline()` | `tests/test_session.py` |
| `autodeck/agents/workspace.py` | `DeckWorkspace`: the draft under construction, `deck_notes`, citable set (`shown_spans`/`shown_claims`), `cold_read`. `build()` = `compose.build_draft`. Saved to `workspace.json` | `tests/test_agent_tools.py`, `tests/test_subjectless_and_cold_read.py` |
| `autodeck/agents/tools/` | Closed tool vocabulary (B72): `registry.py` (ToolBox, repeat guard, error results), `deck.py`, `corpus.py`, `skills.py`, `advisor.py`, `memory.py` | as above, plus `tests/test_memory.py` |
| `autodeck/agents/advisor.py` + `prompts/advisor.md` | Fresh-context second reader on the new `advisor` role (B73) | `tests/test_deck_agent.py`, `tests/test_registry.py` |
| `autodeck/agents/corpus_map.py` | Deterministic corpus map for the opening context | `tests/test_agent_tools.py` |
| `autodeck/agents/deck_agent.py` + `prompts/agent.md` | `compose_deck_agent`, `resume_deck_agent` (reseeds when the transcript is over budget), system and opening message assembly, `SessionFiles` | `tests/test_deck_agent.py` |
| `autodeck/agents/compose.py` (end of `_build`) | Public aliases (`build_draft`, `drop_still_failing`, …) the agent reuses | existing compose tests |
| `autodeck/agents/draft_checks.py` | New advisory `subjectless_point` (B76) | `tests/test_subjectless_and_cold_read.py` |
| `autodeck/providers/registry.py`, `config/models.yaml` | The `advisor` role in every environment; refuses advisor == validation model | `tests/test_registry.py` |
| `autodeck/audit/manifest.py` | `session_record()` (session file, archive and memory hashes), `MANIFEST_VERSION = 2`; `git_state` ignores `clients/*/memory/**` | `tests/test_memory.py`, `tests/test_manifest.py` |
| `autodeck/cli.py` | `draft --agent/--no-agent --agent-steps`, falling back to one-shot on failure or under half the target slides; `revise` resumes the session automatically when one exists; `session/meta.json` | `tests/test_cli_draft.py` |
| `autodeck/ui/*` | "Let the agent build it (beta)" toggle, `GET /api/runs/<id>/session`, timeline rows, "Agent drafting/revising" labels, chat hint | `tests/test_ui_agent.py` |

**Memory** (B77):

| Path | What it does | Tests |
|---|---|---|
| `autodeck/knowledge/memory.py` | `MemoryStore`, with two scopes: engagement memory (`knowledge/clients/<c>/memory/<p>.md`, behind the A4 guard) and owner memory (`~/.autodeck/memory/owner.md`). Owner writes are refused on client or project names, engagement terms or people, 8-word copies of shown passages, and figures. Size caps, `audit.jsonl`, snapshots, and refusal of names that contain a path. | `tests/test_memory.py` |
| `autodeck/agents/tools/memory.py` | `remember` (`replaces`), `forget`, `read_memory`, `revise_memory` | `tests/test_memory.py` |
| `autodeck/cli.py` | `autodeck memory show / forget`; memory passed to the agent paths | `tests/test_memory.py` |
| `autodeck/ui/*`, `autodeck/ui/profile.py` | Settings → Memory tab, `GET`/`PUT /api/memory`, `owner_memory_path()` (`AUTODECK_OWNER_MEMORY`) | `tests/test_memory.py` |

**Meeting Stage A**, local transcription (B78):

| Path | What it does | Tests |
|---|---|---|
| `autodeck/meeting/` | `audio.py` (imageio-ffmpeg decode), `model_files.py` (pinned sha256, `~/.autodeck/models`, `AUTODECK_MODELS_DIR`), `asr.py` (Silero VAD + Parakeet), `diarize.py`, `transcribe.py`, `schema.py` | `tests/test_meeting_stage_a.py` (2 tests need the real models; they skip when the models are absent) |
| `autodeck/cli.py` | `autodeck meeting models [--download] [--speakers]`, `autodeck meeting transcribe RUN --audio F --client C --project P [--speakers] [--num-speakers N] [--threads N] [--runs-root]` | same |
| `tests/fixtures/meeting_clip.{m4a,txt}`, `make_meeting_clip.sh` | 45-second synthetic two-voice clip made with macOS `say`; the script includes "data bricks", "Shikha", "the sixteenth", "first week of February" | same |
| `pyproject.toml` | The `meeting` extra (`sherpa-onnx`, `sherpa-onnx-core`, `soundfile`, `numpy`, `imageio-ffmpeg`) and the `meeting` marker | — |

Full suite on 2026-10-24: **2000 passed, 52 deselected** (`uv run pytest -q -m 'not live and not render'`).

## 3. What did not ship

The plan is 13 steps; steps 1–8 are done. The plan file lives outside the repo, so its
remaining design is summarised here.

| Task | Why deferred | Now owned by |
|---|---|---|
| **Step 9 — transcript as a citable source, and meeting-only runs** | Started (nothing written) when the work moved | Next session. **Design:**<br>- `autodeck/ingest/transcript_source.py`, modelled on `conversation_source.py`: doc id `transcript--<slug>`, one page per segment, one `text` element per segment, `PAGE_BOX` bbox, **no times inside the Document** (A6).<br>- Sidecar `meeting/segments.json` mapping page → start, end, speaker.<br>- New `SourceClass` `"transcript"` and `TRANSCRIPT_DOC_PREFIX` in `ir/models.py` (~:69–76, ~:220). It is allowed in strict mode because it is a document.<br>- Labels: "from the meeting, mm:ss" in `audit/report.py` (~:1096) and `render/draft.py` (~:110).<br>- `run_source_hashes` (`cli.py`) also hashes `meeting/*.json`.<br>- Generalise `_redesign_planning` into `_run_source_planning`, driven by `runs/<run>/meeting/settings.json`. Wire it into `prepare_planning` (`pipeline/planning.py` ~:96, which refuses projects with no corpus) and into `validate` (`cli.py`, which exits 2 without a corpus).<br>- Pass engagement memory Terms to `validate` as context, so "APLD" in a claim is not flagged against a quote reading "APID".<br>- Decision **B79**. |
| **Step 10 — notes written by the agent** | Not started | Next session. **Design:**<br>- `agents/notes_workspace.py` `MeetingNotes`: Summary, Attendees, Themes, Decisions, Key dates (with precision), Action items ("Owner TBD"), Open questions/risks. Each item carries `cites: [{page, quote}]`, resolved through the same `_resolve_citation` path; a citation may span several turns.<br>- `render_notes()` writes `meeting/notes.md` and `notes.json` deterministically.<br>- Tools: `read_transcript`, `search_transcript`, `notes_set_section`, `notes_add_item`, `notes_edit_item`, `notes_remove_item`, `finish_notes`, plus `ask_advisor` (the cold read replaces any fixed verify call), `remember` and `load_skill`.<br>- Preload the whole transcript when it is under about 20k tokens.<br>- Skills `prompts/skills/meeting-notes.md` and `meeting-readout.md` (a storyline suggestion, not a template; a preset only for weak models). Opus writes these.<br>- Review: the person edits `notes.md` and "Apply my edits" sends the diff to the session; or they chat ("APID is APLD"). Chat goes to `revisions.jsonl` and to engagement memory.<br>- A per-environment `confidential_ok` flag in `models.yaml`; meeting commands refuse an unflagged environment.<br>- CLI `autodeck meeting notes RUN [--date] [--attendees]`.<br>- Decisions **B80**, **B81**. |
| Step 11 — deck from the same session | Not started | The same session continues with the deck tools; transcript pages it read are already citable. |
| Step 12 — meeting UI | Not started | Audio upload route (the current `_upload` caps at 50 MB and reads the whole body into memory, so it needs a chunked, ~500 MB audio route), `CHAINS["meeting"]`, notes editor plus chat, "Generate deck". |
| Step 13 — live check on the real recording | Needs steps 9–12, plus the recording, which exists only on the owner's Mac | Owner-supplied; see §9. |
| A properly tested agent on Claude | No `ANTHROPIC_API_KEY` | When a key exists: run `draft --agent --env sit` on the XLP request and compare with XLP4. |
| `revise --agent-steps` | Left out | Small follow-up. |

## 4. Decisions made this phase

- **B71**: `draft --agent`, a step-budgeted session through tools. It supersedes B45/B53 on that path only.
- **B72**: code execution is a closed, args-validated tool vocabulary.
- **B73**: the `advisor` role, fresh context, never the validation model.
- **B74**: session transcript, resume, deterministic compaction, and `session/` hashed in the manifest.
- **B75**: A1's citable set is every passage the session showed.
- **B76**: the advisor must read the whole deck cold before `finish`; every claim names its subject; the `subjectless_point` advisory.
- **B77**: agent memory: engagement memory under the client, owner memory in the home folder, checks on owner writes, snapshots.
- **B78**: local transcription with pinned models; diarization opt-in.
- **Next free id: B79.**

## 5. Invariant coverage delta

| Invariant | Before | After | Test that proves it |
|---|---|---|---|
| A1 citation | tested | tested; the agent's citable set is defined (B75) | `test_agent_tools.py` (a passage never shown gives `doc_not_shown`) |
| A2 numbers | tested | unchanged; `compute` is a dry run only | — |
| A3 validation | tested | unchanged; the advisor cannot share the validator's model | `test_registry.py::test_the_advisor_may_not_share_the_validation_model` |
| A4 isolation | tested | tested; memory sits behind `ClientNamespace`, names with paths are refused, owner writes are checked | `test_memory.py` |
| A5 framing | tested | unchanged | — |
| A6 reproducibility | partial | session, memory snapshots and transcript hashes recorded | `test_memory.py`, `test_deck_agent.py`, `test_session.py` (replay makes 0 new requests) |
| A7 gates | tested | unchanged; the agent approves nothing | — |
| A8 uncertainty | partial | unchanged | — |

## 6. Spike and experiment findings

**The agent on dev-mistral (`ministral-14b`) does not beat one-shot.** Same request as XLP4
(oral semaglutide, five slides, P&T committee, provenance `normal`):

| | XLP4 one-shot | XLP5-agent run 1 | XLP5-agent run 2 (after B76) |
|---|---|---|---|
| Calls / cost | 2 / ~$0.02 | 22, finished / ~$0.12 | 40, **hit the step cap** / ~$0.25 |
| Advisor calls | — | 0 | 2, and it acted on both |
| Verdicts (supported / partly / unsupported / contradicted) | 4 / 0 / 3 / 0 | 4 / 1 / 3 / 2 | 3 / 2 / 4 / 1 (+1 uncorroborated) |

- Run 1's contradictions were subjectless comparison points ("No fasting requirement" under
  "Subcutaneous"); one of them quoted an unrelated passage.
- Run 2 rewrote the comparison slide 14 times and ran out of steps.
- Conclusion: on a small model the turns cost money without adding accuracy. This matches
  the design-freedom-by-model-tier rule (free judgement is for Sonnet and above). The owner
  chose to keep `--agent` opt-in.

**Transcription is fast. Speaker separation is unusable on the real recording.** The real
file is 74 minutes (4,452 s), not the 20 the spec assumed:
- ASR: 2.6–3.9 min (RTF ~0.05), 352 segments.
- Diarization: ~10 min and 2.4 GB peak memory per run.
  - Automatic: 2 speakers, with 98% of the speech on one.
  - `--num-speakers 6`: 4 labels used, 89% on one.
  - In both runs, 18 segments got no label.
- Probably a voice memo of a call: remote voices arrive through one loudspeaker.
- Conclusion: diarization stays off by default, and the notes agent infers speakers from
  direct address.
- On the test clip the same stack gave 1.6% WER and 2 of 2 speakers. Its only errors,
  "Shikha" heard as "Shikta" and "data bricks", are exactly what engagement memory (Terms)
  exists to correct.

## 7. Known gaps, risks, and debt carried forward

| Item | Impact if ignored | Owned by |
|---|---|---|
| The agent's quality on Claude is unknown | `--agent` may never earn the default | Next session with an Anthropic key |
| `cli.py` has 2 pre-existing E501 lines and `ruff format` hunks | Lint noise | Any cleanup pass |
| Owner-memory checks are heuristics: a client fact phrased without names or figures can pass | A4 leak through owner memory | Accepted as a backstop (B77); the prompt rule is primary |
| `subjectless_point` misses synonyms ("injection" under "Subcutaneous") | A false advisory, never a block | Accepted (advisory only) |
| The meeting UI upload must not reuse the 50 MB `_upload` | Large audio files fail | Step 12 |
| The deferred test layers (provider schema conformance, live contract, etc.) | See the earlier `CRAFT-4A-4B.md` | Unchanged |

## 8. Model routing: planned vs actual

| Task | Planned tier | Actual tier | Why it differed |
|---|---|---|---|
| Prompts (`agent.md`, `advisor.md`, skills edits), `workspace.py`, `deck_agent.py`, `knowledge/memory.py`, the manifest, DECISIONS, this handover | Opus | Opus | — |
| Session loop, tools, corpus map, CLI and UI wiring, Stage A package, all tests | Sonnet | Sonnet | — |
| Fixture regeneration, renames | Haiku | not used | Folded into Sonnet tasks |

The owner's routing rule still applies: Opus only for `prompts/`, `autodeck/ir/`,
`autodeck/audit/`, `DECISIONS.md` and `docs/handovers/`. Sonnet does implementation
against settled interfaces and tests; Haiku does mechanical edits. Prompt changes go in
their own commit, with the rationale in the body.

## 9. Preconditions for the next phase

- **Environment:**
  - `uv sync --extra meeting --extra ui`. Syncing one extra alone removes the other's
    packages.
  - `autodeck meeting models --download` (~480 MB; add `--speakers` for another ~34 MB).
    The models live in `~/.autodeck/models`, or wherever `AUTODECK_MODELS_DIR` points.
  - Without them, the two `meeting`-marked tests skip and everything else runs.
- **Secrets:** `MISTRAL_API_KEY` is needed for any live run (dev-mistral is the default
  environment). Set it as an environment secret, never in the repo; `.env` is gitignored.
  `ANTHROPIC_API_KEY` is needed for `sit`/`prod` and the planned Claude agent test.
- **Data that is NOT in the repo:**
  - The test projects `oral-semaglutide`, `transformer-attention` and `lejepa-ssl`, the
    `pharma-demo` client, `corpus/` and `runs/` (including XLP4 and XLP5-agent). The owner
    keeps them out via `.git/info/exclude`.
  - `0. Input Data/`, the three public papers, also left out of the commit.
  - In a fresh checkout only `llm-inference-efficiency` (papers tracked) and the
    `contoso-health` / `northwind-retail` clients exist. A live run there needs
    `autodeck knowledge ingest llm-inference-efficiency` first (Docling; heavy).
- **The real 74-minute recording** is client-confidential and stays on the owner's Mac,
  along with its transcripts. Step 13 must run there, or the owner uploads the recording
  to the remote environment themselves. Never commit it.
- **Owner preferences to carry** (they were in local memory, not the repo):
  - "Too much harness, very little agent": judgement belongs to the agent plus skills;
    fixed LLM stages are rejected.
  - No fixed templates for Sonnet and above; presets only for weak models.
  - Finish one step before starting the next.
  - The owner will not hand-maintain a glossary; the agent's memory fills it.
  - The test budget is the $10/month Mistral allowance.

## 10. Verifying this phase from a cold start

```bash
uv sync --extra meeting --extra ui
uv run pytest -q -m 'not live and not render'
# expected: 1998 passed, 2 skipped (the two `meeting` model tests), 52 deselected —
# or 2000 passed after downloading the models:
uv run autodeck meeting models --download --speakers
uv run pytest -q tests/test_meeting_stage_a.py
# expected: 14 passed
uv run autodeck meeting transcribe CLIP --audio tests/fixtures/meeting_clip.m4a \
  --client contoso-health --project llm-inference-efficiency --runs-root /tmp/mt
# expected: Duration: 44.9s  Segments: 9 ; Real-time factor below 0.2 ; no transcript text printed
uv run autodeck draft --help | grep -- --agent
# expected: the --agent / --no-agent option is listed
```

## 11. Reading notes for the next implementer

- **Read first:** `prompts/agent.md`, then `autodeck/agents/deck_agent.py`. Everything the
  agent sees is assembled there, and every tool is listed in `make_toolbox`.
- **The workspace never decides content.** Every check is `compose.build_draft`, the same
  code a one-shot draft runs. Do not add a second resolver.
- **Cold-read gate:** `finish` holding back until `ask_advisor` covers every slide is
  deliberate (B76), not a bug. Scripted tests must include an `ask_advisor` turn.
- **Memory is not a Document.** If you are tempted to let the agent cite a memory line,
  stop: A1.
- **Step 9 begins in `ir/models.py`** with the source-class literal and the doc-id prefix
  (Opus path). Then `ingest/transcript_source.py`, written next to `conversation_source.py`.
- **Two meeting naming conflicts in the original spec are resolved:** the glossary is
  engagement memory Terms (no `~/.autodeck/glossary.yaml`), and verification is the
  advisor's cold read (no fixed verify call).
- **The owner usually wants:** a short plan, decisions recorded, the build verified
  before reporting, and honest negative results.
