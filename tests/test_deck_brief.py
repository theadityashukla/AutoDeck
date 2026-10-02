"""The DeckBrief — and the rule that an accepted evidence gap cannot go missing.

The load-bearing test is `test_a_weakly_supported_message_needs_a_recorded_risk`. Plan §7
Phase 2a allows the owner to carry a key message with no support — and says the gap **is
not allowed to disappear**. That pairing is what the schema encodes: carrying it is free,
carrying it silently is impossible.

Written against the same posture as `test_ir_models.py`: the invariant is a property of the
type, so the test constructs the bad object and asserts pydantic refuses it, rather than
calling a checker that a later pass might forget.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.ir.models import DeckBrief, KeyMessage, LayoutPin, OpenRisk
from autodeck.ir.store import (
    IRStore,
    IRStoreError,
    dump_brief_yaml,
    load_brief_yaml,
)

OBJECTIVE = "Decide whether to serve the model better or buy more GPUs."
AUDIENCE = "CTO and two engineering leads"


def message(
    message_id: str = "km1",
    text: str = "KV-cache waste is the binding constraint on throughput.",
    status: str = "supported",
) -> KeyMessage:
    return KeyMessage(id=message_id, text=text, evidence_status=status)  # type: ignore[arg-type]


def brief(*messages: KeyMessage, **overrides: object) -> DeckBrief:
    payload: dict[str, object] = {
        "run_id": "northwind-2026-08",
        "objective": OBJECTIVE,
        "audience": AUDIENCE,
        "key_messages": list(messages) or [message()],
    }
    payload.update(overrides)
    return DeckBrief(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A8 — gaps are recorded, never dropped
# ---------------------------------------------------------------------------


def test_a_weakly_supported_message_needs_a_recorded_risk() -> None:
    """The phase's reason for existing, as a schema constraint."""
    for status in ("unsupported", "thin"):
        with pytest.raises(ValidationError, match="no matching entry in open_risks"):
            brief(message(status=status))


def test_carrying_an_unsupported_message_is_allowed_when_the_gap_is_recorded() -> None:
    """Blocking it would push the planner to mark things supported to get past the check.

    That is the failure A8 is about, so the rule demands a receipt rather than a retreat.
    """
    accepted = brief(
        message(status="unsupported"),
        open_risks=[
            OpenRisk(
                message_id="km1",
                description="No source in the corpus measures this on GPU hardware.",
                accepted_by="owner",
                mitigation="State it as an inference from TPU results, not a measurement.",
            )
        ],
    )
    assert accepted.key_messages[0].evidence_status == "unsupported"
    assert accepted.open_risks[0].accepted_by == "owner"


def test_an_accepted_risk_must_name_who_accepted_it() -> None:
    """A gap with nobody's name on it is unaccounted, not accepted (A7)."""
    with pytest.raises(ValidationError):
        OpenRisk(message_id="km1", description="no source", accepted_by="")


def test_unprobed_is_distinct_from_unsupported() -> None:
    """ "Nobody looked" and "somebody looked and found nothing" are different facts.

    Collapsing them would let a brief that skipped the evidence check read exactly like one
    that passed it — so `unprobed` needs no risk, and is surfaced separately for GATE 1.
    """
    drafted = brief(message(status="unprobed"))
    assert [m.id for m in drafted.unprobed_messages()] == ["km1"]
    assert not drafted.key_messages[0].needs_a_risk()


def test_a_risk_for_a_message_that_does_not_exist_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown key messages"):
        brief(
            message(),
            open_risks=[OpenRisk(message_id="ghost", description="x", accepted_by="owner")],
        )


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_a_brief_needs_at_least_one_key_message() -> None:
    with pytest.raises(ValidationError):
        DeckBrief(run_id="r", objective=OBJECTIVE, audience=AUDIENCE, key_messages=[])


def test_duplicate_message_ids_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate key message ids"):
        brief(message("km1"), message("km1", text="Something else."))


def test_a_pin_for_a_message_that_does_not_exist_is_refused() -> None:
    """A pin on a deleted message is a decision nobody will ever see fail."""
    with pytest.raises(ValidationError, match="unknown key messages"):
        brief(
            message(),
            layout_pins=[LayoutPin(message_id="ghost", target="component", value="x")],
        )


def test_pins_are_retrievable_per_message() -> None:
    pinned = brief(
        message("km1"),
        message("km2", text="Speculative decoding preserves outputs exactly."),
        layout_pins=[
            LayoutPin(message_id="km1", target="component", value="big_number"),
            LayoutPin(message_id="km1", target="communication_mode", value="text_led"),
            LayoutPin(message_id="km2", target="diagram_kind", value="process_flow"),
        ],
    )
    assert [p.value for p in pinned.pins_for("km1")] == ["big_number", "text_led"]
    assert pinned.message("km2") is not None
    assert pinned.message("nope") is None


def test_an_unknown_field_is_rejected() -> None:
    """`extra="forbid"`: the brief is LLM-writable, and an invented field must fail loudly."""
    with pytest.raises(ValidationError):
        DeckBrief(
            run_id="r",
            objective=OBJECTIVE,
            audience=AUDIENCE,
            key_messages=[message()],
            tone="punchy",  # type: ignore[call-arg]
        )


def test_approval_is_absent_by_default() -> None:
    """A7: nothing constructs an approved brief. Approval is a separate recorded act."""
    assert brief().approved_by is None


# ---------------------------------------------------------------------------
# YAML round-trip and versioning
# ---------------------------------------------------------------------------


def full_brief() -> DeckBrief:
    return brief(
        message("km1"),
        message("km2", text="Quantisation is the cheapest first phase.", status="thin"),
        must_include=["cost per conversation"],
        must_avoid=["compound multipliers"],
        length_target=12,
        header_style="assertion",
        layout_pins=[LayoutPin(message_id="km1", target="component", value="big_number")],
        open_risks=[
            OpenRisk(
                message_id="km2",
                description="One source, and it measures memory rather than latency.",
                accepted_by="owner",
            )
        ],
    )


def test_a_brief_round_trips_through_yaml() -> None:
    assert load_brief_yaml(dump_brief_yaml(full_brief())) == full_brief()


def test_the_yaml_leads_with_the_objective() -> None:
    """Field order is declaration order, not alphabetical — a reader opens this file to
    find out what the deck is for, and sorting would bury that under `approved_by`."""
    lines = [line for line in dump_brief_yaml(full_brief()).splitlines() if line]
    assert lines[0].startswith("run_id:")
    assert any(line.startswith("objective:") for line in lines[:4])


def test_malformed_yaml_fails_with_a_useful_message() -> None:
    with pytest.raises(IRStoreError, match="not valid YAML"):
        load_brief_yaml("key_messages: [oops\n")


def test_a_yaml_list_is_not_a_brief() -> None:
    with pytest.raises(IRStoreError, match="must be a YAML mapping"):
        load_brief_yaml("- a\n- b\n")


def test_a_hand_edited_brief_still_enforces_the_gap_rule() -> None:
    """The realistic failure: the owner edits the file and deletes the risk they accepted.

    Sign-off happens by editing this YAML, so the invariant has to survive the edit — not
    just the construction path the planner used.
    """
    text = dump_brief_yaml(full_brief()).replace("open_risks:", "removed_risks:")
    with pytest.raises(ValidationError):
        load_brief_yaml(text)


def test_brief_versions_are_immutable(tmp_path: Path) -> None:
    """A brief that changed after sign-off would silently invalidate the approval."""
    store = IRStore(tmp_path, "northwind-2026-08")
    store.save_brief(full_brief())
    with pytest.raises(IRStoreError, match="immutable"):
        store.save_brief(full_brief())


def test_briefs_version_like_the_ir(tmp_path: Path) -> None:
    store = IRStore(tmp_path, "northwind-2026-08")
    assert store.next_brief_version() == 1
    store.save_brief(full_brief())
    assert store.brief_versions() == [1]
    assert store.next_brief_version() == 2

    revised = full_brief().model_copy(update={"version": 2, "length_target": 14})
    store.save_brief(revised)

    assert store.brief_versions() == [1, 2]
    assert store.load_brief().length_target == 14  # latest by default
    assert store.load_brief(1).length_target == 12  # the version that was signed off


def test_a_brief_for_another_run_is_refused(tmp_path: Path) -> None:
    store = IRStore(tmp_path, "some-other-run")
    with pytest.raises(IRStoreError, match="does not match store run"):
        store.save_brief(full_brief())


def test_loading_a_brief_that_does_not_exist_says_so(tmp_path: Path) -> None:
    store = IRStore(tmp_path, "northwind-2026-08")
    with pytest.raises(IRStoreError, match="has no brief"):
        store.load_brief()
