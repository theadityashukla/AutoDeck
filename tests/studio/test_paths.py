"""Workspace layout and the path-based isolation guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio.errors import InvalidSegmentError, WorkspaceLocationError
from autodeck.studio.paths import (
    REPO_ROOT,
    check_segment,
    check_workspace_location,
    default_workspace_root,
    workspace_paths,
)
from tests.studio.helpers import CLIENT, OTHER_CLIENT, PROJECT


def test_default_workspace_is_at_the_repo_root() -> None:
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert default_workspace_root() == REPO_ROOT / "workspace"
    assert workspace_paths().root == REPO_ROOT / "workspace"


def test_workspace_is_git_ignored() -> None:
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/workspace/" in lines


@pytest.mark.parametrize("good", ["northwind-retail", "a", "deck_1.v2"])
def test_safe_segments_pass_through(good: str) -> None:
    assert check_segment(good, label="client") == good


@pytest.mark.parametrize("bad", ["", ".", "..", "../x", "a/b", "a\\b", ".hidden", "a b"])
def test_unsafe_segments_are_refused_with_the_label(bad: str) -> None:
    with pytest.raises(InvalidSegmentError, match="artifact id"):
        check_segment(bad, label="artifact id")


def test_layout(tmp_path: Path) -> None:
    ws = workspace_paths(tmp_path)
    assert ws.engagements == tmp_path / "engagements"
    eng = ws.engagement(CLIENT, PROJECT)
    assert eng.root == tmp_path / "engagements" / CLIENT / PROJECT
    assert eng.record == eng.root / "engagement.json"
    assert eng.artifacts == eng.root / "artifacts"
    assert eng.threads == eng.root / "threads"
    art = eng.artifact("deck-1")
    assert art.root == eng.artifacts / "deck-1"
    assert art.artifact_id == "deck-1"
    assert art.current == art.root / "current.json"
    assert art.changelog == art.root / "changelog.json"
    assert art.versions == art.root / "versions"
    assert art.initial_version == art.versions / "initial.json"
    assert art.version("c0002") == art.versions / "c0002.json"
    assert art.renders == art.root / "renders"


def test_nothing_is_created_until_ensure(tmp_path: Path) -> None:
    eng = workspace_paths(tmp_path / "ws").engagement(CLIENT, PROJECT)
    art = eng.artifact("deck-1")
    assert not (tmp_path / "ws").exists()
    eng.ensure()
    assert eng.artifacts.is_dir() and not eng.threads.exists()
    art.ensure()
    assert art.versions.is_dir()


@pytest.mark.parametrize("bad", ["initial", "c1", "../c0001", "x0001"])
def test_version_names_must_be_entry_ids(tmp_path: Path, bad: str) -> None:
    art = workspace_paths(tmp_path).engagement(CLIENT, PROJECT).artifact("d")
    with pytest.raises(InvalidSegmentError):
        art.version(bad)


def test_engagement_names_are_checked(tmp_path: Path) -> None:
    with pytest.raises(InvalidSegmentError):
        workspace_paths(tmp_path).engagement("../evil", PROJECT)
    with pytest.raises(InvalidSegmentError):
        workspace_paths(tmp_path).engagement(CLIENT, PROJECT).artifact("a/b")


def test_guard_refuses_another_clients_workspace(tmp_path: Path) -> None:
    ws = workspace_paths(tmp_path)
    mine = ws.engagement(CLIENT, PROJECT)
    theirs = ws.engagement(OTHER_CLIENT, PROJECT).artifact("deck").current
    assert mine.foreign_client(theirs) == OTHER_CLIENT
    with pytest.raises(ClientIsolationError, match=OTHER_CLIENT):
        mine.guard(theirs)
    sneaky = mine.root / ".." / ".." / OTHER_CLIENT / PROJECT / "engagement.json"
    with pytest.raises(ClientIsolationError):
        mine.guard(sneaky)


def test_guard_allows_own_paths_other_projects_and_outside(tmp_path: Path) -> None:
    ws = workspace_paths(tmp_path)
    mine = ws.engagement(CLIENT, PROJECT)
    own = mine.artifact("deck").current
    assert mine.guard(own) == own
    other_project = ws.engagement(CLIENT, "another-project").record
    assert mine.foreign_client(other_project) is None
    outside = tmp_path.parent / "elsewhere.txt"
    assert mine.guard(outside) == outside
    assert mine.foreign_client(ws.engagements) is None


def test_engagement_keys_lists_only_engagements_with_a_record(tmp_path: Path) -> None:
    ws = workspace_paths(tmp_path)
    assert ws.engagement_keys() == []
    for client in (OTHER_CLIENT, CLIENT):
        eng = ws.engagement(client, PROJECT).ensure()
        eng.record.write_text("{}", encoding="utf-8")
    ws.engagement(CLIENT, "no-record").ensure()
    assert ws.engagement_keys() == [(OTHER_CLIENT, PROJECT), (CLIENT, PROJECT)]


def test_artifact_ids_lists_valid_directories_only(tmp_path: Path) -> None:
    eng = workspace_paths(tmp_path).engagement(CLIENT, PROJECT)
    assert eng.artifact_ids() == []
    eng.ensure()
    for name in ("b-deck", "a-deck", ".hidden"):
        (eng.artifacts / name).mkdir()
    (eng.artifacts / "stray.txt").write_text("x", encoding="utf-8")
    assert eng.artifact_ids() == ["a-deck", "b-deck"]


def test_workspace_must_not_overlap_the_knowledge_tree(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    for overlapping in (knowledge, knowledge / "ws", tmp_path):
        with pytest.raises(WorkspaceLocationError):
            check_workspace_location(overlapping, knowledge)
    check_workspace_location(tmp_path / "workspace", knowledge)
