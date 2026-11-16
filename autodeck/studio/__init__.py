"""AutoDeck studio: the v3 base (docs/AUTODECK_V3_PLAN.md).

The engagement container, the plain base IR, the change log with undo and redo, and a
render path from the base IR through v2's free-layout drawing and layout QA. Built beside
v2, which it imports and never modifies. Phase 0 task list: docs/phases/V3-PHASE-0.md.

Modules:

* `models`: the contracts (engagement record, deck artifact, slide, block, markers,
  change-log entry and log).
* `errors`: studio errors; isolation reuses v2's `ClientIsolationError`.
* `paths`: the workspace layout and the path-based isolation guard.
* `serialise`: canonical JSON, digests, atomic writes.
* `diff`: the id-keyed diff, reusing v2's walker.
* `changelog`: undo/redo as pure functions over a `ChangeLog`.
* `store`: one artifact on disk (current state, log, snapshots).
* `engagement`: create/open an engagement over the knowledge folders.
* `edits`: a few pure deck edits.
* `render_adapter`: base slide → v2 creative slide, and layout QA.
* `render`: PPTX build, PNG previews, timing.

Phase 1, the conversation core (docs/phases/V3-PHASE-1.md):

* `conversation`: thread, log-line, proposal, render-manifest and turn-event contracts.
* `tool_args`: the lead's tool vocabulary, one argument model per tool.
* `bindings`: `config/studio.yaml`, role -> provider and model, through v2's providers.
* `scripted`: the scripted stand-in model (tests, and the server without a key).
* `prompt`: the lead's system prompt (`prompts/studio/lead.md`) and allowed skills.
* `threads`, `proposals`: threads and proposals on disk.
* `views`: compact text for the model, JSON for the interface.
* `context`: a thread's opening context, built from state only.
* `sources`: knowledge files and ingested documents, behind the guard.
* `tools`: the lead's tools over v2's ToolBox; `loop`: one turn.
* `events`, `previews`: streaming and background renders.
* `session`: the studio (threads, turns, owner actions); `api`, `server`, `__main__`: the
  local interface, `python -m autodeck.studio`.
"""
