"""GATE 2 (task 2b.11): `content`, `validate`, `gate2`, `send-back`.

The load-bearing test here is `test_a_sent_back_claim_does_not_survive_verbatim` — the
design question the task spec poses directly: a send-back a writer could regenerate
verbatim would make GATE 2 decorative. It exercises the whole cycle for real: a content
pass, a send-back naming one of its claims, and a second content pass proving the rejected
sentence does not reappear and that the writer's own prompt was told why.

Everything here uses `typer.testing.CliRunner` against fixtures, per `test_cli_knowledge.py`
— no network, no API key. `ModelRegistry.provider_for` is monkeypatched to hand back a
`Scripted` fake (borrowed from `test_content.py`/`test_validation.py`) instead of a real
provider.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

import autodeck.providers.registry as registry_module
from autodeck.agents.content import ProposedBlock
from autodeck.audit.verdicts import JudgedVerdict
from autodeck.cli import app
from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.ir.models import Deck, DeckBrief, KeyMessage, Slide
from autodeck.ir.store import IRStore
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.pipeline.orchestrator import Gate, Orchestrator
from autodeck.pipeline.send_back import load_send_backs, send_backs_path
from tests.test_knowledge import build_knowledge
from tests.test_validation import Scripted as ScriptedValidator
from tests.test_verdicts import deck_with, diagram_block

runner = CliRunner()

PROJECT = "attention-efficiency"
CLIENT = "acme"
DOC_ID = "kaplan2024"
QUOTE = "Training throughput rose from 412 to 671 sequences per second."
#: No numeral of its own — A2 would otherwise flag it, since a number in claim text has to
#: trace to the cited span or a declared derivation, and this deck has neither for one.
CLAIM_TEXT = "The kernel rewrite raised training throughput, per the cited benchmark."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class ScriptedContent:
    """A fake `content` model, matching `test_content.py`'s own `Scripted`.

    Kept local (rather than imported) because it is trivial and because a second copy here
    makes it obvious this test file depends on nothing about `test_content.py`'s internals
    beyond the `ProposedBlock`/`ProposedClaim`/`ProposedCitation` shapes already covered by
    that module's own tests.
    """

    def __init__(self, draft) -> None:  # type: ignore[no-untyped-def]
        self.draft = draft
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        return self.draft


def element(
    doc_id: str, text: str, *, page: int = 4, element_id: str = "e1"
) -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id=doc_id,
        kind="text",
        page=page,
        bbox=(72.0, 100.0, 523.0, 200.0),
        reading_order=0,
        text=text,
    )


def make_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A knowledge root, corpus root and runs root with one approved-outline run in it."""
    knowledge_root = build_knowledge(tmp_path)
    corpus_root = tmp_path / "corpus"
    runs_root = tmp_path / "runs"

    document = Document(
        doc_id=DOC_ID,
        source_path=f"{DOC_ID}.pdf",
        page_count=6,
        elements=[element(DOC_ID, QUOTE)],
    )
    DocumentStore(corpus_root / PROJECT).add(document)

    orchestrator = Orchestrator("r1", runs_root=runs_root, env="dev")
    brief = DeckBrief(
        run_id="r1",
        objective="Decide whether the kernel rewrite is worth shipping.",
        audience="CTO",
        key_messages=[
            KeyMessage(
                id="km1",
                text="The kernel rewrite raised training throughput.",
                evidence_status="supported",
            )
        ],
        approved_by="tester",
    )
    orchestrator.ir.save_brief(brief)
    deck = Deck(
        run_id="r1",
        project=PROJECT,
        client=CLIENT,
        audience="CTO",
        version=1,
        slides=[
            Slide(
                id="s1",
                narrative_role="evidence",
                component="quote",  # not in the design catalog — budgets skip, no font needed
                intent="State that the kernel rewrite raised training throughput.",
                message_ids=["km1"],
            )
        ],
        theme_ref="config/tokens/dev.json",
        component_lib_version=COMPONENT_LIB_VERSION,
    )
    orchestrator.ir.save(deck)
    orchestrator.approve(Gate.OUTLINE)
    return knowledge_root, corpus_root, runs_root


def content_draft(*, block_id: str = "b1", text: str = CLAIM_TEXT):  # type: ignore[no-untyped-def]
    from autodeck.agents.content import (
        ContentDraft,
        ProposedCitation,
        ProposedClaim,
    )

    block = ProposedBlock(
        id=block_id,
        kind="claim",
        slot="figure",
        claim=ProposedClaim(
            text=text, citations=[ProposedCitation(doc_id=DOC_ID, quote=QUOTE)]
        ),
    )
    return ContentDraft(blocks=[block], speaker_notes=[])


def patch_content_model(monkeypatch: pytest.MonkeyPatch, model: ScriptedContent) -> None:
    monkeypatch.setattr(
        registry_module.ModelRegistry, "provider_for", lambda self, role, **kw: model
    )


def patch_validation_model(monkeypatch: pytest.MonkeyPatch, model: ScriptedValidator) -> None:
    monkeypatch.setattr(
        registry_module.ModelRegistry, "provider_for", lambda self, role, **kw: model
    )


def run_content(
    runs_root: Path,
    knowledge_root: Path,
    corpus_root: Path,
    run_id: str = "r1",
    *,
    header_style: str | None = None,
) -> Result:
    args = [
        "content",
        run_id,
        "--knowledge-root",
        str(knowledge_root),
        "--corpus-root",
        str(corpus_root),
        "--runs-root",
        str(runs_root),
    ]
    if header_style is not None:
        args.extend(["--header-style", header_style])
    return runner.invoke(app, args)


def run_validate(runs_root: Path, corpus_root: Path) -> Result:
    return runner.invoke(
        app,
        ["validate", "r1", "--corpus-root", str(corpus_root), "--runs-root", str(runs_root)],
    )


def run_gate2(runs_root: Path) -> Result:
    return runner.invoke(app, ["gate2", "r1", "--runs-root", str(runs_root)])


# ---------------------------------------------------------------------------
# content
# ---------------------------------------------------------------------------


def test_content_is_blocked_without_an_approved_outline(tmp_path: Path) -> None:
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    # A fresh run whose outline was never approved.
    Orchestrator("r2", runs_root=runs_root, env="dev")
    result = run_content(runs_root, knowledge_root, corpus_root, run_id="r2")
    assert result.exit_code == 3
    assert "GATE" in result.output


def test_content_writes_the_next_ir_version_and_lints_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))

    result = run_content(runs_root, knowledge_root, corpus_root)

    assert result.exit_code == 0, result.output
    assert IRStore(runs_root, "r1").versions() == [1, 2]
    deck = IRStore(runs_root, "r1").load(2)
    [block] = deck.slides[0].blocks
    assert block.claim is not None
    assert block.claim.text == CLAIM_TEXT
    assert "A2 — numeric lint" in result.output
    assert "A5 — framing lint" in result.output
    assert "Header flow" in result.output


def test_header_style_is_a_one_flag_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--header-style` overrides the voice for this run alone: the saved brief on disk
    keeps whatever it was signed off with, and the fixture's `headers.yaml` (`style:
    assertion`, from `build_knowledge`) still supplies every other rule."""
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    model = ScriptedContent(content_draft())
    patch_content_model(monkeypatch, model)

    result = run_content(runs_root, knowledge_root, corpus_root, header_style="question_led")

    assert result.exit_code == 0, result.output
    [prompt] = model.prompts
    assert "style: question_led" in prompt

    # The approved brief file itself is untouched by the override.
    saved_brief = Orchestrator("r1", runs_root=runs_root, env="dev").ir.load_brief()
    assert saved_brief.header_style is None


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_is_blocked_before_content_has_run(tmp_path: Path) -> None:
    _knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    result = run_validate(runs_root, corpus_root)
    assert result.exit_code == 3
    assert "content" in result.output


def test_validate_writes_verdicts_and_prints_the_claims_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autodeck.audit.verdicts import VerdictJudgement

    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    judgement = VerdictJudgement(
        verdict="supported", verdict_notes="matches the source", supporting_quote=QUOTE
    )
    patch_validation_model(monkeypatch, ScriptedValidator({"s1:b1": judgement}))

    result = run_validate(runs_root, corpus_root)

    assert result.exit_code == 0, result.output
    assert IRStore(runs_root, "r1").versions() == [1, 2, 3]
    deck = IRStore(runs_root, "r1").load(3)
    [block] = deck.slides[0].blocks
    assert block.claim is not None
    assert block.claim.verdict == "supported"
    assert "A3 — claim verdicts" in result.output
    assert "supported" in result.output


# ---------------------------------------------------------------------------
# gate2
# ---------------------------------------------------------------------------


def test_gate2_is_blocked_before_validate_has_run(tmp_path: Path) -> None:
    _knowledge_root, _corpus_root, runs_root = make_run(tmp_path)
    result = run_gate2(runs_root)
    assert result.exit_code == 3
    assert "validate" in result.output


def _validated_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verdict: JudgedVerdict
) -> Path:
    from autodeck.audit.verdicts import VerdictJudgement

    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    judgement = VerdictJudgement(
        verdict=verdict,
        verdict_notes="scripted for the test",
        supporting_quote=QUOTE if verdict != "unsupported" else "",
    )
    patch_validation_model(monkeypatch, ScriptedValidator({"s1:b1": judgement}))
    validate_result = run_validate(runs_root, corpus_root)
    assert validate_result.exit_code == 0, validate_result.output
    return runs_root


def test_gate2_exits_zero_and_prints_stable_claim_ids_when_mechanically_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = _validated_run(tmp_path, monkeypatch, "supported")

    result = run_gate2(runs_root)

    assert result.exit_code == 0, result.output
    assert "s1:b1" in result.output
    assert "GATE 2 checkable criteria" in result.output
    assert "[FAIL]" not in result.output
    assert "not the gate" in result.output


def test_gate2_exits_nonzero_when_a_claim_is_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = _validated_run(tmp_path, monkeypatch, "unsupported")

    result = run_gate2(runs_root)

    assert result.exit_code == 4, result.output
    assert "[FAIL]" in result.output


def test_gate2_never_writes_an_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gate2` reports; only `autodeck approve` may record one (A7)."""
    runs_root = _validated_run(tmp_path, monkeypatch, "supported")
    run_gate2(runs_root)
    orchestrator = Orchestrator("r1", runs_root=runs_root, env="dev")
    assert not orchestrator.state.is_approved(Gate.CLAIMS)


# ---------------------------------------------------------------------------
# GATE 2's criteria and GATE 2's claims table must agree
# ---------------------------------------------------------------------------


def test_gate2_fails_on_a_contradicted_diagram_node_claim() -> None:
    """The defect, at the screen a human reads.

    GATE 2 printed the claims table and the checkable criteria one after the other. With a
    `contradicted` claim on a diagram node, the table said `contradicted` and criterion 1
    said `[PASS] zero blocks verdict unsupported/contradicted` — on the same screen, about
    the same claim. A reviewer trusting the criterion would approve it.
    """
    from autodeck.audit.report import build_audit_report
    from autodeck.cli import _gate2_checks
    from autodeck.pipeline.orchestrator import assess_render_safety

    deck = deck_with(diagram_block("b1", {"n1": "contradicted"}))
    safety = assess_render_safety(deck)
    report = build_audit_report(
        deck, brief=None, numeric=safety.numeric, framing=safety.framing
    )

    assert [(r.block_id, r.verdict) for r in report.claim_rows()] == [
        ("b1/n1", "contradicted")
    ], "the claims table has always seen it"

    label, passed, detail = _gate2_checks(None, safety, report)[0]

    assert "unsupported/contradicted" in label
    assert not passed, "the criterion must agree with the table it is printed beside"
    assert "1 blocking block(s)" in detail


def test_gate2_fails_on_an_unverified_diagram_node_claim() -> None:
    """A node the validator never reached is not a node that passed."""
    from autodeck.audit.report import build_audit_report
    from autodeck.cli import _gate2_checks
    from autodeck.pipeline.orchestrator import assess_render_safety

    deck = deck_with(diagram_block("b1", {"n1": "unverified"}))
    safety = assess_render_safety(deck)
    report = build_audit_report(
        deck, brief=None, numeric=safety.numeric, framing=safety.framing
    )

    _, passed, detail = _gate2_checks(None, safety, report)[0]

    assert not passed
    assert "1 unverified claim(s)" in detail


# ---------------------------------------------------------------------------
# send-back — the design question
# ---------------------------------------------------------------------------


def test_send_back_rejects_an_unknown_claim_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    result = runner.invoke(
        app,
        [
            "send-back",
            "r1",
            "--claim",
            "s9:nope",
            "--reason",
            "does not exist",
            "--runs-root",
            str(runs_root),
        ],
    )
    assert result.exit_code == 1
    assert "unknown claim id" in result.output


def test_send_back_requires_one_reason_per_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    result = runner.invoke(
        app,
        [
            "send-back",
            "r1",
            "--claim",
            "s1:b1",
            "--claim",
            "s1:b1",
            "--reason",
            "only one reason",
            "--runs-root",
            str(runs_root),
        ],
    )
    assert result.exit_code == 2


def test_send_back_rejects_an_empty_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    result = runner.invoke(
        app,
        [
            "send-back",
            "r1",
            "--claim",
            "s1:b1",
            "--reason",
            "   ",
            "--runs-root",
            str(runs_root),
        ],
    )
    assert result.exit_code == 2


def test_send_back_records_who_what_and_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    result = runner.invoke(
        app,
        [
            "send-back",
            "r1",
            "--claim",
            "s1:b1",
            "--reason",
            "the 62.9% figure is not in the cited sentence",
            "--by",
            "aditya",
            "--runs-root",
            str(runs_root),
        ],
    )
    assert result.exit_code == 0, result.output

    path = send_backs_path(runs_root / "r1")
    assert path.exists()
    records = load_send_backs(runs_root / "r1")
    [record] = records
    assert record.claim_id == "s1:b1"
    assert record.claim_text == CLAIM_TEXT
    assert record.by == "aditya"
    assert record.ir_version == 2
    assert "62.9%" in record.reason

    # Plain, inspectable JSON — no dependency on this module's own reader to check it.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["reason"] == "the 62.9% figure is not in the cited sentence"


def test_send_back_cannot_record_an_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    runner.invoke(
        app,
        [
            "send-back",
            "r1",
            "--claim",
            "s1:b1",
            "--reason",
            "rejected",
            "--runs-root",
            str(runs_root),
        ],
    )
    orchestrator = Orchestrator("r1", runs_root=runs_root, env="dev")
    assert not orchestrator.state.is_approved(Gate.CLAIMS)


def test_a_sent_back_claim_does_not_survive_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The task's own design question, made concrete.

    A send-back has to survive into the next content pass — the writer has to see what was
    rejected and why — and a rejected claim the writer could regenerate verbatim would make
    the gate decorative. This drives the whole cycle with a content model that behaves
    exactly like a writer who did not get the message (it returns the identical claim on
    its second pass) and checks two things: the repeated block is dropped rather than
    shipped, and the rejection reached the model's own prompt so a writer that *does* read
    its instructions had a chance to do something different.
    """
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)

    first_model = ScriptedContent(content_draft())
    patch_content_model(monkeypatch, first_model)
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    send_back_result = runner.invoke(
        app,
        [
            "send-back",
            "r1",
            "--claim",
            "s1:b1",
            "--reason",
            "62.9% cannot be found in the cited sentence — it only gives 412 and 671",
            "--runs-root",
            str(runs_root),
        ],
    )
    assert send_back_result.exit_code == 0, send_back_result.output

    # A writer that ignores its instructions and proposes the exact same claim again, under
    # a fresh block id — ids are not what the check keys on, the text is.
    second_model = ScriptedContent(content_draft(block_id="b7", text=CLAIM_TEXT))
    patch_content_model(monkeypatch, second_model)
    second_result = run_content(runs_root, knowledge_root, corpus_root)

    assert second_result.exit_code == 0, second_result.output
    assert "dropped as a verbatim repeat of a GATE 2 send-back" in second_result.output

    deck_v3 = IRStore(runs_root, "r1").load(3)
    assert deck_v3.slides[0].blocks == []

    # The rejection reached the model's own prompt, not just this command's bookkeeping.
    [prompt] = second_model.prompts
    assert "rejected by owner at GATE 2" in prompt
    assert "62.9% cannot be found" in prompt


# ---------------------------------------------------------------------------
# A7 — none of these commands can approve anything
# ---------------------------------------------------------------------------


def test_none_of_the_new_commands_can_record_an_approval() -> None:
    """The invariant the task spec asks for explicitly.

    Mirrors `test_orchestrator.test_no_command_can_bypass_a_gate`: a banned-parameter check,
    plus a direct scan of each function's own source for a call to `.approve(`, since a
    parameter check alone would miss a command that hard-codes an approval with no flag at
    all.
    """
    from autodeck import cli

    banned = {"yes", "force", "skip_gates", "no_gates", "auto_approve", "approve"}
    for name in ("content", "validate", "gate2", "send_back"):
        func = getattr(cli, name)
        parameters = set(inspect.signature(func).parameters)
        assert not (parameters & banned), f"cli.{name} exposes a gate bypass"
        source = inspect.getsource(func)
        assert ".approve(" not in source, f"cli.{name} calls .approve() itself"


def test_assembled_context_renders_send_backs_when_present() -> None:
    base = AssembledContext(
        client="acme",
        project="attention-efficiency",
        project_md="Project.",
        client_md="Client.",
        value_prop_md="Value.",
    )
    assert "sent back" not in base.to_prompt_context()

    with_send_back = base.__class__(
        **{**base.__dict__, "send_backs": ("a rejected claim, with its reason",)}
    )
    rendered = with_send_back.to_prompt_context()
    assert "Claims sent back at GATE 2" in rendered
    assert "a rejected claim, with its reason" in rendered
