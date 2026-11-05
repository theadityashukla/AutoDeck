"""A4 multi-client regression (task 4.5): one project, two clients, canaries everywhere.

The proof, by method.  `tests/two_clients.py` builds a shared project `p-shared` and two
clients, `alpha-co` and `beta-co`.  Every client-scoped surface of each client carries a
unique canary token (`ALPHA-VALUEPROP-xxxx`, `BETA-HEADER-xxxx`, ...), so a failure names the
surface that leaked.  Every model role is wrapped in a recorder keeping the full text of each
request (system prompt, prompt, every message, tool arguments and tool results), and
everything a build writes is read back: run folders, memory files, the text of every pptx,
the CLI's stdout.  Each build is run for both clients.

    B1  draft-first one shot: clarify, answer, draft, validate, preview, gate2
    B2  agent: draft --agent (read_memory, remember, ask_advisor), validate, revise --agent
    B3  meeting: source, meeting notes, clarify, answer, draft --agent, validate

Coverage (surface x build x assertion).  "req" = the surface's canary reaches that build's
model requests (non-vacuity, test 2); "no leak" = the other client's canary is absent from
every request, written file and stdout of that build (test 1).  Every row is also pinned at
the loader and assembler (test 9) and, for memory, in the namespace (test 4).

    surface                   B1   B2   B3   isolation tests
    client.md                 req  req  req  1 2 9
    value_prop.md             req  req  req  1 2 3 9   (A5: framing per client)
    engagements/*.md          req  req  req  1 2 9
    style/headers.yaml        req  req  req  1 2 9
    memory/p-shared.md        term req  req  1 2 4 8   (Terms reach the validator in B1)
    theme/tokens.json         B1   B2   B3   1 9       (each build's theme_ref, task 4.1; tests/test_onboard.py)
    decks/past.pptx           -    -    -    1 9       (profiles only; --like reads them, 4.3)
    run-local (transcript,    -    -    -    1 5 6     (clarify prompt, meeting transcript)
      prompt)
    owner memory              -    both both  2 4      (shared by design, checked on write)
    retrieval index, caches   -    -    -    7         (no cross-run state)
    UI read paths             -    -    -    8

The first run of this file found eight leaks (B85): a run accepted another client's
``--client``, and a symlink inside a client or the shared project could pull in another
client's file. Both are fixed (``planning.require_run_binding``, ``loader._contained``); the
tests that found them now pass and keep them fixed.

Offline: fake providers only, nothing is `live`.
"""

from __future__ import annotations

import builtins
import json
import os
import re
import urllib.parse
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from pptx import Presentation

from autodeck.ingest.document_store import DocumentStore
from autodeck.knowledge.context_assembler import (
    ClientNamespace,
    ContextAssembler,
    RetrievalIndex,
)
from autodeck.knowledge.loader import ClientIsolationError, KnowledgeLoader
from autodeck.knowledge.memory import MemoryStore, MemoryWriteError
from autodeck.providers.cache import ResponseCache
from autodeck.retrieval.hybrid import build_index
from autodeck.ui.api import Roots
from autodeck.ui.server import make_server
from tests.test_cli_draft import CLARIFIED, COMPOSED, REVISED, Counting
from tests.test_ui import Client
from tests.two_clients import (
    ALPHA,
    BETA,
    CLIENT_SURFACES,
    CLIENTS,
    OWNER_CANARY,
    PROJECT,
    SHARED_CANARY,
    THEME_HEX,
    TwoClientWorld,
    canary,
    client_canaries,
    hits,
    other,
    pptx_text,
    read_tree,
    snapshot,
)

BUILDS = ("B1", "B2", "B3")
GRID = [(client, kind) for client in CLIENTS for kind in BUILDS]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TwoClientWorld]:
    with pytest.MonkeyPatch.context() as mp:
        built = TwoClientWorld(tmp_path_factory.mktemp("two-clients"), mp)
        built.all_builds()
        yield built


@pytest.fixture
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TwoClientWorld:
    """A world with no builds, for tests that mutate a run."""
    return TwoClientWorld(tmp_path, monkeypatch)


@pytest.fixture(scope="module")
def scratch(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TwoClientWorld]:
    """One alpha-co run, clarified and drafted, that refusals must leave untouched.

    Shared across the crafted-name tests because each asserts the run (and every model
    request count) is unchanged. A refusal that stops working breaks them all, loudly."""
    with pytest.MonkeyPatch.context() as mp:
        built = TwoClientWorld(tmp_path_factory.mktemp("two-clients-refusals"), mp)
        run_id = built.start_b1(ALPHA).run_id
        built.cli("draft", run_id, *built.data_roots)
        yield built


@pytest.fixture
def refusing(scratch: TwoClientWorld, monkeypatch: pytest.MonkeyPatch) -> TwoClientWorld:
    monkeypatch.setenv("AUTODECK_OWNER_MEMORY", str(scratch.owner_file))
    _fresh_scripts(scratch)
    return scratch


def texts(world: TwoClientWorld, client: str, kind: str | None = None) -> dict[str, str]:
    return {
        f"{r.run} {r.role} {r.kind} #{i}": r.text
        for i, r in enumerate(world.requests_for(client, kind))
    }


# -- 0. the harness is not blind ---------------------------------------------------------


def test_every_build_ran_for_both_clients(world: TwoClientWorld) -> None:
    assert sorted((b.client, b.kind) for b in world.builds) == sorted(GRID)
    for client, kind in GRID:
        assert world.requests_for(client, kind), (client, kind)
        assert (world.runs / f"{kind.lower()}-{client}" / "ir").exists()


def test_the_scanner_sees_a_canary_in_every_place_it_looks(tmp_path: Path) -> None:
    """If `hits` or `read_tree` could not see a planted canary, every no-leak test below
    would pass for the wrong reason."""
    planted = canary(BETA, "CLIENTMD")
    (tmp_path / "a.json").write_text(f'{{"x": "{planted}"}}', encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(planted.lower(), encoding="utf-8")
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.notes_slide.notes_text_frame.text = f"note {planted}"
    deck.save(str(tmp_path / "c.pptx"))
    assert planted in pptx_text(tmp_path / "c.pptx")
    found = hits([planted], read_tree(tmp_path))
    assert {Path(where).name for _n, where in found} == {"a.json", "b.jsonl", "c.pptx"}


# -- 1. no cross-client token anywhere --------------------------------------------------


@pytest.mark.parametrize(("client", "kind"), GRID)
def test_no_other_client_canary_in_any_model_request(
    world: TwoClientWorld, client: str, kind: str
) -> None:
    leaked = hits(client_canaries(other(client)), texts(world, client, kind))
    assert leaked == [], f"{kind} for {client} sent {other(client)}'s material to a model"


@pytest.mark.parametrize(("client", "kind"), GRID)
def test_no_other_client_canary_in_any_written_file_or_stdout(
    world: TwoClientWorld, client: str, kind: str
) -> None:
    leaked = hits(client_canaries(other(client)), world.written(client, kind))
    assert leaked == [], f"{kind} for {client} wrote {other(client)}'s material"


@pytest.mark.parametrize("client", CLIENTS)
def test_no_other_client_canary_in_the_client_tree_or_owner_memory(
    world: TwoClientWorld, client: str
) -> None:
    """Memory writes during every build: neither client's folder nor the owner file gained
    the other's canaries."""
    own = read_tree(world.knowledge / "clients" / client)
    assert hits(client_canaries(other(client)), own) == []
    owner = read_tree(world.owner_file.parent)
    assert hits([*client_canaries(ALPHA), *client_canaries(BETA)], owner) == []


@pytest.mark.parametrize("client", CLIENTS)
def test_the_shared_project_stays_free_of_client_canaries(
    world: TwoClientWorld, client: str
) -> None:
    project = read_tree(world.knowledge / "projects")
    assert hits(client_canaries(client), project) == []
    corpus = read_tree(world.corpus)
    assert hits(client_canaries(client), corpus) == []


# -- 2. non-vacuous: each client's own material is really loaded --------------------------


def _surface_cases() -> list[tuple[str, str, str, str]]:
    return [
        (client, surface.name, key, kind)
        for client in CLIENTS
        for surface in CLIENT_SURFACES
        for key in surface.keys
        for kind in sorted(surface.builds_for(key))
    ]


@pytest.mark.parametrize(("client", "surface", "key", "kind"), _surface_cases())
def test_a_surface_reaches_its_own_clients_requests(
    world: TwoClientWorld, client: str, surface: str, key: str, kind: str
) -> None:
    joined = "\n".join(texts(world, client, kind).values())
    assert canary(client, key) in joined, f"{surface} ({key}) never reached {kind} for {client}"


@pytest.mark.parametrize("client", CLIENTS)
def test_own_run_local_material_reaches_its_own_files(
    world: TwoClientWorld, client: str
) -> None:
    """The prompt, the meeting transcript and the remembered term landed in the right run."""
    assert hits([canary(client, "PROMPT")], world.written(client, "B1"))
    assert hits([canary(client, "TRANSCRIPT")], world.written(client, "B3"))
    assert hits([canary(client, "NEWTERM")], world.written(client, "B2"))


@pytest.mark.parametrize("client", CLIENTS)
def test_shared_and_owner_material_reaches_both_clients(
    world: TwoClientWorld, client: str
) -> None:
    for kind in BUILDS:
        joined = "\n".join(texts(world, client, kind).values())
        assert SHARED_CANARY in joined, f"project.md never reached {kind} for {client}"
    for kind in ("B2", "B3"):  # owner memory is read into every agent session, by design
        joined = "\n".join(texts(world, client, kind).values())
        assert OWNER_CANARY in joined, f"owner memory never reached {kind} for {client}"


@pytest.mark.parametrize("client", CLIENTS)
def test_unwired_surfaces_are_pinned_at_the_loader(world: TwoClientWorld, client: str) -> None:
    """Theme and reference decks are not read by any build yet; until they are, the regression
    proves the loader serves each client its own (and the colour differs per client)."""
    assembler = ContextAssembler(world.knowledge, client=client, project=PROJECT)
    [tokens] = assembler.theme_assets()
    body = tokens.read_text(encoding="utf-8")
    assert canary(client, "THEME") in body and THEME_HEX[client] in body
    assert THEME_HEX[other(client)] not in body
    [deck] = assembler.reference_decks()
    assert canary(client, "DECK") in pptx_text(deck)
    assert canary(other(client), "DECK") not in pptx_text(deck)
    assert THEME_HEX[ALPHA] != THEME_HEX[BETA]


# -- 3. per-client framing differs (A5 across clients) -----------------------------------


@pytest.mark.parametrize("client", CLIENTS)
def test_a_clients_value_proposition_reaches_only_its_own_compose_prompt(
    world: TwoClientWorld, client: str
) -> None:
    """B1's second composer call is the compose; its prompt is the one the deck is written
    from. The first is clarify."""
    composer = [r for r in world.requests_for(client, "B1") if r.role == "composer"]
    compose = composer[1]
    assert canary(client, "VALUEPROP") in compose.text
    assert canary(other(client), "VALUEPROP") not in compose.text
    assert canary(client, "HEADER") in compose.text  # its header voice, too


def test_the_two_clients_framing_text_differs(world: TwoClientWorld) -> None:
    framing = {
        client: (world.knowledge / "clients" / client / "value_prop.md").read_text("utf-8")
        for client in CLIENTS
    }
    assert framing[ALPHA] != framing[BETA]
    assert canary(ALPHA, "VALUEPROP") in framing[ALPHA]
    assert canary(BETA, "VALUEPROP") not in framing[ALPHA]


@pytest.mark.parametrize("client", CLIENTS)
def test_agent_sessions_open_with_only_their_own_framing(
    world: TwoClientWorld, client: str
) -> None:
    for kind in ("B2", "B3"):
        opening = next(r for r in world.requests_for(client, kind) if r.kind == "converse")
        assert canary(client, "VALUEPROP") in opening.text
        assert canary(other(client), "VALUEPROP") not in opening.text


# -- 4. memory writes land in the right namespace -----------------------------------------


@pytest.mark.parametrize("client", CLIENTS)
def test_a_remembered_term_lands_in_its_own_clients_memory_only(
    world: TwoClientWorld, client: str
) -> None:
    mine = world.knowledge / "clients" / client / "memory" / f"{PROJECT}.md"
    theirs = world.knowledge / "clients" / other(client)
    term = canary(client, "NEWTERM")
    assert term in mine.read_text(encoding="utf-8")
    assert hits([term], read_tree(theirs)) == []
    audit = (mine.parent / "audit.jsonl").read_text(encoding="utf-8")
    assert term in audit and canary(other(client), "NEWTERM") not in audit
    assert not (mine.parent / "audit.jsonl").samefile(theirs / "memory" / "audit.jsonl")


def test_the_owner_memory_is_unchanged_by_engagement_writes(world: TwoClientWorld) -> None:
    text = world.owner_file.read_text(encoding="utf-8")
    assert OWNER_CANARY in text
    assert hits([canary(c, k) for c in CLIENTS for k in ("NEWTERM",)], {"owner": text}) == []
    assert text.count("- ") == 1  # the one neutral style line it started with
    assert not (world.owner_file.parent / "audit.jsonl").exists()  # no owner write happened


def _memory_store(world: TwoClientWorld, client: str = ALPHA) -> MemoryStore:
    return MemoryStore(
        world.knowledge,
        client=client,
        project=PROJECT,
        run_id="regression",
        owner_path=world.owner_file,
    )


@pytest.mark.parametrize("key", ["MEMTERM", "MEMPERSON", "NEWTERM"])
def test_an_attempt_to_write_a_client_term_or_person_into_owner_memory_is_refused(
    world: TwoClientWorld, key: str
) -> None:
    before = world.owner_file.read_bytes()
    store = _memory_store(world)
    with pytest.raises(MemoryWriteError, match="may not"):
        store.add("owner", "Deck habits", f"Always spell {canary(ALPHA, key)} in capitals")
    assert world.owner_file.read_bytes() == before


@pytest.mark.parametrize("text", [f"{ALPHA} likes charts", f"Never show {PROJECT} numbers"])
def test_owner_memory_refuses_a_client_or_project_name(
    world: TwoClientWorld, text: str
) -> None:
    before = world.owner_file.read_bytes()
    with pytest.raises(MemoryWriteError, match="may not name a client or project"):
        _memory_store(world).add("owner", "Deck habits", text)
    assert world.owner_file.read_bytes() == before


def test_a_store_bound_to_one_client_cannot_open_anothers_memory(world: TwoClientWorld) -> None:
    store = _memory_store(world, ALPHA)
    beta_memory = world.knowledge / "clients" / BETA / "memory" / f"{PROJECT}.md"
    with pytest.raises(ClientIsolationError):
        store.namespace.guard(beta_memory)
    assert canary(BETA, "MEMTERM") not in store.read("engagement")
    assert canary(ALPHA, "MEMTERM") in store.read("engagement")


# -- 5. a run belongs to one client -------------------------------------------------------


def _alpha_run_after_clarify(w: TwoClientWorld) -> str:
    return w.start_b1(ALPHA).run_id


def _alpha_run_with_a_draft(w: TwoClientWorld) -> str:
    run_id = w.start_b1(ALPHA).run_id
    w.cli("draft", run_id, *w.data_roots)
    return run_id


def _alpha_meeting_run(w: TwoClientWorld) -> str:
    from tests.test_cli_draft import AgentComposer
    from tests.two_clients import PROJECT as project

    run_id = w.start_b3(ALPHA).run_id
    composer: AgentComposer = w.roles["composer"]
    w.cli("clarify", run_id, "--client", ALPHA, "--project", project, "--prompt", "Deck it.",
          "--provenance", "strict", *w.data_roots)  # fmt: skip
    w.cli("answer", run_id, "--accept-all", *w.roots)
    assert composer is w.roles["composer"]
    return run_id


def _fresh_scripts(w: TwoClientWorld) -> None:
    """Scripted answers for whatever the command might (wrongly) go on to ask a model."""
    from tests.test_cli_draft import AgentComposer

    composer = AgentComposer(CLARIFIED, COMPOSED, REVISED, CLARIFIED)
    w.roles = {"composer": composer, "validation": Counting(), "advisor": Counting()}


CROSS_CLIENT_ATTEMPTS = [
    pytest.param(
        _alpha_run_after_clarify,
        lambda w, r: ["draft", r, "--client", BETA, *w.data_roots],
        id="draft",
    ),
    pytest.param(
        _alpha_run_with_a_draft,
        lambda w, r: [
            "revise",
            r,
            "--instruction",
            "Soften slide two.",
            "--no-agent",
            "--client",
            BETA,
            *w.data_roots,
        ],
        id="revise",
    ),
    pytest.param(
        _alpha_run_after_clarify,
        lambda w, r: [
            "clarify",
            r,
            "--client",
            BETA,
            "--project",
            PROJECT,
            "--prompt",
            "Anything.",
            *w.data_roots,
        ],
        id="clarify",
    ),
    pytest.param(
        _alpha_meeting_run,
        lambda w, r: ["draft", r, "--agent", "--client", BETA, *w.data_roots],
        id="meeting-draft",
    ),
    pytest.param(
        _alpha_meeting_run,
        lambda w, r: [
            "clarify",
            r,
            "--client",
            BETA,
            "--project",
            PROJECT,
            "--prompt",
            "Anything.",
            *w.data_roots,
        ],
        id="meeting-clarify",
    ),
]


@pytest.mark.parametrize(("make_run", "command"), CROSS_CLIENT_ATTEMPTS)
def test_a_run_made_for_one_client_refuses_another_clients_command(
    fresh: TwoClientWorld,
    make_run: Callable[[TwoClientWorld], str],
    command: Callable[[TwoClientWorld, str], list[str]],
) -> None:
    run_id = make_run(fresh)
    _fresh_scripts(fresh)
    run = fresh.runs / run_id
    before, sent = snapshot(run), len(fresh.requests)

    result = fresh.cli(*command(fresh, run_id), ok=False)

    assert result.exit_code != 0, f"accepted: {result.output[:300]}"
    assert len(fresh.requests) == sent, "something was sent to a model"
    assert snapshot(run) == before, "a file under the run changed"


@pytest.mark.parametrize(
    ("make_run", "args"),
    [
        (_alpha_run_with_a_draft, ["validate"]),
        (_alpha_meeting_run, ["meeting", "notes"]),
    ],
    ids=["validate", "meeting-notes"],
)
def test_validate_and_meeting_notes_have_no_client_option_to_rebind(
    fresh: TwoClientWorld, make_run: Callable[[TwoClientWorld], str], args: list[str]
) -> None:
    """These commands take the client from the run itself; `--client` is a usage error."""
    run_id = make_run(fresh)
    _fresh_scripts(fresh)
    before, sent = snapshot(fresh.runs / run_id), len(fresh.requests)
    result = fresh.cli(*args, run_id, "--client", BETA, *fresh.data_roots, ok=False)
    assert result.exit_code == 2, result.output
    assert len(fresh.requests) == sent and snapshot(fresh.runs / run_id) == before


def test_a_run_keeps_the_client_it_was_created_for(fresh: TwoClientWorld) -> None:
    run_id = _alpha_run_with_a_draft(fresh)
    meta = json.loads((fresh.runs / run_id / "ui.json").read_text(encoding="utf-8"))
    clarify = json.loads((fresh.runs / run_id / "clarify.json").read_text(encoding="utf-8"))
    assert meta["client"] == clarify["client"] == ALPHA
    assert json.loads(next((fresh.runs / run_id / "ir").glob("*.json")).read_text())[
        "client"
    ] == (ALPHA)


# -- 6. crafted names ---------------------------------------------------------------------

BAD_CLIENTS = ["../beta-co", "alpha-co/../beta-co", "..", "clients/beta-co", "./../beta-co"]
BAD_PROJECTS = ["../p-shared", "p-shared/../..", "../clients/beta-co", ".."]


class ReadLog:
    """Every path opened for reading while it is installed (Path methods and `open`)."""

    def __init__(self, mp: pytest.MonkeyPatch) -> None:
        self.paths: list[Path] = []
        for name in ("read_text", "read_bytes", "open"):
            original = getattr(Path, name)
            mp.setattr(Path, name, self._wrap(original))
        original_open = builtins.open
        mp.setattr(builtins, "open", self._wrap_open(original_open))

    def _wrap(self, original: Callable) -> Callable:
        def wrapper(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.paths.append(path)
            return original(path, *args, **kwargs)

        return wrapper

    def _wrap_open(self, original: Callable) -> Callable:
        def wrapper(file, *args, **kwargs):  # type: ignore[no-untyped-def]
            if isinstance(file, str | os.PathLike):
                self.paths.append(Path(file))
            return original(file, *args, **kwargs)

        return wrapper

    def under(self, folder: Path) -> list[Path]:
        folder = folder.resolve()
        found = []
        for path in self.paths:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved == folder or folder in resolved.parents:
                found.append(path)
        return found


def _assert_refused_cleanly(
    w: TwoClientWorld,
    log: ReadLog,
    result,
    sent: int,
    before: dict[str, bytes],  # type: ignore[no-untyped-def]
) -> None:
    assert result.exit_code != 0, result.output[:300]
    assert len(w.requests) == sent, "something was sent to a model"
    assert log.under(w.knowledge / "clients" / BETA) == [], "beta-co's folder was read"
    assert not hits(client_canaries(BETA), {"stdout": result.output})
    assert snapshot(w.runs) == before, "a file under the runs folder changed"
    assert not (w.runs / "new-run").exists()


def test_the_read_log_would_see_a_read_of_beta_cos_folder(
    fresh: TwoClientWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = ReadLog(monkeypatch)
    (fresh.knowledge / "clients" / BETA / "client.md").read_text(encoding="utf-8")
    assert log.under(fresh.knowledge / "clients" / BETA)
    assert log.under(fresh.knowledge / "clients" / ALPHA) == []


@pytest.mark.parametrize("bad", BAD_CLIENTS)
@pytest.mark.parametrize("command", ["clarify", "draft", "revise", "memory-show"])
def test_a_crafted_client_name_is_refused_before_beta_cos_folder_is_read(
    refusing: TwoClientWorld, monkeypatch: pytest.MonkeyPatch, command: str, bad: str
) -> None:
    w, run_id = refusing, f"b1-{ALPHA}"
    args = {
        "clarify": ["clarify", "new-run", "--client", bad, "--project", PROJECT,
                    "--prompt", "Anything.", *w.data_roots],
        "draft": ["draft", run_id, "--client", bad, *w.data_roots],
        "revise": ["revise", run_id, "--instruction", "x", "--no-agent", "--client", bad,
                   *w.data_roots],
        "memory-show": ["memory", "show", "--client", bad, "--project", PROJECT,
                        "--knowledge-root", str(w.knowledge)],
    }[command]  # fmt: skip
    log, sent, before = ReadLog(monkeypatch), len(w.requests), snapshot(w.runs)
    _assert_refused_cleanly(w, log, w.cli(*args, ok=False), sent, before)


@pytest.mark.parametrize("bad", BAD_PROJECTS)
@pytest.mark.parametrize("command", ["clarify", "draft", "revise", "memory-show"])
def test_a_crafted_project_name_is_refused_before_beta_cos_folder_is_read(
    refusing: TwoClientWorld, monkeypatch: pytest.MonkeyPatch, command: str, bad: str
) -> None:
    w, run_id = refusing, f"b1-{ALPHA}"
    args = {
        "clarify": ["clarify", "new-run", "--client", ALPHA, "--project", bad,
                    "--prompt", "Anything.", *w.data_roots],
        "draft": ["draft", run_id, "--project", bad, *w.data_roots],
        "revise": ["revise", run_id, "--instruction", "x", "--no-agent", "--project", bad,
                   *w.data_roots],
        "memory-show": ["memory", "show", "--client", ALPHA, "--project", bad,
                        "--knowledge-root", str(w.knowledge)],
    }[command]  # fmt: skip
    log, sent, before = ReadLog(monkeypatch), len(w.requests), snapshot(w.runs)
    _assert_refused_cleanly(w, log, w.cli(*args, ok=False), sent, before)


@pytest.mark.parametrize("bad", ["../beta-co", "alpha-co/../beta-co"])
@pytest.mark.parametrize("variant", ["both", "clarify-file", "run-meta"])
def test_a_run_whose_recorded_client_is_a_path_is_refused(
    fresh: TwoClientWorld, monkeypatch: pytest.MonkeyPatch, variant: str, bad: str
) -> None:
    """The options are empty, so the run alone decides: `clarify.json` first, else `ui.json`."""
    w = fresh
    run_id = _alpha_run_after_clarify(w)
    _fresh_scripts(w)
    run = w.runs / run_id
    meta, clarify = run / "ui.json", run / "clarify.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["client"] = bad if variant in ("both", "run-meta") else ALPHA
    meta.write_text(json.dumps(data), encoding="utf-8")
    data = json.loads(clarify.read_text(encoding="utf-8"))
    if variant == "run-meta":
        del data["client"]
    else:
        data["client"] = bad
    clarify.write_text(json.dumps(data), encoding="utf-8")
    log, sent, before = ReadLog(monkeypatch), len(w.requests), snapshot(w.runs)
    result = w.cli("draft", run_id, *w.data_roots, ok=False)
    _assert_refused_cleanly(w, log, result, sent, before)


@pytest.mark.parametrize("bad", ["../beta-co", "alpha-co/../beta-co"])
def test_a_crafted_client_name_is_refused_at_every_layer(
    fresh: TwoClientWorld, bad: str
) -> None:
    from autodeck.knowledge.loader import KnowledgeError

    with pytest.raises(KnowledgeError):
        KnowledgeLoader(fresh.knowledge).load_client(bad)
    with pytest.raises(KnowledgeError):
        ContextAssembler(fresh.knowledge, client=bad, project=PROJECT).assemble()
    with pytest.raises(ClientIsolationError):
        MemoryStore(fresh.knowledge, client=bad, project=PROJECT, run_id="r",
                    owner_path=fresh.owner_file)  # fmt: skip
    with pytest.raises(ClientIsolationError):
        MemoryStore(fresh.knowledge, client=ALPHA, project=bad, run_id="r",
                    owner_path=fresh.owner_file)  # fmt: skip


# -- 7. caches ----------------------------------------------------------------------------

#: Every file under `autodeck/` that defines or uses a cache, and why it cannot carry one
#: client's material to another.  A new file here fails the tripwire below until it is
#: reviewed and given its own isolation test.
CACHE_SITES = {
    "audit/numeric_linter.py": "lru_cache on (quote, value): pure functions of their arguments",
    "design/budgets.py": "lru_cache on font family: font metrics, no client text",
    "design/fonts.py": "lru_cache on font family: font files, no client text",
    "design/icons/library.py": "lru_cache on icon name: vendored library",
    "ingest/docling_runner.py": "model weights under ~/.cache; no document or client text",
    "providers/base.py": "builds the response-cache key from the whole request",
    "providers/guard.py": "hands the run's own ResponseCache to the registry",
    "providers/registry.py": "passes the cache through to the provider",
    "pipeline/planning.py": "ResponseCache(runs/<run>/llm_cache), one per run",
    "cli.py": "ResponseCache(runs/<run>/llm_cache), one per run",
}
CACHE_PATTERN = re.compile(
    r"lru_cache|functools\.cache\b|@cache\b|ResponseCache\(|pickle|shelve|sqlite3|joblib|diskcache"
    r"|\.cache\b"
)
ROOT = Path(__file__).resolve().parent.parent


def test_no_new_cache_appears_without_an_isolation_review() -> None:
    found = {
        str(path.relative_to(ROOT / "autodeck"))
        for path in (ROOT / "autodeck").rglob("*.py")
        if "static" not in path.parts and CACHE_PATTERN.search(path.read_text(encoding="utf-8"))
    }
    assert found <= set(CACHE_SITES), (
        f"new cache site(s) {sorted(found - set(CACHE_SITES))}: prove a beta build cannot hit "
        "an entry an alpha build made (A4), then add the file to CACHE_SITES"
    )


def test_the_process_wide_caches_are_keyed_by_nothing_client_specific() -> None:
    import inspect

    from autodeck.audit import numeric_linter
    from autodeck.design import budgets, fonts
    from autodeck.design.icons import library

    keyed = {
        budgets.load_metrics: {"family", "bold", "italic"},
        fonts.resolve_face: {"family", "bold", "italic"},
        library.load_icon: {"name"},
        numeric_linter._keys_for_value: {"quote", "value"},
        numeric_linter._qualifiers_for_value: {"quote", "value"},
    }
    for function, names in keyed.items():
        assert set(inspect.signature(function).parameters) == names, function.__name__


def test_every_response_cache_is_the_builds_own_run_folder(world: TwoClientWorld) -> None:
    """The cache the registry is handed for each role is `runs/<run>/llm_cache`, so two runs
    can never share an entry, and so beta's runs can never read alpha's."""
    by_run: dict[str, set[Path]] = {}
    for run, role, cache in world.caches:
        assert isinstance(cache, ResponseCache), (run, role)
        assert cache.directory == world.runs / run / "llm_cache", (run, role)
        by_run.setdefault(run, set()).add(cache.directory)
    assert len(by_run) == len(world.builds)
    directories = [d for dirs in by_run.values() for d in dirs]
    assert len(directories) == len(set(directories))


def test_an_alpha_cache_entry_is_invisible_to_beta_runs(world: TwoClientWorld) -> None:
    alpha = ResponseCache(world.runs / "b1-alpha-co" / "llm_cache")
    key = ResponseCache.make_key("the same request text")
    alpha.put(key, canary(ALPHA, "CLIENTMD"))
    try:
        for run in (f"{k.lower()}-{BETA}" for k in BUILDS):
            assert ResponseCache(world.runs / run / "llm_cache").get(key) is None
    finally:
        alpha.path_for(key).unlink()


def test_a_cache_key_changes_with_the_clients_context() -> None:
    """The key is a hash of the whole request, and the request carries the client's context:
    an identical task for the other client is a different key."""
    task = "Show the kernel rewrite raised throughput."
    keys = {
        client: ResponseCache.make_key(f"prompt={canary(client, 'CLIENTMD')}\n{task}")
        for client in CLIENTS
    }
    assert keys[ALPHA] != keys[BETA]


def test_no_index_or_cache_file_survives_a_build(world: TwoClientWorld) -> None:
    """The retrieval index is rebuilt in memory for each build; nothing on disk carries it
    from one build to the next."""
    suffixes = {".pkl", ".pickle", ".sqlite", ".db", ".npy", ".npz", ".faiss", ".idx", ".bin"}
    for folder in (world.runs, world.corpus, world.knowledge):
        stray = [p for p in folder.rglob("*") if p.suffix in suffixes or "index" in p.name]
        assert stray == [], stray


def test_the_retrieval_index_carries_no_client_material(world: TwoClientWorld) -> None:
    documents = list(DocumentStore(world.corpus / PROJECT).documents())
    index = build_index(documents, project=PROJECT)
    assert index.client is None
    everything = {eid: el.retrieval_text() for eid, el in index.elements.items()}
    assert everything
    assert hits([*client_canaries(ALPHA), *client_canaries(BETA)], everything) == []


# -- 8. UI read paths ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def _ui_server(
    world: TwoClientWorld, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Client]:
    import threading

    roots = Roots(
        knowledge=world.knowledge,
        corpus=world.corpus,
        runs=world.runs,
        env="dev-mistral",
        profile=tmp_path_factory.mktemp("ui-profile") / "profile.json",
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


@pytest.fixture
def ui(_ui_server: Client, world: TwoClientWorld, monkeypatch: pytest.MonkeyPatch) -> Client:
    monkeypatch.setenv("AUTODECK_OWNER_MEMORY", str(world.owner_file))  # read per request
    return _ui_server


def _memory_url(client: str, project: str = PROJECT) -> str:
    quote = urllib.parse.quote
    return f"/api/memory?client={quote(client, safe='')}&project={quote(project, safe='')}"


@pytest.mark.parametrize("client", CLIENTS)
def test_the_memory_api_returns_only_that_clients_memory(ui: Client, client: str) -> None:
    status, body = ui.json("GET", _memory_url(client))
    assert status == 200
    blob = json.dumps(body)
    assert canary(client, "MEMTERM") in blob and canary(client, "NEWTERM") in blob
    assert hits(client_canaries(other(client)), {"response": blob}) == []
    assert OWNER_CANARY in body["owner"]  # shared by design


@pytest.mark.parametrize(
    "bad", ["../beta-co", "alpha-co/../beta-co", "..", "alpha-co%2F..%2Fbeta-co"]
)
def test_the_memory_api_refuses_a_crafted_client(ui: Client, bad: str) -> None:
    status, body = ui.json("GET", _memory_url(bad))
    assert status in (400, 404)
    assert hits(client_canaries(BETA), {"response": json.dumps(body)}) == []


@pytest.mark.parametrize("bad", ["../p-shared", "p-shared/../..", ".."])
def test_the_memory_api_refuses_a_crafted_project(ui: Client, bad: str) -> None:
    status, body = ui.json("GET", _memory_url(ALPHA, bad))
    assert status in (400, 404)
    assert hits(client_canaries(BETA), {"response": json.dumps(body)}) == []


@pytest.mark.parametrize("bad", ["../beta-co", "alpha-co/../beta-co"])
def test_the_memory_api_will_not_write_through_a_crafted_client(
    ui: Client, world: TwoClientWorld, bad: str
) -> None:
    before = snapshot(world.knowledge / "clients")
    status, _ = ui.json(
        "PUT",
        "/api/memory",
        {"client": bad, "project": PROJECT, "scope": "engagement",
         "content": f"## Terms\n- {canary(ALPHA, 'NEWTERM')} - planted\n"},
    )  # fmt: skip
    assert status in (400, 404)
    assert snapshot(world.knowledge / "clients") == before


# -- 9. the assembler raises, it does not warn ----------------------------------------------


def _alpha(world: TwoClientWorld) -> ContextAssembler:
    return ContextAssembler(world.knowledge, client=ALPHA, project=PROJECT)


@pytest.mark.parametrize("surface", CLIENT_SURFACES, ids=lambda s: s.name)
def test_reaching_into_beta_co_during_an_alpha_build_raises(
    world: TwoClientWorld, surface
) -> None:  # type: ignore[no-untyped-def]
    """Every client-scoped file of beta-co, by every guarded route (and the Phase 1 tests in
    `test_knowledge.py` cover the same guard against the seed folders)."""
    assembler = _alpha(world)
    target = world.knowledge / "clients" / BETA / surface.path
    assert target.exists()
    with pytest.raises(ClientIsolationError, match="belongs to client 'beta-co'"):
        assembler.namespace.read(target)
    with pytest.raises(ClientIsolationError):
        assembler.namespace.guard(target)
    # a path spelled so that it only resolves into beta-co
    sneaky = world.knowledge / "clients" / ALPHA / ".." / BETA / surface.path
    with pytest.raises(ClientIsolationError):
        assembler.namespace.guard(sneaky)


def test_beta_cos_knowledge_cannot_be_handed_to_an_alpha_assembler(
    world: TwoClientWorld,
) -> None:
    assembler = _alpha(world)
    beta = KnowledgeLoader(world.knowledge).load_client(BETA)
    with pytest.raises(ClientIsolationError):
        assembler.theme_assets(beta)
    with pytest.raises(ClientIsolationError):
        assembler.reference_decks(beta)
    assert all(ALPHA in str(p) for p in assembler.theme_assets())
    assert all(ALPHA in str(p) for p in assembler.reference_decks())


def test_a_retrieval_index_built_for_beta_co_is_refused_in_an_alpha_build(
    world: TwoClientWorld,
) -> None:
    assembler = _alpha(world)
    with pytest.raises(ClientIsolationError, match="beta-co"):
        assembler.use_index(RetrievalIndex(client=BETA, project=PROJECT))
    with pytest.raises(ClientIsolationError, match="project"):
        assembler.use_index(RetrievalIndex(client=None, project="another-project"))
    assert assembler.use_index(RetrievalIndex(client=None, project=PROJECT)).client is None
    assert assembler.use_index(RetrievalIndex(client=ALPHA, project=PROJECT)).client == ALPHA


def test_an_assembled_alpha_context_names_nothing_of_beta_co(world: TwoClientWorld) -> None:
    context = _alpha(world).assemble()
    assert context.client == ALPHA
    prompt = context.to_prompt_context()
    assert (
        hits(client_canaries(BETA), {"prompt": prompt, "sources": str(context.sources)}) == []
    )
    assert canary(ALPHA, "VALUEPROP") in prompt and SHARED_CANARY in prompt
    assert all(ClientNamespace(ALPHA, world.knowledge).owns(p.resolve())
               or "projects" in p.parts for p in context.sources)  # fmt: skip
    with pytest.raises(ClientIsolationError, match="beta-co"):
        _alpha(world).check_text(f"as we did for {BETA}")


@pytest.mark.parametrize(
    ("link", "target"),
    [
        pytest.param(
            "clients/alpha-co/value_prop.md", "clients/beta-co/value_prop.md",
            id="client-file",
        ),
        pytest.param(
            "clients/alpha-co/style/headers.yaml", "clients/beta-co/style/headers.yaml",
            id="headers",
        ),
        pytest.param(
            "projects/p-shared/project.md", "clients/beta-co/client.md",
            id="project-file",
        ),
        pytest.param(
            "clients/alpha-co/engagements/2026-q1.md", "clients/beta-co/engagements/2026-q1.md",
            id="engagement",
        ),
    ],
)  # fmt: skip
def test_a_symlink_into_beta_co_is_a_build_error(
    fresh: TwoClientWorld, link: str, target: str
) -> None:
    path = fresh.knowledge / link
    path.unlink()
    try:
        path.symlink_to(fresh.knowledge / target)
    except OSError:  # pragma: no cover - a platform without symlinks
        pytest.skip("symlinks are not available")
    with pytest.raises(ClientIsolationError):
        context = _alpha(fresh).assemble()
        # reached only on a leak: say what came through
        seen = {"ctx": context.to_prompt_context(), "headers": str(context.header_profile)}
        found = hits(client_canaries(BETA), seen)
        pytest.fail(f"assembled without error; beta-co text present: {found}")


def test_meeting_transcribe_refuses_another_clients_run(fresh: TwoClientWorld) -> None:
    """B85: `meeting transcribe` on a run made for alpha-co, with `--client beta-co`, is
    refused before any audio is read or any run file is rewritten."""
    from tests.two_clients import PROJECT

    run_id = _alpha_run_after_clarify(fresh)
    meta = (fresh.runs / run_id / "ui.json").read_text(encoding="utf-8")
    audio = fresh.root / "call.m4a"
    audio.write_bytes(b"not audio")
    result = fresh.cli(
        "meeting", "transcribe", run_id, "--audio", str(audio), "--client", BETA,
        "--project", PROJECT, "--knowledge-root", str(fresh.knowledge),
        "--runs-root", str(fresh.runs), ok=False,
    )  # fmt: skip
    assert result.exit_code == 1
    assert "was made for client" in result.output
    assert (fresh.runs / run_id / "ui.json").read_text(encoding="utf-8") == meta
    assert not (fresh.runs / run_id / "meeting").exists()
