"""`draft --agent`: one agent session writes the deck through tools (Phase 4c, B71).

The one-shot `compose_deck` asks a model for the whole deck in a single reply, then repairs
what failed with one more call (B45, B53). Here the same writer works in a session instead:
it loads the skills it needs, searches and reads the corpus, writes the brief and the slides
one tool call at a time, sees each slide's check results immediately, and fixes them before
it finishes. Nothing about what code decides changes: citations resolve against what the
session showed (A1, B75), budgets and draft checks are `compose.build_draft`'s, and the
result is an ordinary `ComposeResult`, so `cli draft` writes coverage, IR and the draft brief
exactly as it does for a one-shot draft.

What the agent starts with:
- **system**: `prompts/agent.md`, the `deck-thinking` skill, the index of every other skill
  (loaded on demand with `load_skill`), the components (or the creative master) and the
  provenance section. Saved as `session/system.md`, so a resumed session speaks to the model
  under the same instructions it started with even if a prompt file changes in between.
- **opening message**: the request, answers or chat brief, client context, header style,
  design constraints, the corpus map, and a small seed of citable passages — the opening
  paragraphs of each section (`section_lead_spans`), the curated claims that match the
  request and, in `normal` mode, what the person typed. The agent pulls everything else.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodeck.agents.advisor import AdvisorModel, slide_text
from autodeck.agents.compose import (
    COMPONENTS_PROMPT,
    CREATIVE_PROMPT,
    PROMPT_SEPARATOR,
    PROVENANCE_PROMPTS,
    ComposeError,
    ComposeResult,
    answers_text,
    asked_for_sections,
    brief_text,
    coverage_report,
    design_text,
    drop_still_failing,
    header_text,
    like_prompt_section,
    read_prompt,
)
from autodeck.agents.content import _gather_claims, render_evidence
from autodeck.agents.corpus_map import build_corpus_map
from autodeck.agents.evidence_pack import EvidencePack, section_lead_spans, with_conversation
from autodeck.agents.planner import Draft
from autodeck.agents.session import (
    SessionLimits,
    SessionState,
    TranscriptLog,
    compact,
    run_session,
)
from autodeck.agents.skills import _without_project, available_skills, load_skill
from autodeck.agents.tools.advisor import advisor_tools
from autodeck.agents.tools.corpus import corpus_tools
from autodeck.agents.tools.deck import deck_tools
from autodeck.agents.tools.memory import memory_tools
from autodeck.agents.tools.registry import ToolBox
from autodeck.agents.tools.skills import skill_tools
from autodeck.agents.workspace import BuildSettings, DeckWorkspace, WorkspaceError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.ir.models import DesignMode, ProvenanceMode
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.knowledge.loader import CachedClaim
from autodeck.knowledge.memory import MemoryStore
from autodeck.providers.base import Message
from autodeck.retrieval.hybrid import HybridIndex

AGENT_PROMPT = Path("prompts/agent.md")
MEETING_PROMPT = Path("prompts/agent_meeting.md")
MEETING_SKILL = "meeting-readout"

SEED_BUDGET_TOKENS = 4_000
"""The opening passages, estimated as `len(text) // 4`. Small on purpose: the agent searches
for what its argument needs rather than wading through a preloaded pack (plan §4c)."""

ALWAYS_LOADED = "deck-thinking"
NEVER_INDEXED = frozenset({ALWAYS_LOADED, "visual-review", "meeting-notes"})
"""`visual-review` is for looking at rendered slides, which this session does not do yet;
`meeting-notes` is the notes agent's (B80), not a deck-writing skill."""


@dataclass
class SessionFiles:
    """Where a run's session lives: `runs/<run>/session/`."""

    root: Path

    @property
    def transcript(self) -> Path:
        return self.root / "transcript.jsonl"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace.json"

    @property
    def system(self) -> Path:
        return self.root / "system.md"

    @property
    def corpus_map(self) -> Path:
        return self.root / "corpus_map.md"

    @property
    def memory(self) -> Path:
        """Snapshots of the engagement and owner memory the session started from (B77)."""
        return self.root / "memory"


@dataclass
class AgentRun:
    """A finished session: the draft as a `ComposeResult`, and the session behind it."""

    result: ComposeResult
    state: SessionState
    workspace: DeckWorkspace


# -- what the agent is told -------------------------------------------------------


def agent_system(
    *,
    provenance: ProvenanceMode,
    design_mode: DesignMode,
    project: str | None,
    meeting: bool = False,
) -> str:
    """The session's system prompt. Every part is a file, so every part is hashed (A6).

    With `meeting` (B82) the deck is built from a recorded meeting: `prompts/agent_meeting.md`
    and the `meeting-readout` skill follow the deck-thinking skill, and `meeting-readout` is
    no longer offered in the index (it is already loaded)."""
    thinking = load_skill(ALWAYS_LOADED)
    skip = NEVER_INDEXED | {MEETING_SKILL} if meeting else NEVER_INDEXED
    index = "\n".join(
        f"- `{s.name}` — {s.summary} (use when: {s.use_when})"
        for s in (load_skill(n) for n in available_skills())
        if s.name not in skip
    )
    components = CREATIVE_PROMPT if design_mode == "creative" else COMPONENTS_PROMPT
    meeting_parts = []
    if meeting:
        readout = load_skill(MEETING_SKILL)
        meeting_parts = [
            read_prompt(MEETING_PROMPT),
            f"# Skill: `{readout.name}`\n\n{_without_project(readout.body, project)}",
        ]
    return PROMPT_SEPARATOR.join(
        [
            read_prompt(AGENT_PROMPT),
            f"# Skill: `{thinking.name}`\n\n{_without_project(thinking.body, project)}",
            *meeting_parts,
            "# Skills you can load with `load_skill`\n\n" + index,
            read_prompt(components),
            read_prompt(PROVENANCE_PROMPTS[provenance]),
        ]
    )


def seed_pack(
    prompt: str,
    *,
    index: HybridIndex,
    claims: Sequence[CachedClaim],
    conversation: Document | None,
    mode: ProvenanceMode,
    budget_tokens: int = SEED_BUDGET_TOKENS,
) -> EvidencePack:
    """The passages the agent starts with: section leads, matching curated claims and (in
    `normal` mode) the person's own words, which are never trimmed (B55)."""
    picked = _gather_claims(prompt, claims)
    spans = list(section_lead_spans(index))
    text = render_evidence(picked, spans)
    dropped = 0
    while spans and len(text) // 4 > budget_tokens:
        spans.pop()
        dropped += 1
        text = render_evidence(picked, spans)
    pack = EvidencePack(
        claims=tuple(picked),
        spans=tuple(spans),
        text=text,
        queries=(prompt,),
        dropped=dropped,
        approx_tokens=len(text) // 4,
    )
    return with_conversation(pack, conversation, mode)


def opening_message(
    prompt: str,
    *,
    answers: Sequence[tuple[str, str] | str],
    chat_brief: Draft | None,
    context: AssembledContext,
    tokens: DesignTokens,
    design_mode: DesignMode,
    corpus_map: str,
    seed: EvidencePack,
    memory_text: str = "",
    extra_sections: Sequence[str] = (),
    like: Mapping[str, Any] | None = None,
) -> str:
    """The first message. `extra_sections` (a meeting's transcript and notes, B82) go just
    before the seed passages."""
    parts = [f"# The request\n\n{prompt.strip()}"]
    if chat_brief is not None:
        parts.append(
            "# The brief, already agreed\n\nThe person shaped this brief in conversation. Keep "
            "its objective, audience and key messages verbatim; set their origin to chat.\n\n"
            + brief_text(chat_brief)
        )
    parts.append("# The person's answers\n\n" + answers_text(answers))
    parts.append("# Client context\n\n" + context.to_prompt_context())
    parts.append(header_text(context, chat_brief.header_style if chat_brief else None))
    parts.append(design_text(tokens, design_mode))
    if like is not None:
        parts.append(like_prompt_section(like))
    if memory_text:
        parts.append(memory_text)
    parts.append("# The corpus\n\n" + corpus_map)
    parts.extend(extra_sections)
    parts.append(
        "# Passages you start with — citable now; search and read for the rest\n\n" + seed.text
    )
    return PROMPT_SEPARATOR.join(parts)


# -- the session ------------------------------------------------------------------


def build_settings(
    *,
    prompt: str,
    answers: Sequence[tuple[str, str] | str],
    chat_brief: Draft | None,
    store: DocumentStore,
    tokens: DesignTokens,
    provenance: ProvenanceMode,
    deck_fields: dict[str, Any],
) -> BuildSettings:
    return BuildSettings(
        store=store,
        tokens=tokens,
        deck_fields=deck_fields,
        chat_brief=chat_brief,
        allow_unsourced=provenance == "normal",
        keep_words=False,
        dividers_requested=asked_for_sections(prompt, answers, chat_brief),
    )


def make_toolbox(
    ws: DeckWorkspace,
    *,
    index: HybridIndex,
    claims: Sequence[CachedClaim],
    corpus_map: str,
    project: str | None,
    advisor: AdvisorModel | None = None,
    memory: MemoryStore | None = None,
) -> ToolBox:
    tools = [
        *skill_tools(project=project),
        *corpus_tools(ws, index=index, claims=claims, corpus_map=corpus_map),
        *deck_tools(ws, require_cold_read=advisor is not None),
    ]
    if advisor is not None:
        tools.extend(advisor_tools(ws, model=advisor, index=index, project=project))
    if memory is not None:
        memory.shown_texts = lambda: [s.text for s in ws.shown_spans]
        tools.extend(memory_tools(memory))
    return ToolBox(tools, state_key=lambda: ws.revision)


def result_from_workspace(ws: DeckWorkspace, state: SessionState) -> ComposeResult:
    """The workspace as a `ComposeResult`: built, still-failing blocks dropped, coverage
    recomputed by code (B48). Raises `ComposeError` when the session left nothing to build."""
    try:
        built = ws.build()
    except WorkspaceError as exc:
        raise ComposeError(
            f"the agent session ended ({state.stop_reason}) without a usable draft: {exc}"
        ) from exc
    built = drop_still_failing(built)
    coverage = coverage_report(
        ws.coverage,
        messages=built.graded,
        origins=built.origins,
        slides=built.slides,
        must_include=built.brief.must_include,
    )
    corrections = list(built.corrections)
    if state.stop_reason != "finished":
        corrections.append(
            f"the agent session stopped ({state.stop_reason}) before calling finish; the "
            "draft is what it had written by then"
        )
    return ComposeResult(
        deck=built.deck,
        draft_brief=built.brief,
        coverage=coverage,
        rejections=built.rejections,
        notes=ws.notes,
        provider_calls=state.provider_calls,
        corrections=corrections,
        incomplete_slots=built.incomplete,
        origins=built.origins,
        failures=built.failures,
        advisories=built.advisories,
        repairs=[],
        repair_ran=False,
    )


def compose_deck_agent(
    prompt: str,
    *,
    answers: Sequence[tuple[str, str] | str],
    index: HybridIndex,
    claims: Sequence[CachedClaim],
    documents: Sequence[Document],
    context: AssembledContext,
    store: DocumentStore,
    tokens: DesignTokens,
    model: Any,
    advisor: AdvisorModel | None = None,
    run_id: str,
    client: str,
    project: str,
    theme_ref: str,
    component_lib_version: str,
    chat_brief: Draft | None = None,
    provenance: ProvenanceMode = "strict",
    named_terms: Sequence[str] = (),
    design_mode: DesignMode = "structured",
    conversation: Document | None = None,
    session_dir: Path | None = None,
    limits: SessionLimits | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
    memory: MemoryStore | None = None,
    like: Mapping[str, Any] | None = None,
) -> AgentRun:
    """Run a fresh deck agent session and return its draft (B71).

    `model` is a converse-capable provider (`guard.provider("composer")`); `advisor`, when
    given, is `guard.provider("advisor")` and adds the `ask_advisor` tool. With
    `session_dir` the transcript, workspace, system prompt and corpus map are written there
    (B74); without it the session runs in memory (tests). With `memory` (B77) the opening
    message carries the engagement and owner memory as they stand, a snapshot of both goes to
    `session/memory/`, and the memory tools are added.

    Raises:
        ComposeError: a prompt is missing, or the session ended with nothing to build.
    """
    deck_fields = {
        "run_id": run_id,
        "project": project,
        "client": client,
        "theme_ref": theme_ref,
        "component_lib_version": component_lib_version,
        "provenance": provenance,
        "named_terms": list(named_terms),
        "design_mode": design_mode,
    }
    settings = build_settings(
        prompt=prompt,
        answers=answers,
        chat_brief=chat_brief,
        store=store,
        tokens=tokens,
        provenance=provenance,
        deck_fields=deck_fields,
    )
    ws = DeckWorkspace(settings=settings)
    seed = seed_pack(
        prompt, index=index, claims=claims, conversation=conversation, mode=provenance
    )
    ws.show_spans(seed.spans)
    ws.show_claims(seed.claims)
    corpus_map = build_corpus_map(documents, claims)
    system = agent_system(provenance=provenance, design_mode=design_mode, project=project)
    snapshot = memory.snapshot() if memory is not None else None
    opening = opening_message(
        prompt,
        answers=answers,
        chat_brief=chat_brief,
        context=context,
        tokens=tokens,
        design_mode=design_mode,
        corpus_map=corpus_map,
        seed=seed,
        memory_text=memory.context_text(snapshot) if memory is not None else "",
        like=like,
    )
    return _run_fresh_session(
        ws,
        system=system,
        opening=opening,
        corpus_map=corpus_map,
        snapshot=snapshot,
        index=index,
        claims=claims,
        project=project,
        model=model,
        advisor=advisor,
        memory=memory,
        session_dir=session_dir,
        limits=limits,
        on_step=on_step,
        opening_summary="opening message",
        archive_transcript=False,
    )


def _archive_transcript(files: SessionFiles) -> Path:
    n = 1
    while (archived := files.root / f"transcript.{n}.jsonl").exists():
        n += 1
    files.transcript.replace(archived)
    return archived


def _run_fresh_session(
    ws: DeckWorkspace,
    *,
    system: str,
    opening: str,
    corpus_map: str,
    snapshot: Mapping[Any, str] | None,
    index: HybridIndex,
    claims: Sequence[CachedClaim],
    project: str | None,
    model: Any,
    advisor: AdvisorModel | None,
    memory: MemoryStore | None,
    session_dir: Path | None,
    limits: SessionLimits | None,
    on_step: Callable[[dict[str, Any]], None] | None,
    opening_summary: str,
    archive_transcript: bool,
) -> AgentRun:
    """Write the session's files, run it from `opening` and return its draft. Shared by the
    corpus deck (`compose_deck_agent`) and the meeting deck (`meeting_deck.py`, B82).

    A transcript already in `session_dir` is unlinked, or with `archive_transcript` kept as
    `transcript.N.jsonl` (a meeting run's earlier deck session)."""
    files = SessionFiles(session_dir) if session_dir is not None else None
    log = None
    if files is not None:
        files.root.mkdir(parents=True, exist_ok=True)
        if files.transcript.exists():
            if archive_transcript:
                _archive_transcript(files)
            else:
                files.transcript.unlink()  # a fresh draft is a fresh session
        files.system.write_text(system, encoding="utf-8")
        files.corpus_map.write_text(corpus_map, encoding="utf-8")
        if snapshot is not None:
            files.memory.mkdir(exist_ok=True)
            for scope, text in snapshot.items():
                (files.memory / f"{scope}.md").write_text(text, encoding="utf-8")
        log = TranscriptLog(files.transcript)

    state = SessionState(messages=[], summaries={})
    first = Message(role="user", content=opening)
    state.messages.append(first)
    if log is not None:
        log.append(first, summary=opening_summary, step=0)
    toolbox = make_toolbox(
        ws,
        index=index,
        claims=claims,
        corpus_map=corpus_map,
        project=project,
        advisor=advisor,
        memory=memory,
    )
    try:
        state = run_session(
            model,
            system=system,
            state=state,
            toolbox=toolbox,
            limits=limits or SessionLimits(),
            log=log,
            on_step=on_step,
        )
    finally:
        if files is not None:
            ws.save(files.workspace)
    return AgentRun(result=result_from_workspace(ws, state), state=state, workspace=ws)


# -- resume: revise and chat continue the same session (B74) ------------------------

RESEED_TOKENS = 60_000
"""When the (compacted) transcript is estimated above this, a resume starts a fresh
transcript seeded with the agent's notes and the deck as it stands, instead of continuing."""


def revision_message(instruction: str) -> str:
    return (
        "# The person asks for a change\n\n"
        f"{instruction.strip()}\n\n"
        "Change only what this touches: rewrite the slides it affects with `write_slide` "
        "(same ids), update the brief or your notes if it changes them, then `check_deck` and "
        "`finish`. In `finish`'s notes, tell the person in one or two sentences what changed "
        "and why."
    )


def _context_tokens(state: SessionState, limits: SessionLimits) -> int:
    messages = compact(state.messages, state.summaries, limits.keep_recent_results)
    return sum(len(m.content) for m in messages) // 4


def reseed_message(ws: DeckWorkspace, memory_text: str = "") -> str:
    """A fresh start that carries the session's memory: notes, brief and every slide, and
    the engagement and owner memory as they stand now (B77)."""
    parts = ["# You are continuing a deck you built earlier in another session."]
    if memory_text:
        parts.append(memory_text)
    if ws.deck_notes.strip():
        parts.append("# Your working notes\n\n" + ws.deck_notes)
    if ws.brief is not None:
        brief = ws.brief
        messages = "\n".join(f"  - {m.id} [{m.origin}]: {m.text}" for m in brief.key_messages)
        parts.append(
            "# The brief\n\n"
            f"objective: {brief.objective}\naudience: {brief.audience}\n"
            f"length_target: {brief.length_target}\nkey_messages:\n{messages}\n"
            f"must_include: {', '.join(brief.must_include) or '(none)'}\n"
            f"must_avoid: {', '.join(brief.must_avoid) or '(none)'}"
        )
    parts.append("# The deck as it stands\n\n" + "\n\n".join(slide_text(s) for s in ws.slides))
    parts.append(
        "Every passage you cited before is still citable. Read a page again with "
        "`read_passage` before quoting it, since its text is not shown here."
    )
    return PROMPT_SEPARATOR.join(parts)


def resume_deck_agent(
    instruction: str,
    *,
    session_dir: Path,
    settings: BuildSettings,
    index: HybridIndex,
    claims: Sequence[CachedClaim],
    model: Any,
    advisor: AdvisorModel | None = None,
    project: str | None = None,
    limits: SessionLimits | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
    memory: MemoryStore | None = None,
) -> AgentRun:
    """Continue a run's session with one instruction from the person (B74).

    The session speaks under the system prompt it started with (`session/system.md`), from
    the workspace it left (`session/workspace.json`), with the same citable set. A transcript
    over `RESEED_TOKENS` is archived and replaced by a fresh one seeded from the workspace.

    Raises:
        ComposeError: there is no session to resume, or the session left nothing to build.
    """
    files = SessionFiles(session_dir)
    for required in (files.system, files.workspace, files.transcript, files.corpus_map):
        if not required.exists():
            raise ComposeError(
                f"no agent session to resume: {required} is missing. Draft with --agent first."
            )
    limits = limits or SessionLimits()
    system = files.system.read_text(encoding="utf-8")
    corpus_map = files.corpus_map.read_text(encoding="utf-8")
    ws = DeckWorkspace.load(files.workspace, settings)
    state = TranscriptLog.load(files.transcript)
    if _context_tokens(state, limits) > RESEED_TOKENS:
        archived = _archive_transcript(files)
        state = SessionState(messages=[], summaries={})
        log = TranscriptLog(files.transcript)
        memory_text = memory.context_text() if memory is not None else ""
        seed = Message(role="user", content=reseed_message(ws, memory_text))
        state.messages.append(seed)
        note = f"reseeded from the workspace (old transcript: {archived.name})"
        log.append(seed, summary=note, step=0)
    else:
        log = TranscriptLog(files.transcript)
    ask = Message(role="user", content=revision_message(instruction))
    state.messages.append(ask)
    said = " ".join(instruction.split())[:80]
    log.append(ask, summary=f"the person: {said}", step=state.steps)
    toolbox = make_toolbox(
        ws,
        index=index,
        claims=claims,
        corpus_map=corpus_map,
        project=project,
        advisor=advisor,
        memory=memory,
    )
    try:
        state = run_session(
            model,
            system=system,
            state=state,
            toolbox=toolbox,
            limits=limits,
            log=log,
            on_step=on_step,
        )
    finally:
        ws.save(files.workspace)
    return AgentRun(result=result_from_workspace(ws, state), state=state, workspace=ws)
