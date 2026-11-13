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
"""
