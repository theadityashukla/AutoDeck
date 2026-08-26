"""The planning session, and the rule that only a human ends it.

The load-bearing tests are `test_the_model_cannot_sign_its_own_brief` and
`test_signing_off_records_the_a7_gate`. A7 says the pipeline never approves its own work,
and the way this module means it is that `PlannerAction.ready_for_signoff` is never
consulted by `sign_off` — the model has no route to the approval at all, not merely a
discouraged one.

Second in importance: `test_the_probe_overrides_what_the_model_claims`. The planner may
propose key messages; it may not assert they are supported, or the one field the gap check
exists to produce could be filled in by the thing being checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.agents.evidence_gap import EvidenceClassification, EvidenceProbe
from autodeck.agents.planner import (
    BriefIncomplete,
    Draft,
    MessageDraft,
    PinDraft,
    PlannerAction,
    PlannerError,
    PlannerSession,
    RiskDraft,
    Transcript,
    resume_transcript,
)
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.ir.store import IRStoreError
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.pipeline.orchestrator import Gate, Orchestrator
from autodeck.retrieval.hybrid import build_index

MEMORY = (
    "LLM.int8() can cut the memory needed for inference by half while retaining full "
    "precision performance."
)
THROUGHPUT = "vLLM improves the LLM serving throughput by 2-4x over prior systems."

OBJECTIVE = "Decide whether to serve the model better or buy more GPUs."
AUDIENCE = "CTO and two engineering leads"


class ScriptedModel:
    """Replays a fixed list of actions, recording the prompts it was given."""

    def __init__(self, *actions: PlannerAction) -> None:
        self.actions = list(actions)
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        return self.actions.pop(0) if self.actions else PlannerAction(reply="...")


class AlwaysSupported:
    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        return EvidenceClassification(status="supported", reasoning="Fine.")


class Honest:
    """A classifier that returns a given verdict — used where the verdict is the point."""

    def __init__(self, status: str) -> None:
        self.status = status

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        return EvidenceClassification(
            status=self.status,  # type: ignore[arg-type]
            reasoning="The corpus measures memory, not cost in currency.",
        )


def context() -> AssembledContext:
    return AssembledContext(
        client="northwind-retail",
        project="llm-inference-efficiency",
        project_md="Serving cost, not training cost.",
        client_md="Mid-market retailer running a self-hosted assistant.",
        value_prop_md="Serve better before you buy more.",
    )


def probe_for(tmp_path: Path, *texts: str, classifier: object | None = None) -> EvidenceProbe:
    elements = [
        DocumentElement(
            element_id=f"e{i}",
            doc_id="paper-1",
            kind="text",
            page=i + 1,
            bbox=(72.0, 100.0, 523.0, 200.0),
            reading_order=i,
            text=text,
        )
        for i, text in enumerate(texts)
    ]
    document = Document(
        doc_id="paper-1", source_path="paper-1.pdf", page_count=8, elements=elements
    )
    store = DocumentStore(tmp_path / "corpus")
    store.add(document)
    return EvidenceProbe(
        index=build_index([document], project="llm-inference-efficiency"),
        store=store,
        classifier=classifier,  # type: ignore[arg-type]
    )


def session(tmp_path: Path, *actions: PlannerAction, probe: EvidenceProbe | None = None):  # type: ignore[no-untyped-def]
    orchestrator = Orchestrator("northwind-2026-08", runs_root=tmp_path / "runs")
    return PlannerSession(
        orchestrator,
        model=ScriptedModel(*actions),
        probe=probe or probe_for(tmp_path, MEMORY, THROUGHPUT),
        context=context(),
    )


def complete_action(**overrides) -> PlannerAction:  # type: ignore[no-untyped-def]
    payload = {
        "reply": "Here is the brief.",
        "objective": OBJECTIVE,
        "audience": AUDIENCE,
        "key_messages": [MessageDraft(id="km1", text=MEMORY)],
    }
    payload.update(overrides)
    return PlannerAction(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A7 — only a human ends the session
# ---------------------------------------------------------------------------


def test_the_model_cannot_sign_its_own_brief(tmp_path: Path) -> None:
    """`ready_for_signoff` is a suggestion. It approves nothing and ends nothing."""
    planning = session(tmp_path, complete_action(ready_for_signoff=True))

    reply = planning.turn("Draft the brief.")

    assert reply.suggests_signoff is True  # the model said so...
    assert planning.signed is False  # ...and nothing happened
    assert not planning.orchestrator.state.is_approved(Gate.BRIEF)
    with pytest.raises(IRStoreError, match="has no brief"):
        planning.store.load_brief()


def test_signing_off_records_the_a7_gate(tmp_path: Path) -> None:
    planning = session(tmp_path, complete_action())
    planning.turn("Draft the brief.")

    brief = planning.sign_off(approver="aditya")

    assert brief.approved_by == "aditya"
    assert planning.orchestrator.state.is_approved(Gate.BRIEF)
    assert planning.store.load_brief().approved_by == "aditya"


def test_sign_off_needs_a_name(tmp_path: Path) -> None:
    """An approval with nobody's name on it is not an approval."""
    planning = session(tmp_path, complete_action())
    planning.turn("Draft it.")
    for empty in ("", "   "):
        with pytest.raises(PlannerError, match="needs the name"):
            planning.sign_off(approver=empty)


def test_sign_off_ignores_the_models_opinion_entirely(tmp_path: Path) -> None:
    """Sign-off works when the model said it was NOT ready, and is refused when it said it
    was but the brief is invalid. The flag is simply not part of the decision."""
    planning = session(tmp_path, complete_action(ready_for_signoff=False))
    planning.turn("Draft it.")
    assert planning.sign_off(approver="aditya").approved_by == "aditya"


def test_a_signed_brief_cannot_be_edited(tmp_path: Path) -> None:
    """Editing after sign-off would invalidate the approval GATE 1 reviews against."""
    planning = session(tmp_path, complete_action(), complete_action())
    planning.turn("Draft it.")
    planning.sign_off(approver="aditya")

    with pytest.raises(PlannerError, match="signed off"):
        planning.turn("Actually, change the objective.")


def test_an_unaccounted_gap_blocks_sign_off(tmp_path: Path) -> None:
    """The A8 schema rule reaching the session: carrying a weak message is allowed, but
    only with a recorded risk.

    Uses `thin` rather than `unsupported` because it is the realistic blocking case — the
    corpus *does* discuss inference cost, just not on the terms this message states.
    """
    planning = session(
        tmp_path,
        complete_action(
            key_messages=[MessageDraft(id="km1", text="Inference cost falls 90%.")],
            probe_messages=True,
        ),
        probe=probe_for(tmp_path, MEMORY, THROUGHPUT, classifier=Honest("thin")),
    )
    planning.turn("Draft it.")

    assert planning.draft.key_messages[0].evidence_status == "thin"
    assert planning.draft.unaccounted_gaps()
    with pytest.raises(BriefIncomplete, match="cannot be signed off"):
        planning.sign_off(approver="aditya")


def test_a_message_nobody_probed_does_not_block_sign_off(tmp_path: Path) -> None:
    """`unprobed` is honest, not a failure — the owner may sign a brief nobody checked.

    GATE 1 is where that gets noticed, via `DeckBrief.unprobed_messages()`. Blocking here
    would make skipping the probe impossible rather than visible, and the difference
    matters: a planner that cannot proceed is a planner people work around.
    """
    planning = session(
        tmp_path,
        complete_action(
            key_messages=[MessageDraft(id="km1", text="Inference cost falls 90%.")],
            probe_messages=True,
        ),
        probe=probe_for(tmp_path, MEMORY, THROUGHPUT),  # no classifier
    )
    planning.turn("Draft it.")

    assert planning.draft.key_messages[0].evidence_status == "unprobed"
    brief = planning.sign_off(approver="aditya")
    assert [m.id for m in brief.unprobed_messages()] == ["km1"]


def test_a_recorded_risk_unblocks_sign_off(tmp_path: Path) -> None:
    planning = session(
        tmp_path,
        complete_action(
            key_messages=[MessageDraft(id="km1", text="Inference cost falls 90%.")],
            probe_messages=True,
            open_risks=[
                RiskDraft(
                    message_id="km1",
                    description="Nothing in the corpus measures cost in currency.",
                    accepted_by="aditya",
                )
            ],
        ),
    )
    planning.turn("Draft it, I'll carry the risk.")

    brief = planning.sign_off(approver="aditya")
    assert brief.open_risks[0].accepted_by == "aditya"


# ---------------------------------------------------------------------------
# The probe, not the model, sets evidence status
# ---------------------------------------------------------------------------


def test_the_probe_overrides_what_the_model_claims(tmp_path: Path) -> None:
    """`MessageDraft` has no evidence_status field at all — the planner cannot assert it."""
    assert "evidence_status" not in MessageDraft.model_fields

    planning = session(
        tmp_path,
        complete_action(
            key_messages=[MessageDraft(id="km1", text="Photosynthesis is efficient.")],
            probe_messages=True,
        ),
    )
    planning.turn("Draft it.")
    assert planning.draft.key_messages[0].evidence_status == "unsupported"


def test_probing_is_recorded_in_the_transcript(tmp_path: Path) -> None:
    """The audit trail for why a message was carried or dropped."""
    planning = session(
        tmp_path,
        complete_action(probe_messages=True),
        probe=probe_for(tmp_path, MEMORY, THROUGHPUT, classifier=AlwaysSupported()),
    )
    planning.turn("Check the evidence.")

    roles = [turn.role for turn in planning.transcript.turns]
    assert "probe" in roles


def test_re_proposing_a_message_does_not_reset_its_verdict(tmp_path: Path) -> None:
    """Otherwise a `thin` message could shed its risk by being mentioned again."""
    planning = session(
        tmp_path,
        complete_action(probe_messages=True),
        complete_action(reply="Same messages, tightened wording elsewhere."),
        probe=probe_for(tmp_path, MEMORY, THROUGHPUT, classifier=AlwaysSupported()),
    )
    planning.turn("Check the evidence.")
    before = planning.draft.key_messages[0].evidence_status

    planning.turn("Keep going.")
    assert planning.draft.key_messages[0].evidence_status == before


def test_no_probe_runs_unless_asked(tmp_path: Path) -> None:
    planning = session(tmp_path, complete_action(probe_messages=False))
    assert planning.turn("Draft it.").probes == []


# ---------------------------------------------------------------------------
# Layout pins (2a.5)
# ---------------------------------------------------------------------------


def test_a_pin_persists_into_the_brief(tmp_path: Path) -> None:
    planning = session(
        tmp_path,
        complete_action(
            layout_pins=[
                PinDraft(
                    message_id="km1",
                    target="component",
                    value="big_number",
                    rationale="They want the 2-4x to land visually.",
                )
            ]
        ),
    )
    planning.turn("Make that one the big number slide.")
    brief = planning.sign_off(approver="aditya")

    assert brief.pins_for("km1")[0].value == "big_number"


def test_a_pin_on_an_unknown_message_is_dropped(tmp_path: Path) -> None:
    """It would otherwise fail brief construction at sign-off, long after the mistake."""
    planning = session(
        tmp_path,
        complete_action(
            layout_pins=[PinDraft(message_id="ghost", target="component", value="x")]
        ),
    )
    planning.turn("Pin it.")
    assert planning.draft.layout_pins == []


def test_a_pin_with_an_invalid_target_is_dropped(tmp_path: Path) -> None:
    planning = session(
        tmp_path,
        complete_action(
            layout_pins=[PinDraft(message_id="km1", target="font_size", value="48pt")]
        ),
    )
    planning.turn("Pin it.")
    assert planning.draft.layout_pins == []


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


def test_every_turn_reaches_disk_immediately(tmp_path: Path) -> None:
    """A transcript flushed at the end is a transcript lost on a crash."""
    planning = session(tmp_path, complete_action())
    planning.turn("What do you need to know?")

    lines = planning.transcript.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    assert json.loads(lines[0])["role"] == "human"


def test_the_human_turn_is_written_before_the_model_is_called(tmp_path: Path) -> None:
    """A crash inside the provider call must not lose what they said."""

    class Exploding:
        def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider down")

    orchestrator = Orchestrator("northwind-2026-08", runs_root=tmp_path / "runs")
    planning = PlannerSession(
        orchestrator,
        model=Exploding(),  # type: ignore[arg-type]
        probe=probe_for(tmp_path, MEMORY),
        context=context(),
    )
    with pytest.raises(RuntimeError):
        planning.turn("Something I do not want to retype.")

    assert "do not want to retype" in planning.transcript.path.read_text(encoding="utf-8")


def test_a_transcript_can_be_read_back(tmp_path: Path) -> None:
    planning = session(tmp_path, complete_action())
    planning.turn("Hello.")
    assert [t.role for t in resume_transcript(planning.orchestrator)][:2] == [
        "human",
        "planner",
    ]


def test_a_malformed_transcript_line_is_skipped(tmp_path: Path) -> None:
    """A partial write from a hard kill must not make the whole record unreadable."""
    path = tmp_path / "planner.jsonl"
    path.write_text(
        '{"role": "human", "text": "one", "at": ""}\n{"role": "planner", "tex\n',
        encoding="utf-8",
    )
    assert [turn.text for turn in Transcript(path).load()] == ["one"]


# ---------------------------------------------------------------------------
# Prompt and context
# ---------------------------------------------------------------------------


def test_the_prompt_carries_the_client_context(tmp_path: Path) -> None:
    planning = session(tmp_path, complete_action())
    planning.turn("Start.")
    assert "Mid-market retailer" in planning.model.prompts[0]  # type: ignore[attr-defined]


def test_unresolved_gaps_are_put_in_front_of_the_model(tmp_path: Path) -> None:
    """So the next turn raises them rather than drifting past."""
    planning = session(
        tmp_path,
        complete_action(
            key_messages=[MessageDraft(id="km1", text="Cost falls 90%.")], probe_messages=True
        ),
        complete_action(reply="About that gap..."),
    )
    planning.turn("Draft it.")
    planning.turn("Carry on.")

    assert "Unresolved evidence gaps" in planning.model.prompts[1]  # type: ignore[attr-defined]


def test_a_missing_prompt_file_is_a_hard_error(tmp_path: Path) -> None:
    """Plan §0.5: prompts are versioned files hashed into the manifest (A6). An inline
    fallback would make a deck reproducible against a prompt nobody recorded."""
    orchestrator = Orchestrator("r", runs_root=tmp_path / "runs")
    with pytest.raises(PlannerError, match="no inline fallback"):
        PlannerSession(
            orchestrator,
            model=ScriptedModel(),
            probe=probe_for(tmp_path, MEMORY),
            context=context(),
            prompt_path=tmp_path / "nope.md",
        )


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------


def test_a_draft_may_be_invalid_while_the_conversation_runs() -> None:
    """Forcing the schema every turn would mean weakening it or refusing half-thoughts."""
    draft = Draft()
    assert draft.key_messages == []
    with pytest.raises(ValidationError):
        draft.to_brief("r")
