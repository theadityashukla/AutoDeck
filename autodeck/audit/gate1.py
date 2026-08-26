"""GATE 1: does the outline deliver the brief? (task 2a.9)

Plan §6.13 is precise about why this gate is phrased the way it is:

> The owner approves the outline skeleton *against the brief* … the question is not "is
> this a good outline" but "does this outline deliver the brief's key messages in the
> brief's order, honouring its pins?"

That reframing is what gives the gate objective criteria instead of vibes, and this module
is what makes the objective half mechanical. Five checks from the phase brief:

1. every `key_message` maps to at least one slide;
2. every `must_include` appears; no `must_avoid` does;
3. every `layout_pin` is honoured, or its deviation is explicitly flagged;
4. length is within the brief's target;
5. `open_risks` are carried into the IR, not dropped.

## What it does not do

**It does not decide.** No function here returns "approved", and nothing writes a gate
approval — that is `Orchestrator.approve`, called by a human (A7). Findings are `blocking`
or `advisory`, which describes the *finding*, not a verdict on the deck.

**It does not fix.** An agent that repaired its own drift would hide exactly what the
reviewer is there to see. `autodeck/agents/outline.py` corrects structural impossibilities
— a component that does not exist — and reports even those; everything about whether the
outline serves the brief is reported and left alone.

**The mechanical checks are the floor, not the gate.** Every key message can map to a slide
while the deck still fails to make the argument. The report says so where a human has to
look, rather than implying that a clean run is a pass.

Owning phase: 2a (task 2a.9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from autodeck.ir.models import Deck, DeckBrief

Severity = Literal["blocking", "advisory"]


@dataclass(frozen=True)
class Finding:
    """One way the outline does or does not answer the brief.

    `blocking` means a check the phase brief states as a GATE 1 criterion failed.
    `advisory` means something a reviewer should see but which the brief does not make a
    pass/fail condition — an unprobed message, a confident component on weak evidence.

    Even a blocking finding is not a rejection. The owner may look at it and approve
    anyway; what they may not do is fail to see it.
    """

    check: str
    severity: Severity
    detail: str

    def __str__(self) -> str:
        marker = "BLOCKING" if self.severity == "blocking" else "advisory"
        return f"[{marker}] {self.check}: {self.detail}"


@dataclass
class Gate1Report:
    """Everything the mechanical checks found, for a human to read."""

    run_id: str
    brief_version: int
    deck_version: int
    findings: list[Finding] = field(default_factory=list)
    slide_count: int = 0

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def advisory(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "advisory"]

    @property
    def mechanical_checks_pass(self) -> bool:
        """Whether the five checkable criteria hold.

        Deliberately not named `passed`. GATE 1 is a human judgement about whether the deck
        makes the argument; this is the subset a machine can answer, and a name like
        `passed` would invite a caller to treat it as the gate itself.
        """
        return not self.blocking

    def render(self) -> str:
        lines = [
            f"GATE 1 — outline v{self.deck_version} against brief v{self.brief_version}",
            f"run: {self.run_id} · {self.slide_count} slide(s)",
            "",
        ]
        if not self.findings:
            lines.append("All mechanical checks pass.")
        else:
            for finding in self.blocking + self.advisory:
                lines.append(str(finding))
        lines.extend(
            [
                "",
                "These are the checkable criteria only. The gate asks whether this outline "
                "delivers the brief's argument, and no check here answers that — read the "
                "slide intents in order and decide. Approve with `autodeck approve "
                f"{self.run_id} outline`.",
            ]
        )
        return "\n".join(lines)


def review_outline(deck: Deck, brief: DeckBrief) -> Gate1Report:
    """Check an outline against the brief it was built from.

    Raises:
        ValueError: the deck and brief belong to different runs. Reviewing an outline
            against somebody else's brief would produce a confident, meaningless report.
    """
    if deck.run_id != brief.run_id:
        raise ValueError(
            f"deck is for run {deck.run_id!r} but brief is for {brief.run_id!r}; "
            "a GATE 1 review compares one outline against the brief it was built from"
        )

    report = Gate1Report(
        run_id=deck.run_id,
        brief_version=brief.version,
        deck_version=deck.version,
        slide_count=len(deck.slides),
    )
    findings = report.findings
    findings.extend(_check_message_coverage(deck, brief))
    findings.extend(_check_must_include_avoid(deck, brief))
    findings.extend(_check_pins(deck, brief))
    findings.extend(_check_length(deck, brief))
    findings.extend(_check_risks_carried(deck, brief))
    findings.extend(_check_evidence_and_components(deck, brief))
    return report


def _check_message_coverage(deck: Deck, brief: DeckBrief) -> list[Finding]:
    """Criterion 1: every key message maps to at least one slide."""
    served = {mid for slide in deck.slides for mid in slide.message_ids}
    missing = [m for m in brief.key_messages if m.id not in served]
    return [
        Finding(
            check="key message coverage",
            severity="blocking",
            detail=(f"{message.id} is in the brief but no slide serves it: {message.text!r}"),
        )
        for message in missing
    ]


def _check_must_include_avoid(deck: Deck, brief: DeckBrief) -> list[Finding]:
    """Criterion 2: must_include appears, must_avoid does not.

    Matched against slide intents and roles, since an outline has no prose yet. That makes
    this check weaker than it will be at GATE 2 — a topic can be intended and then not
    written — so a *missing* must_include is blocking, while a must_avoid appearing is
    reported as blocking too: an outline that plans to say a forbidden thing is a problem
    now, not later.
    """
    haystack = " \n ".join(
        f"{slide.narrative_role} {slide.intent or ''}" for slide in deck.slides
    ).lower()

    findings = [
        Finding(
            check="must_include",
            severity="blocking",
            detail=(
                f"{item!r} is required by the brief but appears in no slide intent. The "
                "outline has no prose yet, so this is matched against intents — if the "
                "outline covers it under different words, say so and approve."
            ),
        )
        for item in brief.must_include
        if item.lower() not in haystack
    ]
    findings.extend(
        Finding(
            check="must_avoid",
            severity="blocking",
            detail=f"{item!r} is forbidden by the brief but appears in a slide intent",
        )
        for item in brief.must_avoid
        if item.lower() in haystack
    )
    return findings


def _check_pins(deck: Deck, brief: DeckBrief) -> list[Finding]:
    """Criterion 3: every pin honoured, or its deviation flagged.

    A flagged deviation is **advisory**, not blocking. The brief's own wording is "honoured,
    or its deviation is explicitly flagged" — so a recorded deviation satisfies the
    criterion, and the reviewer decides whether the reason is good. An *unrecorded* one does
    not, which is why the outline agent records them whether or not the model explains
    itself.
    """
    findings: list[Finding] = []
    for pin in brief.layout_pins:
        serving = [s for s in deck.slides if pin.message_id in s.message_ids]
        if not serving:
            findings.append(
                Finding(
                    check="layout pin",
                    severity="blocking",
                    detail=(
                        f"pin {pin.target}={pin.value!r} targets message "
                        f"{pin.message_id!r}, which no slide serves"
                    ),
                )
            )
            continue

        honoured = any(_pin_value(slide, pin.target) == pin.value for slide in serving)
        if honoured:
            continue
        flagged = [s for s in serving if s.pin_deviation]
        findings.append(
            Finding(
                check="layout pin",
                severity="advisory" if flagged else "blocking",
                detail=(
                    f"pin {pin.target}={pin.value!r} on message {pin.message_id!r} was not "
                    + (
                        f"honoured; deviation recorded: {flagged[0].pin_deviation}"
                        if flagged
                        else "honoured and no deviation was recorded"
                    )
                ),
            )
        )
    return findings


def _pin_value(slide: object, target: str) -> str | None:
    if target == "component":
        return getattr(slide, "component", None)
    if target == "communication_mode":
        return getattr(slide, "communication_mode", None)
    return None


def _check_length(deck: Deck, brief: DeckBrief) -> list[Finding]:
    """Criterion 4: length within the brief's target.

    Over target is blocking; under is advisory. The prompt tells the outline to come in
    under and say what it left out rather than drop a key message to hit a number, so
    penalising a short deck the same way would push against that instruction — and
    coverage, which is the thing that actually matters, is already checked separately.
    """
    if brief.length_target is None or len(deck.slides) == brief.length_target:
        return []
    count = len(deck.slides)
    if count > brief.length_target:
        return [
            Finding(
                check="length",
                severity="blocking",
                detail=f"{count} slides against a target of {brief.length_target}",
            )
        ]
    return [
        Finding(
            check="length",
            severity="advisory",
            detail=(
                f"{count} slides against a target of {brief.length_target} — under target. "
                "Check the outline's notes for what was left out."
            ),
        )
    ]


def _check_risks_carried(deck: Deck, brief: DeckBrief) -> list[Finding]:
    """Criterion 5: accepted evidence gaps reach the deck rather than evaporating.

    A risk is carried if the message it qualifies has a slide. That is a low bar and it is
    the honest one at outline stage — there is no prose yet in which to hedge. The hedging
    itself is checked at GATE 2, when there are words to check.
    """
    served = {mid for slide in deck.slides for mid in slide.message_ids}
    return [
        Finding(
            check="open risk",
            severity="blocking",
            detail=(
                f"risk on message {risk.message_id!r} accepted by {risk.accepted_by} is not "
                f"carried: no slide serves that message. {risk.description}"
            ),
        )
        for risk in brief.open_risks
        if risk.message_id not in served
    ]


def _check_evidence_and_components(deck: Deck, brief: DeckBrief) -> list[Finding]:
    """Advisory: weak evidence given a component that overstates it, and unprobed messages.

    Neither is a GATE 1 criterion, so neither blocks. Both are things a reviewer looking at
    a tidy outline would otherwise not think to ask about, and both are A8 concerns: a
    `big_number` slide is a claim of confidence, and "nobody checked" reads far too much
    like "it's fine".
    """
    from autodeck.agents.outline import CONFIDENT_COMPONENTS

    findings: list[Finding] = []
    by_id = {message.id: message for message in brief.key_messages}

    for slide in deck.slides:
        if slide.component not in CONFIDENT_COMPONENTS:
            continue
        weak = [
            mid
            for mid in slide.message_ids
            if mid in by_id and by_id[mid].evidence_status in ("thin", "unsupported")
        ]
        if weak:
            findings.append(
                Finding(
                    check="component overstates evidence",
                    severity="advisory",
                    detail=(
                        f"slide {slide.id!r} uses {slide.component!r} for message(s) "
                        f"{', '.join(weak)}, whose evidence is weak. A component that "
                        "stakes the slide on one figure reads as confidence the sources "
                        "do not support (A8)."
                    ),
                )
            )

    unprobed = brief.unprobed_messages()
    if unprobed:
        findings.append(
            Finding(
                check="unprobed messages",
                severity="advisory",
                detail=(
                    f"{', '.join(m.id for m in unprobed)} were never checked against the "
                    "corpus. Not a failure — but 'nobody looked' is different from "
                    "'it's supported', and only this report distinguishes them."
                ),
            )
        )
    return findings
