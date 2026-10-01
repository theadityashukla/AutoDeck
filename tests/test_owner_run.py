"""The owner's run: A7 integrity and the failures the owner guide exposed.

Found by writing `docs/OWNER-GUIDE.md` honestly: every command was run against the real CLI,
and several steps could not be described truthfully because the behaviour was wrong. Two
groups:

**A7 integrity.** An approval is a human's statement about a specific artifact. Today it is
a timestamp and a name with nothing tying it to what was approved, so re-running a stage
after approval silently changes what the approval covers, and `approve` records approval of
artifacts that do not exist. The fix, one design:

- `Orchestrator.approve(gate, approver=…)` records, beside the timestamp and name, the
  **fingerprint of the artifact the gate covers**: brief → sha256 of the current brief file;
  outline → sha256 of the IR version the outline stage produced; claims → sha256 of the IR
  version the validate stage produced; final_render → sha256 of the rendered PPTX's
  `canonical_pptx_digest`. Store it in `state.json`; older `state.json` files without a
  fingerprint are read as "approved, fingerprint unknown" and treated as NOT approved by
  `require_gate` (fail safe, with a message saying re-approve).
- `require_gate(gate)` passes only if the approval's fingerprint equals the current
  artifact's. A mismatch raises `GateBlocked` naming the gate and saying the artifact changed
  after approval. Re-running a stage therefore invalidates the approval automatically; no
  code has to remember to clear it.
- `approve` refuses (clear error, non-zero exit, nothing written) when the gate's artifact
  does not exist yet.
- Every command except `plan` refuses an unknown run id instead of creating an empty run.

**The owner's session on a free tier.**

- Provider failures (`RateLimitError`, `ProviderAuthError`) end a CLI command with a short
  message and exit code 5, never a traceback: which role and model, what it means (daily
  quota resets; or which environment variable is missing), and what has been saved.
- `plan`, `outline`, `content` and `validate` pass the existing
  `autodeck.providers.cache.ResponseCache` rooted at `runs/<run>/cache/`, so re-running a
  command after a quota failure replays completed calls for free and resumes. Do not build a
  second resume mechanism — use the cache that exists.
- `gate2` writes the rendered audit report to `runs/<run>/audit_report.md` every time it runs
  (A6: every deck ships an audit report) and says so.
- `content` reports every dropped block individually — slide, slot, and the first 60
  characters of the sentence — for budget overflows and for `incomplete_slots`, instead of a
  per-slot count that under-reports.
- `status` marks `plan` and `outline` complete when they are.
- `plan` persists the draft brief on `/quit`, `/exit`, Ctrl-C and Ctrl-D, and re-running
  `plan` on the same run id resumes from it, saying so. Signing still happens only by
  `/sign <name>`.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from autodeck.cli import app
from autodeck.ir.store import IRStore
from autodeck.pipeline.orchestrator import ArtifactMissing, Gate, GateBlocked, Orchestrator
from autodeck.providers.base import ProviderAuthError, ProviderConfig, RateLimitError
from autodeck.providers.gemini import GeminiProvider
from tests.gate_artifacts import seed_artifact
from tests.test_cli_gate2 import (
    CLIENT,
    DOC_ID,
    PROJECT,
    QUOTE,
    ScriptedContent,
    content_draft,
    make_run,
    patch_content_model,
    run_content,
    run_gate2,
)
from tests.test_cli_gate2 import _validated_run as validated_run
from tests.test_content import requires_test_font
from tests.test_planner import (
    MEMORY,
    OBJECTIVE,
    AlwaysSupported,
    ScriptedModel,
    complete_action,
)

# -- A7 integrity ---------------------------------------------------------------------------

runner = CliRunner()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_path(orchestrator: Orchestrator, gate: Gate) -> Path:
    """The file whose bytes a gate's fingerprint must equal, found independently of the
    orchestrator's own lookup so the test is not the implementation agreeing with itself."""
    if gate is Gate.BRIEF:
        return orchestrator.paths.brief / "v1.yaml"
    stage = "outline" if gate is Gate.OUTLINE else "validate"
    version = json.loads(orchestrator.paths.state_file.read_text())["stages"][stage][
        "ir_version"
    ]
    return orchestrator.paths.ir / f"v{version}.json"


def _invoke(runs_root: Path, *args: str) -> Result:
    return runner.invoke(app, [*args, "--runs-root", str(runs_root)])


@pytest.mark.parametrize("gate", ["brief", "outline", "claims"])
def test_an_approval_records_the_fingerprint_of_what_was_approved(
    tmp_path: Path, gate: str
) -> None:
    """After approving, `state.json` holds a sha256 for that gate's artifact alongside the
    approver and time."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    seed_artifact(orchestrator, Gate(gate))
    orchestrator.approve(Gate(gate), approver="aditya")

    stored = json.loads(orchestrator.paths.state_file.read_text(encoding="utf-8"))
    assert "aditya" in stored["approvals"][gate]
    assert stored["fingerprints"][gate] == _sha256(_artifact_path(orchestrator, Gate(gate)))
    assert len(stored["fingerprints"][gate]) == 64


def test_rerunning_the_outline_after_approval_invalidates_the_approval(
    tmp_path: Path,
) -> None:
    """Approve outline; re-run the outline stage (new IR bytes); `content` refuses with
    `GateBlocked` whose message says the outline changed after approval. Re-approving
    lets it proceed. The guide found this silently passing."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    seed_artifact(orchestrator, Gate.OUTLINE)
    orchestrator.approve(Gate.OUTLINE)
    orchestrator.require_gate(Gate.OUTLINE)

    # What `autodeck outline` does on a second run: the same IR version, different bytes.
    deck = orchestrator.ir.load(1).model_copy(update={"audience": "a different audience"})
    orchestrator.run_stage(
        "outline", lambda: f"wrote {orchestrator.save_ir(deck, overwrite=True)}", force=True
    )

    with pytest.raises(GateBlocked, match="outline changed after it was approved"):
        Orchestrator("r1", runs_root=tmp_path).require_gate(Gate.OUTLINE)

    # Through the CLI: `content` stops at the gate, exit 3, before it touches anything.
    refused = _invoke(tmp_path, "content", "r1")
    assert refused.exit_code == 3
    assert "outline changed after it was approved" in refused.output
    assert "autodeck approve r1 outline" in refused.output

    # Re-approving is an explicit human act, and it is what lets the run continue.
    approved = _invoke(tmp_path, "approve", "r1", "outline")
    assert approved.exit_code == 0, approved.output
    Orchestrator("r1", runs_root=tmp_path).require_gate(Gate.OUTLINE)


def test_an_approval_without_a_fingerprint_does_not_count(tmp_path: Path) -> None:
    """A `state.json` in the old format (timestamp and name only) is treated as not
    approved, with a message telling the owner to re-approve."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    seed_artifact(orchestrator, Gate.OUTLINE)
    old_format = json.loads(orchestrator.paths.state_file.read_text(encoding="utf-8"))
    old_format.pop("fingerprints")
    old_format["approvals"] = {"outline": "2026-09-01T10:00:00+00:00 by owner"}
    orchestrator.paths.state_file.write_text(json.dumps(old_format), encoding="utf-8")

    reopened = Orchestrator("r1", runs_root=tmp_path)
    assert not reopened.state.is_approved(Gate.OUTLINE)
    assert Gate.OUTLINE in reopened.pending_gates()
    with pytest.raises(GateBlocked, match=r"(?i)re-approve"):
        reopened.require_gate(Gate.OUTLINE)

    status = _invoke(tmp_path, "status", "r1")
    assert status.exit_code == 0, status.output
    assert "NOT CURRENT" in status.output
    assert "Re-approve" in status.output


@pytest.mark.parametrize("gate", ["outline", "claims"])
def test_approving_a_gate_whose_artifact_does_not_exist_is_refused(
    tmp_path: Path, gate: str
) -> None:
    """`autodeck approve <run> <gate>` on a run where that stage never ran exits non-zero,
    names what is missing, and writes nothing to `state.json`. The guide found
    `approve quit-demo claims` succeeding on an empty run."""
    Orchestrator("r1", runs_root=tmp_path)
    state_file = tmp_path / "r1" / "state.json"
    before = state_file.read_bytes() if state_file.exists() else None

    refused = _invoke(tmp_path, "approve", "r1", gate)

    assert refused.exit_code != 0
    stage = "outline" if gate == "outline" else "validate"
    assert f"the {stage} stage has not completed" in refused.output
    assert f"autodeck {stage} r1" in refused.output
    assert (state_file.read_bytes() if state_file.exists() else None) == before

    # The other two gates refuse the same way when their artifacts are absent, directly.
    fresh = Orchestrator("r1", runs_root=tmp_path)
    for other in (Gate.BRIEF, Gate.FINAL_RENDER):
        with pytest.raises(ArtifactMissing):
            fresh.approve(other)
    assert (state_file.read_bytes() if state_file.exists() else None) == before


#: Commands beyond the five the spec names that also work on an existing run. They ride on
#: the `approve` case below rather than adding cases of their own.
_ALSO_NEEDS_A_RUN = (
    ("outline", "--client", "c", "--project", "p"),
    ("send-back", "--claim", "s1:b1", "--reason", "x"),
    ("ir", "versions"),
    ("ir", "diff", "1", "2"),
)


@pytest.mark.parametrize("command", ["approve", "status", "content", "validate", "gate2"])
def test_an_unknown_run_id_is_an_error_not_a_new_run(tmp_path: Path, command: str) -> None:
    """Non-zero exit, message says no such run, and no `runs/<id>/` directory is created."""
    invocations: list[tuple[str, ...]] = [(command,)]
    if command == "approve":
        invocations += list(_ALSO_NEEDS_A_RUN)

    for invocation in invocations:
        head, rest = invocation[0], invocation[1:]
        if head == "ir":
            args = [head, rest[0], "ghost", *rest[1:]]
        elif command == "approve" and head == "approve":
            args = ["approve", "ghost", "brief"]
        else:
            args = [head, "ghost", *rest]
        result = _invoke(tmp_path, *args)

        assert result.exit_code != 0, args
        assert "no such run 'ghost'" in result.output, args
        assert not (tmp_path / "ghost").exists(), args
    assert list(tmp_path.iterdir()) == []


# -- the owner's session ----------------------------------------------------------------------


def _patch_roles(monkeypatch: pytest.MonkeyPatch, **by_role: object) -> None:
    """Hand each role its own fake; any role not named gets `AlwaysSupported`."""
    import autodeck.providers.registry as registry_module

    fallback = AlwaysSupported()
    monkeypatch.setattr(
        registry_module.ModelRegistry,
        "provider_for",
        lambda self, role, **kw: by_role.get(role, fallback),
    )


def _binding(role: str) -> tuple[str, str]:
    from autodeck.providers.registry import ModelRegistry

    binding = ModelRegistry.load("dev").binding(role)
    return binding.provider, binding.model


class ScriptedOutline:
    def __init__(self, draft) -> None:  # type: ignore[no-untyped-def]
        self.draft = draft

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        return self.draft


class _Failing:
    """A `content` model that raises whatever it is given."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        raise self.error


@pytest.mark.parametrize("failure", ["rate limit", "missing key"])
def test_provider_failures_end_with_a_message_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A fake provider raising `RateLimitError` / `ProviderAuthError` inside `content`: exit
    code 5, output names the role and model and says what to do, and contains no
    "Traceback"."""
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    provider, model = _binding("content")

    if failure == "rate limit":
        _patch_roles(monkeypatch, content=_Failing(RateLimitError("groq: rate limited (429)")))
    else:
        import autodeck.providers.registry as registry_module

        def no_key(self, role, **kw):  # type: ignore[no-untyped-def]
            raise ProviderAuthError(f"{provider} has no API key. Set X in the environment.")

        monkeypatch.setattr(registry_module.ModelRegistry, "provider_for", no_key)

    result = run_content(runs_root, knowledge_root, corpus_root)

    assert result.exit_code == 5, result.output
    assert "Traceback" not in result.output
    assert "role 'content'" in result.output
    assert model in result.output
    assert "Saved:" in result.output
    assert "autodeck content r1" in result.output
    if failure == "rate limit":
        assert "daily quota" in result.output
    else:
        assert "GROQ_API_KEY" in result.output
    # Nothing was half-written: the IR is still the approved outline alone.
    assert IRStore(runs_root, "r1").versions() == [1]
    assert not Orchestrator("r1", runs_root=runs_root).state.is_complete("content")


def _three_slide_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    """`make_run`, but with three slides whose intents differ, so each has its own prompt
    and therefore its own cache entry."""
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    orchestrator = Orchestrator("r1", runs_root=runs_root)
    deck = orchestrator.ir.load(1)
    slides = [
        deck.slides[0].model_copy(
            update={"id": f"s{n}", "intent": f"State that the kernel rewrite raised {what}."}
        )
        for n, what in ((1, "training throughput"), (2, "sequence rates"), (3, "kernel speed"))
    ]
    three = deck.model_copy(update={"slides": slides})
    orchestrator.run_stage(
        "outline", lambda: f"wrote {orchestrator.save_ir(three, overwrite=True)}", force=True
    )
    orchestrator.approve(Gate.OUTLINE)
    return knowledge_root, corpus_root, runs_root


def test_content_resumes_from_the_cache_after_a_quota_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fake provider that fails on the third slide. First run exits 5. Second run with a
    working provider makes calls only for slides three onward — the first two are replayed
    from `runs/<run>/llm_cache/`. Count provider calls to prove it.

    Uses a real provider class over a counting `httpx` transport, because the cache lives in
    the provider: a fake that replaces the whole provider would never touch it."""
    import httpx

    import autodeck.providers.registry as registry_module

    knowledge_root, corpus_root, runs_root = _three_slide_run(tmp_path)
    reply = content_draft().model_dump_json()
    calls: list[int] = []
    fail_on: list[int | None] = [3]

    class Counting(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            calls.append(len(calls) + 1)
            if calls[-1] == fail_on[0]:
                return httpx.Response(429)
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": reply}]}}]}
            )

    def real_provider_over_fake_wire(self, role, *, cache=None, **overrides):  # type: ignore[no-untyped-def]
        return GeminiProvider(
            ProviderConfig(
                model="m",
                api_key="k",
                cache=cache,
                transport=Counting(),
                max_rate_limit_retries=0,
            )
        )

    monkeypatch.setattr(
        registry_module.ModelRegistry, "provider_for", real_provider_over_fake_wire
    )

    first = run_content(runs_root, knowledge_root, corpus_root)
    assert first.exit_code == 5, first.output
    assert len(calls) == 3
    assert "2 completed provider call(s) are saved" in first.output
    assert IRStore(runs_root, "r1").versions() == [1]

    fail_on[0] = None
    calls.clear()
    second = run_content(runs_root, knowledge_root, corpus_root)

    assert second.exit_code == 0, second.output
    assert len(calls) == 1, (
        "slides one and two must replay from the cache; only slide three is new"
    )
    deck = IRStore(runs_root, "r1").load()
    assert [len(slide.blocks) for slide in deck.slides] == [1, 1, 1]


def test_gate2_writes_the_audit_report_to_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After `gate2`, `runs/<run>/audit_report.md` exists and equals the report printed."""
    runs_root = validated_run(tmp_path, monkeypatch, "supported")
    report_path = runs_root / "r1" / "audit_report.md"
    assert not report_path.exists()

    result = run_gate2(runs_root)

    assert result.exit_code == 0, result.output
    written = report_path.read_text(encoding="utf-8")
    assert written.strip(), "an empty report is not a report"
    assert result.output.startswith(written), "the file is the report the screen showed"
    assert f"Audit report written to {report_path}" in result.output

    # Every run rewrites it, so the file is always the report for the latest IR.
    report_path.write_text("stale", encoding="utf-8")
    assert run_gate2(runs_root).exit_code == 0
    assert report_path.read_text(encoding="utf-8") == written


@requires_test_font
def test_content_names_every_dropped_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two over-budget claims on one slot: output names both, with slide, slot and the start
    of each sentence — not "1 block(s) dropped"."""
    from autodeck.agents.content import (
        ContentDraft,
        ProposedBlock,
        ProposedCitation,
        ProposedClaim,
    )
    from tests.test_content import tokens_for

    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    # A token set whose font is installed here, so the budgets can be measured.
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(tokens_for().model_dump_json(), encoding="utf-8")

    orchestrator = Orchestrator("r1", runs_root=runs_root)
    deck = orchestrator.ir.load(1).model_copy(update={"theme_ref": str(tokens_path)})
    deck = deck.model_copy(
        update={
            "slides": [deck.slides[0].model_copy(update={"component": "bullets_supporting"})]
        }
    )
    orchestrator.run_stage(
        "outline", lambda: f"wrote {orchestrator.save_ir(deck, overwrite=True)}", force=True
    )
    orchestrator.approve(Gate.OUTLINE)

    first = "Kernel fusion lifted throughput on every model we tried, " + "and then some " * 12
    second = "Memory traffic fell sharply once the kernels were fused, " + "and then some " * 12
    blocks = [
        ProposedBlock(
            id=block_id,
            kind="claim",
            slot="points",
            claim=ProposedClaim(
                text=text, citations=[ProposedCitation(doc_id=DOC_ID, quote=QUOTE)]
            ),
        )
        for block_id, text in (("b1", first), ("b2", second))
    ]
    patch_content_model(
        monkeypatch, ScriptedContent(ContentDraft(blocks=blocks, speaker_notes=[]))
    )

    result = run_content(runs_root, knowledge_root, corpus_root)

    assert result.exit_code == 0, result.output
    assert "2 block(s) dropped" in result.output
    dropped = [line for line in result.output.splitlines() if "dropped block '" in line]
    assert len(dropped) == 2, result.output
    for line, block_id, text in zip(dropped, ("b1", "b2"), (first, second), strict=True):
        assert line.lstrip().startswith("slide s1: ")
        assert f"dropped block '{block_id}' (slot 'points')" in line
        assert "overflow" in line
        assert text[:60] in line
        assert text[:61] not in line, "only the first 60 characters"
    assert IRStore(runs_root, "r1").load().slides[0].blocks == []


def _planning(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Knowledge, corpus and runs roots for `plan`. The run it creates is `planning`."""
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    return knowledge_root, corpus_root, runs_root


def _plan(runs_root: Path, knowledge_root: Path, corpus_root: Path, typed: str) -> Result:
    return runner.invoke(
        app,
        [
            "plan",
            "planning",
            "--client",
            CLIENT,
            "--project",
            PROJECT,
            "--knowledge-root",
            str(knowledge_root),
            "--corpus-root",
            str(corpus_root),
            "--runs-root",
            str(runs_root),
        ],
        input=typed,
    )


def test_status_marks_plan_and_outline_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a signed plan and an outline, `status` shows both as complete."""
    from autodeck.agents.outline import OutlineDraft, SlideDraft

    knowledge_root, corpus_root, runs_root = _planning(tmp_path)
    _patch_roles(monkeypatch, planner=ScriptedModel(complete_action()))

    signed = _plan(runs_root, knowledge_root, corpus_root, "let us plan\n/sign Jane Owner\n")
    assert signed.exit_code == 0, signed.output

    before = _invoke(runs_root, "status", "planning")
    assert re.search(r"plan\s+completed", before.output), before.output
    assert re.search(r"outline\s+not-started", before.output), before.output

    outline_draft = OutlineDraft(
        slides=[
            SlideDraft(
                id="s1",
                narrative_role="evidence",
                component="bullets_supporting",
                intent="Establish that memory is the constraint.",
                message_ids=["km1"],
            )
        ]
    )
    _patch_roles(monkeypatch, outline=ScriptedOutline(outline_draft))
    built = runner.invoke(
        app,
        [
            "outline",
            "planning",
            "--client",
            CLIENT,
            "--project",
            PROJECT,
            "--knowledge-root",
            str(knowledge_root),
            "--runs-root",
            str(runs_root),
        ],
    )
    assert built.exit_code in (0, 4), built.output  # 4 = a GATE 1 mechanical check failed

    after = _invoke(runs_root, "status", "planning")
    assert re.search(r"plan\s+completed", after.output), after.output
    assert re.search(r"outline\s+completed", after.output), after.output
    assert "PENDING" in after.output, "status marks the stages; it approves nothing"


@pytest.mark.parametrize("how", ["/quit", "/exit", "EOF"])
def test_leaving_the_planner_keeps_the_draft_and_resumes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """Draft a brief, leave by `how`; nothing is signed. Re-run `plan` on the same run id:
    `/brief` shows the same draft, and the output says it resumed. `/sign` still required."""
    knowledge_root, corpus_root, runs_root = _planning(tmp_path)
    _patch_roles(monkeypatch, planner=ScriptedModel(complete_action()))

    typed = "let us plan\n" + ("" if how == "EOF" else f"{how}\n")
    left = _plan(runs_root, knowledge_root, corpus_root, typed)

    assert left.exit_code == 1, left.output
    assert "left without signing" in left.output
    assert "draft kept" in left.output
    draft_file = runs_root / "planning" / "draft_brief.json"
    assert draft_file.exists()
    orchestrator = Orchestrator("planning", runs_root=runs_root)
    assert not orchestrator.state.is_approved(Gate.BRIEF)
    assert orchestrator.ir.brief_versions() == []

    # A fresh process, a model that would say something different if it were asked: the
    # draft on screen is the one that was saved, not a new one.
    _patch_roles(monkeypatch, planner=ScriptedModel())
    resumed = _plan(runs_root, knowledge_root, corpus_root, "/brief\n/quit\n")

    assert "Resumed the unsigned draft" in resumed.output
    assert OBJECTIVE in resumed.output
    assert MEMORY in resumed.output
    assert resumed.exit_code == 1
    assert not Orchestrator("planning", runs_root=runs_root).state.is_approved(Gate.BRIEF), (
        "resuming approves nothing"
    )

    # Signing is still a human typing /sign.
    signed = _plan(runs_root, knowledge_root, corpus_root, "/sign Jane Owner\n")
    assert signed.exit_code == 0, signed.output
    assert Orchestrator("planning", runs_root=runs_root).state.is_approved(Gate.BRIEF)
    assert not draft_file.exists(), "a signed brief leaves no draft to resume"


def test_a_quota_spent_during_validation_fails_the_stage_rather_than_passing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The validation pass swallows a provider failure on purpose — an unjudged claim is
    reported as unjudged. Left alone, that is a `validate` that exits 0 having judged
    nothing, and a claims table the owner could approve. It must end like any other provider
    failure, with the stage marked failed so `gate2` and `approve ... claims` stay closed."""
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))
    assert run_content(runs_root, knowledge_root, corpus_root).exit_code == 0

    _patch_roles(monkeypatch, validation=_Failing(RateLimitError("gemini: rate limited (429)")))
    result = runner.invoke(
        app,
        ["validate", "r1", "--corpus-root", str(corpus_root), "--runs-root", str(runs_root)],
    )

    assert result.exit_code == 5, result.output
    assert "Traceback" not in result.output
    assert "role 'validation'" in result.output
    orchestrator = Orchestrator("r1", runs_root=runs_root)
    assert not orchestrator.state.is_complete("validate")
    assert run_gate2(runs_root).exit_code == 3
    with pytest.raises(ArtifactMissing, match="validate stage has not completed"):
        orchestrator.approve(Gate.CLAIMS)


class _PlannerThatRunsOut:
    """Answers the first turn, then hits the quota."""

    def __init__(self) -> None:
        self.inner = ScriptedModel(complete_action())
        self.turns = 0

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.turns += 1
        if self.turns > 1:
            raise RateLimitError("gemini: rate limited (429)")
        return self.inner.complete_structured(prompt, response_model, system=system)


def test_a_quota_spent_mid_session_keeps_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_root, corpus_root, runs_root = _planning(tmp_path)
    _patch_roles(monkeypatch, planner=_PlannerThatRunsOut())

    result = _plan(runs_root, knowledge_root, corpus_root, "first\nsecond\n")

    assert result.exit_code == 5, result.output
    assert "Traceback" not in result.output
    assert "role 'planner'" in result.output
    assert "draft brief is kept" in result.output
    assert (runs_root / "planning" / "draft_brief.json").exists()
    assert not Orchestrator("planning", runs_root=runs_root).state.is_approved(Gate.BRIEF)
