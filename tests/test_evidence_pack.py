"""The evidence pack: deterministic, claims first, budgeted, and resolvable.

The last test is the load-bearing one — whatever the pack shows a model must resolve
through the same `resolve_blocks` that slides use.
"""

from __future__ import annotations

from pathlib import Path

from autodeck.agents.content import (
    ProposedBlock,
    ProposedCitation,
    ProposedClaim,
    render_evidence,
    resolve_blocks,
)
from autodeck.agents.evidence_pack import build_evidence_pack
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import build_index
from tests.test_content import element, store_with

QUOTE = "Quantisation reduces the memory required for inference by half on a 13B model."
OTHER = "Batching requests raises throughput under a fixed latency budget substantially."
PROMPT = "quantisation memory inference"


def _setup(tmp_path: Path, extra: int = 0):
    elements = [
        element("e1", QUOTE, page=4),
        element("e2", OTHER, page=5),
        *(
            element(
                f"x{i}", f"Quantisation memory inference filler passage number {i} " * 6, page=6
            )
            for i in range(extra)
        ),
    ]
    store = store_with(tmp_path, *elements)
    index = build_index([store.get("paper-1")], project="p")
    claim = CachedClaim(
        claim="Quantisation halves memory.", doc_id="paper-1", page=4, quote=QUOTE
    )
    return store, index, [claim]


def _pack(index, claims, **kw):
    return build_evidence_pack(
        PROMPT,
        project_md=kw.pop("project_md", "# Goals\n- batching throughput latency\n"),
        claims=claims,
        index=index,
        **kw,
    )


def test_same_inputs_give_an_identical_pack(tmp_path: Path) -> None:
    _, index, claims = _setup(tmp_path)
    assert _pack(index, claims) == _pack(index, claims)


def test_claims_come_before_spans(tmp_path: Path) -> None:
    _, index, claims = _setup(tmp_path)
    pack = _pack(index, claims)
    assert pack.claims == tuple(claims)
    assert pack.spans
    assert pack.text.index("[claims.md") < pack.text.index("[corpus")


def test_spans_are_deduplicated_across_queries(tmp_path: Path) -> None:
    _, index, claims = _setup(tmp_path)
    pack = _pack(index, claims, project_md="- quantisation memory\n- inference memory\n")
    keys = [(s.doc_id, s.page, s.text) for s in pack.spans]
    assert len(keys) == len(set(keys))
    assert len(pack.claims) == 1


def test_budget_trims_spans_from_the_end_and_counts_them(tmp_path: Path) -> None:
    _, index, claims = _setup(tmp_path, extra=6)
    full = _pack(index, claims)
    assert full.dropped == 0 and len(full.spans) > 2
    small = _pack(index, claims, budget_tokens=full.approx_tokens - 100)
    assert small.dropped >= 1
    assert small.dropped == len(full.spans) - len(small.spans)
    assert small.spans == full.spans[: len(small.spans)]
    assert small.approx_tokens <= full.approx_tokens - 100
    assert small.claims == full.claims


def test_empty_project_md_uses_the_prompt_only(tmp_path: Path) -> None:
    _, index, claims = _setup(tmp_path)
    pack = _pack(index, claims, project_md="")
    assert pack.queries == (PROMPT,)
    assert pack.claims and pack.spans


def test_text_is_exactly_the_shared_rendering(tmp_path: Path) -> None:
    _, index, claims = _setup(tmp_path)
    pack = _pack(index, claims)
    assert pack.text == render_evidence(pack.claims, pack.spans)
    assert pack.approx_tokens == len(pack.text) // 4


def test_every_curated_quote_resolves_through_the_shared_resolver(tmp_path: Path) -> None:
    store, index, claims = _setup(tmp_path)
    pack = _pack(index, claims)
    proposed = [
        ProposedBlock(
            id=f"b{i}",
            kind="claim",
            slot="figure",
            claim=ProposedClaim(
                text=c.claim, citations=[ProposedCitation(doc_id=c.doc_id, quote=c.quote)]
            ),
        )
        for i, c in enumerate(pack.claims)
    ]
    rejections: list[str] = []
    blocks = resolve_blocks(
        proposed,
        store=store,
        claims=pack.claims,
        spans=pack.spans,
        location="test",
        rejections=rejections,
    )
    assert not rejections
    assert len(blocks) == len(pack.claims) >= 1


# -- section leads and answer queries (run XLP2) ---------------------------------------------

RESULT = (
    "Oral semaglutide 14 mg was found to be superior in reducing HbA1c versus empagliflozin "
    "at 26 weeks, the trial's primary endpoint, when used as second-line treatment."
)


def _paper(tmp_path: Path):
    """A paper whose key result sits under a heading no prompt word would retrieve."""
    elements = [
        element("h1", "4.1.1 Active-Comparator Trials", page=7, kind="section_header"),
        element("t1", RESULT, page=7),
        element("h2", "References", page=9, kind="section_header"),
        element("t2", "Smith J, Jones K. A long reference entry that is not evidence " * 3, page=9),
        element("t3", OTHER * 2, page=3),
    ]
    store = store_with(tmp_path, *elements)
    return store, build_index([store.get("paper-1")], project="p")


def test_section_leads_bring_in_results_no_query_found(tmp_path: Path) -> None:
    """XLP2: the review's headline HbA1c result was never in the pack, because nothing in
    the prompt or project.md retrieved it. A section's opening paragraph now is."""
    _, index = _paper(tmp_path)
    without = _pack(index, [], section_leads=False)
    with_leads = _pack(index, [])
    assert RESULT not in without.text
    assert RESULT in " ".join(with_leads.text.split())


def test_boilerplate_sections_are_not_section_leads(tmp_path: Path) -> None:
    from autodeck.agents.evidence_pack import section_lead_spans

    _, index = _paper(tmp_path)
    ids = [s.element_id for s in section_lead_spans(index)]
    assert any(i.endswith("t1") for i in ids)
    assert not any(i.endswith("t2") for i in ids)


def test_answers_are_queried_right_after_the_prompt(tmp_path: Path) -> None:
    _, index, claims = _setup(tmp_path)
    pack = _pack(index, claims, extra_queries=("Include comparisons? Yes, with trial specifics",))
    assert pack.queries[:2] == (PROMPT, "Include comparisons? Yes, with trial specifics")
