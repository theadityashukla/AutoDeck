"""Phase 1 path helpers: threads, proposals, render directories (implemented by the lead)."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.studio.errors import InvalidSegmentError
from autodeck.studio.paths import workspace_paths
from tests.studio.helpers import CLIENT, PROJECT


def test_thread_and_proposal_paths(workspace_root: Path) -> None:
    engagement = workspace_paths(workspace_root).engagement(CLIENT, PROJECT)
    thread = engagement.thread("t0001")
    assert thread.root == engagement.root / "threads" / "t0001"
    assert thread.record.name == "thread.json"
    assert thread.messages.name == "messages.jsonl"
    assert thread.context.name == "context.md"
    proposal = engagement.proposal("p0002")
    assert proposal.root == engagement.root / "proposals" / "p0002"
    assert proposal.record.name == "proposal.json"
    assert proposal.option_renders("B") == proposal.root / "renders" / "B"


@pytest.mark.parametrize("bad", ["t1", "../t0001", "t0001/x", "thread", ""])
def test_thread_ids_are_checked(workspace_root: Path, bad: str) -> None:
    with pytest.raises(InvalidSegmentError):
        workspace_paths(workspace_root).engagement(CLIENT, PROJECT).thread(bad)


def test_proposal_option_and_digest_checks(workspace_root: Path) -> None:
    engagement = workspace_paths(workspace_root).engagement(CLIENT, PROJECT)
    with pytest.raises(InvalidSegmentError):
        engagement.proposal("p1")
    with pytest.raises(InvalidSegmentError):
        engagement.proposal("p0001").option_renders("E")
    artifact = engagement.artifact("deck")
    assert artifact.render_dir("0123456789ab") == artifact.renders / "0123456789ab"
    for bad in ("0123456789AB", "0123", "../0123456789", "0123456789abc"):
        with pytest.raises(InvalidSegmentError):
            artifact.render_dir(bad)


def test_listings_skip_what_is_not_an_id(workspace_root: Path) -> None:
    engagement = workspace_paths(workspace_root).engagement(CLIENT, PROJECT)
    assert engagement.thread_ids() == [] and engagement.proposal_ids() == []
    for name in ("t0002", "t0001", "notes", ".t0003"):
        (engagement.threads / name).mkdir(parents=True)
    (engagement.threads / "t0004").write_text("a file, not a thread")
    for name in ("p0001", "tmp"):
        (engagement.proposals / name).mkdir(parents=True)
    assert engagement.thread_ids() == ["t0001", "t0002"]
    assert engagement.proposal_ids() == ["p0001"]
    created = engagement.thread("t0009").ensure()
    assert created.root.is_dir()
