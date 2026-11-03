"""The corpus tools: how the agent reads the sources, and how a passage becomes citable.

Showing is the gate (B75). A span joins the workspace's citable set only when one of these
tools puts it in front of the agent, so a quote from a page it never read fails with
`doc_not_shown` exactly as it would against an evidence pack. Non-citable hits (figure
descriptions, page furniture) are shown as metadata and never added.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.content import _gather_claims, render_evidence
from autodeck.agents.tools.registry import Tool, ToolError, ToolResult
from autodeck.agents.workspace import DeckWorkspace
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import HybridIndex, RetrievedSpan, search

CLAIM_LIST_CAP = 40


class CorpusMapArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchCorpusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="What to look for, in the sources' words.")
    limit: int = Field(default=8, description="Passages to return, 1 to 12.")


class ReadPassageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    page: int = Field(ge=1)


class ReadClaimsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", description="Narrow to claims about this; '' for all.")


def _docs(spans: Sequence[RetrievedSpan]) -> str:
    return ", ".join(sorted({s.doc_id for s in spans})) or "none"


def corpus_tools(
    ws: DeckWorkspace,
    *,
    index: HybridIndex,
    claims: Sequence[CachedClaim],
    corpus_map: str,
) -> list[Tool]:
    def show_corpus_map(_: CorpusMapArgs) -> ToolResult:
        return ToolResult(corpus_map, "corpus map")

    def search_corpus(args: SearchCorpusArgs) -> ToolResult:
        limit = max(1, min(args.limit, 12))
        spans = search(index, args.query, limit=limit, citable_only=False)
        ws.show_spans(s for s in spans if s.citable)
        curated = _gather_claims(args.query, claims)
        ws.show_claims(curated)
        return ToolResult(
            render_evidence(curated, spans),
            f'search "{args.query[:60]}": {len(spans)} passages (docs {_docs(spans)})',
        )

    def read_passage(args: ReadPassageArgs) -> ToolResult:
        elements = sorted(
            (
                e
                for e in index.elements.values()
                if e.doc_id == args.doc_id and e.page == args.page
            ),
            key=lambda e: e.reading_order,
        )
        if not elements:
            known = sorted({e.doc_id for e in index.elements.values()})
            if args.doc_id in known:
                pages = sorted(
                    {e.page for e in index.elements.values() if e.doc_id == args.doc_id}
                )
                raise ToolError(
                    f"{args.doc_id} has no readable text on page {args.page}; "
                    f"pages with text run {pages[0]} to {pages[-1]}."
                )
            raise ToolError(
                f"unknown document {args.doc_id!r}; known: {', '.join(known[:20]) or '(none)'}."
            )
        spans = [
            RetrievedSpan(
                doc_id=e.doc_id,
                element_id=e.element_id,
                page=e.page,
                text=e.retrieval_text(),
                score=0.0,
                citable=e.is_citable,
            )
            for e in elements
        ]
        ws.show_spans(s for s in spans if s.citable)
        return ToolResult(
            render_evidence((), spans),
            f"read {args.doc_id} p.{args.page}: {len(spans)} elements",
        )

    def read_claims(args: ReadClaimsArgs) -> ToolResult:
        chosen = (
            _gather_claims(args.query, claims)
            if args.query.strip()
            else list(claims)[:CLAIM_LIST_CAP]
        )
        ws.show_claims(chosen)
        label = f' about "{args.query[:60]}"' if args.query.strip() else ""
        return ToolResult(
            render_evidence(chosen, ()), f"read_claims{label}: {len(chosen)} claims"
        )

    return [
        Tool(
            "corpus_map",
            "The documents available and their section headings by page.",
            CorpusMapArgs,
            show_corpus_map,
        ),
        Tool(
            "search_corpus",
            "Search the source documents. Only passages shown by a search or read are citable.",
            SearchCorpusArgs,
            search_corpus,
        ),
        Tool(
            "read_passage",
            "Read every element of one page of a document; citable ones become citable.",
            ReadPassageArgs,
            read_passage,
        ),
        Tool(
            "read_claims",
            "Read the curated claims (claims.md), all or about a topic; each is citable.",
            ReadClaimsArgs,
            read_claims,
        ),
    ]
