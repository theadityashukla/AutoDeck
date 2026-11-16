"""The engagement container: one client and one project over the knowledge folders, with
client isolation (A4, V9) enforced in both the knowledge tree and the workspace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodeck.knowledge.loader import ClientIsolationError, KnowledgeError
from autodeck.studio.engagement import (
    Engagement,
    create_engagement,
    list_engagements,
    open_engagement,
)
from autodeck.studio.errors import (
    ArtifactMismatchError,
    EngagementExistsError,
    EngagementMismatchError,
    EngagementNotFoundError,
    InvalidSegmentError,
    WorkspaceLocationError,
)
from autodeck.studio.models import DeckArtifact, EngagementRecord
from autodeck.studio.paths import workspace_paths
from autodeck.studio.serialise import dump_model
from autodeck.studio.store import ArtifactStore
from tests.studio.helpers import ARTIFACT_ID, CLIENT, OTHER_CLIENT, PROJECT, T0


def _create(knowledge_root: Path, workspace_root: Path, client: str = CLIENT) -> Engagement:
    return create_engagement(
        client, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )


# -- create and open -----------------------------------------------------------------


def test_create_writes_the_record(knowledge_root: Path, workspace_root: Path) -> None:
    engagement = create_engagement(
        CLIENT,
        PROJECT,
        knowledge_root=knowledge_root,
        workspace_root=workspace_root,
        title="Pilot readout",
        now=T0,
    )
    assert (engagement.client, engagement.project) == (CLIENT, PROJECT)
    assert engagement.knowledge_root == knowledge_root
    assert engagement.namespace.client == CLIENT
    record_path = workspace_root / "engagements" / CLIENT / PROJECT / "engagement.json"
    expected = EngagementRecord(
        client=CLIENT, project=PROJECT, title="Pilot readout", created_at=T0
    )
    assert engagement.record == expected
    assert record_path.read_text(encoding="utf-8") == dump_model(expected)
    assert (record_path.parent / "artifacts").is_dir()
    assert not (record_path.parent / "threads").exists()


def test_open_reads_back_what_create_wrote(knowledge_root: Path, workspace_root: Path) -> None:
    created = _create(knowledge_root, workspace_root)
    opened = open_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root
    )
    assert opened.record == created.record
    assert opened.paths == created.paths


def test_create_twice_is_refused(knowledge_root: Path, workspace_root: Path) -> None:
    _create(knowledge_root, workspace_root)
    with pytest.raises(EngagementExistsError):
        _create(knowledge_root, workspace_root)


def test_open_without_a_record(knowledge_root: Path, workspace_root: Path) -> None:
    with pytest.raises(EngagementNotFoundError):
        open_engagement(
            CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root
        )


@pytest.mark.parametrize(
    "client,project", [("no-such-client", PROJECT), (CLIENT, "no-such-project")]
)
def test_missing_knowledge_folders_are_knowledge_errors(
    knowledge_root: Path, workspace_root: Path, client: str, project: str
) -> None:
    with pytest.raises(KnowledgeError) as caught:
        create_engagement(
            client, project, knowledge_root=knowledge_root, workspace_root=workspace_root
        )
    assert not isinstance(caught.value, ClientIsolationError)
    assert not workspace_root.exists()


def test_open_revalidates_the_knowledge_folders(
    knowledge_root: Path, workspace_root: Path
) -> None:
    _create(knowledge_root, workspace_root)
    (knowledge_root / "projects" / PROJECT / "project.md").unlink()
    with pytest.raises(KnowledgeError):
        open_engagement(
            CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root
        )


@pytest.mark.parametrize(
    "client,project", [("../evil", PROJECT), (CLIENT, "a/b"), (".x", PROJECT)]
)
def test_unsafe_names_are_refused(
    knowledge_root: Path, workspace_root: Path, client: str, project: str
) -> None:
    with pytest.raises(InvalidSegmentError):
        create_engagement(
            client, project, knowledge_root=knowledge_root, workspace_root=workspace_root
        )
    assert not workspace_root.exists()


def test_a_workspace_inside_the_knowledge_tree_is_refused(knowledge_root: Path) -> None:
    with pytest.raises(WorkspaceLocationError):
        create_engagement(
            CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=knowledge_root / "ws"
        )
    assert not (knowledge_root / "ws").exists()


def test_list_engagements(knowledge_root: Path, workspace_root: Path) -> None:
    assert list_engagements(workspace_root) == []
    _create(knowledge_root, workspace_root, CLIENT)
    _create(knowledge_root, workspace_root, OTHER_CLIENT)
    assert list_engagements(workspace_root) == [(OTHER_CLIENT, PROJECT), (CLIENT, PROJECT)]


# -- client isolation (A4) -------------------------------------------------------------


def test_guard_refuses_another_clients_knowledge(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = _create(knowledge_root, workspace_root)
    theirs = knowledge_root / "clients" / OTHER_CLIENT / "client.md"
    with pytest.raises(ClientIsolationError, match=OTHER_CLIENT):
        engagement.guard(theirs)
    with pytest.raises(ClientIsolationError):
        engagement.read_knowledge_text(theirs)


def test_guard_refuses_another_clients_workspace(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = _create(knowledge_root, workspace_root)
    theirs = workspace_root / "engagements" / OTHER_CLIENT / PROJECT / "engagement.json"
    with pytest.raises(ClientIsolationError, match=OTHER_CLIENT):
        engagement.guard(theirs)
    sneaky = engagement.paths.root / ".." / ".." / OTHER_CLIENT / PROJECT / "engagement.json"
    with pytest.raises(ClientIsolationError):
        engagement.guard(sneaky)


def test_guard_allows_own_client_shared_project_and_outside(
    knowledge_root: Path, workspace_root: Path, tmp_path: Path
) -> None:
    engagement = _create(knowledge_root, workspace_root)
    own = knowledge_root / "clients" / CLIENT / "client.md"
    assert engagement.guard(own) == own
    assert engagement.read_knowledge_text(own) == f"# {CLIENT}\n"
    shared = knowledge_root / "projects" / PROJECT / "project.md"
    assert engagement.read_knowledge_text(shared) == "# Project\n"
    outside = tmp_path / "elsewhere.txt"
    assert engagement.guard(outside) == outside
    with pytest.raises(FileNotFoundError):
        engagement.read_knowledge_text(knowledge_root / "clients" / CLIENT / "missing.md")


def test_a_client_folder_symlinked_into_another_client_is_refused(
    knowledge_root: Path, workspace_root: Path
) -> None:
    alias = knowledge_root / "clients" / "alias-client"
    alias.symlink_to(knowledge_root / "clients" / OTHER_CLIENT, target_is_directory=True)
    with pytest.raises(ClientIsolationError):
        create_engagement(
            "alias-client",
            PROJECT,
            knowledge_root=knowledge_root,
            workspace_root=workspace_root,
        )
    assert not workspace_root.exists()


def test_a_record_copied_from_another_client_is_refused(
    knowledge_root: Path, workspace_root: Path
) -> None:
    mine = _create(knowledge_root, workspace_root, CLIENT)
    theirs = _create(knowledge_root, workspace_root, OTHER_CLIENT)
    mine.paths.record.write_bytes(theirs.paths.record.read_bytes())
    with pytest.raises(ClientIsolationError):
        open_engagement(
            CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root
        )


def test_a_record_naming_another_project_is_a_mismatch(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = _create(knowledge_root, workspace_root)
    data = json.loads(engagement.paths.record.read_text(encoding="utf-8"))
    data["project"] = "another-project"
    engagement.paths.record.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(EngagementMismatchError):
        open_engagement(
            CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root
        )


# -- artifacts -------------------------------------------------------------------------


def test_create_artifact_and_list_it(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _create(knowledge_root, workspace_root)
    assert engagement.artifact_ids() == []
    store = engagement.create_artifact(base_deck)
    assert isinstance(store, ArtifactStore)
    assert (store.client, store.project, store.artifact_id) == (CLIENT, PROJECT, ARTIFACT_ID)
    assert store.paths == workspace_paths(workspace_root).engagement(CLIENT, PROJECT).artifact(
        ARTIFACT_ID
    )
    assert engagement.artifact_ids() == [ARTIFACT_ID]
    assert engagement.artifact_store(ARTIFACT_ID).load() == base_deck


def test_artifact_store_does_not_touch_the_disk(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = _create(knowledge_root, workspace_root)
    store = engagement.artifact_store("not-yet")
    assert not store.exists() and not store.paths.root.exists()
    with pytest.raises(InvalidSegmentError):
        engagement.artifact_store("../escape")


def test_create_artifact_refuses_another_clients_deck(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _create(knowledge_root, workspace_root)
    with pytest.raises(ClientIsolationError):
        engagement.create_artifact(base_deck.model_copy(update={"client": OTHER_CLIENT}))
    with pytest.raises(ArtifactMismatchError):
        engagement.create_artifact(base_deck.model_copy(update={"project": "another-project"}))
    assert engagement.artifact_ids() == []
