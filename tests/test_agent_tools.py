"""The deck agent's tools (B71): fakes only, a tiny real store and index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autodeck.agents.compose import CoverageNote
from autodeck.agents.corpus_map import build_corpus_map
from autodeck.agents.tools.corpus import corpus_tools
from autodeck.agents.tools.deck import deck_tools
from autodeck.agents.tools.registry import Tool, ToolBox, ToolError, ToolResult
from autodeck.agents.tools.skills import skill_tools
from autodeck.agents.workspace import BuildSettings, DeckBriefDraft, DeckWorkspace
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.ir.schema import export_schema
from autodeck.knowledge.loader import CachedClaim
from autodeck.providers.base import ToolCall
from autodeck.retrieval.hybrid import build_index
from tests.test_compose import OTHER, QUOTE, claim_block, message, slide
from tests.test_content import element

TOKENS = DesignTokens.load(Path("config/tokens/dev.json"))
CLAIMS = [
    CachedClaim(claim="Quantisation halves memory.", doc_id="paper-1", page=4, quote=QUOTE)
]


def make_env(tmp_path: Path):  # type: ignore[no-untyped-def]
    store = DocumentStore(tmp_path)
    header = element("h1", "Quantisation   Results", page=4, kind="section_header")
    store.add(
        Document(
            doc_id="paper-1",
            source_path="p1.pdf",
            title="Paper One",
            page_count=6,
            elements=[header, element("e1", QUOTE, page=4)],
        )
    )
    store.add(
        Document(
            doc_id="paper-2",
            source_path="p2.pdf",
            page_count=3,
            elements=[element("f1", OTHER, doc_id="paper-2", page=2)],
        )
    )
    docs = list(store.documents())
    index = build_index(docs, project="p")
    ws = DeckWorkspace(
        settings=BuildSettings(store=store, tokens=TOKENS, deck_fields=deck_fields())
    )
    return ws, index, docs


def deck_fields() -> dict[str, Any]:
    from autodeck.design.components.catalog import COMPONENT_LIB_VERSION

    return {
        "run_id": "r1",
        "project": "p",
        "client": "northwind",
        "theme_ref": "config/tokens/dev.json",
        "component_lib_version": COMPONENT_LIB_VERSION,
        "provenance": "strict",
        "named_terms": [],
        "design_mode": "structured",
    }


def box(ws: DeckWorkspace, index, docs) -> ToolBox:  # type: ignore[no-untyped-def]
    tools = [
        *deck_tools(ws),
        *corpus_tools(
            ws, index=index, claims=CLAIMS, corpus_map=build_corpus_map(docs, CLAIMS)
        ),
        *skill_tools(project=None),
    ]
    return ToolBox(tools, state_key=lambda: ws.revision)


def call(box_: ToolBox, name: str, **arguments: Any) -> ToolResult:
    return box_.dispatch(ToolCall(id="c", name=name, arguments=arguments))


def brief_args() -> dict[str, Any]:
    brief = DeckBriefDraft(
        objective="Decide.",
        audience="CTO",
        length_target=2,
        key_messages=[message("km1", "Quantisation halves memory.", "prompt", QUOTE)],
        must_include=[],
        must_avoid=[],
    )
    return brief.model_dump(mode="json")


def slide_args() -> dict[str, Any]:
    s = slide("s1", ["km1"], claim_block("b1", "Quantisation halves memory.", QUOTE))
    return {"slide": s.model_dump(mode="json")}


def test_write_slide_before_brief_is_refused(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    result = call(box(ws, index, docs), "write_slide", **slide_args())
    assert result.error and "set_brief" in result.text and ws.slides == []


def test_unshown_quote_fails_until_shown(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    b = box(ws, index, docs)
    assert not call(b, "set_brief", **brief_args()).error
    first = call(b, "write_slide", **slide_args())
    assert "doc_not_shown" in first.text or "not shown" in first.text
    shown = call(b, "read_passage", doc_id="paper-1", page=4)
    assert "citable" in shown.text and len(ws.shown_spans) >= 1
    again = call(b, "write_slide", **slide_args())
    assert "doc_not_shown" not in again.text and "replaced slide s1" in again.text


def test_search_shows_only_citable_and_adds_claims(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    b = box(ws, index, docs)
    result = call(b, "search_corpus", query="quantisation memory inference", limit=50)
    assert result.summary.startswith('search "quantisation')
    assert any(s.element_id == "e1" for s in ws.shown_spans)
    assert ws.shown_claims


def test_read_passage_errors(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    b = box(ws, index, docs)
    assert "paper-1, paper-2" in call(b, "read_passage", doc_id="nope", page=1).text
    assert (
        "pages with text run 4 to 4" in call(b, "read_passage", doc_id="paper-1", page=2).text
    )


def test_read_claims_shows_claims(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    result = call(box(ws, index, docs), "read_claims")
    assert not result.error and ws.shown_claims == CLAIMS and "claims.md" in result.text


def test_check_deck_format_and_finish_twice(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    b = box(ws, index, docs)
    call(b, "set_brief", **brief_args())
    call(b, "write_slide", **slide_args())  # cites a passage never shown: fails
    report = call(b, "check_deck")
    assert report.text.startswith("s1:") and "doc_not_shown" in report.text
    assert report.text.rstrip().endswith("advisories.")
    fin = {"coverage": [], "notes": ""}
    first = call(b, "finish", **fin)
    assert not first.finished and "will be dropped" in first.text
    second = call(b, "finish", **{**fin, "notes": "n"})
    assert second.finished and ws.notes == "n"


def test_finish_without_slides_is_refused(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    result = call(box(ws, index, docs), "finish", coverage=[], notes="")
    assert result.error and not result.finished


def test_compute_and_budgets_and_notes(tmp_path: Path) -> None:
    ws, index, docs = make_env(tmp_path)
    b = box(ws, index, docs)
    assert call(b, "compute", formula="(a - b) / b * 100", inputs={"a": 3, "b": 2}).text == (
        "result = 50.0"
    )
    assert call(b, "compute", formula="open('x')", inputs={}).error
    assert not call(b, "component_budgets", component="quote").error
    call(b, "set_notes", text="governing thought")
    assert ws.deck_notes == "governing thought"


def test_corpus_map_is_deterministic_and_collapses_headings(tmp_path: Path) -> None:
    _ws, _index, docs = make_env(tmp_path)
    text = build_corpus_map(list(reversed(docs)), CLAIMS)
    assert text == build_corpus_map(docs, CLAIMS)
    assert text.startswith("## paper-1 — Paper One (6 pages)")
    assert "- p.4: Quantisation Results" in text
    assert text.index("paper-1") < text.index("paper-2")
    assert text.endswith(
        "## Curated claims (claims.md): 1 — call read_claims to see and cite them"
    )
    assert build_corpus_map([], []) == "(no documents)"


def test_load_skill_unknown_is_an_error() -> None:
    (tool,) = skill_tools(project=None)
    result = tool.run(tool.args_model(name="nope"))
    assert result.error and "unknown skill" in result.text


def test_toolbox_rejects_duplicates_and_reports_validation() -> None:
    (tool,) = skill_tools(project=None)
    with pytest.raises(ValueError):
        ToolBox([tool, tool])
    result = ToolBox([tool]).dispatch(ToolCall(id="c", name="load_skill", arguments={}))
    assert result.error and "name" in result.text


def test_toolbox_error_types_become_results() -> None:
    def boom(_: Any) -> ToolResult:
        raise ToolError("nope")

    (base,) = skill_tools(project=None)
    result = ToolBox([Tool("t", "d", base.args_model, boom)]).dispatch(
        ToolCall(id="c", name="t", arguments={"name": "x"})
    )
    assert result.error and result.text == "ERROR: nope" and result.summary == "t: refused"


def _depth(node: Any) -> int:
    if isinstance(node, dict):
        return 1 + max((_depth(v) for v in node.values()), default=0)
    if isinstance(node, list):
        return 1 + max((_depth(v) for v in node), default=0)
    return 0


@pytest.mark.parametrize("creative", [False, True])
def test_every_tool_schema_is_small_and_shallow(tmp_path: Path, creative: bool) -> None:
    ws, index, _docs = make_env(tmp_path)
    if creative:
        ws.settings = BuildSettings(
            store=ws.settings.store,
            tokens=TOKENS,
            deck_fields={**deck_fields(), "design_mode": "creative"},
        )
    tools = [
        *deck_tools(ws),
        *corpus_tools(ws, index=index, claims=CLAIMS, corpus_map=""),
        *skill_tools(project=None),
    ]
    for tool in tools:
        strict = export_schema(tool.args_model, "strict")
        assert len(json.dumps(strict)) < 60_000, tool.name
        assert _depth(strict) <= 12, tool.name
        assert export_schema(tool.args_model, "standard")


def test_coverage_note_roundtrip_in_finish_args() -> None:
    note = CoverageNote(item="x", status="covered", detail="s1")
    assert note.status == "covered"
