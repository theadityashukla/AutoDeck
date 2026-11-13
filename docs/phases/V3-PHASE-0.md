# v3 Phase 0 — Foundations

**Branch:** `claude/autodeck-principles-review-zp7nsm` · **Source:** `docs/AUTODECK_V3_PLAN.md`
§4, §8.1, §12 Phase 0, §13 (preview speed)

> **Done when:** a hand-written base deck renders to PPTX and previews, and an edit to it
> can be made, listed and undone. Preview speed is measured and reported.
>
> The exit test is `tests/studio/test_phase0_done.py` (PPTX in the default suite, PPTX and
> previews under `-m render`). It loads the fixture, renders it, applies an edit, lists the
> log, undoes, and asserts `current.json` is byte-identical to before.

## How to use this document

The scaffold is written: models in full (`autodeck/studio/models.py`), every other public
function as a signature, type hints and a docstring with a `NotImplementedError` body, and
the acceptance tests. Each task below fills in the bodies of the files it owns until its
tests pass. Tasks own disjoint files, so all tasks in a wave can run at once.

Rules for every implementer:

- Implement only the files your task owns. The docstrings are the spec; if one is wrong or
  ambiguous, stop and report it rather than guessing.
- Do not edit `models.py`, `errors.py`, `tests/studio/helpers.py`, `tests/studio/conftest.py`
  or `tests/studio/fixtures/` (owned by the lead). Do not change a signature.
- Do not modify any v2 file (`autodeck/` outside `studio/`). Import from v2; never copy it.
- Do not edit your tests to make them pass. If a test is demonstrably wrong, report it with
  the reason; the lead decides.
- Checks before handing back: `uv run ruff check` and `uv run ruff format --check` on your
  files, `uv run pyright autodeck/studio`, and your task's tests. A test that still fails
  must fail only because a *dependency's* body is unimplemented (`NotImplementedError` from
  another task's file), never from your own file.

Running the tests: `uv run pytest -q -p no:cacheprovider tests/studio` for the default
suite; `uv run pytest -q -p no:cacheprovider -m render tests/studio` for the tests that need
LibreOffice (the repo's `render` marker, deselected by default in `pyproject.toml`). Tests
that build a PPTX need the Carlito font (`scripts/install-dev-fonts.sh`) and skip without it.

## Tasks

| id | Wave | Model | Files owned | What to implement | Proven by | Depends on |
|---|---|---|---|---|---|---|
| 0.1 | 1 | haiku | `autodeck/studio/serialise.py` | Canonical JSON dump, loads, SHA-256 digests, atomic write (temp file + fsync + `os.replace`), exact read with `newline=""` | `tests/studio/test_serialise.py` | none (`test_other_models_round_trip` also needs 0.4) |
| 0.2 | 1 | haiku | `autodeck/studio/diff.py` | `diff_artifacts` over v2's `ir.store._diff`; `describe` via v2's `Change.__str__` | `tests/studio/test_diff.py` | none |
| 0.3 | 1 | sonnet | `autodeck/studio/paths.py` | Workspace layout, segment checks, workspace/knowledge overlap check, the path-based client guard (`foreign_client`, `guard`), listings | `tests/studio/test_paths.py` | none |
| 0.4 | 1 | sonnet | `autodeck/studio/changelog.py` | Pure undo/redo transitions over `ChangeLog`, entry ids, listing; every result re-validated with `ChangeLog.model_validate` | `tests/studio/test_changelog.py` | none |
| 0.5 | 1 | haiku | `autodeck/studio/edits.py` | `set_block_text`, `set_slide_marker`, `move_slide`: new validated deck, input never mutated, ids never changed | `tests/studio/test_edits.py` | none |
| 0.6 | 1 | sonnet | `autodeck/studio/render_adapter.py` | Base block/slide to v2 creative block/slide (`model_construct` for citation-free `ChartSpec`/`FigureRef`), layout QA per slide and per deck | `tests/studio/test_render_adapter.py` | none |
| 0.7 | 2 | sonnet | `autodeck/studio/store.py` | One artifact on disk: create, load with digest and isolation checks, apply, undo/redo by snapshot copy, write order snapshot → log → current, nothing written on error | `tests/studio/test_store.py` | 0.1, 0.2, 0.3, 0.4 |
| 0.8 | 2 | sonnet | `autodeck/studio/render.py` | PPTX build (blank layout, slide tags, `render_free_layout`, placeholders, plain notes, `save_themed`), previews via `libreoffice.render_pptx`, timing | `tests/studio/test_render.py` | 0.6 |
| 0.9 | 2 | sonnet | `autodeck/studio/engagement.py` | Create/open/list engagements over `KnowledgeLoader`, symlinked-client check, record checks, two-tree `guard`, artifact store factory | `tests/studio/test_engagement.py` | 0.1, 0.3; the three artifact tests also need 0.7 |
| 0.10 | 3 | haiku | `scripts/studio_demo.py` | The demo: temporary workspace, render, edit, list, undo, print timings | `tests/studio/test_studio_demo.py` (`test_defaults` in the default suite, the rest under `-m render`) | 0.1–0.9 |
| 0.11 | 3 | lead | none (verification) | Run the exit test in both modes, run the demo once with `--keep`, look at the PNGs, record the timings below, run the full v2 suite | `tests/studio/test_phase0_done.py` | 0.1–0.10 |

Waves: **wave 1** (0.1–0.6) has no dependency on another task's body and can start at once.
**Wave 2** (0.7–0.9) can start as soon as wave 1 is merged; 0.9 can start alongside 0.7
because their files are disjoint, but it is only done when 0.7 is. **Wave 3** is the demo
and the lead's verification.

Why the tags: 0.1, 0.2 and 0.5 are short and every behaviour is pinned by the docstring and
tests. 0.3 is the client-isolation guard in the workspace (A4, enforced in every mode), so
its resolution and prefix edge cases want care. 0.4 and 0.7 are where exact undo lives.
0.6 and 0.8 work against v2's drawing code and python-pptx, with one deliberate validation
exemption. 0.9 composes v2's loader and namespace with the studio guard. 0.10 is a script
over finished functions with its steps listed.

## Design choices

**New package beside v2.** All new code is in `autodeck/studio/`, tests in `tests/studio/`.
No v2 file is modified. v2 types are imported, not copied: `FreeLayout` and its elements,
`ChartSeries`, `ChartKind`, `IconRef`, `ClientIsolationError`, `KnowledgeError`,
`KnowledgeLoader`, `ClientNamespace`, the diff walker and the drawing and QA functions.

**The base IR (`models.py`).** Plain data, `extra="forbid"`. A `Block` is text, a chart, a
figure or an icon, with exactly one payload and an optional `SourceNote` that nothing
reads. No claim, citation, verdict or approval anywhere (P3, V8). `ChartData` and
`FigureData` are v2's `ChartSpec` and `FigureRef` without the required citation, which is a
strict-mode rule. A `Slide` has intent, blocks, plain-text speaker notes, an optional
`FreeLayout` (a slide may be composed but not yet placed, P7), a marker and `serves` links
to storyline points; when a layout is present it must place every block exactly once, as
what it is (v2's B69 rule restated for base kinds). The deck carries brief, storyline,
design concept and a design-system reference (id and version), each optional and each
with a marker. Slide and block ids are stable across edits so the Phase 6 overlay can key
on `slide_id:block_id`.

**The deck carries no timestamp or version.** Its serialisation is then a pure function
of its state, which is what makes "undo restores it byte for byte" testable. Time lives in
change-log entries and the engagement record (A6 does not apply outside strict, V7).

**Canonical serialisation (`serialise.py`).** One state, one text: `model_dump(mode="json")`,
`json.dumps(indent=2, ensure_ascii=False)`, one trailing newline (v2's `ir/store` format).
Digests are SHA-256 of that text.

**Undo restores snapshots; it never inverts diffs (`store.py`).** Each entry's resulting
state is written once to `versions/<entry-id>.json`, plus `versions/initial.json`. Undo
copies the parent snapshot's bytes over `current.json`; redo copies the entry's own. Both
check digests first and raise `ChangeLogIntegrityError` rather than guess. Exactness is by
construction. The diff is kept for display and thread context only.

**The change log is a tree with a head (`models.ChangeLog`, `changelog.py`).** Entries
carry `parent_id` and before/after digests; the model validates that the live chain from
`head` is exactly the not-undone entries and that digests chain without gaps. Undo moves
head to the parent; redo re-applies the most recent undone child of head; a new change
after an undo leaves the undone entry in the log (the next thread is told what was
rejected, §5.1) but no longer redoable. Transitions are pure functions, so the logic is
tested without I/O.

**Entry fields.** id (`c0001`...), parent id, the id-keyed diff, the instruction as one
line, thread id, layer (`direction`, `system`, `composition`, `placement`, `mechanics`,
`review`), model id as a free string (`human` for a hand edit), aware timestamp, undone
flag, before/after digests.

**The engagement (`engagement.py`, `paths.py`).** One client and one project, both
validated through v2's `KnowledgeLoader` on create *and* on open. Working state is under a
workspace root (default `<repo>/workspace/`, git-ignored; every function takes an explicit
root, and tests always pass a temporary one), laid out as
`engagements/<client>/<project>/{engagement.json, artifacts/<id>/{current.json,
changelog.json, versions/, renders/}, threads/}`. The workspace may not overlap the
knowledge tree. Isolation (A4, V9) is enforced on both trees: v2's `ClientNamespace.guard`
in the knowledge tree, `EngagementPaths.guard` (client = first path component under
`engagements/`) in the workspace, and both raise v2's own `ClientIsolationError`. The
artifact store also refuses a deck whose `client` field is not its own, which catches a
file copied between clients. Projects are shared, as in v2 (D8).

**How rendering reaches v2 without changing it (`render_adapter.py`, `render.py`).** v2's
`renderer.render_deck` begins with `require_safe_to_render` (A2 and A5 linters). A base
deck has no claims, so that guard would block any sentence with a number; it is right for
v2 and must not be loosened (V10). The studio therefore does what `render/draft.py` already
does: it calls the lower-level public functions directly. The adapter turns each base slide
into a v2 creative-mode `Slide` (`component="free_layout"`, the base slide's own
`FreeLayout`, text blocks as v2 `framing` blocks, charts and figures as `ChartSpec` and
`FigureRef` built with `model_construct` and no citation). `render.py` draws each slide
with `free_layout.render_free_layout`, which runs `free_layout_qa.check_free_layout`
itself and refuses to draw a failing layout, then saves with `master_builder.save_themed`
and rasterises with `render.qa.libreoffice.render_pptx`. Every layout check (text fit, safe
area, overlap, minimum size, contrast, hidden text) runs on every base slide exactly as on
a v2 creative slide; nothing is weakened. A slide that cannot be drawn becomes a labelled
placeholder and the rest of the deck still renders. Speaker notes are plain text written
directly. A throwaway prototype of exactly this path was run against the fixture while
writing the scaffold: all four slides pass v2's QA and render, chart emphasis included.

**The one validation exemption.** `ChartSpec.model_construct` and `FigureRef.model_construct`
skip v2's A1 citation requirement. The objects exist only for the duration of a draw, go
only to drawing code that ignores a figure's citation and draws no source line for an
empty `source_citations`, and are never stored or audited. Pass the real `ChartSeries`
objects, not dumped dicts, or v2's code breaks.

**Tokens are explicit.** The design system is Phase 3; Phase 0 render functions take a
`DesignTokens`. Tests and the demo use `config/tokens/dev.json` (Carlito, installable
locally); the fixture uses only theme colour tokens (`dk1`, `lt1`, `accent1`...), so it
draws in any token file.

**The fixture (`tests/studio/fixtures/base_deck.json`).** Four free-layout slides for the
real knowledge pair `northwind-retail` / `llm-inference-efficiency`: a title slide on a
dark ground, a big-number slide with a source note, a native column chart with one
emphasised category, and a three-panel close. Illustrative figures, labelled as such in
the brief. Validates against `models.py` (pinned by `test_models.py`).

## Preview speed (plan §13)

Measured with the scaffold-time prototype in the build container (4 slides, dev tokens,
150 dpi): PPTX build about **0.03 s**; PPTX to PDF to PNGs about **2.0 s**, nearly all of it
LibreOffice start-up and conversion. Task 0.11 re-measures with the real implementation
through `scripts/studio_demo.py` and replaces these numbers. At about two seconds per
deck, rendered options (three directions of three slides each) are feasible if run in
parallel; one LibreOffice process per render means start-up is paid every time, so a
persistent process or a cache keyed by slide content is the first optimisation if Phase 3
finds it slow.

## Deliberately left out of Phase 0

- **Diagrams.** Every v2 diagram node must be a `Claim` or a `LabelFraming`, which is the
  strict model, not a plain one. Carrying them would mean either a base diagram model with
  a parallel adapter or importing assurance types into the base. A layout `diagram`
  element cannot validate on a base slide (pinned by `test_models.py`). Revisit when the
  overlay (Phase 6) or the vocabulary review (Phase 3) gives diagrams a plain node.
- **Undo of one change from the middle of the history** while keeping later ones (plan §5.3
  "per change"). Phase 0 undo/redo is linear along the live chain. Selective undo needs a
  three-way merge of states, and its semantics should be decided with threads in Phase 1.
- **Threads, sources and memory** (Phase 1, 5): `threads/` is reserved in the layout only.
- **Notes artifacts** (Phase 5): `ArtifactKind` is `deck` only.
- **Design system artifacts** (Phase 3): only the reference is carried.
- **Staleness computation** (Phase 4): markers are plain data.
- **Locking / several writers** (Phase 4): the store assumes one writer.
- **Crash repair**: a crash between writing the log and `current.json` is detected on load
  (`ChangeLogIntegrityError`), not repaired.
- **Figures with images**: v2's free layout draws a figure as a captioned panel; so does
  the base.
- **Preview caching and parallel rendering**: Phase 0 measures only.

## Risks found while scaffolding

1. **v2's `ClientNamespace.guard` does not catch a symlinked client folder.** `own_root` is
   resolved through the link, so `knowledge/clients/alias -> clients/other` looks like
   `alias`'s own folder. The studio adds its own check (the resolved client root must be
   `clients/<client>`; `create_engagement` step 4, tested). v2's assembler may have the same
   gap; not changed here (no v2 edits), flagged for the owner.
2. **Imports of v2 private names.** `diff.py` uses `autodeck.ir.store._diff` (v2's public
   `diff_decks` is typed to v2's `Deck`); `render.py` uses `renderer._BLANK_LAYOUT` and
   `SLIDE_TAG_PREFIX` as `render/draft.py` does. A v2 refactor could break them; the
   studio tests would catch it.
3. **The `model_construct` exemption** couples the adapter to the fact that v2's drawing
   code never reads a figure's citation and tolerates empty `source_citations`. If v2's
   drawing code starts reading them, the adapter tests fail loudly rather than drawing
   something wrong.
4. **Font dependence.** Layout QA measures text in the real font, so PPTX-building tests
   skip without Carlito, and CI (no fonts, per B10) will skip them, including the
   default-suite exit test. The exit test must be run locally before the phase is called
   done.
5. **Exact undo assumes pydantic's dump is stable** for a given model and library version.
   Undo and redo copy stored bytes, so existing artifacts stay exact across an upgrade;
   but if a pydantic upgrade changed the dump format, an apply's `NoChangeError` check
   (new dump against stored text) could see a difference where there is none. Pin pydantic
   or re-snapshot artifacts when upgrading.

## Result (task 0.11, lead verification, 2026-11-13)

Phase 0 meets its "done when".

- **Studio tests:** 154 passed in the default selection; the 5 `render`-marked tests pass
  with LibreOffice and the fonts installed. No skeleton body remains.
- **End to end:** `scripts/studio_demo.py` creates an engagement over the real knowledge
  folders, renders the four-slide fixture, applies an edit, lists it, and undoes it;
  `current.json` is byte-identical to before.
- **Rendered output:** all four fixture slides were viewed: title, hero number, native
  chart with one emphasised bar, and a three-card slide. Nothing blank or clipped.
- **v2 unchanged:** no file outside `autodeck/studio/` was edited under `autodeck/`. Full
  default suite: 2286 passed, 1 failed, which is v2's 2132 plus the 154 studio tests and
  the one known pre-existing font failure.
- **Lint and types:** ruff check, ruff format and pyright clean on the studio code.

### Preview speed

Four slides at 150 dpi on the build container: PPTX build 0.06-0.07 s; rasterisation
1.5-1.6 s. Rasterisation is one LibreOffice start plus the conversion, so it should grow
slowly with slide count, but that has not been measured on a full deck. Three design
directions of three slides each would cost one conversion each if rendered in parallel.

### Carried to Phase 1

- Undo of a change from the middle of the history (needs merge rules; decide with threads).
- Diagrams in the base IR (v2's diagram nodes are typed claims).
- Isolation cases raised by implementers and not yet tested: a workspace
  `engagements/<client>` that is a symlink to another client's tree; a
  `knowledge/projects/<project>` symlink into `clients/<other>`; listings that follow
  symlinked directories. The same symlink gap may exist in v2's `ClientNamespace.guard`;
  not verified.
- No locking and no crash repair in the store (single writer assumed).
- The studio depends on two private v2 names (`ir.store._diff`,
  `render.renderer._BLANK_LAYOUT`).
