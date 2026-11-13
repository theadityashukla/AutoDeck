"""The engagement container over the existing knowledge folders (plan §4, P1, V9).

An engagement is exactly one client and one project: the v2 pair
`knowledge/clients/<client>/` + `knowledge/projects/<project>/`, plus the working state made
for it under `<workspace>/engagements/<client>/<project>/`. Both knowledge folders are
validated through v2's `KnowledgeLoader` (so a missing folder or required file fails with
v2's own `KnowledgeError`, naming it), and the client is bound to a v2 `ClientNamespace` at
construction.

**Isolation (A4) is enforced on two trees.** In the knowledge tree, by v2's
`ClientNamespace.guard`; in the workspace, by `EngagementPaths.guard`. `Engagement.guard`
applies both, and every path this module hands out passes through it. A reach for another
client's data raises v2's `ClientIsolationError` in either tree. There is no method that
takes a second client name, so an `Engagement` cannot be repointed (the v2 assembler's
design).

The project tier stays shared, as in v2 (D8): reading another project's knowledge folder is
not an isolation error. Only client data is isolated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import ClientIsolationError, KnowledgeLoader
from autodeck.studio import serialise
from autodeck.studio.errors import (
    EngagementExistsError,
    EngagementMismatchError,
    EngagementNotFoundError,
)
from autodeck.studio.models import DeckArtifact, EngagementRecord
from autodeck.studio.paths import (
    EngagementPaths,
    check_segment,
    check_workspace_location,
    workspace_paths,
)
from autodeck.studio.store import ArtifactStore


class Engagement:
    """An open engagement: its record, paths and client namespace.

    Construct with `create_engagement` or `open_engagement`, which validate; the
    constructor only stores its arguments and checks nothing.
    """

    def __init__(
        self,
        record: EngagementRecord,
        paths: EngagementPaths,
        namespace: ClientNamespace,
    ) -> None:
        self.record = record
        self.paths = paths
        self.namespace = namespace

    @property
    def client(self) -> str:
        return self.record.client

    @property
    def project(self) -> str:
        return self.record.project

    @property
    def knowledge_root(self) -> Path:
        return self.namespace.knowledge_root

    def guard(self, path: Path) -> Path:
        """Return `path` unchanged if this engagement may touch it.

        Applies `self.namespace.guard` (knowledge tree) and then `self.paths.guard`
        (workspace). Paths outside both trees are allowed (they are not client data).

        Raises:
            ClientIsolationError: the path is under another client's knowledge folder or
                another client's workspace engagements.
        """
        self.namespace.guard(path)
        self.paths.guard(path)
        return path

    def read_knowledge_text(self, path: Path) -> str:
        """Read a text file through `guard` (UTF-8). Phase 0 has no other reader; Phase 1's
        source tools go through this.

        Raises:
            ClientIsolationError: as `guard`.
            FileNotFoundError: the file does not exist.
        """
        return self.guard(path).read_text(encoding="utf-8")

    def artifact_ids(self) -> list[str]:
        """`self.paths.artifact_ids()`: the artifacts in this engagement, sorted."""
        return self.paths.artifact_ids()

    def artifact_store(self, artifact_id: str) -> ArtifactStore:
        """An `ArtifactStore` for `artifact_id`, bound to this client and project. The
        artifact need not exist yet; nothing is read or written.

        Raises:
            InvalidSegmentError: `artifact_id` is not a safe segment.
        """
        artifact_paths = self.paths.artifact(artifact_id)
        self.guard(artifact_paths.root)
        return ArtifactStore(artifact_paths, client=self.client, project=self.project)

    def create_artifact(self, deck: DeckArtifact) -> ArtifactStore:
        """Create a new artifact from `deck` (its `id` names the directory) and return its
        store. Delegates every check to `ArtifactStore.create`.

        Raises:
            ClientIsolationError: `deck.client` is not this engagement's client.
            ArtifactMismatchError: `deck.project` is not this engagement's project.
            ArtifactExistsError: an artifact with that id exists.
            InvalidSegmentError: `deck.id` is not a safe segment (cannot happen for a valid
                `DeckArtifact`, whose `id` is pattern-checked).
        """
        store = self.artifact_store(deck.id)
        store.create(deck)
        return store


def _validate(
    client: str, project: str, knowledge_root: Path, workspace_root: Path | None
) -> tuple[EngagementPaths, ClientNamespace]:
    """Steps 1-4 shared by create and open."""
    check_segment(client, label="client")
    check_segment(project, label="project")
    workspace = workspace_paths(workspace_root)
    check_workspace_location(workspace.root, knowledge_root)
    loader = KnowledgeLoader(knowledge_root)
    loader.load_client(client)
    loader.load_project(project)
    namespace = ClientNamespace(client=client, knowledge_root=knowledge_root)
    if namespace.own_root != namespace.clients_root / client:
        raise ClientIsolationError(
            f"client folder for {client!r} resolves to {namespace.own_root}, not "
            f"{namespace.clients_root / client}: it points into another client's data"
        )
    return workspace.engagement(client, project), namespace


def create_engagement(
    client: str,
    project: str,
    *,
    knowledge_root: Path,
    workspace_root: Path | None = None,
    title: str = "",
    now: datetime | None = None,
) -> Engagement:
    """Create the engagement for `client` and `project` and return it open.

    Steps, in order (nothing is written until all checks pass):

    1. `paths.check_segment` on both names (`InvalidSegmentError`).
    2. Resolve the workspace (`paths.workspace_paths(workspace_root)`) and refuse it if it
       overlaps `knowledge_root` (`paths.check_workspace_location`, `WorkspaceLocationError`).
    3. `KnowledgeLoader(knowledge_root).load_client(client)` and `.load_project(project)`:
       a missing folder or required file raises v2's `KnowledgeError`.
    4. Bind `ClientNamespace(client=client, knowledge_root=knowledge_root)` and refuse a
       client folder that resolves somewhere other than its own name:
       `namespace.own_root != namespace.clients_root / client` raises v2's
       `ClientIsolationError` naming both paths. This catches
       `knowledge/clients/<client>` being a symlink into another client's folder.
       (`namespace.guard(client_root)` would *not* catch it: `own_root` is itself
       resolved through the symlink, so the guard sees the folder as the client's own.)
    5. Refuse if `engagement.json` already exists (`EngagementExistsError`).
    6. `EngagementPaths.ensure()`, then write the `EngagementRecord` (`created_at = now or
       datetime.now(UTC)`; `now` must be timezone-aware) with `serialise.dump_model` via
       `serialise.atomic_write_text`.
    """
    paths, namespace = _validate(client, project, knowledge_root, workspace_root)
    if paths.record.exists():
        raise EngagementExistsError(
            f"engagement {client}/{project} already exists: {paths.record}"
        )
    record = EngagementRecord(
        client=client,
        project=project,
        title=title,
        created_at=now or datetime.now(UTC),
    )
    paths.ensure()
    serialise.atomic_write_text(paths.record, serialise.dump_model(record))
    return Engagement(record, paths, namespace)


def open_engagement(
    client: str,
    project: str,
    *,
    knowledge_root: Path,
    workspace_root: Path | None = None,
) -> Engagement:
    """Open an existing engagement, re-validating it against the knowledge folders.

    Steps 1-4 of `create_engagement`, then read `engagement.json`:
    missing → `EngagementNotFoundError`; the record's `client` differs from `client` →
    `ClientIsolationError` (a record copied from another client's folder); the record's
    `project` differs → `EngagementMismatchError`; malformed → `pydantic.ValidationError`.
    Re-validation matters: a knowledge folder deleted since creation fails here loudly
    rather than leaving an engagement with no context.
    """
    paths, namespace = _validate(client, project, knowledge_root, workspace_root)
    try:
        text = serialise.read_text(paths.record)
    except FileNotFoundError:
        raise EngagementNotFoundError(
            f"no engagement for {client}/{project}: {paths.record} does not exist"
        ) from None
    record = serialise.load_engagement_record(text)
    if record.client != client:
        raise ClientIsolationError(
            f"engagement record {paths.record} names client {record.client!r}, not {client!r}"
        )
    if record.project != project:
        raise EngagementMismatchError(
            f"engagement record {paths.record} names project {record.project!r}, "
            f"not {project!r}"
        )
    return Engagement(record, paths, namespace)


def list_engagements(workspace_root: Path | None = None) -> list[tuple[str, str]]:
    """Every `(client, project)` with a record under the workspace, sorted
    (`WorkspacePaths.engagement_keys`). Reads no record and touches no knowledge folder:
    a listing for a picker, not a validation."""
    return workspace_paths(workspace_root).engagement_keys()
