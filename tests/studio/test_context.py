"""A thread's opening context: a pure function of on-disk state (plan §5.1)."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from autodeck.studio import context as context_module
from autodeck.studio.context import (
    ArtifactState,
    ContextInputs,
    Knowledge,
    build_context,
    gather_inputs,
    is_returning,
    open_items,
    render_context,
)
from autodeck.studio.conversation import ProposalRecord
from autodeck.studio.engagement import create_engagement
from autodeck.studio.models import ChangeEntry, ChangeLog, DeckArtifact, DiffItem
from autodeck.studio.proposals import ProposalStore
from tests.studio.helpers import ARTIFACT_ID, CLIENT, PROJECT, T0, T1, T2, with_text

DA, DB, DC = "a" * 64, "b" * 64, "c" * 64


def _deck() -> DeckArtifact:
    return DeckArtifact.model_validate(
        {
            "id": "deck",
            "client": CLIENT,
            "project": PROJECT,
            "title": "Readout",
            "brief": {"audience": "Board", "goal": "Approve", "marker": "decided"},
            "storyline": {
                "points": [{"id": "p1", "text": "First"}, {"id": "p2", "text": "Second"}]
            },
            "slides": [
                {
                    "id": "s1",
                    "intent": "Open",
                    "marker": "decided",
                    "serves": ["p1"],
                    "blocks": [{"id": "t", "kind": "text", "text": "Hello"}],
                },
                {"id": "s2", "blocks": []},
            ],
        }
    )


def _log() -> ChangeLog:
    def diff(*paths: str) -> list[DiffItem]:
        return [DiffItem(path=p, kind="changed", before="a", after="b") for p in paths]

    first = ChangeEntry(
        id="c0001",
        diff=[DiffItem(path="brief.audience", kind="changed", before="", after="Board")],
        instruction="Set the brief",
        thread_id="t0001",
        layer="direction",
        model_id="scripted",
        created_at=T1,
        before_digest=DA,
        after_digest=DB,
    )
    second = ChangeEntry(
        id="c0002",
        parent_id="c0001",
        diff=diff("d1", "d2", "d3", "d4", "d5"),
        instruction="Shorter",
        thread_id="t0001",
        layer="composition",
        model_id="scripted",
        created_at=T2,
        undone=True,
        before_digest=DB,
        after_digest=DC,
    )
    return ChangeLog(
        artifact_id="deck", initial_digest=DA, head="c0001", entries=[first, second]
    )


def _proposal(pid: str, **changes: Any) -> ProposalRecord:
    data: dict[str, Any] = {
        "id": pid,
        "thread_id": "t0001",
        "turn_id": "u0002",
        "artifact_id": "deck",
        "created_at": T1,
    }
    data.update(changes)
    return ProposalRecord.model_validate(data)


def _inputs() -> ContextInputs:
    candidate = {"id": "s1", "blocks": [{"id": "t", "kind": "text", "text": "41%"}]}
    return ContextInputs(
        client=CLIENT,
        project=PROJECT,
        title="Pilot",
        knowledge=Knowledge(
            project_md="# Project\n\nP text\n",
            client_md="# Client\n",
            value_prop_md="Value.\n",
            engagement_notes=("Note one.\n",),
        ),
        engagement_memory=(("Terms", ("KV cache: key-value cache (run r1)",)), ("People", ())),
        owner_memory=(("Note style", ()), ("Deck habits", ())),
        artifacts=(ArtifactState(_deck(), _log()),),
        proposals=(
            _proposal(
                "p0001",
                summary="Two openings",
                status="dismissed",
                resolved_by="owner",
                resolved_at=T2,
                options=[
                    {
                        "id": "A",
                        "label": "Number",
                        "text": "Open on the number.",
                        "candidates": [{"slide": candidate, "replaces": "s1"}],
                    },
                    {"id": "B", "label": "Question", "text": "Open on\nthe question."},
                ],
            ),
            _proposal(
                "p0002",
                artifact_id=None,
                summary="Tone",
                status="accepted",
                chosen="B",
                resolved_by="chat",
                resolved_at=T2,
                options=[
                    {"id": "A", "label": "Bold", "text": "Bold tone."},
                    {"id": "B", "label": "Plain", "text": "Plain tone."},
                ],
            ),
            _proposal(
                "p0003",
                thread_id="t0002",
                summary="Close",
                options=[{"id": "A", "label": "Ask", "text": "End on the ask."}],
            ),
        ),
    )


EXPECTED = """\
# Engagement

Client: northwind-retail · Project: llm-inference-efficiency · Pilot

## Client and project knowledge

### Project: llm-inference-efficiency

# Project

P text

### Client: northwind-retail

# Client

### Client value proposition

Value.

### Engagement note 1

Note one.

## Memory (read-only)

### This engagement

Terms:
- KV cache: key-value cache (run r1)

### How the owner works

(nothing yet)

# Artifacts

## deck

Deck `deck`: Readout (2 slides)
Brief [decided]: audience: Board | goal: Approve | notes: -
Storyline [provisional]:
  p1. First
  p2. Second
Design concept: none
Design system: none
Slides:
  1. s1 [decided] serves p1 | no layout | intent: Open
     "Hello"
  2. s2 [provisional] serves - | no layout | intent: -
     (no blocks)

### Recent changes (newest first)

- c0002 undone | composition | scripted | t0001 | Shorter
    ~ d1: 'a' -> 'b'
    ~ d2: 'a' -> 'b'
    ~ d3: 'a' -> 'b'
    (+2 more)
- c0001 live | direction | scripted | t0001 | Set the brief
    ~ brief.audience: '' -> 'Board'

# Proposals

Statuses:
- accepted: the owner picked one option and it was applied.
  The options they did not pick were not chosen; that is not a dismissal.
- dismissed: the owner turned down every option; nothing was applied.
- open: not yet decided.

## Dismissed

- p0001 (deck, thread t0001) [dismissed]: Two openings
  - A. Number: Open on the number. (1 candidate slide)
  - B. Question: Open on the question.

## Accepted

- p0002 (no artifact, thread t0001) [accepted: option B]: Tone
  - chosen: B. Plain
  - not chosen: A. Bold

## Open

- p0003 (deck, thread t0002) [open]: Close
  - A. Ask: End on the ask.

# Provisional, stale and open

- deck: the storyline is provisional
- deck: no design concept yet
- deck: slide 1 (s1) has no layout yet
- deck: slide 2 (s2) is provisional
- deck: slide 2 (s2) has no layout yet
- deck: storyline point p2 is not served by any slide
- proposal p0003 is open: Close
"""


def test_render_context_is_exact() -> None:
    assert render_context(_inputs()) == EXPECTED


def test_older_changes_are_counted_not_listed() -> None:
    text = render_context(_inputs(), recent_changes=1)
    assert "- c0002 undone" in text and "- c0001 live" not in text
    assert "- (1 earlier changes not shown)" in text


def test_an_empty_engagement() -> None:
    inputs = ContextInputs(
        client=CLIENT,
        project=PROJECT,
        title="",
        knowledge=Knowledge(project_md="P", client_md="C", value_prop_md="V"),
        engagement_memory=(("Terms", ()),),
        owner_memory=(),
        artifacts=(),
        proposals=(),
    )
    text = render_context(inputs)
    assert text.startswith(f"# Engagement\n\nClient: {CLIENT} · Project: {PROJECT}\n\n")
    assert "### Engagement note" not in text
    assert text.endswith(
        "# Artifacts\n\nNone yet.\n\n# Proposals\n\nNone.\n\n"
        "# Provisional, stale and open\n\nNothing.\n"
    )
    assert not is_returning(inputs)
    assert open_items(inputs) == []


def test_is_returning_and_open_items() -> None:
    inputs = _inputs()
    assert is_returning(inputs)
    assert open_items(inputs)[0] == "deck: the storyline is provisional"


def test_gather_reads_knowledge_memory_artifacts_and_proposals(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact, tmp_path: Path
) -> None:
    memory = knowledge_root / "clients" / CLIENT / "memory" / f"{PROJECT}.md"
    memory.parent.mkdir(parents=True)
    memory.write_text(
        "# Memory\n\n## Terms\n- Carlito: the dev font (run r1)\n", encoding="utf-8"
    )
    owner = tmp_path / "owner.md"
    owner.write_text("# Me\n\n## Deck habits\n- Short headlines\n", encoding="utf-8")
    engagement = create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )
    store = engagement.create_artifact(base_deck)
    store.apply(
        with_text(base_deck, "s2", "number", "38%"),
        instruction="Make it 38%",
        thread_id="t0001",
        layer="composition",
        model_id="scripted",
        now=T1,
    )
    ProposalStore(engagement).create(
        thread_id="t0001",
        turn_id="u0002",
        artifact_id=ARTIFACT_ID,
        summary="Two openings",
        options=_inputs().proposals[0].options,
        now=T1,
    )
    inputs = gather_inputs(engagement, owner_memory_path=owner)
    assert (
        inputs.knowledge.project_md == "# Project\n"
        and inputs.knowledge.client_md == f"# {CLIENT}\n"
    )
    assert ("Terms", ("Carlito: the dev font (run r1)",)) in inputs.engagement_memory
    assert ("Deck habits", ("Short headlines",)) in inputs.owner_memory
    assert [a.deck.id for a in inputs.artifacts] == [ARTIFACT_ID]
    assert inputs.artifacts[0].log.head == "c0001"
    assert [p.id for p in inputs.proposals] == ["p0001"]
    text = build_context(engagement, owner_memory_path=owner)
    assert text == render_context(inputs)
    assert "c0001 live | composition | scripted | t0001 | Make it 38%" in text
    assert not (knowledge_root / "clients" / CLIENT / "memory" / "audit.jsonl").exists()


def test_the_context_module_never_reads_threads() -> None:
    source = inspect.getsource(context_module)
    for forbidden in ("ThreadStore", "read_lines", "messages.jsonl", "studio.threads"):
        assert forbidden not in source.split('"""', 2)[2], forbidden


def test_an_accepted_proposal_is_never_worded_as_dismissed() -> None:
    context = render_context(_inputs())
    accepted = context.split("## Accepted\n\n")[1].split("\n\n## ")[0]
    assert "[accepted: option B]" in accepted and "chosen: B. Plain" in accepted
    assert "not chosen: A. Bold" in accepted and "dismissed" not in accepted
    assert "that is not a dismissal" in context
