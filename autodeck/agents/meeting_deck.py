"""`draft --agent` on a meeting run: the deck is written in the run's agent session (B82).

A meeting run has a transcript as its source and, usually, notes the agent wrote from it
(`notes_agent.py`, B80). The deck agent that follows is a fresh deck session that carries the
notes session over by reseeding, the way `resume_deck_agent` carries a long session over: it
does not append deck turns to the notes transcript, because the two sessions' tool vocabularies
differ and a history of calls to tools that are not in the toolset is fragile across providers.

What carries over from the notes session:
- the session folder (`runs/<run>/session/`): the notes keep their own files, the deck uses the
  deck agent's names, so `revise` resumes the deck exactly as for any other run;
- the citable set: the turns the notes session showed, or every turn when the transcript is
  short enough to be put in front of the agent whole;
- the notes with the words they cite, the transcript (whole when short) and memory, all in the
  opening message.

Nothing about what code decides changes (A1): a slide cites turns, never notes, and a quote
resolves only against a turn the session showed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from autodeck.agents.advisor import AdvisorModel
from autodeck.agents.corpus_map import build_corpus_map
from autodeck.agents.deck_agent import (
    AgentRun,
    _run_fresh_session,
    agent_system,
    build_settings,
    opening_message,
    seed_pack,
)
from autodeck.agents.evidence_pack import document_spans
from autodeck.agents.notes_agent import PRELOAD_TOKENS, migrate_notes_session, transcript_text
from autodeck.agents.notes_workspace import NotesWorkspace, notes_with_quotes
from autodeck.agents.planner import Draft
from autodeck.agents.session import SessionLimits
from autodeck.agents.workspace import DeckWorkspace
from autodeck.audit.report import meeting_stamp
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.ir.models import DesignMode, ProvenanceMode
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.knowledge.loader import CachedClaim
from autodeck.knowledge.memory import MemoryStore
from autodeck.retrieval.hybrid import HybridIndex


def meeting_sections(
    transcript: Document,
    times: Mapping[int, float],
    notes: NotesWorkspace | None,
    *,
    whole: bool,
) -> list[str]:
    """The opening message's meeting sections: the transcript, then the notes (context, not
    evidence) with what the agent told the person about them."""
    if whole:
        body = transcript_text(transcript, times)
    else:
        long = f", about {meeting_stamp(max(times.values()))} long" if times else ""
        body = (
            f"{transcript.page_count} turns{long}. It is too long to show here. Find turns "
            "with `search_corpus` and read them with `read_passage` (the document id above "
            "and a turn number); a turn is citable once you have read it."
        )
    sections = [
        f"# The meeting (citable: doc id `{transcript.doc_id}`, one page per turn)\n\n{body}"
    ]
    if notes is not None and any(notes.sections.values()):
        text = (
            "# Your notes from this meeting (context, not evidence: cite the turns)\n\n"
            + notes_with_quotes(notes)
        )
        if notes.note_to_person.strip():
            text += "\n\n## What you told the person about the notes\n\n" + (
                notes.note_to_person.strip()
            )
        sections.append(text)
    return sections


def compose_meeting_deck_agent(
    prompt: str,
    *,
    answers: Sequence[tuple[str, str] | str],
    transcript: Document,
    times: Mapping[int, float],
    notes: NotesWorkspace | None,
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
) -> AgentRun:
    """Run a fresh deck session over a meeting run and return its draft (B82).

    `notes` is the notes session's workspace, or None when no notes were written; the deck is
    written from the transcript either way. With `session_dir` the deck session's files are
    written there beside the notes session's, which are never touched (a step-10 layout is
    migrated to the notes names first), and an earlier deck transcript is archived as
    `transcript.N.jsonl`.

    Raises:
        ComposeError: a prompt is missing, or the session ended with nothing to build.
    """
    if session_dir is not None:
        migrate_notes_session(session_dir)
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
    whole = len(transcript_text(transcript, times)) // 4 <= PRELOAD_TOKENS
    if whole:
        ws.show_spans(document_spans(transcript))
    elif notes is not None:
        ws.show_spans(notes.shown_spans())
    corpus_map = build_corpus_map(documents, claims)
    system = agent_system(
        provenance=provenance, design_mode=design_mode, project=project, meeting=True
    )
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
        extra_sections=meeting_sections(transcript, times, notes, whole=whole),
    )
    from_notes = notes is not None and any(notes.sections.values())
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
        opening_summary=(
            "opening message (from the meeting session)" if from_notes else "opening message"
        ),
        archive_transcript=True,
    )


__all__ = ["compose_meeting_deck_agent", "meeting_sections"]
