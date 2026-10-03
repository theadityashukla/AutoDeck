"""Phase 3d: redesign an existing deck (B41, B49) — evidence, compose, validate, audit, upload.

Fake providers only. The headline is the same as 3c's: clarify, compose and validate are
exactly three model calls, and every citation in the resulting IR points into the client's own
deck (`client-deck--`), on the slide the text came from.
"""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pptx import Presentation
from typer.testing import CliRunner

import autodeck.providers.registry as registry_module
from autodeck.agents.compose import (
    ComposedMessage,
    ComposedSlide,
    ComposeError,
    LayoutChange,
    RedesignDraft,
    compose_deck,
)
from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
from autodeck.agents.evidence_pack import build_redesign_pack
from autodeck.agents.validation import ClaimJudgement, ValidationDraft
from autodeck.audit.numeric_linter import lint_deck
from autodeck.audit.report import build_audit_report, render
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.cli import app
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.deck_source import DOC_ID_PREFIX, ingest_deck, run_source_root
from autodeck.ingest.document_store import (
    Document,
    DocumentStore,
    IngestError,
    QuoteNotFoundError,
)
from autodeck.ingest.multi_store import MultiStore
from autodeck.ir.models import Block, Citation, Claim, Deck, Slide
from autodeck.knowledge.context_assembler import ContextAssembler
from autodeck.pipeline.orchestrator import Orchestrator
from autodeck.render import draft as draft_module
from autodeck.render.qa.libreoffice import RenderError
from autodeck.ui import api
from autodeck.ui.api import Roots, UIError
from autodeck.ui.server import (
    MAX_UPLOAD,
    PPTX_TYPE,
    UPLOAD_HEADER,
    App,
    Handler,
    _upload_name,
)
from tests.test_cli_draft import Counting
from tests.test_cli_gate2 import CLIENT, DOC_ID, PROJECT, QUOTE, element
from tests.test_deck_source import BULLET, _build
from tests.test_knowledge import build_knowledge
from tests.test_ui import Client, make_client

runner = CliRunner()

TABLE_QUOTE = "412 units"
DECK_ID = "client-deck--acme-review"


def _clarified():  # type: ignore[no-untyped-def]
    from autodeck.agents.compose import Assumption, ClarifyingQuestion, ClarifyResult

    return ClarifyResult(
        assumptions=[Assumption(topic="scope", statement="One slide out for each slide in.")],
        questions=[
            ClarifyingQuestion(
                id="q1",
                question="Keep the client's wording?",
                why="Changes how much is rewritten.",
                suggested_answer="Keep it.",
                options=["Keep it.", "Light rewording."],
            )
        ],
    )


def claim_slide(sid: str, text: str, quote: str, *, doc_id: str = DECK_ID) -> ComposedSlide:
    return ComposedSlide(
        id=sid,
        narrative_role="evidence",
        component="quote",
        intent=f"Land {sid}.",
        message_ids=["km1"],
        blocks=[
            ProposedBlock(
                id="b1",
                kind="claim",
                slot="figure",
                claim=ProposedClaim(
                    text=text, citations=[ProposedCitation(doc_id=doc_id, quote=quote)]
                ),
            )
        ],
        speaker_notes=[],
    )


def redesigned(
    *slides: ComposedSlide, changes: list[LayoutChange] | None = None
) -> RedesignDraft:
    return RedesignDraft(
        objective="Present the annual review to the board.",
        audience="The board",
        length_target=len(slides),
        key_messages=[
            ComposedMessage(
                id="km1",
                text="Revenue grew in 2024.",
                origin="prompt",
                citations=[ProposedCitation(doc_id=DECK_ID, quote=BULLET)],
            )
        ],
        must_include=[],
        must_avoid=[],
        slides=list(slides),
        coverage=[],
        notes="",
        changes=changes
        or [
            LayoutChange(slide_id=s.id, original_slides=[2 if s.id == "s1" else 3], why="kept")
            for s in slides
        ],
    )


GOOD = redesigned(
    claim_slide("s1", "Revenue grew in 2024, per the deck.", BULLET),
    claim_slide("s2", "EMEA sold 412 units.", TABLE_QUOTE),
)


class QuoteJudge:
    """Validation fake: every claim named in the prompt is supported by its own quote."""

    QUOTES: ClassVar[dict[str, str]] = {"s1:b1": BULLET, "s2:b1": TABLE_QUOTE, "s3:b1": QUOTE}

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        return ValidationDraft(
            judgements=[
                ClaimJudgement(
                    claim_id=cid,
                    judgement=VerdictJudgement(
                        verdict="supported", verdict_notes="faithful", supporting_quote=quote
                    ),
                )
                for cid, quote in self.QUOTES.items()
                if cid in prompt
            ]
        )


class World:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *answers: Any,
        papers: bool = False,
    ) -> None:
        self.tmp = tmp_path
        self.knowledge = build_knowledge(tmp_path)
        self.corpus = tmp_path / "corpus"
        self.runs = tmp_path / "runs"
        self.deck = _build(tmp_path / "Acme Review.pptx")
        if papers:
            DocumentStore(self.corpus / PROJECT).add(
                Document(
                    doc_id=DOC_ID,
                    source_path=f"{DOC_ID}.pdf",
                    page_count=6,
                    elements=[element(DOC_ID, QUOTE)],
                )
            )
        self.composer = Counting(*answers)
        self.judge = QuoteJudge()
        roles = {"composer": self.composer, "validation": self.judge}
        monkeypatch.setattr(
            registry_module.ModelRegistry, "provider_for", lambda self, role, **kw: roles[role]
        )

        def build(deck: Deck, tokens: object, out_path: Path) -> None:
            presentation = Presentation()
            for _ in deck.slides:
                presentation.slides.add_slide(presentation.slide_layouts[6])
            presentation.save(str(out_path))

        monkeypatch.setattr(draft_module, "_build_pptx", build)
        monkeypatch.setattr(
            draft_module, "render_pptx", lambda *a, **k: (_ for _ in ()).throw(RenderError("x"))
        )

    @property
    def roots(self) -> list[str]:
        return ["--runs-root", str(self.runs)]

    @property
    def data_roots(self) -> list[str]:
        return [
            *self.roots,
            "--knowledge-root",
            str(self.knowledge),
            "--corpus-root",
            str(self.corpus),
        ]

    def run(self, *args: str):  # type: ignore[no-untyped-def]
        return runner.invoke(app, list(args))

    def redesign(self, *extra: str):  # type: ignore[no-untyped-def]
        return self.run(
            "redesign", "r1", "--client", CLIENT, "--project", PROJECT,
            "--deck", str(self.deck), *extra, *self.data_roots,
        )  # fmt: skip

    def calls(self) -> int:
        return len(self.composer.prompts) + len(self.judge.prompts)

    def api_roots(self) -> Roots:
        return Roots(
            knowledge=self.knowledge,
            corpus=self.corpus,
            runs=self.runs,
            env="dev",
            profile=self.tmp / "profile.json",
        )


# ---------------------------------------------------------------------------
# The flow: redesign -> answer -> draft -> validate, three model calls
# ---------------------------------------------------------------------------


def test_redesign_flow_is_three_model_calls_and_cites_only_the_deck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The project's paper corpus does not even exist, and anything that opened it would fail.
    corpus = tmp_path / "corpus"
    real_get, real_ids = DocumentStore.get, DocumentStore.doc_ids

    def guarded(self: DocumentStore, *a: Any) -> Any:
        assert corpus not in Path(self.root).parents and Path(self.root) != corpus, self.root
        return real_get(self, *a)

    def guarded_ids(self: DocumentStore) -> list[str]:
        assert corpus not in Path(self.root).parents, self.root
        return real_ids(self)

    monkeypatch.setattr(DocumentStore, "get", guarded)
    monkeypatch.setattr(DocumentStore, "doc_ids", guarded_ids)

    w = World(tmp_path, monkeypatch, _clarified(), GOOD)
    result = w.redesign()
    assert result.exit_code == 0, result.output
    run_root = w.runs / "r1"
    assert json.loads((run_root / "redesign.json").read_text()) == {
        "deck_doc_id": DECK_ID,
        "source_file": "Acme Review.pptx",
        "wording": "keep",
        "layouts": True,
        "check_papers": False,
    }
    assert (run_source_root(w.runs, "r1") / f"{DECK_ID}.json").exists()
    saved = json.loads((run_root / "clarify.json").read_text())
    assert saved["answers"] is None and saved["questions"][0]["id"] == "q1"
    clarify_prompt = w.composer.prompts[0]
    assert "redesign" in clarify_prompt.lower() and BULLET in clarify_prompt
    assert "Merging or splitting" in clarify_prompt  # B49: only on request
    assert "slide 3" in clarify_prompt

    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    result = w.run("draft", "r1", *w.data_roots)
    assert result.exit_code == 0, result.output
    compose_prompt = w.composer.prompts[1]
    assert "Redesign settings" in compose_prompt and "keep my words" in compose_prompt
    assert f"{DECK_ID} p.2" in compose_prompt and BULLET in compose_prompt

    orch = Orchestrator("r1", runs_root=w.runs)
    deck = orch.ir.load()
    citations = [c for site in deck.claim_sites() for c in site.claim.citations]
    assert citations and all(c.doc_id.startswith(DOC_ID_PREFIX) for c in citations)
    assert [c.page for c in citations] == [2, 3]  # the original slide, not the new one
    coverage = json.loads((run_root / "coverage.json").read_text())
    assert [c["slide_id"] for c in coverage["changes"]] == ["s1", "s2"]
    assert coverage["changes"][0]["original_slides"] == [2]

    result = w.run("validate", "r1", "--corpus-root", str(w.corpus), *w.roots)
    assert result.exit_code == 0, result.output
    assert w.calls() == 3
    # validation indexed the run-local deck store (there is no paper corpus at all)
    assert DECK_ID in w.judge.prompts[0] and "Revenue grew 12%" in w.judge.prompts[0]
    final = orch.ir.load()
    assert [s.blocks[0].claim.verdict for s in final.slides] == ["supported"] * 2
    assert orch.state.approvals == {}  # nothing approved anywhere along the way

    # the review view: settings, layout notes, and the original slide beside each slide
    view = api.draft_view(w.api_roots(), "r1")
    assert view["redesign"]["settings"]["wording"] == "keep"
    assert [c["slide_id"] for c in view["redesign"]["changes"]] == ["s1", "s2"]
    original = view["slides"][0]["original"]
    assert [o["slide"] for o in original] == [2]
    assert BULLET in original[0]["text"] and "Highlights" in original[0]["text"]
    assert [o["slide"] for o in view["slides"][1]["original"]] == [3]


def test_settings_are_recorded_and_shown_to_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, _clarified(), GOOD)
    assert w.redesign("--wording", "light", "--no-layouts").exit_code == 0
    settings = json.loads((w.runs / "r1" / "redesign.json").read_text())
    assert settings["wording"] == "light" and settings["layouts"] is False
    assert "layouts may not change" in w.composer.prompts[0]
    assert w.redesign("--wording", "loud").exit_code == 1


def test_a_missing_deck_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(tmp_path, monkeypatch)
    w.deck.unlink()
    assert w.redesign().exit_code == 1
    assert not (w.runs / "r1" / "redesign.json").exists()


def test_check_papers_adds_the_paper_pack_and_a_paper_quote_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    both = redesigned(
        claim_slide("s1", "Revenue grew in 2024, per the deck.", BULLET),
        ComposedSlide(
            id="s2",
            narrative_role="evidence",
            component="quote",
            intent="Support it.",
            message_ids=["km1"],
            blocks=[
                ProposedBlock(
                    id="b1",
                    kind="claim",
                    slot="figure",
                    claim=ProposedClaim(
                        text="The kernel rewrite raised throughput.",
                        citations=[ProposedCitation(doc_id=DOC_ID, quote=QUOTE)],
                    ),
                )
            ],
            speaker_notes=[],
        ),
    )
    w = World(tmp_path, monkeypatch, _clarified(), both, papers=True)
    assert w.redesign("--check-papers").exit_code == 0
    assert json.loads((w.runs / "r1" / "redesign.json").read_text())["check_papers"] is True
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    result = w.run("draft", "r1", *w.data_roots)
    assert result.exit_code == 0, result.output
    assert "Project papers" in w.composer.prompts[1]
    deck = Orchestrator("r1", runs_root=w.runs).ir.load()
    docs = {c.doc_id for site in deck.claim_sites() for c in site.claim.citations}
    assert docs == {DECK_ID, DOC_ID}

    result = w.run("validate", "r1", "--corpus-root", str(w.corpus), *w.roots)
    assert result.exit_code == 0, result.output
    assert DOC_ID in w.judge.prompts[0] or QUOTE in w.judge.prompts[0]


def test_check_papers_needs_ingested_papers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, _clarified())
    assert w.redesign("--check-papers").exit_code == 2


# ---------------------------------------------------------------------------
# Compose in redesign mode: the resolver and the linter still decide
# ---------------------------------------------------------------------------


def _compose(tmp_path: Path, draft: RedesignDraft, *, check_papers: bool = False):  # type: ignore[no-untyped-def]
    deck_path = _build(tmp_path / "Acme Review.pptx")
    root = run_source_root(tmp_path / "runs", "r1")
    document = ingest_deck(deck_path, store_root=root)
    store = MultiStore(root)
    pack = build_redesign_pack(document)
    knowledge = tmp_path / "knowledge"
    if not knowledge.exists():
        build_knowledge(tmp_path)
    context = ContextAssembler(knowledge, client=CLIENT, project=PROJECT).assemble()
    model = Counting(draft)
    result = compose_deck(
        "Redesign the deck.",
        answers=[],
        pack=pack,
        context=context,
        store=store,
        tokens=DesignTokens.load(Path("config/tokens/dev.json")),
        model=model,
        run_id="r1",
        client=CLIENT,
        project=PROJECT,
        theme_ref="config/tokens/dev.json",
        component_lib_version="0",
        mode="redesign",
        settings={"wording": "keep", "layouts": True, "check_papers": check_papers},
    )
    return result, model, pack


def test_a_quote_not_in_the_deck_is_dropped_with_a_rejection(tmp_path: Path) -> None:
    draft = redesigned(
        claim_slide("s1", "Revenue grew in 2024, per the deck.", BULLET),
        claim_slide(
            "s2", "Margins reached forty percent.", "Margins improved to forty percent"
        ),
    )
    result, model, _pack = _compose(tmp_path, draft)
    assert len(model.prompts) == 1 and result.provider_calls == 1
    assert len(result.deck.slides[0].blocks) == 1
    assert result.deck.slides[1].blocks == []
    assert any("s2" in r and "did not resolve" in r for r in result.rejections)


def test_a_number_the_deck_does_not_state_fails_the_numeric_linter(tmp_path: Path) -> None:
    # The quote is real (so it resolves), but the claim states a figure the slide does not.
    draft = redesigned(claim_slide("s1", "Revenue grew 15% in 2024.", BULLET))
    result, _model, _pack = _compose(tmp_path, draft)
    assert result.deck.slides[0].blocks  # A1 is satisfied ...
    assert not lint_deck(result.deck).passes  # ... A2 is not: 15 is not in the cited text
    ok = redesigned(claim_slide("s1", "Revenue grew 12% in 2024.", BULLET))
    result, _model, _pack = _compose(tmp_path, ok)
    assert lint_deck(result.deck).passes


def test_a_redesign_needs_settings(tmp_path: Path) -> None:
    with pytest.raises(ComposeError):
        deck_path = _build(tmp_path / "Acme Review.pptx")
        document = ingest_deck(deck_path, store_root=run_source_root(tmp_path / "runs", "r1"))
        knowledge = build_knowledge(tmp_path)
        compose_deck(
            "x",
            answers=[],
            pack=build_redesign_pack(document),
            context=ContextAssembler(knowledge, client=CLIENT, project=PROJECT).assemble(),
            store=MultiStore(run_source_root(tmp_path / "runs", "r1")),
            tokens=DesignTokens.load(Path("config/tokens/dev.json")),
            model=Counting(GOOD),
            run_id="r1",
            client=CLIENT,
            project=PROJECT,
            theme_ref="t",
            component_lib_version="0",
            mode="redesign",
        )


def test_the_pack_is_the_whole_deck_in_slide_order(tmp_path: Path) -> None:
    deck_path = _build(tmp_path / "Acme Review.pptx")
    document = ingest_deck(deck_path, store_root=run_source_root(tmp_path / "runs", "r1"))
    pack = build_redesign_pack(document)
    positions = [pack.text.index(f"## slide {n}") for n in (1, 2, 3)]
    assert positions == sorted(positions)
    assert pack.claims == () and pack.dropped == 0
    assert "Acme Annual Review" in pack.text and "Berlin pilot" in pack.text  # notes included
    assert "412 units" in pack.text
    assert all(s.doc_id == DECK_ID for s in pack.spans)
    # a picture is listed, but is not citable
    assert any(not s.citable and "picture" in s.text for s in pack.spans)
    # every citable element can be quoted back through the resolver
    store = DocumentStore(run_source_root(tmp_path / "runs", "r1"))
    for span in pack.spans:
        if span.citable:
            assert span.to_citation(store).page == span.page


# ---------------------------------------------------------------------------
# MultiStore: read-only, and a run sees exactly its own sources (A4)
# ---------------------------------------------------------------------------


def test_multistore_reads_both_roots_and_never_writes(tmp_path: Path) -> None:
    deck_path = _build(tmp_path / "Acme Review.pptx")
    source = run_source_root(tmp_path / "runs", "r1")
    document = ingest_deck(deck_path, store_root=source)
    papers = tmp_path / "corpus" / PROJECT
    paper = Document(
        doc_id=DOC_ID, source_path="p.pdf", page_count=6, elements=[element(DOC_ID, QUOTE)]
    )
    DocumentStore(papers).add(paper)

    both = MultiStore(source, papers)
    assert both.doc_ids() == sorted([DECK_ID, DOC_ID])
    assert {d.doc_id for d in both.documents()} == {DECK_ID, DOC_ID}
    assert both.resolve_quote(DECK_ID, BULLET).page == 2
    assert both.resolve_quote(DOC_ID, QUOTE).doc_id == DOC_ID
    with pytest.raises(IngestError, match="read-only"):
        both.add(document)
    assert sorted(p.name for p in source.iterdir()) == [f"{DECK_ID}.json"]
    assert not (papers / f"{DECK_ID}.json").exists()

    only_deck = MultiStore(source)  # the paper check is off: the corpus is not a root at all
    assert only_deck.doc_ids() == [DECK_ID] and only_deck.roots == (source,)
    with pytest.raises(IngestError):
        only_deck.get(DOC_ID)
    with pytest.raises(QuoteNotFoundError):
        only_deck.resolve_quote(DECK_ID, QUOTE)


def test_another_runs_deck_is_invisible(tmp_path: Path) -> None:
    mine = ingest_deck(
        _build(tmp_path / "Acme Review.pptx"),
        store_root=run_source_root(tmp_path / "runs", "r1"),
    )
    other_deck = _build(tmp_path / "Other Deck.pptx")
    theirs = ingest_deck(other_deck, store_root=run_source_root(tmp_path / "runs", "r2"))
    store = MultiStore(run_source_root(tmp_path / "runs", "r1"))
    assert store.doc_ids() == [mine.doc_id]
    with pytest.raises(IngestError):
        store.get(theirs.doc_id)


# ---------------------------------------------------------------------------
# 3d.3 — the audit report labels the client's own deck
# ---------------------------------------------------------------------------


def test_the_audit_report_labels_client_deck_citations() -> None:
    def cite(doc_id: str, page: int, quote: str) -> Citation:
        return Citation.for_quote(
            doc_id=doc_id,
            page=page,
            bbox=(10.0, 10.0, 200.0, 50.0),
            quote=quote,
            retrieved_by="writer",
        )

    claims = [
        Claim(
            text="Revenue grew in 2024.",
            citations=[cite(DECK_ID, 2, BULLET)],
            verdict="supported",
        ),
        Claim(
            text="Throughput rose.",
            citations=[cite("kaplan2024", 4, QUOTE)],
            verdict="supported",
        ),
    ]
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="stat_pair",
        intent="x",
        blocks=[
            Block(id=f"b{i}", kind="claim", slot="body", claim=c)
            for i, c in enumerate(claims, start=1)
        ],
        speaker_notes=[],
        message_ids=[],
    )
    deck = Deck(
        run_id="r1",
        project="p",
        client="acme",
        audience="board",
        version=1,
        slides=[slide],
        theme_ref="t",
        component_lib_version="0",
    )
    text = render(build_audit_report(deck, brief=None))
    assert "client-supplied deck, slide 2" in text
    assert BULLET in text  # and its quote, verbatim
    assert "`kaplan2024` p.4" in text  # research keeps its own form
    assert "client-supplied deck, slide 4" not in text


# ---------------------------------------------------------------------------
# 3d.7 — the upload route
# ---------------------------------------------------------------------------


def stub_redesign(roots: Roots, calls: list[list[str]]):  # type: ignore[no-untyped-def]
    """Stands in for `autodeck redesign`: records argv and writes the clarify file."""

    def runner(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        run_id = argv[argv.index("redesign") + 1]
        folder = roots.runs / run_id
        (folder / "clarify.json").write_text(
            json.dumps(
                {
                    "prompt": "Redesign the deck.",
                    "client": "acme",
                    "project": "proj",
                    "assumptions": [{"topic": "scope", "statement": "One for one."}],
                    "questions": [],
                    "answers": None,
                    "corrections": [],
                }
            )
        )
        return 0, ""

    return runner


@pytest.fixture
def uploads(tmp_path: Path) -> Iterator[tuple[Client, App, Roots, list[list[str]]]]:
    from http.server import ThreadingHTTPServer

    (tmp_path / "knowledge" / "projects" / "proj").mkdir(parents=True)
    roots = Roots(
        knowledge=tmp_path / "knowledge",
        corpus=tmp_path / "corpus",
        runs=tmp_path / "runs",
        env="dev",
        profile=tmp_path / "profile.json",
    )
    make_client(roots)
    calls: list[list[str]] = []
    app_ = App(roots, cli_runner=stub_redesign(roots, calls))
    handler = type("BoundHandler", (Handler,), {"app": app_})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(httpd.server_address[1]), app_, roots, calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


QUERY = "run_id=r1&client=acme&project=proj&name=My%20Deck.pptx"
GOOD_HEADERS = {UPLOAD_HEADER: "1", "Content-Type": PPTX_TYPE}


def test_upload_happy_path_runs_the_cli_and_returns_the_checkpoint(
    uploads: tuple[Client, App, Roots, list[list[str]]], tmp_path: Path
) -> None:
    client, _app, roots, calls = uploads
    data = _build(tmp_path / "x.pptx").read_bytes()
    status, body = client.request(
        "POST",
        f"/api/redesign/upload?{QUERY}&wording=light&layouts=0&check_papers=1",
        headers=GOOD_HEADERS,
        raw=data,
    )
    payload = json.loads(body)
    assert status == 200, payload
    assert payload["assumptions"][0]["topic"] == "scope" and payload["answered"] is False
    saved = roots.runs / "r1" / "upload" / "My Deck.pptx"
    assert saved.read_bytes() == data
    [argv] = calls
    assert argv[argv.index("--deck") + 1] == str(saved)
    assert argv[argv.index("--wording") + 1] == "light"
    assert "--no-layouts" in argv and "--check-papers" in argv
    assert argv[argv.index("--client") + 1] == "acme"
    assert api.read_run_meta(roots, "r1") == {"client": "acme", "project": "proj"}


def test_upload_defaults_leave_the_flags_off(
    uploads: tuple[Client, App, Roots, list[list[str]]], tmp_path: Path
) -> None:
    client, _app, _roots, calls = uploads
    status, _ = client.request(
        "POST",
        f"/api/redesign/upload?{QUERY}",
        headers=GOOD_HEADERS,
        raw=_build(tmp_path / "x.pptx").read_bytes(),
    )
    assert status == 200
    [argv] = calls
    assert "--no-layouts" not in argv and "--check-papers" not in argv
    assert argv[argv.index("--wording") + 1] == "keep"


def test_upload_refuses_a_request_without_the_header_or_type(
    uploads: tuple[Client, App, Roots, list[list[str]]], tmp_path: Path
) -> None:
    client, _app, roots, calls = uploads
    data = _build(tmp_path / "x.pptx").read_bytes()
    status, _ = client.request(
        "POST", f"/api/redesign/upload?{QUERY}", headers={"Content-Type": PPTX_TYPE}, raw=data
    )
    assert status == 403
    status, _ = client.request(
        "POST", f"/api/redesign/upload?{QUERY}", headers={UPLOAD_HEADER: "1"}, raw=data
    )
    assert status == 415
    status, _ = client.request(
        "POST",
        f"/api/redesign/upload?{QUERY}",
        headers={UPLOAD_HEADER: "1", "Content-Type": "text/plain"},
        raw=data,
    )
    assert status == 415
    assert calls == [] and not (roots.runs / "r1").exists()


def test_upload_over_the_cap_is_refused_before_it_is_read(
    uploads: tuple[Client, App, Roots, list[list[str]]],
) -> None:
    client, _app, roots, calls = uploads
    conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=10)
    try:
        conn.putrequest("POST", f"/api/redesign/upload?{QUERY}")
        for key, value in GOOD_HEADERS.items():
            conn.putheader(key, value)
        conn.putheader("Content-Length", str(MAX_UPLOAD + 1))
        conn.endheaders()  # no body is ever sent: the server must answer without reading it
        assert conn.getresponse().status == 413
    finally:
        conn.close()
    assert calls == [] and not (roots.runs / "r1").exists()


def test_upload_refuses_a_non_pptx_and_a_bad_run(
    uploads: tuple[Client, App, Roots, list[list[str]]],
) -> None:
    client, _app, _roots, calls = uploads
    status, _ = client.request(
        "POST", f"/api/redesign/upload?{QUERY}", headers=GOOD_HEADERS, raw=b"not a deck"
    )
    assert status == 415
    status, _ = client.request(
        "POST",
        "/api/redesign/upload?run_id=..%2Fx&client=acme&project=proj&name=a.pptx",
        headers=GOOD_HEADERS,
        raw=b"PK\x03\x04",
    )
    assert status == 400
    status, _ = client.request(
        "POST",
        "/api/redesign/upload?run_id=r1&client=ghost&project=proj&name=a.pptx",
        headers=GOOD_HEADERS,
        raw=b"PK\x03\x04",
    )
    assert status == 400
    assert calls == []


def test_upload_reports_a_failed_command(
    uploads: tuple[Client, App, Roots, list[list[str]]], tmp_path: Path
) -> None:
    client, app_, _roots, _calls = uploads
    app_.cli_runner = lambda argv: (1, "Error: cannot read x as a .pptx")
    status, body = client.request(
        "POST",
        f"/api/redesign/upload?{QUERY}",
        headers=GOOD_HEADERS,
        raw=_build(tmp_path / "x.pptx").read_bytes(),
    )
    assert status == 400 and b"cannot read" in body


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Q3 deck.pptx", "Q3 deck.pptx"),
        ("../../etc/passwd", "passwd.pptx"),
        ("..\\..\\boot.ini", "boot.ini.pptx"),
        ("a<b>|c.PPTX", "a_b_c.pptx"),
        ("", "deck.pptx"),
        ("...", "deck.pptx"),
    ],
)
def test_upload_names_are_sanitised(raw: str, expected: str) -> None:
    assert _upload_name(raw) == expected


def test_start_redesign_refuses_a_run_that_has_a_draft(
    uploads: tuple[Client, App, Roots, list[list[str]]], tmp_path: Path
) -> None:
    _client, app_, roots, _calls = uploads
    orch = Orchestrator("r1", runs_root=roots.runs, env="dev")
    orch.run_stage("compose", lambda: "x")
    api.write_run_meta(roots, "r1", client="acme", project="proj")
    with pytest.raises(UIError) as caught:
        app_.start_redesign(
            {"run_id": "r1", "client": "acme", "project": "proj", "name": "a"}, b"PK\x03\x04"
        )
    assert caught.value.status == 409


def test_a_message_stated_on_one_slide_of_the_clients_deck_is_supported(tmp_path: Path) -> None:
    """B50: on a redesign, one slide of the client's own deck supports a message."""
    result, _model, _pack = _compose(tmp_path, GOOD)
    [message] = result.draft_brief.key_messages
    assert message.evidence_status == "supported"
    assert message.probe_notes == "stated in the client's deck: slide 2"


def test_the_pack_shows_each_table_row_once_and_each_row_resolves(tmp_path: Path) -> None:
    """The pack renders an element's `text`, not `retrieval_text` (which repeats every cell),
    one table row per line — so what the writer is shown is what the resolver will find."""
    deck_path = _build(tmp_path / "Acme Review.pptx")
    root = run_source_root(tmp_path / "runs", "r1")
    document = ingest_deck(deck_path, store_root=root)
    pack = build_redesign_pack(document)
    table = next(e for e in document.elements if e.table)
    store = MultiStore(root)
    for row in (r for r in table.text.splitlines() if r.strip()):
        shown = " ".join(row.split())
        assert pack.text.count(shown) == 1, shown
        assert store.resolve_quote(document.doc_id, shown).page == table.page


def test_a_bullet_the_redesign_drops_is_called_out_by_code(tmp_path: Path) -> None:
    """B48 on a redesign: coverage checks every line of the client's deck in code, so a
    bullet nobody cites or carries is reported `left_out` whatever the model says."""
    result, _model, _pack = _compose(tmp_path, GOOD)
    left_out = [c for c in result.coverage if c["status"] == "left_out"]
    assert any("Churn fell to 3.1%" in c["item"] and "slide 2" in c["item"] for c in left_out)
    # The bullet the draft does cite is not reported.
    assert not any(BULLET in c["item"] for c in left_out)
