"""Opening a planning session: the one setup path the CLI and the review UI share (B40).

`autodeck plan` used to build its `PlannerSession` inline. The review UI needs the same
session, and two copies of this setup would drift — the day one of them forgets
`assembler.use_index`, A4's isolation check stops covering that path. So the setup lives
here, and both front ends call it.

Nothing in here approves anything. Signing the brief stays `PlannerSession.sign_off`
(A7).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from autodeck.agents.evidence_gap import CLASSIFIER_ROLE, EvidenceProbe
from autodeck.agents.planner import PlannerSession
from autodeck.ingest.deck_source import run_source_root
from autodeck.ingest.document_store import Document, DocumentStore, IngestError
from autodeck.ingest.multi_store import MultiStore
from autodeck.ingest.redesign_settings import RedesignSettingsError, load_redesign
from autodeck.ingest.transcript_source import (
    MeetingSettingsError,
    ingest_transcript,
    load_meeting_settings,
)
from autodeck.ir.models import CONVERSATION_DOC_PREFIX
from autodeck.ir.store import IRStoreError, run_paths
from autodeck.knowledge.context_assembler import (
    AssembledContext,
    ContextAssembler,
    NamespacedIndex,
)
from autodeck.knowledge.loader import CachedClaim, KnowledgeError, KnowledgeLoader
from autodeck.pipeline.orchestrator import Orchestrator
from autodeck.providers.cache import ResponseCache
from autodeck.providers.guard import ProviderGuard
from autodeck.providers.registry import ModelRegistry, default_env_name
from autodeck.retrieval.hybrid import build_index


class PlanningSetupError(RuntimeError):
    """The session cannot start. `exit_code` is what the CLI exits with."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def require_confidential(env: str, path: Path | None = None) -> None:
    """Refuse an environment that is not marked `confidential_ok` (B81).

    A meeting transcript is client-confidential and every model call on a meeting run sends
    its text to the environment's providers, so the environment must say that is acceptable.

    Raises:
        PlanningSetupError: the environment is not flagged (exit 1).
    """
    from autodeck.providers import registry

    if not ModelRegistry.load(env, path or registry.DEFAULT_CONFIG_PATH).confidential_ok:
        raise PlanningSetupError(
            f"environment {env!r} is not marked confidential_ok in config/models.yaml; a "
            "meeting transcript is client-confidential and would be sent to its providers.",
            exit_code=1,
        )


@dataclass
class PlanningContext:
    """Everything set up before the first model call."""

    orchestrator: Orchestrator
    guard: ProviderGuard
    assembled: AssembledContext
    index: NamespacedIndex
    store: DocumentStore
    claims: list[CachedClaim]

    def open_session(self) -> PlannerSession:
        """Build the session.

        Resolving the two model roles can raise a provider failure (a missing key), so the
        caller wraps this call in its own failure handling, as `plan` always has.
        """
        return PlannerSession(
            self.orchestrator,
            model=self.guard.provider("planner"),
            probe=EvidenceProbe(
                index=self.index,  # type: ignore[arg-type]
                store=self.store,
                claims=self.claims,
                classifier=self.guard.provider(CLASSIFIER_ROLE),
            ),
            context=self.assembled,
        )


@dataclass
class RunSourcePlanning(PlanningContext):
    """`PlanningContext` for a run whose evidence is a run-local source (not the corpus): the
    store is a `MultiStore`, and the settings travel with it so every later step builds the
    same pack."""

    settings: dict


@dataclass
class RedesignPlanning(RunSourcePlanning):
    """A redesign run: the client's deck is the evidence (B41)."""

    deck_document: Document


@dataclass
class MeetingPlanning(RunSourcePlanning):
    """A meeting run: the transcript is the evidence (B78)."""

    transcript_document: Document


def _evidence_documents(store: DocumentStore) -> list[Document]:
    """What the index is built from: every document except the person's own conversation
    (A3: their words are citable, but never retrieved as independent evidence)."""
    return [d for d in store.documents() if not d.doc_id.startswith(CONVERSATION_DOC_PREFIX)]


def _run_source_planning(
    run_id: str,
    *,
    kind: Literal["redesign", "meeting"],
    client: str,
    project: str,
    env: str,
    knowledge_root: Path,
    corpus_root: Path,
    runs_root: Path,
    doc_ids: Sequence[str],
    check_papers: bool,
) -> tuple[PlanningContext, dict[str, Document]]:
    """What a compose-family call needs for a redesign or meeting run (B41, B49, B78, A4).

    Like the corpus path, but the sources are the run-local document(s) and — only with the
    paper check on — the project's papers, read through one `MultiStore`. With the check off
    the corpus folder is never touched, so a project with no ingested papers still works.
    Returns the context and the run-source documents by id.
    """
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader

    try:
        assembler = ContextAssembler(knowledge_root, client=client, project=project)
        assembled = assembler.assemble()
        knowledge = KnowledgeLoader(knowledge_root).load_project(project)
    except KnowledgeError as exc:
        raise PlanningSetupError(str(exc), exit_code=1) from None

    store = MultiStore(
        run_source_root(runs_root, run_id), corpus_root / project if check_papers else None
    )
    found: dict[str, Document] = {}
    for doc_id in doc_ids:
        try:
            found[doc_id] = store.get(doc_id)
        except IngestError as exc:
            if kind == "meeting":
                message = (
                    f"the meeting transcript is missing: {exc} Run `autodeck meeting source "
                    f"{run_id}` (or transcribe) first."
                )
            else:
                message = f"the run's deck is missing: {exc}"
            raise PlanningSetupError(message, exit_code=2) from None
    documents = _evidence_documents(store)
    if check_papers and len(documents) < 2:
        raise PlanningSetupError(
            f"the paper check is on but there are no ingested documents under "
            f"{corpus_root / project}. Run `autodeck knowledge ingest {project}` first, or "
            "turn the check off.",
            exit_code=2,
        )
    index = assembler.use_index(build_index(documents, project=project))
    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    guard = ProviderGuard(
        ModelRegistry.load(env), cache=ResponseCache(orchestrator.paths.llm_cache)
    )
    context = PlanningContext(
        orchestrator=orchestrator,
        guard=guard,
        assembled=assembled,
        index=index,
        store=store,
        claims=list(knowledge.claims) if check_papers else [],
    )
    return context, found


def run_source_settings(runs_root: Path, run_id: str) -> tuple[str, dict] | None:
    """`("redesign" | "meeting", settings)` for a run that has its own source, else None.

    Reads only; an unknown run folder is not created. Raises `PlanningSetupError` (exit 1)
    for a settings file that cannot be read.
    """
    try:
        root = run_paths(runs_root, run_id).root
        redesign = load_redesign(root)
        if redesign is not None:
            return "redesign", redesign
        meeting = load_meeting_settings(root)
    except (IRStoreError, RedesignSettingsError, MeetingSettingsError) as exc:
        raise PlanningSetupError(str(exc), exit_code=1) from None
    return ("meeting", meeting) if meeting is not None else None


def _ensure_transcript_document(runs_root: Path, run_id: str, doc_id: str) -> None:
    """Self-heal: the settings exist and `meeting/transcript.json` too, but the Document is
    not in `source/` (a copied or cleaned run). Re-ingesting is deterministic."""
    root = run_paths(runs_root, run_id).root
    if doc_id in DocumentStore(run_source_root(runs_root, run_id)).doc_ids():
        return
    if not (root / "meeting" / "transcript.json").is_file():
        return
    try:
        ingest_transcript(root, run_id)
    except IngestError as exc:
        raise PlanningSetupError(str(exc), exit_code=1) from None


def run_source_store(
    runs_root: Path, run_id: str, *, corpus_root: Path, project: str, env: str | None = None
) -> tuple[DocumentStore, list[Document]] | None:
    """`(store, documents to index)` for a redesign or meeting run; None for an ordinary
    corpus run. The validator's counterpart of `prepare_planning` (it opens no planner). A
    meeting run needs `env` to be `confidential_ok` (B81); `env` defaults to the config's."""
    found = run_source_settings(runs_root, run_id)
    if found is None:
        return None
    kind, settings = found
    if kind == "meeting":
        require_confidential(env or default_env_name())
        _ensure_transcript_document(runs_root, run_id, settings["doc_id"])
    source = run_source_root(runs_root, run_id)
    store = MultiStore(source, corpus_root / project if settings["check_papers"] else None)
    documents = _evidence_documents(store)
    required = settings["doc_id"] if kind == "meeting" else settings["deck_doc_id"]
    if required not in store.doc_ids():
        if kind == "meeting":
            raise PlanningSetupError(
                f"the meeting transcript is missing from {source}. Run `autodeck meeting "
                f"source {run_id}` (or transcribe) first.",
                exit_code=2,
            )
        raise PlanningSetupError(f"the redesign's deck is missing from {source}.", exit_code=2)
    return store, documents


def prepare_planning(
    run_id: str,
    *,
    client: str,
    project: str,
    env: str,
    knowledge_root: Path,
    corpus_root: Path,
    runs_root: Path,
) -> PlanningContext:
    """Load knowledge (enforcing A4), the corpus and the index, and open the run.

    A run folder that holds `redesign.json` (B41) or `meeting/settings.json` (B78) is a
    run-source run: the evidence is its own `source/` folder (plus the corpus only when the
    paper check is on) and the result is a `RedesignPlanning` or `MeetingPlanning`. Anything
    else takes the corpus path below.

    Raises:
        PlanningSetupError: the knowledge folders are malformed (exit 1), or the project
            has no ingested documents (exit 2) — the evidence-gap check is the point of
            planning, so it does not start without them.
    """
    run_source = run_source_settings(runs_root, run_id)
    if run_source is not None:
        kind, settings = run_source
        common = dict(
            client=client,
            project=project,
            env=env,
            knowledge_root=knowledge_root,
            corpus_root=corpus_root,
            runs_root=runs_root,
            check_papers=bool(settings["check_papers"]),
        )
        if kind == "redesign":
            context, found = _run_source_planning(
                run_id, kind="redesign", doc_ids=[settings["deck_doc_id"]], **common
            )
            return RedesignPlanning(
                **vars(context), settings=settings, deck_document=found[settings["deck_doc_id"]]
            )
        require_confidential(env)
        _ensure_transcript_document(runs_root, run_id, settings["doc_id"])
        context, found = _run_source_planning(
            run_id, kind="meeting", doc_ids=[settings["doc_id"]], **common
        )
        return MeetingPlanning(
            **vars(context), settings=settings, transcript_document=found[settings["doc_id"]]
        )

    try:
        assembler = ContextAssembler(knowledge_root, client=client, project=project)
        assembled = assembler.assemble()
        knowledge = KnowledgeLoader(knowledge_root).load_project(project)
    except KnowledgeError as exc:
        raise PlanningSetupError(str(exc), exit_code=1) from None

    store = DocumentStore(corpus_root / project)
    documents = list(store.documents())
    if not documents:
        raise PlanningSetupError(
            f"no ingested documents under {corpus_root / project}. The evidence-gap check "
            f"is the point of this session — run `autodeck knowledge ingest {project}` first.",
            exit_code=2,
        )

    registry = ModelRegistry.load(env)
    index = assembler.use_index(build_index(documents, project=project))
    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    guard = ProviderGuard(registry, cache=ResponseCache(orchestrator.paths.llm_cache))
    return PlanningContext(
        orchestrator=orchestrator,
        guard=guard,
        assembled=assembled,
        index=index,
        store=store,
        claims=knowledge.claims,
    )
