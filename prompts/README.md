# Prompts

**Every LLM prompt in AutoDeck lives here as a versioned file. None are inlined in Python.**
That is plan §0.5, and it is not a style preference — a prompt is product surface, and an
undiffable prompt makes A3 and A8 regressions invisible.

## Rules

1. One file per agent role, named for the role: `planner.md`, `outline.md`, `content.md`,
   `validation.md`, `art_direction.md`, `aesthetic_critique.md`.
2. **A prompt change is its own commit, with the rationale in the commit body** — never
   bundled with a code change (`docs/BRANCHING.md`, commit conventions).
3. **Opus tier only.** `docs/MODEL_ROUTING.md` lists `prompts/` as a path guardrail:
   Sonnet does not author or amend prompts, and no prompt body is ever delegated to Haiku,
   regardless of how complete the specification looks.
4. Prompt file hashes go into the build manifest (A6), so a deck always records the exact
   prompt text that produced it.

## Status

Empty at the end of Phase 0 — by design. Phase 0 builds contracts and de-risks the
rendering strategy; no agent runs yet. The first prompts land in Phase 2a (`planner.md`,
`outline.md`).
