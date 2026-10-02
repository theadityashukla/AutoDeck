"""Opening a planning session: the one setup path the CLI and the review UI share (B40).

`autodeck plan` used to build its `PlannerSession` inline. The review UI needs the same
session, and two copies of this setup would drift — the day one of them forgets
`assembler.use_index`, A4's isolation check stops covering that path. So the setup lives
here, and both front ends call it.

Nothing in here approves anything. Signing the brief stays `PlannerSession.sign_off`
(A7).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autodeck.agents.evidence_gap import CLASSIFIER_ROLE, EvidenceProbe
from autodeck.agents.planner import PlannerSession
from autodeck.ingest.document_store import DocumentStore
from autodeck.knowledge.context_assembler import (
    AssembledContext,
    ContextAssembler,
    NamespacedIndex,
)
from autodeck.knowledge.loader import CachedClaim, KnowledgeError, KnowledgeLoader
from autodeck.pipeline.orchestrator import Orchestrator
from autodeck.providers.cache import ResponseCache
from autodeck.providers.guard import ProviderGuard
from autodeck.providers.registry import ModelRegistry
from autodeck.retrieval.hybrid import build_index


class PlanningSetupError(RuntimeError):
    """The session cannot start. `exit_code` is what the CLI exits with."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


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

    Raises:
        PlanningSetupError: the knowledge folders are malformed (exit 1), or the project
            has no ingested documents (exit 2) — the evidence-gap check is the point of
            planning, so it does not start without them.
    """
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
