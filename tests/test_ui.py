"""The review UI: its API functions, its local HTTP server, and the A7 gate-bypass guards.

Everything runs against `tmp_path` roots. No test makes a model call: the planning routes
are only exercised up to the point where they refuse a request.
"""

from __future__ import annotations

import http.client
import json
import re
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import autodeck
from autodeck.pipeline.orchestrator import Gate, Orchestrator
from autodeck.ui import api, jobs, profile
from autodeck.ui.api import Roots, UIError
from autodeck.ui.server import App, make_server
from tests.gate_artifacts import seed_artifact


@pytest.fixture
def roots(tmp_path: Path) -> Roots:
    (tmp_path / "knowledge" / "projects" / "proj").mkdir(parents=True)
    return Roots(
        knowledge=tmp_path / "knowledge",
        corpus=tmp_path / "corpus",
        runs=tmp_path / "runs",
        env="dev",
        profile=tmp_path / "profile.json",
    )


def make_client(roots: Roots, name: str = "acme") -> None:
    api.create_client(
        roots, name=name, client_md="A manufacturer.", value_prop_md="Plain language."
    )


def make_run(roots: Roots, run_id: str = "r1") -> Orchestrator:
    return Orchestrator(run_id, runs_root=roots.runs, env="dev")


# ---------------------------------------------------------------------------
# create_client
# ---------------------------------------------------------------------------


def test_create_client_writes_both_files(roots: Roots) -> None:
    folder = api.create_client(
        roots, name="acme-co", client_md="Who they are.", value_prop_md="How they talk."
    )
    assert folder == roots.knowledge / "clients" / "acme-co"
    assert "Who they are." in (folder / "client.md").read_text(encoding="utf-8")
    assert "How they talk." in (folder / "value_prop.md").read_text(encoding="utf-8")
    assert api.list_clients(roots) == ["acme-co"]


@pytest.mark.parametrize("name", ["", "Bad Name", "../x", "-lead", "UPPER"])
def test_create_client_refuses_a_bad_name(roots: Roots, name: str) -> None:
    with pytest.raises(UIError) as caught:
        api.create_client(roots, name=name, client_md="x", value_prop_md="y")
    assert caught.value.status == 400
    assert api.list_clients(roots) == []


def test_create_client_refuses_an_existing_name(roots: Roots) -> None:
    make_client(roots)
    with pytest.raises(UIError) as caught:
        api.create_client(roots, name="acme", client_md="x", value_prop_md="y")
    assert caught.value.status == 409


@pytest.mark.parametrize(("who", "positioning"), [("", "text"), ("text", "  "), ("", "")])
def test_create_client_refuses_empty_fields(roots: Roots, who: str, positioning: str) -> None:
    with pytest.raises(UIError):
        api.create_client(roots, name="acme", client_md=who, value_prop_md=positioning)
    assert not (roots.knowledge / "clients" / "acme").exists()


@pytest.mark.parametrize("field", ["client_md", "value_prop_md"])
def test_create_client_refuses_text_naming_another_client(roots: Roots, field: str) -> None:
    """A4: caught while typing, not only at build time."""
    make_client(roots, "acme")
    texts = {"client_md": "Fine.", "value_prop_md": "Fine."}
    texts[field] = "We beat acme on price."
    with pytest.raises(UIError, match="acme"):
        api.create_client(roots, name="globex", **texts)
    assert not (roots.knowledge / "clients" / "globex").exists()


# ---------------------------------------------------------------------------
# lint_framing
# ---------------------------------------------------------------------------


def test_lint_framing_flags_a_numeral_and_a_proven_claim(roots: Roots) -> None:
    numeral = api.lint_framing("We cut costs by 40% last year.")
    assert numeral
    assert all({"reason", "severity", "excerpt", "detail"} <= set(f) for f in numeral)
    assert "line 1" in numeral[0]["excerpt"]
    assert api.lint_framing("A proven approach to planning.")


def test_lint_framing_reports_the_line_number() -> None:
    findings = api.lint_framing("Calm and plain.\n\nOur proven method.")
    assert findings
    assert all("line 3" in f["excerpt"] for f in findings)


def test_lint_framing_passes_clean_text() -> None:
    assert api.lint_framing("We help teams plan with care.\nPlain language, short words.") == []
    assert api.lint_framing("") == []


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


def test_run_summary_maps_gates_to_stages(roots: Roots) -> None:
    orch = make_run(roots)
    seed_artifact(orch, Gate.BRIEF)
    orch.approve(Gate.BRIEF, approver="aditya")
    seed_artifact(orch, Gate.OUTLINE)
    orch.approve(Gate.OUTLINE, approver="aditya")

    summary = api.run_summary(roots, "r1")
    assert summary["stages"] == {
        "brief": "done",
        "outline": "done",
        "claims": "now",
        "final": "todo",
    }
    by_gate = {g["gate"]: g for g in summary["gates"]}
    assert by_gate["brief"]["approved"] and by_gate["brief"]["by"] == "aditya"
    assert not by_gate["claims"]["approved"]
    assert summary["next"] == "Next: write the content"


def test_a_fresh_run_waits_at_the_brief(roots: Roots) -> None:
    make_run(roots)
    summary = api.run_summary(roots, "r1")
    assert summary["stages"]["brief"] == "now"
    assert [summary["stages"][k] for k in ("outline", "claims", "final")] == ["todo"] * 3
    assert summary["next"] == "Planning not finished"


def test_next_text_for_a_draft_brief(roots: Roots) -> None:
    orch = make_run(roots)
    orch.paths.draft_brief.parent.mkdir(parents=True, exist_ok=True)
    orch.paths.draft_brief.write_text("{}", encoding="utf-8")
    assert api.run_summary(roots, "r1")["next"] == "Brief draft saved, not signed"


def test_run_meta_feeds_the_summary_and_the_resume_link(roots: Roots) -> None:
    make_run(roots)
    api.write_run_meta(roots, "r1", client="acme", project="proj")
    summary = api.run_summary(roots, "r1")
    assert (summary["client"], summary["project"]) == ("acme", "proj")
    assert summary["resume"] == "#/plan/r1"
    assert "--client acme --project proj" in summary["command_hint"]


def test_unknown_run_is_a_404(roots: Roots) -> None:
    with pytest.raises(UIError) as caught:
        api.run_summary(roots, "nope")
    assert caught.value.status == 404
    assert not (roots.runs / "nope").exists()  # looking must not create


@pytest.mark.parametrize("run_id", ["../x", "a b", "", ".hidden", "a/b"])
def test_an_invalid_run_id_is_rejected(roots: Roots, run_id: str) -> None:
    with pytest.raises(UIError) as caught:
        api.run_summary(roots, run_id)
    assert caught.value.status == 400
    with pytest.raises(UIError):
        api.check_run_id(run_id)


def test_list_runs_returns_each_run(roots: Roots) -> None:
    assert api.list_runs(roots) == []
    make_run(roots, "r1")
    make_run(roots, "r2")
    assert {r["id"] for r in api.list_runs(roots)} == {"r1", "r2"}


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            sent = dict(headers or {})
            data = raw
            if body is not None:
                data = json.dumps(body).encode("utf-8")
                sent.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=data, headers=sent)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def json(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        status, payload = self.request(method, path, body)
        return status, json.loads(payload)


@pytest.fixture
def server(roots: Roots) -> Iterator[Client]:
    httpd = make_server(roots, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/static/app.css"])
def test_static_files_are_served(server: Client, path: str) -> None:
    status, body = server.request("GET", path)
    assert status == 200
    assert body


def test_home_has_the_expected_keys(server: Client) -> None:
    status, payload = server.json("GET", "/api/home")
    assert status == 200
    assert {"env", "checks", "clients", "projects", "runs"} <= set(payload)
    assert payload["projects"] == ["proj"]
    assert payload["env"]["name"] == "dev"


def test_a_foreign_host_header_is_refused(server: Client) -> None:
    status, _ = server.request("GET", "/api/home", headers={"Host": "evil.example"})
    assert status == 403
    status, _ = server.request("GET", "/", headers={"Host": "evil.example:80"})
    assert status == 403


def test_a_non_json_post_is_refused(server: Client, roots: Roots) -> None:
    status, _ = server.request(
        "POST",
        "/api/clients",
        raw=b'{"name": "acme"}',
        headers={"Content-Type": "text/plain"},
    )
    assert status == 415
    assert api.list_clients(roots) == []


def test_post_clients_creates_a_client(server: Client, roots: Roots) -> None:
    status, payload = server.json(
        "POST", "/api/clients", {"name": "acme", "client_md": "Who.", "value_prop_md": "How."}
    )
    assert status == 200 and payload["name"] == "acme"
    assert (roots.knowledge / "clients" / "acme" / "client.md").is_file()
    status, payload = server.json(
        "POST", "/api/clients", {"name": "acme", "client_md": "Who.", "value_prop_md": "How."}
    )
    assert status == 409 and "error" in payload


def test_an_unknown_api_path_is_404(server: Client) -> None:
    assert server.json("GET", "/api/nothing-here")[0] == 404
    assert server.json("POST", "/api/nothing-here", {})[0] == 404
    assert server.json("GET", "/api/runs/missing")[0] == 404


@pytest.mark.parametrize(
    "path",
    [
        "/static/../../pyproject.toml",
        "/static/%2e%2e/%2e%2e/pyproject.toml",
        "/../pyproject.toml",
    ],
)
def test_path_traversal_does_not_return_files(server: Client, path: str) -> None:
    status, body = server.request("GET", path)
    assert status == 404
    assert b"[project]" not in body and b"[tool." not in body


def test_plan_start_refuses_an_unknown_client(server: Client, roots: Roots) -> None:
    status, payload = server.json(
        "POST", "/api/plan/start", {"run_id": "r1", "client": "ghost", "project": "proj"}
    )
    assert status == 400
    assert "ghost" in payload["error"]
    assert not (roots.runs / "r1").exists()


def test_plan_start_refuses_a_run_that_was_not_started_here(
    server: Client, roots: Roots
) -> None:
    make_client(roots)
    make_run(roots, "r1")  # on disk, no ui.json
    status, payload = server.json(
        "POST", "/api/plan/start", {"run_id": "r1", "client": "acme", "project": "proj"}
    )
    assert status == 409
    assert "already exists" in payload["error"]
    assert not (roots.runs / "r1" / api.UI_META).exists()


# ---------------------------------------------------------------------------
# Profile (B42): the name approvals carry
# ---------------------------------------------------------------------------


def test_profile_falls_back_to_git_then_saves(
    roots: Roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(profile, "_git_name", lambda: "Git Person")
    assert profile.read_profile(roots.profile) == {"name": "Git Person", "source": "git"}
    assert profile.save_profile(roots.profile, "  Ada   Lovelace ")["name"] == "Ada Lovelace"
    assert profile.read_profile(roots.profile) == {"name": "Ada Lovelace", "source": "saved"}


def test_profile_without_any_name_refuses_to_approve(
    roots: Roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(profile, "_git_name", lambda: "")
    monkeypatch.setattr(profile, "_system_name", lambda: "")
    with pytest.raises(UIError) as caught:
        profile.approver_name(roots.profile)
    assert caught.value.status == 409


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_profile_refuses_a_bad_name(roots: Roots, name: str) -> None:
    with pytest.raises(UIError):
        profile.save_profile(roots.profile, name)
    assert not roots.profile.exists()


def test_profile_routes(server: Client) -> None:
    status, saved = server.json("POST", "/api/profile", {"name": "Ada"})
    assert status == 200 and saved == {"name": "Ada", "source": "saved"}
    assert server.json("GET", "/api/profile") == (200, saved)


# ---------------------------------------------------------------------------
# Jobs (B42): pipeline steps run as the CLI commands, one chain per run
# ---------------------------------------------------------------------------


def fake_jobs(codes: dict[str, int]) -> jobs.JobManager:
    """A JobManager whose steps print their name and exit with the given code."""

    def command_for(step: str, run_id: str) -> list[str]:
        code = codes.get(step, 0)
        return [sys.executable, "-c", f"print('ran {step} {run_id}'); raise SystemExit({code})"]

    return jobs.JobManager(command_for)


def test_a_chain_runs_every_step_in_order() -> None:
    manager = fake_jobs({})
    manager.start("r1", "content")
    job = manager.wait("r1")
    assert job is not None and job.status == "done"
    assert [line for line in job.log if line.startswith("ran")] == [
        "ran content r1",
        "ran validate r1",
        "ran gate2 r1",
    ]


def test_a_report_with_findings_does_not_stop_the_chain() -> None:
    manager = fake_jobs({"render": 4})
    manager.start("r1", "render")
    job = manager.wait("r1")
    assert job is not None and job.status == "done" and "ran gate3 r1" in job.log


def test_a_blocked_gate_stops_the_chain_and_says_so() -> None:
    manager = fake_jobs({"content": 3})
    manager.start("r1", "content")
    job = manager.wait("r1")
    assert job is not None and job.status == "failed" and job.exit_code == 3
    assert "ran validate r1" not in job.log
    assert "nothing was approved" in job.message


def test_one_job_per_run_at_a_time() -> None:
    manager = jobs.JobManager(
        lambda step, run_id: [sys.executable, "-c", "import time; time.sleep(5)"]
    )
    manager.start("r1", "outline")
    try:
        with pytest.raises(UIError) as caught:
            manager.start("r1", "outline")
        assert caught.value.status == 409
    finally:
        manager.stop("r1")
    job = manager.wait("r1")
    assert job is not None and job.status == "stopped"


def test_an_unknown_chain_is_refused() -> None:
    with pytest.raises(UIError):
        fake_jobs({}).start("r1", "approve")


def test_cli_commands_carry_the_ui_roots(roots: Roots) -> None:
    make_run(roots)
    api.write_run_meta(roots, "r1", client="acme", project="proj")
    argv = jobs.cli_command("outline", "r1", roots=roots)
    assert argv[1:5] == ["-m", "autodeck.cli", "outline", "r1"]
    assert argv[argv.index("--client") + 1] == "acme"
    assert argv[argv.index("--runs-root") + 1] == str(roots.runs)
    for step in ("content", "validate", "gate2", "render", "gate3"):
        argv = jobs.cli_command(step, "r1", roots=roots)
        assert argv[3:5] == [step, "r1"]
        assert "--by" not in argv  # no step is an approval


# ---------------------------------------------------------------------------
# Approvals (B42): one route, through `Orchestrator.approve`, under the profile name
# ---------------------------------------------------------------------------


def test_approve_records_the_profile_name(roots: Roots) -> None:
    orch = make_run(roots)
    seed_artifact(orch, Gate.OUTLINE)
    profile.save_profile(roots.profile, "Ada")
    app = App(roots, fake_jobs({}))
    result = app.approve_run("r1", {"gate": "outline"})
    assert result["by"] == "Ada" and result["gate"] == "outline"
    assert result["job"]["steps"] == ["content", "validate", "gate2"]
    app.jobs.wait("r1")
    reloaded = Orchestrator("r1", runs_root=roots.runs, create=False)
    assert reloaded.state.approvals["outline"].endswith(" by Ada")


def test_approve_without_the_artifact_is_a_409(roots: Roots) -> None:
    make_run(roots)
    profile.save_profile(roots.profile, "Ada")
    with pytest.raises(UIError) as caught:
        App(roots, fake_jobs({})).approve_run("r1", {"gate": "claims"})
    assert caught.value.status == 409


def test_final_render_needs_a_passing_final_audit(roots: Roots) -> None:
    orch = make_run(roots)
    seed_artifact(orch, Gate.FINAL_RENDER)
    profile.save_profile(roots.profile, "Ada")
    with pytest.raises(UIError) as caught:
        App(roots, fake_jobs({})).approve_run("r1", {"gate": "final_render"})
    assert caught.value.status == 409
    assert (
        "final_render"
        not in Orchestrator("r1", runs_root=roots.runs, create=False).state.approvals
    )


@pytest.mark.parametrize("gate", ["brief", "", "BRIEF", "everything"])
def test_the_brief_and_unknown_gates_cannot_be_approved_here(roots: Roots, gate: str) -> None:
    orch = make_run(roots)
    seed_artifact(orch, Gate.BRIEF)
    profile.save_profile(roots.profile, "Ada")
    with pytest.raises(UIError):
        App(roots, fake_jobs({})).approve_run("r1", {"gate": gate})
    assert Orchestrator("r1", runs_root=roots.runs, create=False).state.approvals == {}


def test_no_approval_while_a_step_is_running(roots: Roots) -> None:
    orch = make_run(roots)
    seed_artifact(orch, Gate.OUTLINE)
    profile.save_profile(roots.profile, "Ada")
    manager = jobs.JobManager(
        lambda step, run_id: [sys.executable, "-c", "import time; time.sleep(5)"]
    )
    app = App(roots, manager)
    manager.start("r1", "outline")
    try:
        with pytest.raises(UIError) as caught:
            app.approve_run("r1", {"gate": "outline"})
        assert caught.value.status == 409
    finally:
        manager.stop("r1")
        manager.wait("r1")
    assert (
        "outline" not in Orchestrator("r1", runs_root=roots.runs, create=False).state.approvals
    )


def test_the_timeline_waits_on_the_person_after_the_outline(roots: Roots) -> None:
    orch = make_run(roots)
    seed_artifact(orch, Gate.BRIEF)
    orch.approve(Gate.BRIEF, approver="aditya")
    seed_artifact(orch, Gate.OUTLINE)
    steps = {s["key"]: s for s in api.run_summary(roots, "r1")["stage_list"]}
    assert steps["planning"]["status"] == "done"
    assert steps["outline"]["status"] == "done"
    assert steps["outline_approval"]["status"] == "yours"
    assert steps["outline_approval"]["screen"] == "outline"
    assert steps["content"]["status"] == "locked"
    assert steps["final_approval"]["status"] == "locked"


# ---------------------------------------------------------------------------
# A7 / B39 / B42: exactly two routes reach an approval, and nothing else does
# ---------------------------------------------------------------------------

UI_ROOT = Path(autodeck.__file__).parent / "ui"


def _ui_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(UI_ROOT.rglob("*.py"))}


def test_only_approvals_py_calls_approve() -> None:
    sources = _ui_sources()
    calls = {name: len(re.findall(r"\.approve\(", src)) for name, src in sources.items()}
    assert calls.pop("approvals.py") == 1
    assert calls.pop("server.py") == 0, "server.py must go through approve_gate"
    assert all(n == 0 for n in calls.values()), calls
    approvals_src = sources["approvals.py"]
    body = approvals_src.split("def approve_gate", 1)[1]
    assert ".approve(" in body
    planning = (UI_ROOT.parent / "pipeline" / "planning.py").read_text(encoding="utf-8")
    assert ".approve(" not in planning


def test_approve_gate_is_reachable_only_from_the_approve_route() -> None:
    sources = _ui_sources()
    for name, src in sources.items():
        if name not in ("approvals.py", "server.py"):
            assert "approve_gate(" not in src, name
            assert not re.search(r"import[^\n]*\bapprovals\b|ui\.approvals", src), name
    server_src = sources["server.py"]
    assert len(re.findall(r"approve_gate\(", server_src)) == 1
    app_approve = server_src.split("    def approve_run(self", 1)[1].split("\n    def ", 1)[0]
    assert "approve_gate(" in app_approve
    assert len(re.findall(r"\.approve_run\(", server_src)) == 1
    route = re.search(r'case "POST", \["runs", run_id, "approve"\]:\s+return (.*)', server_src)
    assert route and "app.approve_run(" in route.group(1)


def test_only_the_plan_sign_route_can_sign_the_brief() -> None:
    sources = _ui_sources()
    server_src = sources["server.py"]
    assert len(re.findall(r"\.sign_off\(", server_src)) == 1
    plan_sign = server_src.split("def plan_sign", 1)[1].split("\ndef ", 1)[0]
    assert ".sign_off(" in plan_sign
    assert len(re.findall(r"\.plan_sign\(", server_src)) == 1
    route = re.search(r'case "POST", \["plan", run_id, "sign"\]:\s+return (.*)', server_src)
    assert route and "plan_sign" in route.group(1)
    for name, src in sources.items():
        if name != "server.py":
            assert ".sign_off(" not in src, name


def test_jobs_never_approve() -> None:
    jobs_src = _ui_sources()["jobs.py"]
    assert ".approve(" not in jobs_src and "approve_gate" not in jobs_src
    assert not re.search(r"import[^\n]*\bapprovals\b|ui\.approvals", jobs_src)
    for chain in jobs.CHAINS.values():
        assert "approve" not in chain and "send-back" not in chain


@pytest.mark.parametrize(
    ("detail", "shown"),
    [
        (
            "wrote /tmp/Gen AI dir/runs/r1/ir/v1.json · 1 provider call(s)",
            "wrote v1.json · 1 provider call(s)",
        ),
        ("wrote runs/r1/ir/v2.json", "wrote v2.json"),
        ("nothing written", "nothing written"),
    ],
)
def test_stage_details_show_file_names_not_paths(detail: str, shown: str) -> None:
    assert api._short_detail(detail) == shown


# ---------------------------------------------------------------------------
# Planning screen: the brief as fields, and why it cannot be approved yet
# ---------------------------------------------------------------------------


def test_an_empty_draft_lists_what_is_missing() -> None:
    from autodeck.agents.planner import Draft
    from autodeck.ui.server import _brief_fields, _sign_blockers

    blockers = _sign_blockers(Draft(), "r1")
    assert any("objective" in b for b in blockers)
    assert any("audience" in b for b in blockers)
    assert any("key messages" in b for b in blockers)
    fields = _brief_fields(Draft())
    assert fields["key_messages"] == [] and fields["objective"] == ""


def test_a_thin_message_without_a_risk_blocks_and_a_complete_draft_does_not() -> None:
    from autodeck.agents.planner import Draft
    from autodeck.ir.models import KeyMessage, OpenRisk
    from autodeck.ui.server import _brief_fields, _sign_blockers

    draft = Draft(
        objective="Decide whether to buy GPUs.",
        audience="CTO",
        key_messages=[
            KeyMessage(id="km1", text="Memory is the bottleneck.", evidence_status="thin")
        ],
    )
    assert any(b.startswith("km1 is thin") for b in _sign_blockers(draft, "r1"))
    draft.open_risks.append(
        OpenRisk(message_id="km1", description="One source only.", accepted_by="Ada")
    )
    assert _sign_blockers(draft, "r1") == []
    [message] = _brief_fields(draft)["key_messages"]
    assert message["evidence"] == "thin" and message["id"] == "km1"


def _stub_live(roots: Roots) -> tuple[App, Any]:
    from types import SimpleNamespace

    from autodeck.agents.planner import Draft
    from autodeck.ui.server import LiveSession

    session = SimpleNamespace(
        signed=False,
        draft=Draft(),
        transcript=SimpleNamespace(turns=[SimpleNamespace(role="human", text="Hello")]),
    )
    app = App(roots, fake_jobs({}))
    live = LiveSession(session, None, "acme", "proj")  # type: ignore[arg-type]
    app.sessions["r1"] = live
    return app, live


def test_a_reply_in_progress_shows_as_thinking_when_the_screen_is_reopened(
    roots: Roots,
) -> None:
    import time

    app, live = _stub_live(roots)
    assert app.plan_state("r1")["thinking"] is False
    live.busy_since = time.monotonic() - 7
    state = app.plan_state("r1")
    assert state["thinking"] is True and state["thinking_for"] >= 7
    with pytest.raises(UIError) as caught:
        app.plan_say("r1", {"text": "another message"})
    assert caught.value.status == 409
