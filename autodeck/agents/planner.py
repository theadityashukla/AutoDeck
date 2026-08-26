"""The planning session: a conversation that ends in a signed brief (tasks 2a.3, 2a.5, 2a.8).

This is the **first place a human touches the pipeline**, and §6.13 makes its
conversational quality an explicit goal — whether the system feels like a colleague or a
form is decided here. The prompt (`prompts/planner.md`) carries that half. This module
carries the half that must not depend on a model behaving well.

## Three things the code guarantees, not the prompt

1. **Only a human ends the session.** The model can set `ready_for_signoff`, and that is a
   *suggestion* — it moves nothing. `sign_off()` is a separate call taking an approver's
   name, and it is the only path to a completed brief. There is no flag, no
   `auto_approve`, and `ready_for_signoff` is deliberately never consulted by `sign_off`.
   A7 says the pipeline never approves its own work; the way to mean that is to give the
   model no route to the approval at all.

2. **Every turn is on disk before the next one starts.** The transcript is what the audit
   report points at when someone asks why a message with no evidence is in the deck. A
   transcript flushed at the end is a transcript lost on a crash — so it is appended per
   turn, and the session can be reconstructed from it.

3. **Evidence status is set by the probe, not by the model's draft.** The planner may
   propose key messages; it may not assert that they are supported. Every draft message
   goes through `EvidenceProbe`, and the probe's verdict overwrites whatever the model
   wrote. Otherwise the one field the gap check exists to produce could be filled in by
   the thing being checked.

## What proceeds without a signed brief

Nothing. `Orchestrator.require_gate(Gate.BRIEF)` guards the outline stage, and
`sign_off()` is what records that approval. The brief is written as an immutable version
and stamped with the approver, so GATE 1 later reviews an outline against a brief that
provably has not moved since it was signed.

Owning phase: 2a (tasks 2a.3, 2a.5, 2a.8).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.evidence_gap import EvidenceProbe, ProbeResult
from autodeck.ir.models import DeckBrief, KeyMessage, LayoutPin, OpenRisk
from autodeck.ir.store import IRStore
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.pipeline.orchestrator import Gate, Orchestrator

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/planner.md")

#: Appended to the end of every turn prompt.
#:
#: The same instruction is in `prompts/planner.md`, which is where it belongs — but the
#: system prompt is long, and the turn prompt puts several thousand words of curated
#: knowledge in front of it. In the first live run the model produced a genuinely good brief
#: entirely as prose in `reply` and left every structured field null, twice, on two
#: different models. Restating it last, closest to generation, is what stopped that.
#:
#: It lives here rather than in the prompt file because it is *positional*: the point is
#: that it arrives after the context, and a prompt file cannot express that.
_FIELD_REMINDER = """\
# Before you answer

`reply` is what the consultant reads. The other fields ARE the brief — they are what gets
recorded and signed off, and anything you write only in `reply` does not exist.

If this turn changes the brief, set the fields: `objective`, `audience`, `key_messages`
(the complete current set, with stable ids), `must_include`, `must_avoid`, `length_target`,
`layout_pins`, `open_risks`. To have the evidence checked, set `probe_messages: true` —
saying you checked it in prose does not check it."""


class PlannerError(RuntimeError):
    """The planning session cannot proceed."""


class BriefIncomplete(PlannerError):
    """Sign-off was attempted on a brief that is not yet valid.

    Carries pydantic's message, which for the common case says exactly which key message
    has weak evidence and no recorded risk.
    """


# ---------------------------------------------------------------------------
# What the model may propose
# ---------------------------------------------------------------------------


class MessageDraft(BaseModel):
    """A key message the planner proposes.

    Note what is absent: `evidence_status`. The planner does not get to say whether its own
    proposal is supported — `EvidenceProbe` decides, and the field is filled from the
    probe. Letting the model write it would make the gap check advisory.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PinDraft(BaseModel):
    """A layout pin the human asked for (task 2a.5).

    Only recorded when the human actually asked. The prompt says so; this model exists so
    that what they asked for survives into the brief in a shape the outline agent reads.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    target: str = Field(min_length=1, description="component, communication_mode, diagram_kind")
    value: str = Field(min_length=1)
    rationale: str | None = None


class RiskDraft(BaseModel):
    """A gap the human agreed to carry.

    `accepted_by` is required here as it is on `OpenRisk`. If the planner has not been given
    a name, it must ask for one rather than invent it — a risk accepted by nobody is an
    unaccounted risk wearing a receipt.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    accepted_by: str = Field(min_length=1)
    mitigation: str | None = None


class PlannerAction(BaseModel):
    """One turn of the planner's output — the whole brief state, not a delta.

    **Every brief field is required and non-nullable, and that is load-bearing.** Gemini
    populates a nullable nested array (`list[Model] | None`) only sometimes: across three
    models and several attempts, `key_messages`, `layout_pins` and `open_risks` were
    omitted from most responses while plain scalars in the same object arrived every time.
    No error is raised — the field is simply absent — so the session read perfectly and
    recorded nothing. Making the fields required is what makes them arrive.

    The cost is that the model restates the full brief each turn. That was already the
    documented contract ("the complete current set, not a delta"), so it changes the
    reliability rather than the protocol.

    **Empty means "unchanged", not "cleared".** A brief cannot legitimately drop to zero key
    messages, so an empty list is far more likely to be a model that omitted them than an
    intention to wipe them — and treating it as a wipe would silently destroy a brief the
    consultant had been building for ten minutes. Clearing a list is done by editing the
    signed YAML, which is a deliberate act with a diff.
    """

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, description="What to say to the consultant.")
    objective: str = Field(description="The decision this deck should produce. '' = unchanged.")
    audience: str = Field(description="Who it is for. '' = unchanged.")
    key_messages: list[MessageDraft] = Field(
        description="The COMPLETE current set every turn, not a delta. [] = unchanged."
    )
    must_include: list[str] = Field(default_factory=list, description="[] = unchanged.")
    must_avoid: list[str] = Field(default_factory=list, description="[] = unchanged.")
    length_target: int | None = Field(default=None, ge=1)
    header_style: str | None = None
    layout_pins: list[PinDraft] = Field(default_factory=list, description="[] = unchanged.")
    open_risks: list[RiskDraft] = Field(default_factory=list, description="[] = unchanged.")
    probe_messages: bool = Field(
        default=False,
        description="Run the evidence-gap check over the current key messages this turn.",
    )
    ready_for_signoff: bool = Field(
        default=False,
        description=(
            "A suggestion that the brief looks complete. It approves nothing and ends "
            "nothing — only a human calling sign_off does that (A7)."
        ),
    )


class PlannerModel(Protocol):
    """What the session needs from a provider."""

    def complete_structured(
        self,
        prompt: str,
        response_model: type[PlannerAction],
        *,
        system: str | None = None,
    ) -> PlannerAction: ...  # pragma: no cover — protocol shape only


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Turn:
    """One exchange, as it goes to disk."""

    role: str
    text: str
    at: str

    def as_json(self) -> str:
        return json.dumps({"role": self.role, "text": self.text, "at": self.at})


class Transcript:
    """The planning conversation, appended to disk as it happens.

    JSONL rather than a single JSON document so that an interrupted session leaves a
    readable partial record instead of a truncated object that will not parse. The audit
    report points at this when someone asks why a message with no evidence is in the deck,
    and a record that only exists if the session exited cleanly is not an audit trail.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.turns: list[Turn] = []

    def append(self, role: str, text: str) -> Turn:
        turn = Turn(role=role, text=text, at=datetime.now(UTC).isoformat())
        self.turns.append(turn)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(turn.as_json() + "\n")
        return turn

    def load(self) -> list[Turn]:
        """Read an existing transcript back, for resuming or for audit."""
        if not self.path.exists():
            return []
        turns: list[Turn] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("skipping malformed transcript line in %s", self.path)
                continue
            turns.append(
                Turn(role=payload["role"], text=payload["text"], at=payload.get("at", ""))
            )
        self.turns = turns
        return turns

    def render(self, limit: int | None = None) -> str:
        """The conversation so far, as the model's context."""
        turns = self.turns[-limit:] if limit else self.turns
        return "\n\n".join(f"{turn.role.upper()}: {turn.text}" for turn in turns)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    """The brief as it stands mid-conversation.

    Separate from `DeckBrief` because a brief under construction is legitimately invalid —
    no key messages yet, a gap not yet discussed — and forcing it through the schema every
    turn would mean either weakening the schema or refusing to hold a half-finished
    thought. The schema applies at sign-off, which is when it means something.
    """

    objective: str = ""
    audience: str = ""
    key_messages: list[KeyMessage] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    must_avoid: list[str] = field(default_factory=list)
    length_target: int | None = None
    header_style: str | None = None
    layout_pins: list[LayoutPin] = field(default_factory=list)
    open_risks: list[OpenRisk] = field(default_factory=list)

    def message(self, message_id: str) -> KeyMessage | None:
        return next((m for m in self.key_messages if m.id == message_id), None)

    def unaccounted_gaps(self) -> list[KeyMessage]:
        """Weak messages with no recorded risk — what blocks sign-off, listed."""
        excused = {risk.message_id for risk in self.open_risks}
        return [m for m in self.key_messages if m.needs_a_risk() and m.id not in excused]

    def to_brief(self, run_id: str, *, version: int = 1) -> DeckBrief:
        """Build the real brief. Raises if it is not yet valid."""
        return DeckBrief(
            run_id=run_id,
            version=version,
            objective=self.objective,
            audience=self.audience,
            key_messages=self.key_messages,
            must_include=self.must_include,
            must_avoid=self.must_avoid,
            length_target=self.length_target,
            header_style=self.header_style,
            layout_pins=self.layout_pins,
            open_risks=self.open_risks,
        )


@dataclass
class PlannerReply:
    """What one turn produced, for the CLI to render."""

    text: str
    probes: list[ProbeResult] = field(default_factory=list)
    suggests_signoff: bool = False
    """The model's opinion that the brief looks done. Never acted on automatically."""


class PlannerSession:
    """One planning conversation, bound to one run and one client namespace."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        model: PlannerModel,
        probe: EvidenceProbe,
        context: AssembledContext,
        prompt_path: Path = PROMPT_PATH,
    ) -> None:
        self.orchestrator = orchestrator
        self.model = model
        self.probe = probe
        self.context = context
        self.draft = Draft()
        # The orchestrator already owns the run's store; building a second one from a
        # guessed root is how two components end up writing to different directories.
        self.store: IRStore = orchestrator.ir
        self.transcript = Transcript(orchestrator.paths.logs / "planner.jsonl")
        self.system_prompt = _read_prompt(prompt_path)
        self.signed = False

    # -- conversation ------------------------------------------------------

    def turn(self, user_text: str) -> PlannerReply:
        """Take one turn of the conversation.

        The user's words go to disk before the model is called, so a crash mid-request
        still leaves what they said.
        """
        if self.signed:
            raise PlannerError(
                "this brief has been signed off. Start a new run to change it — editing a "
                "signed brief would invalidate the approval GATE 1 reviews against."
            )

        self.transcript.append("human", user_text)
        action = self.model.complete_structured(
            self._prompt(), PlannerAction, system=self.system_prompt
        )
        self.transcript.append("planner", action.reply)

        self._apply(action)
        probes = self._probe_if_asked(action)

        return PlannerReply(
            text=action.reply, probes=probes, suggests_signoff=action.ready_for_signoff
        )

    def _prompt(self) -> str:
        parts = [
            "# Curated knowledge for this build\n\n" + self.context.to_prompt_context(),
            "# Brief so far\n\n" + render_draft(self.draft),
            "# Conversation\n\n" + self.transcript.render(),
        ]
        gaps = self.draft.unaccounted_gaps()
        if gaps:
            parts.append(
                "# Unresolved evidence gaps\n\nThese messages have weak or absent support "
                "and no recorded risk. The brief cannot be signed until each is softened, "
                "sourced, or carried with somebody's name on it:\n"
                + "\n".join(f"- {m.id}: {m.text} ({m.evidence_status})" for m in gaps)
            )
        parts.append(_FIELD_REMINDER)
        return "\n\n---\n\n".join(parts)

    def _apply(self, action: PlannerAction) -> None:
        """Fold the model's proposals into the draft.

        Empty means "unchanged" throughout — see `PlannerAction` for why. Every field is
        required in the schema so that it actually arrives; the emptiness check is what
        stops a turn that only answers a question from wiping the brief.

        Key messages keep the evidence status they already had. A re-proposal of the same
        message must not quietly reset a `thin` verdict to `unprobed` and thereby shed the
        risk attached to it.
        """
        if action.objective.strip():
            self.draft.objective = action.objective.strip()
        if action.audience.strip():
            self.draft.audience = action.audience.strip()
        if action.must_include:
            self.draft.must_include = action.must_include
        if action.must_avoid:
            self.draft.must_avoid = action.must_avoid
        if action.length_target is not None:
            self.draft.length_target = action.length_target
        if action.header_style is not None:
            self.draft.header_style = action.header_style

        if action.key_messages:
            existing = {m.id: m for m in self.draft.key_messages}
            self.draft.key_messages = [
                existing[draft.id].model_copy(update={"text": draft.text})
                if draft.id in existing and existing[draft.id].text == draft.text
                else KeyMessage(id=draft.id, text=draft.text)
                for draft in action.key_messages
            ]

        known = {m.id for m in self.draft.key_messages}
        if action.layout_pins:
            self.draft.layout_pins = [
                LayoutPin(
                    message_id=pin.message_id,
                    target=pin.target,  # type: ignore[arg-type]
                    value=pin.value,
                    rationale=pin.rationale,
                )
                for pin in action.layout_pins
                if pin.message_id in known and pin.target in _PIN_TARGETS
            ]
        if action.open_risks:
            self.draft.open_risks = [
                OpenRisk(
                    message_id=risk.message_id,
                    description=risk.description,
                    accepted_by=risk.accepted_by,
                    mitigation=risk.mitigation,
                )
                for risk in action.open_risks
                if risk.message_id in known
            ]

    def _probe_if_asked(self, action: PlannerAction) -> list[ProbeResult]:
        """Run the gap check and let it, not the model, set evidence status."""
        if not action.probe_messages or not self.draft.key_messages:
            return []
        results = self.probe.probe_all(self.draft.key_messages)
        by_id = {result.message_id: result for result in results}
        self.draft.key_messages = [
            by_id[message.id].apply(message) if message.id in by_id else message
            for message in self.draft.key_messages
        ]
        for result in results:
            self.transcript.append(
                "probe",
                f"{result.message_id}: {result.status}"
                + (" (capped)" if result.capped else "")
                + (f" — {result.reasoning}" if result.reasoning else ""),
            )
        return results

    # -- sign-off (A7) -----------------------------------------------------

    def sign_off(self, *, approver: str) -> DeckBrief:
        """End the session with an explicit human approval. The only way out.

        `PlannerAction.ready_for_signoff` is **not** consulted here, deliberately. The model
        may believe the brief is finished; that belief has no authority, and reading it
        would create exactly the auto-approval path A7 forbids.

        Args:
            approver: who is signing. Required and non-empty — an approval with no name is
                not an approval.

        Raises:
            PlannerError: no approver was named.
            BriefIncomplete: the draft is not a valid brief — most often a weak key message
                with no recorded risk.
        """
        if not approver or not approver.strip():
            raise PlannerError(
                "sign-off needs the name of whoever is approving. A7 records who approved "
                "each gate; an unnamed approval is not one."
            )

        version = self.store.next_brief_version()
        try:
            brief = self.draft.to_brief(self.orchestrator.run_id, version=version)
        except Exception as exc:
            raise BriefIncomplete(f"this brief cannot be signed off yet: {exc}") from exc

        signed = brief.model_copy(update={"approved_by": approver.strip()})
        self.store.save_brief(signed)
        self.orchestrator.approve(Gate.BRIEF, approver=approver.strip())
        self.transcript.append("system", f"brief v{version} signed off by {approver.strip()}")
        self.signed = True
        return signed


_PIN_TARGETS = frozenset({"component", "communication_mode", "diagram_kind"})


def _read_prompt(path: Path) -> str:
    """Load the planner prompt.

    Missing is a hard error rather than a default. Plan §0.5 puts every prompt in a
    versioned file and hashes it into the build manifest (A6); an inline fallback would
    make a deck reproducible against a prompt that was never recorded.
    """
    path = Path(path)
    if not path.exists():
        raise PlannerError(
            f"planner prompt not found at {path}. Prompts are versioned files (plan §0.5) "
            "and their hashes go into the build manifest — there is no inline fallback."
        )
    return path.read_text(encoding="utf-8")


def render_draft(draft: Draft) -> str:
    """The draft as a human reads it mid-conversation.

    Public because the CLI shows it on `/brief` and the session feeds it to the model —
    two callers, so it is API rather than an internal helper.
    """
    lines = [
        f"objective: {draft.objective or '(not yet set)'}",
        f"audience: {draft.audience or '(not yet set)'}",
        f"length_target: {draft.length_target or '(not set)'}",
        f"header_style: {draft.header_style or '(not set)'}",
    ]
    lines.append("key_messages:")
    for message in draft.key_messages:
        lines.append(f"  - [{message.id}] ({message.evidence_status}) {message.text}")
        if message.probe_notes:
            lines.append(f"      probe: {message.probe_notes}")
    if not draft.key_messages:
        lines.append("  (none yet)")
    for label, values in (
        ("must_include", draft.must_include),
        ("must_avoid", draft.must_avoid),
    ):
        lines.append(f"{label}: {', '.join(values) if values else '(none)'}")
    lines.append("layout_pins:")
    for pin in draft.layout_pins:
        lines.append(f"  - {pin.message_id} -> {pin.target}={pin.value}")
    if not draft.layout_pins:
        lines.append("  (none)")
    lines.append("open_risks:")
    for risk in draft.open_risks:
        lines.append(
            f"  - {risk.message_id}: {risk.description} (accepted by {risk.accepted_by})"
        )
    if not draft.open_risks:
        lines.append("  (none)")
    return "\n".join(lines)


def resume_transcript(orchestrator: Orchestrator) -> Sequence[Turn]:
    """Read a previous session's transcript for this run."""
    return Transcript(orchestrator.paths.logs / "planner.jsonl").load()
