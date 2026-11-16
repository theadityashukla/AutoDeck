# `autodeck/studio/`: the v3 studio

The conversational studio. It imports from v2 (`autodeck/` outside this folder) and changes
none of it. Plan: `docs/AUTODECK_V3_PLAN.md`; record: `docs/phases/V3-PHASE-0.md`,
`V3-PHASE-1.md`, `V3-PHASE-2-3.md`; guide: `docs/STUDIO-GUIDE.md`; handover:
`docs/handovers/V3-STUDIO.md`. Tests are in `tests/studio/`. Run: `python -m autodeck.studio`.

Some module docstrings still say "Phase 0" or "a few pure edits"; the phase documents are the
record of what each module does now.

| Area | Modules |
|---|---|
| The base model and state | `models.py` (plain deck, engagement, change log, staleness), `serialise.py`, `diff.py`, `changelog.py` (pure undo and redo), `store.py` (one artifact on disk), `edits.py` (pure edits), `paths.py` (workspace layout and the path guard), `engagement.py`, `errors.py` |
| Rendering | `render_adapter.py` (base slide to v2's drawing code and layout QA), `layout_rules.py` (the three studio rules), `render.py`, `design_render.py` (render in a deck's design system), `previews.py` (background previews) |
| The conversation | `session.py` (the `Studio`: threads, turns, owner actions), `loop.py` (the lead loop), `conversation.py` (contracts, events), `context.py` (opening context from state), `threads.py`, `proposals.py`, `sources.py`, `prompt.py`, `tool_args.py`, `tools.py` (the lead's and the mechanic's tools), `views.py`, `change_summary.py` |
| Layers | `compose.py` (composition orchestration), `designer.py` and `designer_prompt.py` (the designer), `system_layer.py` (palette from a direction), `design.py` (design system, palette check, tokens), `routing.py`, `mechanic.py`, `usage.py` (layers, calls, estimated cost) |
| Models | `bindings.py` (`config/studio.yaml`), `responses.py` (the OpenAI Responses path), `scripted.py` (the scripted stand-in) |
| Interface | `api.py` (routes, socket-free), `server.py` (HTTP, Server-Sent Events), `events.py`, `__main__.py`, `static/` (plain HTML, CSS, JavaScript; no build step) |

Prompts are in `prompts/studio/`, bindings in `config/studio.yaml`, assumed prices in
`config/studio_prices.yaml`.
