"""The review UI: its API functions, its local HTTP server, and the A7 gate-bypass guards.

Everything runs against `tmp_path` roots. No test makes a model call: the planning routes
are only exercised up to the point where they refuse a request.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import autodeck
from autodeck.pipeline.orchestrator import Gate, Orchestrator
from autodeck.ui import api
from autodeck.ui.api import Roots, UIError
from autodeck.ui.server import make_server
from tests.gate_artifacts import seed_artifact


@pytest.fixture
def roots(tmp_path: Path) -> Roots:
    (tmp_path / "knowledge" / "projects" / "proj").mkdir(parents=True)
    return Roots(
        knowledge=tmp_path / "knowledge",
        corpus=tmp_path / "corpus",
        runs=tmp_path / "runs",
        env="dev",
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
# A7 / B39: the UI cannot approve anything except through the plan sign route
# ---------------------------------------------------------------------------


def test_the_ui_source_never_calls_approve() -> None:
    root = Path(autodeck.__file__).parent
    files = [*sorted((root / "ui").rglob("*.py")), root / "pipeline" / "planning.py"]
    assert len(files) >= 4
    for path in files:
        assert ".approve(" not in path.read_text(encoding="utf-8"), path


def test_only_the_plan_sign_route_can_reach_an_approval() -> None:
    root = Path(autodeck.__file__).parent / "ui"
    server_src = (root / "server.py").read_text(encoding="utf-8")
    # `sign_off` is called from exactly one place, `plan_sign`, ...
    assert len(re.findall(r"\.sign_off\(", server_src)) == 1
    plan_sign = server_src.split("def plan_sign", 1)[1].split("\ndef ", 1)[0]
    assert ".sign_off(" in plan_sign
    # ... and that method is reachable only from the sign route.
    assert len(re.findall(r"\.plan_sign\(", server_src)) == 1
    route = re.search(r'case "POST", \["plan", run_id, "sign"\]:\s+return (.*)', server_src)
    assert route and "plan_sign" in route.group(1)
    # Nothing else in the UI package names an approval.
    for path in sorted(root.rglob("*.py")):
        if path.name != "server.py":
            assert ".sign_off(" not in path.read_text(encoding="utf-8"), path
