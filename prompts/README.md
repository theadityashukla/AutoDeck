# Prompts

**Every LLM prompt in AutoDeck lives here as a versioned file. None are inlined in Python.**
That is plan §0.5, and it is not a style preference — a prompt is product surface, and an
undiffable prompt makes A3 and A8 regressions invisible.

## Rules

1. One file per agent role, named for the role: `planner.md`, `outline.md`, `content.md`,
   `validation.md`, `art_direction.md`, `aesthetic_critique.md`, `clarify.md`, `compose.md`,
   `revise.md`, `redesign.md`, `repair.md` (B53). Shared sections are files too, appended by
   code in a fixed order: the draft-first writer's system prompt is
   `<role>.md` + `components.md` + the skills + `provenance_<mode>.md` (B55, B59). The
   gate-first per-slide writer's is `content.md` + the skills.
2. **Deck craft lives in `skills/`** (B59): one file per skill, YAML front matter (`name` =
   file stem, `summary`, `use_when`) then the body. `autodeck/agents/skills.py` loads them;
   `SKILL_SETS` fixes which skills each writer role gets, in order. Today they are loaded
   statically into each call; the deck agent (Phase 4c) will load them on demand from the
   index the front matter forms. A skill holds *craft* that applies to every role. A role
   file holds only what is specific to its call. Skills are hashed into the manifest like
   every other prompt file.
3. **A prompt change is its own commit, with the rationale in the commit body** — never
   bundled with a code change (`docs/BRANCHING.md`, commit conventions).
4. **Opus tier only.** `docs/MODEL_ROUTING.md` lists `prompts/` as a path guardrail:
   Sonnet does not author or amend prompts, and no prompt body is ever delegated to Haiku,
   regardless of how complete the specification looks.
5. Prompt file hashes go into the build manifest (A6), so a deck always records the exact
   prompt text that produced it.

## Status

Empty at the end of Phase 0 — by design. Phase 0 builds contracts and de-risks the
rendering strategy; no agent runs yet. The first prompts land in Phase 2a (`planner.md`,
`outline.md`).
