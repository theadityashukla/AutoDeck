"""`autodeck build` (Phase 4, task 4.4): the draft-first flow end to end, four typed approvals.

Fake providers only. A terminal is stood in for by patching `cli._stdin_is_interactive`; no
environment variable can do that, which is also asserted. `render` and `gate3` (art direction
and a true render) are replaced by fakes that leave what the real ones leave, so the final
approval is exercised through the real `approve_gate` and its real refusals.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

import autodeck.cli as cli
import autodeck.ui.approvals as approvals_module
from autodeck.cli import app
from autodeck.pipeline.orchestrator import ApprovalState, Gate, Orchestrator
from tests.gate_artifacts import seed_artifact, seed_passing_final_assessment
from tests.test_cli_draft import CLARIFIED, COMPOSED, REVISED, World
from tests.test_cli_gate2 import CLIENT, PROJECT
from tests.test_like import LikeWorld
from tests.test_reference_decks import TITLES

runner = CliRunner()

needs_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None and shutil.which("libreoffice") is None,
    reason="LibreOffice is not installed",
)

APPROVE = "approve\n"


class Fakes:
    """What `render` and `gate3` do, without art direction or a true render."""

    def __init__(self, runs: Path) -> None:
        self.runs = runs
        self.renders = 0
        self.gate3s = 0
        self.claims_were_current: list[bool] = []
        self.gate3_passes = True

    def render(self, run_id, runs_root, env):  # type: ignore[no-untyped-def]
        orchestrator = Orchestrator(run_id, runs_root=runs_root, create=False)
        self.claims_were_current.append(
            orchestrator.approval_state(Gate.CLAIMS)[0] is ApprovalState.CURRENT
        )
        self.renders += 1
        seed_artifact(orchestrator, Gate.FINAL_RENDER)
        orchestrator.run_stage("render", lambda: "fake", force=True)

    def gate3(self, run_id, runs_root, env, knowledge_root):  # type: ignore[no-untyped-def]
        orchestrator = Orchestrator(run_id, runs_root=runs_root, create=False)
        self.gate3s += 1
        seed_passing_final_assessment(orchestrator, passes=self.gate3_passes)
        if not self.gate3_passes:
            raise typer.Exit(code=4)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Fakes:
    fake = Fakes(tmp_path / "runs")
    monkeypatch.setattr(cli, "render", fake.render)
    monkeypatch.setattr(cli, "gate3", fake.gate3)
    return fake


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)


def build(w: World, *extra: str, run: str | None = "r1", input: str | None = None):  # type: ignore[no-untyped-def]
    args = ["build", "--by", "Ada", *w.data_roots, *extra]
    if run is not None:
        args += ["--run", run]
    if "--prompt" not in extra and "--client" not in extra and not _resuming(w, run):
        args += [
            "--client", CLIENT, "--project", PROJECT, "--audience", "CTO",
            "--prompt", "Show that the kernel rewrite raised training throughput.",
        ]  # fmt: skip
    return runner.invoke(app, args, input=input)


def _resuming(w: World, run: str | None) -> bool:
    return run is not None and (w.runs / run / "clarify.json").is_file()


def orchestrator(w: World) -> Orchestrator:
    return Orchestrator("r1", runs_root=w.runs, create=False)


def test_the_happy_path_records_four_approvals_through_the_shared_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    seen: list[tuple[str, str]] = []
    real = approvals_module.approve_gate

    def spy(roots, run_id, gate, **kwargs):  # type: ignore[no-untyped-def]
        seen.append((gate, kwargs["approver"]))
        return real(roots, run_id, gate, **kwargs)

    monkeypatch.setattr(approvals_module, "approve_gate", spy)

    result = build(w, input="Neutral, please.\n" + APPROVE * 4)

    assert result.exit_code == 0, result.output
    assert seen == [
        ("brief", "Ada"),
        ("outline", "Ada"),
        ("claims", "Ada"),
        ("final_render", "Ada"),
    ]
    orch = orchestrator(w)
    assert orch.pending_gates() == []
    assert all(orch.state.approvals[g.value].endswith(" by Ada") for g in Gate)
    # The typed answer is the person's; the questions were put to them (B55).
    saved = json.loads((w.runs / "r1" / "clarify.json").read_text())
    assert saved["answers"] == {"q1": "Neutral, please."}
    assert saved["answer_sources"] == {"q1": "typed"}
    assert "Neutral summary or recommendation?" in result.output
    # The claims were current when the final deck was drawn, and it was drawn once.
    assert fakes.claims_were_current == [True] and fakes.renders == 1 and fakes.gate3s == 1
    assert "APPROVAL 1 of 4" in result.output and "APPROVAL 4 of 4" in result.output
    assert "1. [quote]" in result.output  # the outline, as the headline list
    assert (w.runs / "r1" / "previews" / "draft").is_dir()


def test_an_empty_line_takes_the_suggestion_as_an_accepted_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    result = build(w, input="\n" + APPROVE * 4)
    assert result.exit_code == 0, result.output
    saved = json.loads((w.runs / "r1" / "clarify.json").read_text())
    assert saved["answers"] == {"q1": "Recommendation."}
    assert saved["answer_sources"] == {"q1": "accepted"}


@pytest.mark.parametrize("stop_at", [0, 1, 2, 3])
def test_a_no_stops_there_and_nothing_later_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None, stop_at: int
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    gates = [g.value for g in Gate]

    result = build(w, input="\n" + APPROVE * stop_at + "no\n")

    assert result.exit_code == 3, result.output
    assert "autodeck build --run r1" in result.output
    orch = orchestrator(w)
    assert sorted(orch.state.approvals) == sorted(gates[:stop_at])
    audit_run = (w.runs / "r1" / "audit_report.md").exists()
    assert audit_run == (stop_at >= 2)  # gate2 runs only once the claims are asked about
    assert fakes.renders == (1 if stop_at == 3 else 0)
    assert fakes.gate3s == (1 if stop_at == 3 else 0)


def test_an_answer_that_is_not_the_word_is_asked_again_and_enter_is_not_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    result = build(w, input="\n" + "y\n\nok\nyes\n" + "no\n")
    assert result.exit_code == 3
    assert result.output.count("Type 'approve' or 'no'.") == 4
    assert orchestrator(w).state.approvals == {}


def test_without_a_terminal_it_stops_at_the_first_approval_and_names_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes
) -> None:
    for name in ("AUTODECK_YES", "AUTODECK_APPROVE", "YES", "CI"):
        monkeypatch.setenv(name, "1")  # nothing in the environment can approve
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)

    result = build(w, input=APPROVE * 8)  # input is on stdin, but stdin is not a terminal

    assert result.exit_code == 3, result.output
    assert "autodeck approve r1 brief --by Ada" in result.output
    assert "autodeck build --run r1" in result.output
    orch = orchestrator(w)
    assert orch.state.approvals == {}
    # Everything up to the approval ran: the draft exists, validated and previewed.
    assert orch.state.is_complete("compose") and orch.state.is_complete("validate")
    assert orch.state.is_complete("preview")
    assert fakes.renders == 0
    saved = json.loads((w.runs / "r1" / "clarify.json").read_text())
    assert saved["answer_sources"] == {"q1": "accepted"}  # never "typed" for the person


def test_no_option_can_answer_for_the_person() -> None:
    command = typer.main.get_command(app).commands["build"]  # type: ignore[attr-defined]
    names = [p.name or "" for p in command.params]
    flags = [opt for p in command.params for opt in getattr(p, "opts", [])]
    for word in ("yes", "approve", "skip", "force", "trust", "auto", "all"):
        assert not [n for n in [*names, *flags] if word in n.lower()], word
    assert "by" in names  # the name an approval carries, not a way past one


def test_resume_continues_and_asks_only_the_pending_approvals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    first = build(w, input="\n" + APPROVE + "no\n")
    assert first.exit_code == 3
    calls = w.calls()
    assert sorted(orchestrator(w).state.approvals) == ["brief"]

    second = build(w, input=APPROVE * 3)

    assert second.exit_code == 0, second.output
    assert w.calls() == calls  # nothing was clarified, drafted or validated again
    assert "APPROVAL 1 of 4" not in second.output  # the brief was not asked again
    assert orchestrator(w).pending_gates() == []


def test_resume_without_options_reads_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    assert build(w).exit_code == 3  # no terminal: stops at the brief
    again = runner.invoke(app, ["build", "--run", "r1", "--by", "Ada", *w.data_roots])
    assert again.exit_code == 3 and "autodeck approve r1 brief" in again.output
    assert w.calls() == 3


def test_a_revised_draft_is_validated_again_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED, REVISED)
    assert build(w, input="\nno\n").exit_code == 3
    result = w.run("revise", "r1", "--instruction", "Soften slide two.", *w.data_roots)
    assert result.exit_code == 0, result.output
    before = len(w.judge.prompts)

    result = build(w, input="no\n")

    assert result.exit_code == 3
    assert len(w.judge.prompts) == before + 1  # the changed claim is judged again


def test_a_failed_final_audit_is_not_approvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    fakes.gate3_passes = False
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)

    result = build(w, input="\n" + APPROVE * 4)

    assert result.exit_code == 4, result.output
    assert "final audit did not pass" in result.output
    assert sorted(orchestrator(w).state.approvals) == ["brief", "claims", "outline"]


def test_a_refusal_from_the_shared_path_stops_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    """The final approval needs the deck the final audit described; if it did not, the shared
    path refuses and `build` reports it rather than recording anything."""
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)

    def forgetful(run_id, runs_root, env, knowledge_root):  # type: ignore[no-untyped-def]
        Orchestrator(run_id, runs_root=runs_root, create=False)  # records no assessment

    monkeypatch.setattr(cli, "gate3", forgetful)
    result = build(w, input="\n" + APPROVE * 4)
    assert result.exit_code == 1, result.output
    assert "final audit has not been run" in result.output
    assert "final_render" not in orchestrator(w).state.approvals


def test_starting_needs_the_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED)
    result = runner.invoke(app, ["build", "--client", CLIENT, "--project", PROJECT, *w.roots])
    assert result.exit_code == 1 and "--prompt and --audience" in result.output
    assert not (w.runs / "r1").exists()


@needs_soffice
def test_a_strict_deck_gets_its_audit_report_as_a_pdf_at_the_claims_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    result = build(w, "--provenance", "strict", input="\n" + APPROVE * 3 + "no\n")
    assert result.exit_code == 3, result.output
    orch = orchestrator(w)
    assert orch.ir.load().provenance == "strict"
    assert orch.paths.audit_report.with_suffix(".pdf").is_file()
    assert "Audit report PDF:" in result.output


def test_like_builds_a_deck_like_a_past_one_and_still_asks_four_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED)

    result = build(w, "--like", "margin-review", input="\n" + APPROVE * 4)

    assert result.exit_code == 0, result.output
    like = json.loads((w.runs / "r1" / "like.json").read_text())
    assert like["deck"] == "margin-review"
    assert "build it like margin-review: 10 slides, 2 sections" in w.composer.prompts[0]
    compose_prompt = w.composer.prompts[1]
    assert f"4. [content] {TITLES['content1']}" in compose_prompt
    assert orchestrator(w).pending_gates() == []


def test_like_with_an_unknown_deck_stops_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes: Fakes, terminal: None
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    result = build(w, "--like", "Globex Only.pptx", input=APPROVE * 4)
    assert result.exit_code == 1, result.output
    assert len(w.composer.prompts) == 0
    assert orchestrator(w).state.approvals == {}
