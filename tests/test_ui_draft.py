"""The UI's draft-first plumbing (B43, B47, B48): routes, chains, timeline and the draft view.

No model is called: the clarify step goes through a stubbed command runner and jobs through
a stubbed manager, so these tests pin routing and validation, not the pipeline.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from autodeck.ui import api, jobs
from autodeck.ui.api import Roots, UIError
from autodeck.ui.server import App, Handler
from tests.test_renderer import _claim_block, _deck, _slide
from tests.test_ui import Client, make_client, make_run
from tests.test_ui import roots as roots


class StubJobs:
    """Records what would have been started; never runs a process."""

    def __init__(self) -> None:
        self.started: list[tuple[str, str, dict[str, Any]]] = []

    def start(self, run_id: str, chain: str, extra: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
        self.started.append((run_id, chain, dict(extra or {})))
        return jobs.Job(run_id=run_id, steps=list(jobs.CHAINS[chain]))

    def running(self, run_id: str) -> bool:
        return False

    def get(self, run_id: str) -> None:
        return None


def seed_draft(roots: Roots, run_id: str = "r1", verdict: str = "unsupported"):  # type: ignore[no-untyped-def]
    orch = make_run(roots, run_id)
    deck = _deck(
        _slide("s1", "quote", [_claim_block("figure", "A claim.", verdict=verdict)])  # type: ignore[arg-type]
    )
    deck = deck.model_copy(update={"run_id": run_id})
    orch.run_stage("compose", lambda: f"wrote {orch.save_ir(deck)}")
    return orch


def stub_clarify(roots: Roots, calls: list[list[str]]):  # type: ignore[no-untyped-def]
    """Stands in for `autodeck clarify`: records argv and writes what the CLI would."""

    def runner(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        run_id = argv[argv.index("clarify") + 1]
        folder = roots.runs / run_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "clarify.json").write_text(
            json.dumps(
                {
                    "prompt": argv[argv.index("--prompt") + 1],
                    "client": "acme",
                    "project": "proj",
                    "assumptions": [{"topic": "audience", "statement": "The CTO."}],
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Recommend or summarise?",
                            "why": "w",
                            "suggested_answer": "Recommend.",
                            "options": [],
                        }
                    ],
                    "answers": None,
                    "corrections": [],
                }
            )
        )
        return 0, ""

    return runner


# -- /api/draft/start ------------------------------------------------------------------------


def test_draft_start_runs_clarify_and_returns_the_checkpoint(roots: Roots) -> None:
    make_client(roots)
    calls: list[list[str]] = []
    app = App(roots, StubJobs(), cli_runner=stub_clarify(roots, calls))  # type: ignore[arg-type]

    out = app.start_draft(
        {"run_id": "r1", "client": "acme", "project": "proj", "prompt": " Make a deck. "}
    )

    assert out["assumptions"][0]["topic"] == "audience"
    assert out["questions"][0]["id"] == "q1" and out["answered"] is False
    assert out["missing"] == ["q1"]
    [argv] = calls
    assert argv[3:5] == ["clarify", "r1"]
    assert argv[argv.index("--prompt") + 1] == "Make a deck."
    assert argv[argv.index("--client") + 1] == "acme"
    assert api.read_run_meta(roots, "r1") == {"client": "acme", "project": "proj"}


@pytest.mark.parametrize(
    "body",
    [
        {"run_id": "r1", "client": "ghost", "project": "proj", "prompt": "x"},
        {"run_id": "r1", "client": "acme", "project": "ghost", "prompt": "x"},
        {"run_id": "r1", "client": "acme", "project": "proj", "prompt": "  "},
        {"run_id": "../x", "client": "acme", "project": "proj", "prompt": "x"},
    ],
)
def test_draft_start_validates_like_plan_start(roots: Roots, body: dict[str, str]) -> None:
    make_client(roots)
    calls: list[list[str]] = []
    app = App(roots, StubJobs(), cli_runner=stub_clarify(roots, calls))  # type: ignore[arg-type]
    with pytest.raises(UIError):
        app.start_draft(body)
    assert calls == []


def test_draft_start_reports_a_failed_clarify(roots: Roots) -> None:
    make_client(roots)
    app = App(roots, StubJobs(), cli_runner=lambda argv: (5, "STOPPED: rate limited"))  # type: ignore[arg-type]
    with pytest.raises(UIError, match="rate limited"):
        app.start_draft({"run_id": "r1", "client": "acme", "project": "proj", "prompt": "x"})


def test_draft_start_refuses_a_run_that_already_has_a_draft(roots: Roots) -> None:
    make_client(roots)
    seed_draft(roots)
    api.write_run_meta(roots, "r1", client="acme", project="proj")
    app = App(roots, StubJobs(), cli_runner=lambda argv: (0, ""))  # type: ignore[arg-type]
    with pytest.raises(UIError) as caught:
        app.start_draft({"run_id": "r1", "client": "acme", "project": "proj", "prompt": "x"})
    assert caught.value.status == 409


# -- answers ---------------------------------------------------------------------------------


def test_answers_are_recorded_and_start_the_draft_chain(roots: Roots) -> None:
    make_client(roots)
    stub = StubJobs()
    app = App(roots, stub, cli_runner=stub_clarify(roots, []))  # type: ignore[arg-type]
    app.start_draft({"run_id": "r1", "client": "acme", "project": "proj", "prompt": "x"})

    with pytest.raises(UIError, match="unanswered"):
        app.submit_answers("r1", {})
    assert stub.started == []

    out = app.submit_answers("r1", {"accept_all": True, "corrections": ["Two slides."]})
    assert out["answers"] == {"q1": "Recommend."}
    assert stub.started == [("r1", "draft", {})]
    view = api.clarify_view(roots, "r1")
    assert view["answered"] is True and view["corrections"] == ["Two slides."]


def test_clarify_view_404s_without_a_clarify_step(roots: Roots) -> None:
    make_run(roots)
    with pytest.raises(UIError) as caught:
        api.clarify_view(roots, "r1")
    assert caught.value.status == 404


# -- chat: one conversation (B48) ------------------------------------------------------------


def test_chat_goes_to_the_planner_before_a_draft_exists(
    roots: Roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_run(roots)
    stub = StubJobs()
    app = App(roots, stub)  # type: ignore[arg-type]
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        app, "plan_say", lambda run_id, body: seen.append(body) or {"draft": "d"}
    )

    out = app.chat("r1", {"text": "Make it about cost."})

    assert out == {"mode": "plan", "draft": "d"}
    assert seen == [{"text": "Make it about cost."}] and stub.started == []


def test_chat_after_a_draft_is_a_revision(
    roots: Roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_draft(roots)
    stub = StubJobs()
    app = App(roots, stub)  # type: ignore[arg-type]
    monkeypatch.setattr(app, "plan_say", lambda *a: pytest.fail("the planner is not used"))

    out = app.chat("r1", {"text": "Soften slide 2."})

    assert out["mode"] == "revise" and out["job"]["steps"] == ["revise", "validate", "preview"]
    assert stub.started == [("r1", "revise", {"instruction": "Soften slide 2."})]
    with pytest.raises(UIError):
        app.chat("r1", {"text": "  "})


def test_revise_route_needs_a_draft_and_an_instruction(roots: Roots) -> None:
    make_run(roots)
    app = App(roots, StubJobs())  # type: ignore[arg-type]
    with pytest.raises(UIError) as caught:
        app.start_revise("r1", {"instruction": "x"})
    assert caught.value.status == 409
    seed_draft(roots, "r2")
    with pytest.raises(UIError):
        app.start_revise("r2", {"instruction": ""})


@pytest.fixture
def http(roots: Roots) -> Iterator[tuple[Client, App, StubJobs]]:
    from http.server import ThreadingHTTPServer

    stub = StubJobs()
    app = App(roots, stub, cli_runner=stub_clarify(roots, []))  # type: ignore[arg-type]
    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(httpd.server_address[1]), app, stub
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_the_routes_are_wired(roots: Roots, http: tuple[Client, App, StubJobs]) -> None:
    client, _app, stub = http
    make_client(roots)
    status, body = client.json(
        "POST",
        "/api/draft/start",
        {"run_id": "r1", "client": "acme", "project": "proj", "prompt": "Make a deck."},
    )
    assert status == 200 and body["questions"][0]["id"] == "q1"
    status, body = client.json("GET", "/api/runs/r1/clarify")
    assert status == 200 and body["answered"] is False
    status, body = client.json("POST", "/api/runs/r1/answers", {"accept_all": True})
    assert status == 200 and body["job"]["steps"] == ["draft", "validate", "preview"]
    assert stub.started == [("r1", "draft", {})]

    seed_draft(roots, "r2")
    status, body = client.json("POST", "/api/runs/r2/chat", {"text": "Shorter."})
    assert status == 200 and body["mode"] == "revise"
    assert stub.started[-1] == ("r2", "revise", {"instruction": "Shorter."})
    status, body = client.json("POST", "/api/runs/r2/revise", {"instruction": "Again."})
    assert status == 200 and stub.started[-1][2] == {"instruction": "Again."}

    status, body = client.json("GET", "/api/runs/r2/draft")
    assert status == 200 and body["slides"][0]["blocks"][0]["verdict"] == "unsupported"
    status, _ = client.request("GET", "/api/runs/r2/draft-preview/1")
    assert status == 404  # no preview drawn yet
    status, _ = client.request("POST", "/api/runs/r2/chat", raw=b"{}")
    assert status == 415  # JSON only, like every POST


# -- the draft view, timeline and chains -------------------------------------------------------


def test_draft_view_shows_slides_verdicts_flags_and_approvals(roots: Roots) -> None:
    seed_draft(roots)
    out = api.draft_view(roots, "r1")
    [slide] = out["slides"]
    assert slide["flag"] == "blocking" and out["flags"] == {"s1": "blocking"}
    [block] = slide["blocks"]
    assert block["text"] == "A claim." and block["verdict"] == "unsupported"
    assert block["citations"] and {"doc_id", "page", "quote"} <= set(block["citations"][0])
    assert slide["preview"] is None and out["previews"] == []
    assert set(out["approvals"]) == {"brief", "outline", "claims", "final"}
    assert all(a["approved"] is False for a in out["approvals"].values())
    assert out["coverage"] == [] and out["revisions"] == []


def test_draft_view_needs_a_draft(roots: Roots) -> None:
    make_run(roots)
    with pytest.raises(UIError) as caught:
        api.draft_view(roots, "r1")
    assert caught.value.status == 409


def test_draft_view_lists_previews_and_coverage(roots: Roots) -> None:
    orch = seed_draft(roots)
    previews = orch.paths.root / "previews" / "draft"
    previews.mkdir(parents=True)
    (previews / "draft-1.png").write_bytes(b"\x89PNG")
    (orch.paths.root / "coverage.json").write_text(
        json.dumps({"coverage": [{"item": "x", "status": "gap", "detail": "d"}], "origins": {}})
    )
    (orch.paths.root / "revisions.jsonl").write_text(
        json.dumps({"instruction": "i", "reply": "r", "at": "t"}) + "\n"
    )
    out = api.draft_view(roots, "r1")
    assert out["slides"][0]["preview"] == "/api/runs/r1/draft-preview/1"
    assert out["coverage"][0]["status"] == "gap"
    assert out["revisions"] == [{"instruction": "i", "reply": "r", "at": "t"}]
    assert api.draft_preview_file(roots, "r1", 1) == (b"\x89PNG", "image/png")


def test_a_draft_first_timeline_lists_the_draft_steps(roots: Roots) -> None:
    seed_draft(roots)
    labels = [s["label"] for s in api.run_summary(roots, "r1")["stage_list"]]
    assert labels == [
        "Check what the draft needs",
        "Write brief, outline and slides",
        "Check every claim",
        "Draw the draft",
        "Approve the brief",
        "Approve the outline",
        "Approve the claims",
        "Art direction and render",
        "Final audit",
        "Approve the final deck",
    ]
    summary = api.run_summary(roots, "r1")
    compose = next(s for s in summary["stage_list"] if s["key"] == "compose")
    assert compose["status"] == "done"
    assert summary["resume"] == "#/draft/r1"


def test_a_gate_first_timeline_is_unchanged(roots: Roots) -> None:
    make_run(roots)
    labels = [s["label"] for s in api.run_summary(roots, "r1")["stage_list"]]
    assert labels[0] == "Plan the brief" and "Build the outline" in labels


def test_chains_and_commands_for_the_draft_steps(roots: Roots) -> None:
    assert jobs.CHAINS["draft"] == ["draft", "validate", "preview"]
    assert jobs.CHAINS["revise"] == ["revise", "validate", "preview"]
    argv = jobs.cli_command("revise", "r1", roots=roots, extra={"instruction": "Shorter."})
    assert argv[3:5] == ["revise", "r1"] and argv[argv.index("--instruction") + 1] == "Shorter."
    argv = jobs.cli_command("draft", "r1", roots=roots, extra={"from_chat": True})
    assert "--from-chat" in argv and argv[argv.index("--runs-root") + 1] == str(roots.runs)
    assert "--from-chat" not in jobs.cli_command("draft", "r1", roots=roots)
    argv = jobs.cli_command("preview", "r1", roots=roots)
    assert argv[3:5] == ["preview", "r1"]
    for step in ("clarify", "draft", "revise", "preview"):
        assert "--by" not in jobs.cli_command(step, "r1", roots=roots)


def test_a_job_passes_its_extra_inputs_to_the_command() -> None:
    import sys

    seen: list[tuple[str, dict[str, Any]]] = []

    def command_for(step: str, run_id: str, extra: dict[str, Any] | None = None) -> list[str]:
        seen.append((step, dict(extra or {})))
        return [sys.executable, "-c", "pass"]

    manager = jobs.JobManager(command_for)
    manager.start("r1", "revise", {"instruction": "Shorter."})
    job = manager.wait("r1")
    assert job is not None and job.status == "done"
    assert seen == [
        (step, {"instruction": "Shorter."}) for step in ("revise", "validate", "preview")
    ]


def test_the_generic_run_route_does_not_start_draft_chains(roots: Roots) -> None:
    make_run(roots)
    app = App(roots, StubJobs())  # type: ignore[arg-type]
    with pytest.raises(UIError):
        app.start_job("r1", "revise")


def test_draft_view_carries_storyline_findings_per_slide_and_deck_level(roots: Roots) -> None:
    from autodeck.ir.models import StorylineCheck, StorylineFinding

    deck = _deck(
        _slide("s1", "quote", [_claim_block("figure", "A.", verdict="supported")]),  # type: ignore[arg-type]
        _slide("s2", "quote", [_claim_block("figure", "B.", verdict="supported")]),  # type: ignore[arg-type]
    ).model_copy(update={"run_id": "r1"})
    orch = make_run(roots, "r1")
    orch.run_stage("compose", lambda: f"wrote {orch.save_ir(deck)}")
    out = api.draft_view(roots, "r1")
    assert out["storyline_check"] is None
    assert all(s["storyline_findings"] == [] for s in out["slides"])

    check = StorylineCheck(
        tells_story=False,
        summary="Jumps.",
        findings=[StorylineFinding(slide_id="s2", issue="repeats", notes="Same as s1.")],
    )
    orch2 = make_run(roots, "r2")
    orch2.run_stage(
        "compose",
        lambda: f"wrote {orch2.save_ir(deck.model_copy(update={'run_id': 'r2', 'storyline_check': check}))}",
    )
    out = api.draft_view(roots, "r2")
    s1, s2 = out["slides"]
    assert s1["storyline_findings"] == [] and s1["flag"] == ""
    assert s2["storyline_findings"] == [{"slide_id": "s2", "issue": "repeats", "notes": "Same as s1."}]
    assert s2["flag"] == "story"
    assert out["storyline_check"]["summary"] == "Jumps."
