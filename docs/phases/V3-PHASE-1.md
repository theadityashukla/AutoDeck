# v3 Phase 1 — Conversation core

**Branch:** `claude/autodeck-principles-review-zp7nsm` · **Source:** `docs/AUTODECK_V3_PLAN.md`
P2, P3, P6, P7, V3, V4, V5, V8, V9, §4, §5, §8, §12 Phase 1

> **Done when:** the owner builds a short deck over two separate threads, and the second
> thread picks up correctly with no transcript.
>
> The exit test is `tests/studio/test_phase1_done.py`. With the scripted model and the real
> knowledge pair `northwind-retail` / `llm-inference-efficiency`, thread one builds a
> three-slide deck, offers two openings (the owner dismisses them) and answers a question.
> Thread two is opened fresh. The test asserts that the model's first message in thread two
> is exactly the context built from state plus the recap request; that this context equals
> `build_context(engagement)` and does not change when thread one's `messages.jsonl` is
> removed; that it carries the deck, its change history and the dismissed proposal; that it
> carries none of thread one's replies or of the owner's messages that changed nothing.
> Thread two then changes slide 2 and undoes it, and `current.json` is byte-identical to
> before. The `render` version draws the first draft with LibreOffice.

## How to use this document

The scaffold is written: the Phase 1 contracts in full (`conversation.py`, `tool_args.py`,
the models in `bindings.py`, `TurnLedger` in `tools.py`), the scripted model
(`scripted.py`), the prompt assembly (`prompt.py`) and the lead's prompt
(`prompts/studio/lead.md`), the path helpers (`paths.py` additions), every other public
function as a signature, type hints and a docstring with a `NotImplementedError` body, the
acceptance tests, a prepared script, and the front-end contract below. Each task fills in
the bodies of the files it owns until its tests pass. Tasks own disjoint files.

Rules for every implementer (Phase 0's, plus the Phase 1 lead files):

- Implement only the files your task owns. The docstrings are the spec; if one is wrong or
  ambiguous, stop and report it rather than guessing.
- Lead-owned, do not edit: `models.py`, `errors.py`, `paths.py`, `conversation.py`,
  `tool_args.py`, `scripted.py`, `prompt.py`, the models and constants at the top of
  `bindings.py`, `TurnLedger` and the constants at the top of `tools.py`,
  `prompts/studio/lead.md`, `config/studio.yaml`, `tests/studio/helpers.py`,
  `tests/studio/conftest.py`, `tests/studio/fixtures/`. Do not change a signature.
- Do not modify any v2 file (`autodeck/` outside `studio/`, `config/models.yaml`, v2
  prompts, v2 tests). Import from v2; never copy it.
- Do not edit your tests to make them pass. If a test is demonstrably wrong, report it.
- Checks before handing back: `uv run ruff check` and `uv run ruff format --check` on your
  files, `uv run pyright autodeck/studio`, and your task's tests. A test that still fails
  must fail only with `NotImplementedError` from *another* task's file.

Running the tests: `uv run pytest -q -p no:cacheprovider tests/studio` (default) and
`uv run pytest -q -p no:cacheprovider -m render tests/studio` (LibreOffice). Tests that run
`write_slide` or the layout check need the Carlito font and skip without it.

## Tasks

| id | Wave | Model | Files owned | What to implement | Proven by | Depends on |
|---|---|---|---|---|---|---|
| 1.1 | 1 | haiku | `autodeck/studio/bindings.py` (the four functions) | Load `config/studio.yaml`, resolve env and role, token path, bind a v2 provider with a response cache | `tests/studio/test_bindings.py` | none |
| 1.2 | 1 | haiku | `autodeck/studio/edits.py` (the Phase 1 functions below the marker) | `set_brief`, `set_storyline` (id assignment, dropped links), `set_design_concept`, `upsert_slide`, `remove_slide`, `set_part_marker`, `apply_candidate_slides` | `tests/studio/test_edits_phase1.py` (and `test_edits.py` still green) | none |
| 1.3 | 1 | sonnet | `autodeck/studio/views.py` | `flat`, `clip`, the exact `deck_outline` and `change_line` text, and every JSON view for the API | `tests/studio/test_views.py` | none |
| 1.4 | 1 | haiku | `autodeck/studio/threads.py` | `ThreadStore`: ids, create (context then record), load with isolation, list, append-only JSONL with seq checks, turn ids | `tests/studio/test_threads.py` | none |
| 1.5 | 1 | haiku | `autodeck/studio/proposals.py` | `ProposalStore`: ids, create, load, list, resolve exactly once | `tests/studio/test_proposals.py` | none |
| 1.6 | 1 | sonnet | `autodeck/studio/events.py` | `EventBus` and `Subscription`: global ids, per-channel ring buffer, replay, blocking get, close | `tests/studio/test_events.py` | none |
| 1.7 | 1 | sonnet | `autodeck/studio/sources.py` | `SourceLibrary`: knowledge files and ingested documents behind the guard, read windows/outline/page, mixed search | `tests/studio/test_sources.py` | 1.3 (`views.clip`) for the tests to pass |
| 1.8 | 1 | sonnet | `autodeck/studio/loop.py` | `build_model_messages` (merging, notes, interrupted calls) and `run_steps` (reply ends the turn, caps, nudge, events from the ledger) | `tests/studio/test_loop.py` | none |
| 1.9 | 2 | sonnet | `autodeck/studio/context.py` | `gather_inputs` over v2's assembler and memory store, `render_context` byte-exact, `open_items`, `is_returning`, `build_context` | `tests/studio/test_context.py` | 1.3, 1.5 |
| 1.10 | 2 | sonnet | `autodeck/studio/tools.py` (everything below `TurnLedger`) | `instruction_line`, `guarded`, `resolve_artifact`, `apply_edit`, `qa_text`, `change_text`, and the 19 tools in `build_toolbox` | `tests/studio/test_tools.py` | 1.2, 1.3, 1.5, 1.7 |
| 1.11 | 2 | sonnet | `autodeck/studio/previews.py` | Render per deck state (digest dirs, temp + rename, reuse, prune), worker thread with coalescing, proposal previews, LibreOffice renderer | `tests/studio/test_previews.py` | 1.5, 1.6 |
| 1.12 | 3 | sonnet | `autodeck/studio/session.py` | `Studio`: engagement access, threads from state, the turn in its fixed order, async turns with the per-engagement lock, pick, dismiss, owner undo/redo, render requests | `tests/studio/test_session.py`, `tests/studio/test_phase1_done.py` | 1.3–1.11 |
| 1.13 | 4 | sonnet | `autodeck/studio/api.py` | `StudioApp.handle` for every route in the contract, body validation, error mapping, `subscribe`, images from manifests | `tests/studio/test_api.py` | 1.12 |
| 1.14 | 4 | sonnet | `autodeck/studio/server.py`, `autodeck/studio/__main__.py` | HTTP plumbing (host check, JSON-only POST, size limit, security headers, static files, SSE with pings and Last-Event-ID), entry point | `tests/studio/test_server.py` | 1.13 |
| 1.15 | 1–4 | sonnet | `autodeck/studio/static/index.html`, `app.css`, `app.js` | The front end, from the contract below only (it can start at once against the contract and the scripted server) | the lead, in a browser (task 1.16) | the contract; 1.14 to run it |
| 1.16 | 5 | lead | none (verification) | Both test modes, the full v2 suite, a browser walk-through on the scripted server, viewing the PNGs, a first run on `dev-mistral` if a key is available | `tests/studio/test_phase1_done.py` | 1.1–1.15 |

Waves: **wave 1** (1.1–1.8) needs no other task's body; 1.7's tests also need 1.3's two
small helpers, so start both at once. **Wave 2** (1.9–1.11) once its dependencies are
merged. **Wave 3** is the session, which wires everything. **Wave 4** is the API and the
server. The front end (1.15) works only from the contract, so it can run from wave 1 and is
integrated in wave 4. **Wave 5** is the lead's verification.

Why the tags: 1.1, 1.2, 1.4 and 1.5 are short, mechanical and pinned line by line by their
docstrings and tests. 1.3 and 1.9 produce text that is tested byte for byte. 1.6 and 1.11
are concurrent code. 1.7 is the client guard on sources (A4). 1.8, 1.10 and 1.12 are where
the conversation's behaviour lives. 1.13 and 1.14 are the isolation and security boundary
of the interface. 1.15 is product surface.

## Design choices

**A thread is a log, and nothing reads it but its own thread.** Under
`<engagement>/threads/<id>/`: `thread.json` (written once), `context.md` (the exact opening
context, its digest on the record) and `messages.jsonl` (one `ThreadLine` per line,
append-only, `seq` = line number). The interface displays it and the same thread rebuilds
its model conversation from it (so a server restart resumes a thread). `context.py` never
touches it; a test removes it and rebuilds the context to the same bytes, and another
checks the module's source. That is the code behind P2.

**The opening context is built from state, as plan §5.1 lists, and is a pure function.**
`gather_inputs` reads: the curated knowledge through v2's `assemble_context` (so v2's
loader and namespace guard apply), both memory files through v2's `MemoryStore` (read
only: nothing is added and no audit line is written), each artifact and its whole change
log, and every proposal. `render_context` turns those into markdown whose format is
specified to the byte (`test_context.py` has a golden copy): the engagement and its
knowledge, memory, each deck's compact outline (`views.deck_outline`, the same text the
`view_deck` tool returns), the last 15 change-log entries newest first with up to three
diff lines each (undone entries included: that is what was rejected), proposals grouped
Dismissed / Accepted / Open, and the provisional, stale and open items. `claims.md` and
other knowledge files are not inlined; they are sources the lead reads with tools.

**What "no transcript" means, exactly.** A change-log entry records "the instruction that
caused it, in a sentence" (plan §4), and Phase 1 records the owner's message as that
instruction. So an owner message that changed the deck reaches later threads, as state,
on the entries it caused. Everything else from a thread (the model's replies, tool output,
the owner's messages that changed nothing) is gone when the thread ends. The exit test
asserts exactly this.

**The recap is the model's, from that context.** A thread opens `returning` when the
engagement has an artifact or a proposal. Its first turn then runs at once with the fixed
request `prompt.RECAP_REQUEST`; the model's first message is the context and the request,
merged into one user message. A fresh thread runs nothing until the owner speaks; its
first message is the context and the owner's words. The interface hides the context and
recap lines.

**Proposals are a small record on disk.** `<engagement>/proposals/<id>/proposal.json`:
what is being decided, the options (label, text, optional candidate slides and where new
ones go), and a status set once (`accepted` with the option, or `dismissed`), with who
resolved it (`owner` by button, `chat` when the model applied an option the owner chose in
words) and when. That is the smallest record that lets the next thread know what was
rejected. Candidate slides must have a layout and pass the layout check before a proposal
is recorded, so the owner never sees a placeholder as an option. Picking an option with the
button resolves it and sends `I pick option B of p0003: <label>.` into the conversation;
the model then applies it (`apply_option` copies the candidate slides in as one change).
Dismissing records it and leaves a note for the model's next turn.

**Owner actions between turns become notes.** A dismissal, or an undo/redo from the
Changes tab with a thread open, appends a `NoteLine` to that thread. At the next turn the
note is merged into the front of the owner's message as `[Note: ...]`, so the model knows
the deck moved without it.

**A turn ends on a text reply.** The loop is new (v2's ends on `finish` and treats text as
a stall). It keeps v2's step and token caps, v2's pure compaction of old tool results, and
v2's `ToolBox` (closed vocabulary, pydantic argument models, bad calls returned as error
results). Because v2's `ToolBox` converts only its own error types, every studio tool runs
inside `tools.guarded`, which converts the studio's expected refusals (and v2's
`ClientIsolationError`, reported with a fixed sentence that names nothing) into
`ToolError`. An unexpected exception still ends the turn, with `stop_reason="error"` and
the message on the turn's last line and event. A model call with neither text nor a tool
call is nudged once, then the turn stops as `stalled`.

**Every turn is classified by what its tools did.** `conversation.classify_turn`: any
change-log entry recorded, undone or redone, or an artifact created → `change`; else any
proposal → `proposal`; else `talk`. `TurnEndLine` and `TurnFinished` validate their kind
against their lists, so a mislabelled turn cannot be written.

**Every edit goes through `ArtifactStore.apply`, with layer and model (V4, V5).** Phase 1
has one model, but each editing tool records its layer (`tools.TOOL_LAYERS`: brief,
storyline, concept, markers and slide order are `direction`; writing slides and text and
applying options are `composition`) and the bound model's id (`provider/model`, or the
script's id). The loop takes a `BoundModel` (role, model id, model), and the session reads
`Studio.lead` at the start of each turn, so Phase 2 routes a call by passing a different
binding, not by rewriting the loop.

**The tool vocabulary (19 tools).** Read the deck (`view_deck`, `view_slide`), read
sources (`list_sources`, `read_source`, `search_sources`), edit (`create_deck`, `set_brief`,
`set_storyline`, `set_design_concept`, `write_slide`, `set_block_text`, `remove_slide`,
`move_slide`, `set_marker`), propose (`propose`, `apply_option`), undo (`undo`, `redo`),
and `load_skill`. Two additions to the lead's list: `set_marker`, because "I like slide 3"
must be able to make a part `decided` without rewriting it; and `apply_option`, so a picked
option's candidate slides go in exactly as previewed. `write_slide` takes the whole slide
(blocks and free layout) and answers with the layout check, so the model fixes overflow at
once; the IR is unchanged, and Phase 2 splits the tool (plan §6.2). `create_deck` is
refused when the engagement already has an artifact. Deck tools default to the
engagement's only deck.

**Sources: knowledge always, documents where they exist, no v2 change.** Knowledge files
are every `*.md` under the client and project knowledge folders except the client's
`memory/` (memory is context, not a source). Documents are those in v2's `DocumentStore` at
`<corpus_root>/<project>` (v2's location); search over them uses v2's `build_index` and
`search` in memory, BM25 only (no embedder: D2), with the index refused unless it is
tagged for this project and no other client, as v2's `use_index` checks. Knowledge search
is a small, deterministic term-overlap score over paragraphs. Every path passes the
engagement guard; a source id is parsed and must be one the listing produced, so `..`,
absolute paths and memory files are unknown by construction, and a symlink into another
client's folder is refused without saying what it points to. Retrieval wiring therefore
did not need any v2 change, and is in scope.

**Bindings live in the studio's own file.** `config/studio.yaml` binds the role `lead` per
environment, reusing ids already pinned in `config/models.yaml`: `dev-mistral` uses
`mistral/ministral-14b-2512` (v2's composer and advisor, its tool-calling conversational
roles), `sit` and `prod` use `claude/claude-opus-5` (v2's planner and outline, the lead
tier of plan §6.1). Resolution goes through v2's `PROVIDERS`, `api_key_env` and
`ResponseCache` (cache under `<workspace>/llm_cache/`). The file also names the token file
the studio renders with (`config/tokens/dev.json`) until the design system exists.

**The scripted model.** `scripted.ScriptedModel` implements `converse` and plays back a
script's steps, recording every call for assertions. The server runs on one with
`--script PATH` or `AUTODECK_STUDIO_SCRIPT`. `tests/studio/fixtures/scripts/two_threads.json`
is the walk-through the exit test uses (16 steps, model id `scripted/two-threads`), built
from the Phase 0 fixture's layouts so every slide passes the layout check.

**Previews: one render per deck state, in the background.** A render lives in
`renders/<first 12 hex of the state digest>/` with `render.json` written last, built in a
temporary directory and renamed into place. A state rendered once is reused (an undo back
to it needs no LibreOffice run); six renders per artifact are kept. Renders run on one
worker thread, coalescing repeated requests, after the turn's `turn_finished`; each sends
`previews_ready`. Image URLs carry the digest, so a browser never shows a stale image. A
slide with no layout or a failing layout is the placeholder Phase 0 already draws.

**The interface is local, dependency-light, no build step.** Standard-library
`ThreadingHTTPServer` on 127.0.0.1, refusing any non-localhost `Host` (as v2's UI server
does), POSTs JSON-only (no CORS ever granted), a strict CSP (no inline script or style, no
external resource), plain HTML/CSS/JS served from `autodeck/studio/static/`. Streaming is
Server-Sent Events at event granularity: the provider layer returns whole turns, so tokens
are not streamed. `api.py` is socket-free (tested directly); `server.py` is the plumbing.
Entry point `python -m autodeck.studio`; v2's `cli.py` is untouched.

**One turn at a time per engagement.** Phase 0's store assumes one writer, and several
threads on one artifact is Phase 4. A per-engagement lock is taken without blocking by
every operation that changes state; a second one gets `409 turn_in_progress`.

**Client isolation on every route (A4, V9).** Every route that names an engagement opens
it with `open_engagement` first; threads, artifacts and proposals are looked up through
that engagement's own stores, so another client's id is simply not found; percent-decoded
path segments are validated before use; a directory that resolves into another client's
tree is `403 isolation` with a fixed message. `test_api.py` covers ids from another client,
encoded traversal, and symlinked thread and artifact directories. This also closes two of
the Phase 0 carried items for the new trees (symlinked thread directories, symlinked
knowledge files in listings).

## Skills the base allows

`prompt.ALLOWED_SKILLS = ("storyline", "slide-design", "writing-style")`; `load_skill`
refuses every other name and the system prompt indexes only these.

| Skill | Decision | Why |
|---|---|---|
| `storyline` | **Allowed** | The argument: governing thought, answer-first or question-led, the ghost deck, opening and close. Craft that holds for any deck. Its mentions of `narrative_role` and the draft's `notes` are mapped by the prompt (role goes in the intent; notes go in the reply). |
| `slide-design` | **Allowed** | Designing a slide inside the master with a free layout: one system, restraint, one focal point, layout patterns. Exactly the Phase 1 job, since `write_slide` takes the layout. |
| `writing-style` | **Allowed** | Plain slide prose, machine tics to cut, one name per concept, numbers in text. Its two "cited" phrases read as "from the source" under the prompt's rule. |
| `deck-thinking` | Refused | Its core is the claim-and-quote model ("the citation is the proof") and the strict working order with the advisor and `finish`. |
| `headlines` | Refused | Rule 3 requires every fact in a headline to be carried by a cited block on the slide; it teaches citation mechanics as a headline rule. |
| `slide-bodies` | Refused | Built around the component catalog and "cited block beneath every headline". |
| `charts-and-diagrams` | Refused | Valuable chart honesty, but its formats are v2's claim/citation JSON (`source_citations`, diagram nodes typed as claims), and diagrams are out of the base. Revisit when the base has a chart skill of its own. |
| `fidelity` | Refused | Written as rules for claims against their quoted passages. The lead prompt keeps its substance in two lines ("say what the source says at the strength it says it"). |
| `citations`, `from-source-to-slide`, `exemplars`, `self-review`, `reworking-decks` | Refused | Citation mechanics, the sentence-vs-quote model, gold decks graded by citation, a citation checklist, and verbatim-citation rules for lifted slides: all strict-mode (P3, V8). |
| `visual-review` | Refused | For reading rendered slides; the Phase 1 lead does not see renders (the reviewer that does is Phase 3). |
| `meeting-notes`, `meeting-readout` | Refused | Notes and transcripts are Phase 5, and both require citing transcript turns. |

## Front-end contract

Everything the front end (task 1.15) needs. The server's code is not required reading.

### Conventions

- All API paths start with `/api/`. `E` below means
  `/api/engagements/<client>/<project>` (segments percent-encoded by the client with
  `encodeURIComponent`).
- Requests with a body are `POST` with `Content-Type: application/json` and a JSON object.
  Anything else is refused (415 / 400). There are no PUT, PATCH or DELETE routes.
- Times are ISO 8601 strings with seconds and an offset (`2026-11-13T09:05:00+00:00`).
- Every error is `{"error": {"code": "<code>", "message": "<one sentence for the owner>"}}`
  with the status below. Show `message` in a toast; never show a stack.

| Code | Status | When |
|---|---|---|
| `bad_request` | 400 | malformed body, missing/unknown/mistyped field, invalid id or path segment, blank or over-long message |
| `isolation` | 403 | the request reached another client's data (message: "That belongs to another client's engagement.") |
| `forbidden_host` | 403 | the `Host` header is not localhost |
| `not_found` | 404 | unknown route, engagement, thread, artifact, proposal, render or image |
| `knowledge_not_found` | 404 | the client or project knowledge folder is missing |
| `method_not_allowed` | 405 | known path, wrong method |
| `conflict` | 409 | engagement (or artifact) already exists |
| `turn_in_progress` | 409 | a turn is running in this engagement; try again when it finishes |
| `nothing_to_undo`, `nothing_to_redo` | 409 | as named |
| `proposal_resolved` | 409 | the proposal is no longer open, or the option does not exist |
| `payload_too_large` | 413 | body over 64 KiB |
| `unsupported_media_type` | 415 | POST that is not `application/json` |
| `internal` | 500 | a bug; message is `"<Type>: <message>"` |

### Shapes

- **EngagementView** `{client, project, title, created_at}`.
- **ArtifactSummary** `{id, kind: "deck", title, slide_count, head: entry id | null,
  entries: int, updated_at: time | null}`.
- **ArtifactView** = ArtifactSummary + `{deck: <the DeckArtifact JSON, see models.py>,
  can_undo, can_redo, render: RenderView | null}`. `render` is the render of the *current*
  state, or null while it is being made.
- **RenderView** `{digest, rendered: bool, note, placeholders: {slide id: reason},
  slide_ids: [..], images: [url per slide, in slide order] }` (`images` is `[]` when not
  rendered; then show a placeholder per slide with `note`).
- **ChangeView** `{id, parent_id, live: bool, layer, model_id, thread_id, instruction,
  created_at, lines: [diff line], truncated: bool, is_head, can_undo, can_redo}`;
  **ChangesView** `{artifact_id, head, can_undo, can_redo, entries: [ChangeView, newest
  first]}`.
- **ThreadSummary** `{id, title, created_at, opening: "fresh" | "returning", model_id,
  turns: int, last_activity, preview: first owner message, clipped}`.
- **MessageView**, one of:
  - `{type: "user", turn_id, origin: "owner" | "choice", text, created_at}`;
  - `{type: "assistant", turn_id, texts: [str], tools: [{name, summary, error}], model_id,
    kind: "talk" | "proposal" | "change" | null, stop_reason | null, error, change_ids,
    undone_ids, redone_ids, created_artifacts, proposal_ids, created_at}` (`kind` null while
    the turn is running);
  - `{type: "note", note: "proposal_dismissed" | "owner_undo" | "owner_redo", ref, text,
    created_at}`.
- **ProposalView** `{id, thread_id, turn_id, artifact_id, summary, status: "open" |
  "accepted" | "dismissed", chosen, resolved_by, resolved_at, created_at, options: [{id:
  "A".."D", label, text, slide_ids, insert_at, previews: [image url]}]}`.
- **SourceView** `{id, kind: "knowledge" | "document", title, detail}`.

### Routes

| Method and path | Body | Success |
|---|---|---|
| `GET /api/health` | | 200 `{ok: true, model_id, env, scripted}` |
| `GET /api/engagements` | | 200 `{engagements: [EngagementView + {error: str \| null}], knowledge: {clients: [..], projects: [..]}}` (an engagement that no longer opens is listed with `error`) |
| `POST /api/engagements` | `{client, project, title?}` | 201 `{engagement: EngagementView}` |
| `GET E` | | 200 `{engagement, artifacts: [ArtifactSummary], threads: [ThreadSummary], sources: [SourceView], proposals: [ProposalView], running_turn: "t0001/u0003" \| null}` (anything refused by the isolation guard is omitted) |
| `GET E/artifacts/<a>` | | 200 ArtifactView |
| `GET E/artifacts/<a>/changes` | | 200 ChangesView |
| `POST E/artifacts/<a>/undo` | `{thread_id?}` | 200 `{entry: ChangeView, changes: ChangesView}` |
| `POST E/artifacts/<a>/redo` | `{thread_id?}` | 200 as undo |
| `POST E/artifacts/<a>/render` | `{thread_id}` | 202 `{status: "queued"}`; a `previews_ready` follows on that thread's stream |
| `GET E/artifacts/<a>/renders/<digest>/<n>.png` | | 200 `image/png` (the URLs in RenderView) |
| `GET E/threads` | | 200 `{threads: [ThreadSummary]}` |
| `POST E/threads` | `{title?}` | 201 `{thread: ThreadSummary, recap_turn_id: str \| null}`; when not null the recap turn is already running |
| `GET E/threads/<t>` | | 200 `{thread: ThreadSummary, messages: [MessageView], running_turn}` |
| `POST E/threads/<t>/messages` | `{text}` (1..8000 chars, not blank) | 202 `{turn_id}`; the turn runs in the background |
| `GET E/threads/<t>/events` | | 200 `text/event-stream` (below) |
| `GET E/proposals/<p>` | | 200 ProposalView (with preview URLs) |
| `GET E/proposals/<p>/options/<o>/previews/<n>.png` | | 200 `image/png` |
| `POST E/proposals/<p>/pick` | `{option_id, thread_id}` | 202 `{turn_id, proposal: ProposalView}` |
| `POST E/proposals/<p>/dismiss` | `{thread_id}` | 200 `{proposal: ProposalView}` |

Undo and redo with a `thread_id` tell the model in that thread at its next turn and send
`change_reverted` then `previews_ready` on that thread's stream.

### The event stream

`GET E/threads/<t>/events` stays open. Each event is

```
id: <integer, increasing across the server>
event: <type>
data: <the event as compact JSON; it also carries "type">

```

plus `: ping` comment lines every 15 seconds. Use `EventSource`; on reconnect it sends
`Last-Event-ID` and the server replays what was missed (the last 512 events per thread).
Every event carries `thread_id`. Types and their other fields (`conversation.py`):

| Type | Fields | Meaning |
|---|---|---|
| `turn_started` | `turn_id, origin, text, model_id` | a turn began (`text` is "" for a recap) |
| `assistant_text` | `turn_id, step, text, model_id` | the model said something (may come before tool calls) |
| `tool_called` | `turn_id, step, call_id, name` | a tool is running |
| `tool_finished` | `turn_id, step, call_id, name, summary, error` | its one-line result |
| `artifact_created` | `turn_id, artifact_id` | a deck was created |
| `change_recorded` | `turn_id, artifact_id, entry_id, instruction, layer, model_id, lines, truncated` | the deck changed |
| `change_reverted` | `turn_id \| null, artifact_id, entry_id, action: "undo" \| "redo", by: "model" \| "owner"` | an entry was undone or redone |
| `proposal_created` | `turn_id, proposal_id, artifact_id, summary, option_ids` | options were offered |
| `proposal_resolved` | `proposal_id, status, chosen, by` | picked or dismissed |
| `turn_finished` | `turn_id, turn_kind, stop_reason, model_id, steps, change_ids, undone_ids, redone_ids, created_artifacts, proposal_ids, input_tokens, output_tokens, error` | the turn ended (always sent, also on error) |
| `previews_ready` | `turn_id \| null, artifact_id, digest, slide_ids, rendered, note, placeholders` | new previews; image n is `E/artifacts/<artifact_id>/renders/<digest>/<n>.png` |
| `proposal_previews_ready` | `proposal_id, options: {option id: image count}, rendered, note` | candidate slides rendered; refetch the proposal |

Order within a turn: `turn_started`; then per model call an optional `assistant_text`
and, per tool call, `tool_called`, `tool_finished`, then that call's `artifact_created` /
`change_recorded` / `change_reverted` / `proposal_created`; then `turn_finished`; then,
later, `previews_ready` per changed deck and `proposal_previews_ready` per proposal with
candidate slides.

### Screens and behaviour

Hash routes, plain names: `#/` (engagements), `#/e/<client>/<project>` (engagement home),
`#/e/<client>/<project>/t/<thread>` (thread). Empty hash shows `#/`.

- **Top bar:** "AutoDeck"; the current engagement as "client · project" linking to its
  home; the model id from `/api/health`, and a quiet "Scripted" tag when `scripted`.
- **Engagements (`#/`):** the list from `GET /api/engagements` (an entry with `error` is
  shown disabled with the message). A small form to create one: client and project
  pickers filled from `knowledge`, optional title; 409 opens the existing one.
- **Engagement home:** three columns that stack below 900px: Sources (title and detail),
  Artifacts (title, slide count, last updated), Threads (title or preview, turns, last
  activity, newest first). A primary "New thread" button: `POST E/threads`, then go to the
  thread (and, if `recap_turn_id`, show the recap as it streams).
- **Thread view:** two panes; below 900px they become two tabs, "Chat" and "Deck".
  - *Conversation:* owner messages on one side; each assistant turn as one message with a
    label for its kind (**Talk**, **Proposal**, **Change**) and its model id, its texts as
    paragraphs, and its tool calls as a compact, collapsible activity list (name and
    summary; errors marked in text, not colour alone). While a turn runs, show it live from
    the stream ("Working", then each tool line as it arrives); on `turn_finished` refetch
    `GET E/threads/<t>` and render from it (the canonical record). A Change message lists
    its entries and links to the Changes tab. A turn that stopped for any reason other than
    `replied` says why in one quiet line. Notes appear as one muted line.
  - *Proposals:* a Proposal message shows its options as cards: label, text, the candidate
    slide previews (placeholders until `proposal_previews_ready`), "Use this" (pick) and,
    once per proposal, "Dismiss". After it is resolved, the cards show which option was
    chosen, or "Dismissed", and the buttons go.
  - *Composer:* a textarea; Enter sends, Shift+Enter adds a line; disabled while a turn
    runs in this engagement (and a 409 shows a toast). The context and recap request are
    never shown.
  - *Artifact panel,* tabs **Slides**, **Storyline**, **Changes**, for the engagement's
    deck (if there is more than one, a small picker):
    - Slides: a thumbnail strip and a large preview of the selected slide, both from
      `render.images`. Markers: `decided` shows nothing; `provisional` a dashed outline and
      a small "Provisional" tag; `stale` a desaturated slide and a "Stale" tag (tag text
      always present). With no render, or `rendered: false`, or a slide in `placeholders`,
      show a calm placeholder with the slide id and the reason. On `previews_ready` for
      this deck, swap the images (the digest changes, so caching is safe). When the thread
      opens and `render` is null, `POST .../render` once.
    - Storyline: the brief (audience, goal, notes), the storyline points in order with the
      slides that serve each, and the design concept, each with its marker tag.
    - Changes: `ChangesView`, newest first: instruction, layer and model, thread, time,
      diff lines collapsed. "Undo" on the entry with `can_undo`, "Redo" on the one with
      `can_redo` (both send this thread's id). Undone entries stay, struck through.
  - After `change_recorded`, `change_reverted` or `artifact_created`, refetch the
    artifact and its changes; briefly highlight the affected thumbnails.
- **Look:** follow the accepted mock-up (`mockups/v3/SPEC.md` §4.1,
  `mockups/v3/src/app.css`): light and calm, close to a native settings window, system
  fonts, one blue accent, cool greys, the deck as the lit object on a slightly darker
  stage. Every colour is a token on `:root`, redefined for dark mode under
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {...} }` and
  under `:root[data-theme="dark"]` (the tokens are already in `static/app.css`). No emoji,
  no gradients, inline SVG icons only. Visible focus states; honour
  `prefers-reduced-motion`; no horizontal page scroll down to 390px.
- **Rules from the CSP:** no inline `<script>` or `<style>`, no `style="..."` attributes in
  markup (set classes, or `element.style` from script), no external fonts or libraries,
  no `eval`. Wrap any `localStorage` use in try/catch. Build dialogs in the page; never
  `alert`, `confirm` or `prompt`.
- **Do not copy the mock-up's scripted logic.** It is a visual reference only.

## Deliberately left out of Phase 1

- **Routing, per-layer bindings, the manual override** (Phase 2). One role, `lead`. The
  layer and model are recorded anyway.
- **Propose-first, selection as scope, staleness, export confirmation, several threads on
  one artifact** (Phase 4). Editing is automatic; `stale` is never set; one turn at a time
  per engagement.
- **Undo from the middle of the history.** Undo and redo stay newest-first along the live
  chain (Phase 0's semantics). An undo in thread two can undo a change made in thread one;
  the tool's reply says which.
- **Memory writes.** Both memory files are read-only context. Taste notes are Phase 3.
- **Diagrams, figures with images, icons** in what the lead writes. Diagrams are not in
  the base IR; the prompt tells the lead not to use figure or icon blocks (no images, and
  no glyph ids it could know).
- **Notes artifacts, fact-check, design-system artifacts, the strict overlay** (Phases 3,
  5, 6).
- **Token streaming.** The provider layer returns whole turns; events stream at turn-step
  granularity.
- **The model seeing renders.** The lead reads the layout check, not images; a reviewer
  that reads renders is Phase 3.
- **Per-slide render caching and parallel rendering.** Whole deck, one LibreOffice run at
  a time; whole-state reuse only.
- **Export / PPTX download.** Phase 4's single confirmation.
- **Deleting or renaming threads, engagements or artifacts.**

## Risks found while scaffolding

1. **v2's `ToolBox` converts only its own error types.** Every studio tool must run
   through `tools.guarded`; a refusal type it misses ends the turn with an error instead of
   letting the model correct itself. The tests cover the main refusals; watch for others in
   the first real runs.
2. **The whole `Slide` schema is in `write_slide` and `propose`.** It is large (free layout
   elements are a discriminated union). v2's creative mode already sends the same schema,
   but a small model (dev-mistral) may still struggle with it; Phase 2's split exists for
   this. Measure on the first real run.
3. **Phase 1 runs every layer on the lead tier.** On `sit`/`prod` that is `claude-opus-5`
   for everything, which is the cost Phase 2 is meant to remove. Keep Phase 1 sessions on
   `dev-mistral` or the scripted model unless judging quality.
4. **The owner's instruction travels on the change log.** By design (plan §4), but it
   means the words of any message that changed the deck reach every later thread. If the
   owner pastes something sensitive into a message that edits the deck, it persists in the
   log. The "no transcript" guarantee is scoped to this in the exit test.
5. **Context growth.** Knowledge files (except `claims.md` and others read on demand) are
   inlined in full, and 15 changes per artifact are listed. Fine for the fixture pair;
   measure on a larger engagement.
6. **Owner memory defaults to the real home directory** (`~/.autodeck/memory/owner.md`,
   v2's default). The server reads it; tests always pass a temporary path.
7. **Background renders can finish out of order.** Each render reads the state current
   when it starts and announces its digest; the interface refetches the artifact view,
   whose `render` is always the current state's. A late event for an older state is
   harmless.
8. **The scripted server is one walk-through.** Its steps are consumed in order across
   every thread; a different click order (or a non-empty workspace) misaligns it. Use a
   fresh `--workspace` for each walk-through.
9. **Private v2 names.** Still `ir.store._diff` and `render.renderer._BLANK_LAYOUT`
   (Phase 0). Phase 1 adds no new private import; `tools.load_skill` uses v2's public
   `load_skill` (v2's own skill tool uses the private `_without_project`, which the studio
   does not need because none of the allowed skills has project-tagged sections).
10. **Symlinked `engagements/<client>` directories** (Phase 0 carried item) are still only
    caught by the path guard's resolution, as in Phase 0; the new trees (threads,
    proposals, sources) add their own guard calls and tests.

## How the lead verifies the phase (task 1.16)

1. `uv run pytest -q -p no:cacheprovider tests/studio` and the same with `-m render`: all
   green, no `NotImplementedError` left.
2. `uv run ruff check`, `uv run ruff format --check`, `uv run pyright autodeck/studio`.
3. The full default suite: v2's result unchanged (2286 passed and the one known font
   failure before Phase 1, plus the new studio tests).
4. A browser walk-through on the scripted model, with a fresh workspace:

   ```
   uv run python -m autodeck.studio \
       --script tests/studio/fixtures/scripts/two_threads.json \
       --workspace /tmp/studio-walkthrough
   ```

   Open `http://127.0.0.1:8765/`. Create the engagement `northwind-retail` /
   `llm-inference-efficiency`. Start a thread and send three messages (the words do not
   matter to the script): the first builds three slides (a Change, previews appear); the
   second offers two openings (a Proposal; dismiss it with the button); the third is a
   Talk. Go back to the engagement and start a new thread: the recap appears by itself and
   mentions the dismissed openings. Send two more messages: slide 2 changes to 38%, then
   the change is undone. Check the Changes tab (undo and redo from the buttons), the
   Storyline tab, the markers, both themes, and widths 1280, 900 and 390px.
5. Look at the rendered PNGs under `/tmp/studio-walkthrough/engagements/.../renders/`.
6. If a `MISTRAL_API_KEY` is available, one short real session on `dev-mistral`
   (`uv run python -m autodeck.studio --env dev-mistral --workspace /tmp/studio-live`),
   noting where the model struggles with the tools; record it below.

## Result (task 1.16)

Verified by the lead on 2026-11-13, on the build container, with the scripted model.

**What passes**

- **Studio tests:** 342 in the default selection, and the 7 `render`-marked tests with
  LibreOffice. No skeleton body remains. Ruff and pyright are clean on the studio code.
- **v2 unchanged:** no v2 file was edited. Full default suite: 2474 passed, 1 failed (the
  known `tests/test_design.py::test_a_missing_face_is_as_loud_as_a_missing_family`).
- **Browser walk-through on the real server** (`--script two_threads.json`, fresh
  workspace), driven with Playwright and viewed: create the engagement; thread one builds
  three slides (Change, previews appear), offers two openings (Proposal with a rendered
  candidate, dismissed), answers a question (Talk); thread two opens with a recap by
  itself, changes slide 2, and undoes it; Changes tab undo and redo; Storyline tab; dark
  theme; 390px width with no horizontal scroll. No console errors, no server errors.
- **No transcript carried over:** the recap in thread two named the three slides, the
  provisional storyline and the dismissed openings, all from state. `test_phase1_done.py`
  pins that thread two's opening context equals `build_context` computed from disk and
  contains none of thread one's replies or tool output.

**Found and fixed during verification**

- The Changes tab and Change messages led with the owner's instruction, so several changes
  from one message were indistinguishable. They now lead with what changed.
- Threads were all titled "New thread"; they now take their first owner message.
- The thread view did not fill the window height.
- A read of an artifact landing between the store's file writes raised
  `ChangeLogIntegrityError` (a 500 in the interface). `ArtifactStore` operations now
  exclude each other per artifact within the process; a test reproduces the race.

**Not verified**

- **No run against a real model.** The build container has no provider key. How well a
  model drives the 19 tools is unknown, in particular writing a whole slide (text, blocks
  and coordinates that pass layout QA) in one call, which the tools implementer expects
  small models to fail often. This is step 6 of the checklist and needs the owner's
  machine.

**Carried forward**

- A turn that fails before it starts (for example a corrupt thread log) is only printed on
  the server; the interface is never told the turn ended.
- `api.py` and `context.py` read the deck and its change log as two calls; a write between
  them can pair a deck with a slightly newer log (an inconsistent view, not an error).
- A failed preview for a deck state (LibreOffice missing) is stored and not retried until
  the deck changes.
- Proposal candidates that share a slide id with each other replace one another silently.
- Error types `guarded` does not convert (for example v2's `KnowledgeError` during a source
  read) end the turn instead of letting the model correct itself.
- Project-tier knowledge and documents are shared across clients by design (D8); the
  source tools cannot tell where a project document came from.
- Everything on Phase 0's carried list except the store's lack of in-process locking.

### First real-model run (2026-11-14)

One session on `dev-openai` (`gpt-5.4-mini`, added to `config/studio.yaml`), driven over
the HTTP API by a Sonnet agent; the lead viewed the rendered deck.

- **Cost:** 9 turns, 25 model calls, 400k input and 4.8k output tokens. About $1.27 at a
  deliberately high assumed price ($3 / $15 per million); the real price was not confirmed.
  Every call resends about 12k tokens of opening context and tool definitions.
- **The loop and tools work on a real model.** Every turn ended normally and was
  classified correctly. The adapter and all tool schemas were accepted unchanged. The
  model loaded the three skills and read sources unprompted.
- **Writing slides was not the obstacle expected.** Four `write_slide` calls: one refused
  for an invented `rationale` field, corrected on the next call; no layout QA findings.
- **The slides are generic.** Each is a title, a rule and two paragraphs on white, with
  the lower half empty: no numbers, charts, shapes or use of the free layout. The model
  passes QA by staying inside a safe text-only pattern. This is the problem Phases 2 and 3
  exist to solve; Phase 1 has no design layer.
- **Defect: `apply_option` appended the chosen opening as a fourth slide** instead of
  replacing slide 1 (the candidate carried a new id and no position), and the model then
  told the owner slide 1 had been replaced. It was corrected only when pointed out.
- **The second thread's recap came from state and was mostly right**, including the
  duplicate opening, but called the accepted proposal "dismissed".

To fix first: make a candidate that replaces a slide apply as a replacement and have
`apply_option` report the resulting slide order; make the recap quote proposal status
exactly; name the allowed fields in `write_slide`'s description.
