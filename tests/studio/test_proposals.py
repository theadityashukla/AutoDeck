"""Proposals on disk: create, list, resolve once, isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.studio.conversation import ProposalOption, ProposalRecord
from autodeck.studio.engagement import Engagement, create_engagement
from autodeck.studio.errors import ProposalNotFoundError, ProposalStateError
from autodeck.studio.proposals import ProposalStore
from tests.studio.helpers import CLIENT, PROJECT, T0, T1, T2, load_fixture_deck


def _engagement(knowledge_root: Path, workspace_root: Path) -> Engagement:
    return create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )


def _options(with_slide: bool = False) -> list[ProposalOption]:
    slides = [load_fixture_deck().slides[1]] if with_slide else []
    return [
        ProposalOption(
            id="A", label="Lead with the number", text="Open on 41%.", slides=slides
        ),
        ProposalOption(id="B", label="Lead with the question", text="Open on the question."),
    ]


def _create(store: ProposalStore, **changes: object) -> ProposalRecord:
    args: dict = {
        "thread_id": "t0001",
        "turn_id": "u0002",
        "artifact_id": "deck",
        "summary": "Two ways to open",
        "options": _options(),
        "now": T1,
    }
    args.update(changes)
    return store.create(**args)


def test_create_load_list(knowledge_root: Path, workspace_root: Path) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    store = ProposalStore(engagement)
    first = _create(store, options=_options(with_slide=True))
    assert first.id == "p0001" and first.status == "open" and first.created_at == T1
    assert store.paths("p0001").record.is_file()
    assert store.load("p0001") == first
    second = _create(store, artifact_id=None)
    assert second.id == "p0002"
    assert [p.id for p in store.list()] == ["p0001", "p0002"]


def test_invalid_proposals_write_nothing(knowledge_root: Path, workspace_root: Path) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    store = ProposalStore(engagement)
    with pytest.raises(ValidationError):
        _create(store, summary="two\nlines")
    with pytest.raises(ValidationError):
        _create(store, options=_options(with_slide=True), artifact_id=None)
    assert engagement.paths.proposal_ids() == []


def test_accept_then_no_second_resolution(knowledge_root: Path, workspace_root: Path) -> None:
    store = ProposalStore(_engagement(knowledge_root, workspace_root))
    _create(store)
    accepted = store.resolve("p0001", status="accepted", chosen="B", by="owner", now=T2)
    assert (accepted.status, accepted.chosen, accepted.resolved_by, accepted.resolved_at) == (
        "accepted",
        "B",
        "owner",
        T2,
    )
    assert store.load("p0001") == accepted
    with pytest.raises(ProposalStateError, match="accepted"):
        store.resolve("p0001", status="dismissed", chosen=None, by="owner", now=T2)


def test_dismiss(knowledge_root: Path, workspace_root: Path) -> None:
    store = ProposalStore(_engagement(knowledge_root, workspace_root))
    _create(store)
    dismissed = store.resolve("p0001", status="dismissed", chosen=None, by="owner", now=T2)
    assert dismissed.status == "dismissed" and dismissed.chosen is None


@pytest.mark.parametrize(
    ("status", "chosen"),
    [("accepted", None), ("accepted", "C"), ("dismissed", "A"), ("maybe", None)],
)
def test_bad_resolutions_are_refused_and_write_nothing(
    knowledge_root: Path, workspace_root: Path, status: str, chosen: str | None
) -> None:
    store = ProposalStore(_engagement(knowledge_root, workspace_root))
    _create(store)
    before = store.paths("p0001").record.read_bytes()
    with pytest.raises(ProposalStateError):
        store.resolve("p0001", status=status, chosen=chosen, by="owner", now=T2)  # type: ignore[arg-type]
    assert store.paths("p0001").record.read_bytes() == before


def test_unknown_proposal(knowledge_root: Path, workspace_root: Path) -> None:
    store = ProposalStore(_engagement(knowledge_root, workspace_root))
    with pytest.raises(ProposalNotFoundError, match="p0009"):
        store.load("p0009")
    with pytest.raises(ProposalNotFoundError):
        store.resolve("p0009", status="dismissed", chosen=None, by="owner", now=T2)
