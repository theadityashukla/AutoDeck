"""Agent memory (B77): the store, the owner boundary, isolation, the tools, the session, the
manifest, the CLI and the UI route."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autodeck.agents.deck_agent import SessionFiles, resume_deck_agent
from autodeck.agents.tools.memory import memory_tools
from autodeck.agents.tools.registry import ToolBox
from autodeck.audit.manifest import git_state, session_record
from autodeck.knowledge.loader import ClientIsolationError
from autodeck.knowledge.memory import (
    CAPS,
    MAX_ITEM_CHARS,
    MemoryStore,
    MemoryWriteError,
)
from autodeck.providers.base import ToolCall
from autodeck.ui import api
from autodeck.ui.api import Roots
from autodeck.ui.profile import owner_memory_path
from autodeck.ui.server import make_server
from tests.test_cli_draft import (
    CLARIFIED,
    agent_script,
    agent_world,
)
from tests.test_deck_agent import _settings, good_script, start, turn
from tests.test_knowledge import build_knowledge
from tests.test_session import ScriptedConverse
from tests.test_ui import Client

PROJECT = "attention-efficiency"
TICK = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
def knowledge(tmp_path: Path) -> Path:
    return build_knowledge(tmp_path)


def make_store(
    knowledge: Path, tmp_path: Path, client: str = "acme", run_id: str = "r1", **kw
) -> MemoryStore:  # type: ignore[no-untyped-def]
    return MemoryStore(
        knowledge,
        client=client,
        project=PROJECT,
        run_id=run_id,
        owner_path=tmp_path / "owner" / "owner.md",
        clock=lambda: TICK,
        **kw,
    )


# -- the store ---------------------------------------------------------------------


def test_add_replace_remove_rewrite_round_trip(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    assert "remembered under Terms" in store.add("engagement", "Terms", "APLD - patient data")
    text = store.read("engagement")
    assert "- APLD - patient data (run r1)" in text

    store.replace("engagement", "Terms", "APLD - patient data", "APLD - anonymised data")
    assert "anonymised" in store.read("engagement") and "patient data" not in store.read(
        "engagement"
    )

    assert "forgot under Terms" in store.remove("engagement", "Terms", "APLD")
    assert "APLD" not in store.read("engagement")

    store.rewrite("engagement", "## People\n- Shikha - runs the walkthrough\n")
    assert store.load("engagement").sections["People"] == ["Shikha - runs the walkthrough"]
    assert store.load("engagement").sections["Terms"] == []


def test_a_duplicate_add_is_a_no_op_with_a_message(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    store.add("engagement", "Terms", "APLD - patient data")
    before = store.engagement_path.read_text(encoding="utf-8")
    message = store.add("engagement", "Terms", "apld - patient data")
    assert message.startswith("already remembered")
    assert store.engagement_path.read_text(encoding="utf-8") == before


def test_items_carry_the_run_tag(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path, run_id="run-42")
    store.add("engagement", "Decisions", "Ship in Q3")
    assert "- Ship in Q3 (run run-42)" in store.read("engagement")


def test_refusals_unknown_section_long_item_and_cap(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    with pytest.raises(MemoryWriteError, match="no section"):
        store.add("engagement", "Gossip", "x")
    with pytest.raises(MemoryWriteError, match=str(MAX_ITEM_CHARS)):
        store.add("engagement", "Terms", "w" * (MAX_ITEM_CHARS + 1))

    filler = "- " + "y" * 255 + "\n"
    store.rewrite("engagement", "## Terms\n" + filler * 30)
    with pytest.raises(MemoryWriteError, match="Consolidate first"):
        store.add("engagement", "Decisions", "one more thing " * 19)
    assert len(store.read("engagement")) <= CAPS["engagement"]


def test_every_write_is_audited_with_sizes(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    store.add("engagement", "Terms", "APLD - data")
    store.remove("engagement", "Terms", "APLD")
    log = store.engagement_path.parent / "audit.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["op"] for r in records] == ["add", "remove"]
    assert records[0]["chars_before"] == 0
    assert records[0]["chars_after"] == records[1]["chars_before"] > records[1]["chars_after"]
    assert records[0]["run"] == "r1" and records[0]["scope"] == "engagement"
    assert records[0]["at"].startswith("2026-01-02T03:04:05")


# -- the owner boundary ------------------------------------------------------------


@pytest.mark.parametrize(
    "note",
    [
        "Acme likes short decks",
        "Always open with the attention-efficiency summary",
        "Keep slides to 40% white space",
        "Use 1.5 line spacing",
        "Aim for 250 words",
    ],
)
def test_owner_memory_refuses_client_facts(knowledge: Path, tmp_path: Path, note: str) -> None:
    store = make_store(knowledge, tmp_path)
    with pytest.raises(MemoryWriteError):
        store.add("owner", "Deck habits", note)
    assert not store.owner_path.exists()


def test_owner_memory_refuses_engagement_terms_and_people(
    knowledge: Path, tmp_path: Path
) -> None:
    store = make_store(knowledge, tmp_path)
    store.add("engagement", "People", "Shikha - runs the FIA walkthrough")
    store.add("engagement", "Terms", "APLD - anonymised patient data")
    with pytest.raises(MemoryWriteError, match="shikha"):
        store.add("owner", "Note style", "Send Shikha the notes first")
    with pytest.raises(MemoryWriteError, match="apld"):
        store.add("owner", "Note style", "Spell APLD in capitals")


def test_owner_memory_refuses_an_eight_word_copy_of_a_shown_passage(
    knowledge: Path, tmp_path: Path
) -> None:
    passage = "the kernel rewrite raised training throughput on every tested accelerator"
    store = make_store(knowledge, tmp_path, shown_texts=lambda: [passage])
    with pytest.raises(MemoryWriteError, match="copy"):
        store.add(
            "owner", "Deck habits", "kernel rewrite raised training throughput on every tested"
        )
    # Seven words in a row is allowed.
    store.add("owner", "Deck habits", "rewrite raised training throughput on")


def test_owner_memory_allows_style_and_small_counts(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    store.add("owner", "Deck habits", "At most 6 bullets on a slide")
    store.add("owner", "Note style", "Plain verbs, short sentences, no jargon")
    assert "At most 6 bullets" in store.read("owner")


# -- isolation ---------------------------------------------------------------------


def test_two_clients_never_see_each_others_memory(knowledge: Path, tmp_path: Path) -> None:
    acme = make_store(knowledge, tmp_path, "acme")
    globex = make_store(knowledge, tmp_path, "globex")
    acme.add("engagement", "Decisions", "Pilot in Q3")
    assert "Pilot" not in globex.read("engagement")
    assert acme.engagement_path != globex.engagement_path
    assert "acme" in str(acme.engagement_path) and "globex" in str(globex.engagement_path)


def test_a_path_into_another_clients_folder_is_refused(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    with pytest.raises(ClientIsolationError):
        store.namespace.guard(knowledge / "clients" / "globex" / "memory" / "p.md")
    # A project name that climbs out of acme's folder into globex's is refused when the
    # store is built, before any path exists.
    with pytest.raises(ClientIsolationError):
        MemoryStore(
            knowledge,
            client="acme",
            project="../../globex/memory/p",
            run_id="r",
            owner_path=tmp_path / "o.md",
        )


# -- context and tools -------------------------------------------------------------


def test_context_text_marks_memory_as_context_and_demotes_headings(
    knowledge: Path, tmp_path: Path
) -> None:
    store = make_store(knowledge, tmp_path)
    store.add("engagement", "Terms", "APLD - data")
    text = store.context_text()
    assert "context, not evidence" in text
    assert "### Terms" in text and "\n## Terms" not in text
    assert "(nothing yet)" in text  # the empty owner file


def tool_box(store: MemoryStore) -> ToolBox:
    return ToolBox(memory_tools(store))


def run_tool(box: ToolBox, name: str, **args):  # type: ignore[no-untyped-def]
    return box.dispatch(ToolCall(id="c", name=name, arguments=args))


def test_memory_tools_remember_read_revise_forget(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    box = tool_box(store)
    ok = run_tool(
        box, "remember", scope="engagement", section="Terms", text="APLD - data", replaces=""
    )
    assert not ok.error and "remembered" in ok.text
    ok = run_tool(
        box,
        "remember",
        scope="engagement",
        section="Terms",
        text="APLD - anonymised data",
        replaces="APLD",
    )
    assert "replaced" in ok.text
    assert "anonymised" in run_tool(box, "read_memory", scope="engagement").text
    assert not run_tool(
        box, "revise_memory", scope="engagement", content="## People\n- Shikha - lead\n"
    ).error
    assert (
        "forgot"
        in run_tool(box, "forget", scope="engagement", section="People", item="Shikha").text
    )


def test_a_refused_write_is_an_error_result(knowledge: Path, tmp_path: Path) -> None:
    box = tool_box(make_store(knowledge, tmp_path))
    result = run_tool(
        box,
        "remember",
        scope="owner",
        section="Deck habits",
        text="Acme wants 40% charts",
        replaces="",
    )
    assert result.error and result.text.startswith("ERROR: ")


# -- the session -------------------------------------------------------------------


def test_a_session_with_memory_snapshots_and_writes(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    store.add("engagement", "Terms", "APLD - anonymised data")
    pre = store.snapshot()
    script = [
        turn(
            "remember",
            0,
            scope="engagement",
            section="People",
            text="Shikha - runs the walkthrough",
            replaces="",
        ),
        *good_script(),
    ]
    model = ScriptedConverse(*script)
    run, _index, _ws = start(tmp_path, model, memory=store)

    assert run.state.stop_reason == "finished"
    assert "Shikha" in store.engagement_path.read_text(encoding="utf-8")
    memory_dir = tmp_path / "session" / "memory"
    assert (memory_dir / "engagement.md").read_text(encoding="utf-8") == pre["engagement"]
    assert (memory_dir / "owner.md").read_text(encoding="utf-8") == pre["owner"]
    assert "Memory (context, not evidence" in model.seen[0][0].content
    assert "APLD" in model.seen[0][0].content
    record = session_record(tmp_path / "session")
    assert record is not None and set(record["memory"]) == {"engagement.md", "owner.md"}


def test_resume_with_memory_adds_the_tools(knowledge: Path, tmp_path: Path) -> None:
    store = make_store(knowledge, tmp_path)
    _run, index, ws = start(tmp_path, ScriptedConverse(*good_script()), memory=store)
    seen_tools: list[list[str]] = []

    class Recording(ScriptedConverse):
        def converse(self, messages, tools, *, system=None):  # type: ignore[no-untyped-def]
            seen_tools.append([t.name for t in tools])
            return super().converse(messages, tools, system=system)

    from tests.test_agent_tools import CLAIMS

    resume_deck_agent(
        "Tighten it.",
        session_dir=SessionFiles(tmp_path / "session").root,
        settings=_settings(ws),
        index=index,
        claims=CLAIMS,
        model=Recording(turn("finish", 9, coverage=[], notes="Changed.")),
        memory=store,
    )
    assert {"remember", "forget", "read_memory", "revise_memory"} <= set(seen_tools[0])


# -- the manifest ------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@needs_git
def test_memory_edits_do_not_dirty_the_knowledge_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    knowledge = repo / "knowledge"
    (knowledge / "clients" / "x").mkdir(parents=True)
    (knowledge / "claims.md").write_text("A claim.\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.email=t@e", "-c", "user.name=t", *args],
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    memory = knowledge / "clients" / "x" / "memory"
    memory.mkdir()
    (memory / "p.md").write_text("- remembered\n", encoding="utf-8")
    (memory / "audit.jsonl").write_text("{}\n", encoding="utf-8")
    assert git_state(knowledge).dirty is False
    (knowledge / "clients" / "x" / "client.md").write_text("New.\n", encoding="utf-8")
    assert git_state(knowledge).dirty is True


# -- the CLI -----------------------------------------------------------------------


def test_memory_show_and_forget_commands(knowledge: Path, tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from autodeck.cli import app

    runner = CliRunner()
    store = make_store(knowledge, tmp_path)
    store.add("engagement", "Terms", "APLD - anonymised data")
    owner = owner_memory_path()
    owner.parent.mkdir(parents=True, exist_ok=True)
    owner.write_text("# Memory\n\n## Deck habits\n- At most 6 bullets\n", encoding="utf-8")
    base = ["--client", "acme", "--project", PROJECT, "--knowledge-root", str(knowledge)]

    shown = runner.invoke(app, ["memory", "show", *base])
    assert shown.exit_code == 0, shown.output
    assert "APLD - anonymised data" in shown.output and "At most 6 bullets" in shown.output

    gone = runner.invoke(
        app,
        ["memory", "forget", *base, "--scope", "engagement", "--section", "Terms",
         "--item", "APLD"],
    )  # fmt: skip
    assert gone.exit_code == 0, gone.output
    assert "APLD" not in store.read("engagement")

    missing = runner.invoke(
        app,
        ["memory", "forget", *base, "--scope", "engagement", "--section", "Terms",
         "--item", "APLD"],
    )  # fmt: skip
    assert missing.exit_code == 1 and "no item" in missing.output

    bad = runner.invoke(
        app, ["memory", "show", "--client", "../globex", "--project", PROJECT,
              "--knowledge-root", str(knowledge)],
    )  # fmt: skip
    assert bad.exit_code == 1


def test_draft_agent_snapshots_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = agent_world(tmp_path, monkeypatch, CLARIFIED)
    w.composer.turns = agent_script(length_target=2)
    result = w.run("draft", "r1", "--agent", *w.data_roots)
    assert result.exit_code == 0, result.output
    session = w.runs / "r1" / "session" / "memory"
    assert (session / "engagement.md").is_file() and (session / "owner.md").is_file()


# -- the UI route ------------------------------------------------------------------


@pytest.fixture
def ui(tmp_path: Path, knowledge: Path) -> Iterator[Client]:
    roots = Roots(
        knowledge=knowledge,
        corpus=tmp_path / "corpus",
        runs=tmp_path / "runs",
        env="dev-mistral",
        profile=tmp_path / "profile.json",
    )
    httpd = make_server(roots, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_memory_get_and_put(ui: Client) -> None:
    query = f"/api/memory?client=acme&project={PROJECT}"
    status, body = ui.json("GET", query)
    assert status == 200 and body["audit"] == []

    status, saved = ui.json(
        "PUT",
        "/api/memory",
        {"client": "acme", "project": PROJECT, "scope": "engagement",
         "content": "## Terms\n- APLD - data\n"},
    )  # fmt: skip
    assert status == 200 and "APLD - data" in saved["text"]
    status, body = ui.json("GET", query)
    assert "APLD - data" in body["engagement"]
    assert body["audit"][0]["scope"] == "engagement" and body["audit"][0]["op"] == "rewrite"


def test_memory_put_refusals_are_400(ui: Client) -> None:
    status, body = ui.json(
        "PUT",
        "/api/memory",
        {"client": "acme", "project": PROJECT, "scope": "owner",
         "content": "## Deck habits\n- Acme wants 40% charts\n"},
    )  # fmt: skip
    assert status == 400 and "may not" in body["error"]
    status, _ = ui.json("GET", f"/api/memory?client=../globex&project={PROJECT}")
    assert status == 404
    assert api.MEMORY_AUDIT_LIMIT == 50


@pytest.mark.parametrize("client", ["../globex", "../clients/globex", "a/b", ".hidden", "x..y"])
def test_a_client_name_with_a_path_in_it_is_refused(tmp_path: Path, client: str) -> None:
    """A4: `ClientNamespace` derives its root from the client name, so the name itself must
    not be able to climb into another client's folder (found by review, 2026-10-23)."""
    with pytest.raises(ClientIsolationError, match="plain folder name"):
        MemoryStore(
            tmp_path, client=client, project="p", run_id="r", owner_path=tmp_path / "o.md"
        )
