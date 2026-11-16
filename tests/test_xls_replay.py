"""Replay the cached live compose answer for run Xls through today's resolver.

The live run (oral-semaglutide, env dev-mistral) lost all three bullets of slide s5 because
one of them overflowed, and its s3 chart failed to cite a quote the model had stitched from
two passages. This feeds the very JSON the model returned (kept in the run's LLM cache)
through `compose_deck` with the run's own evidence pack, so the fix is judged on the real
case. Skipped wherever the run, its cache or the corpus is absent (a fresh checkout).
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "Xls"
CACHE = (
    RUN / "llm_cache" / "51"
    / "510ceac53b57a14cda4a8e638978281c8407ef7a67aed4a0e2a43fa64f719f5e.txt"
)

pytestmark = pytest.mark.skipif(
    not CACHE.exists() or not (ROOT / "corpus" / "oral-semaglutide").exists(),
    reason="the Xls live-run cache or the oral-semaglutide corpus is not present",
)


class _Replay:
    def __init__(self, draft: object) -> None:
        self.draft = draft

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        return self.draft


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from autodeck.agents.compose import ComposeDraft, compose_deck
    from autodeck.cli import _draft_setup, _pack_for
    from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
    from autodeck.design.theme.tokens import DesignTokens
    from autodeck.knowledge.loader import load_project_settings
    from autodeck.pipeline.clarify_state import answer_pairs, load_clarify

    # A copy of the run (state and clarify only), so replaying never touches the original.
    runs_root = tmp_path_factory.mktemp("runs")
    shutil.copytree(
        RUN,
        runs_root / "Xls",
        ignore=shutil.ignore_patterns("llm_cache", "previews", "ir", "artifacts"),
    )
    clarify = load_clarify(runs_root / "Xls")
    planning, client, project = _draft_setup(
        "Xls",
        client=None,
        project=None,
        env="dev-mistral",
        knowledge_root=ROOT / "knowledge",
        corpus_root=ROOT / "corpus",
        runs_root=runs_root,
        clarify_data=clarify,
    )
    request = clarify["prompt"]
    pack = _pack_for(planning, request)
    draft = ComposeDraft.model_validate_json(CACHE.read_text(encoding="utf-8"))
    result = compose_deck(
        request,
        answers=answer_pairs(clarify),
        pack=pack,
        context=planning.assembled,
        store=planning.store,
        tokens=DesignTokens.load(ROOT / "config" / "tokens" / "dev.json"),
        model=_Replay(draft),
        run_id="Xls",
        client=client,
        project=project,
        theme_ref="config/tokens/dev.json",
        component_lib_version=COMPONENT_LIB_VERSION,
        repair=False,  # the replay measures what the first pass keeps; the cache has no repair
        named_terms=load_project_settings(ROOT / "knowledge", project).named_terms,
    )
    return draft, result


def test_replay_summary_and_the_overflow_only_costs_the_block_at_fault(replayed) -> None:  # type: ignore[no-untyped-def]
    draft, result = replayed
    old = json.loads((RUN / "coverage.json").read_text(encoding="utf-8"))

    proposed = {s.id: [b.id for b in s.blocks] for s in draft.slides}
    kept = {s.id: [b.id for b in s.blocks] for s in result.deck.slides}
    old_dropped = Counter(
        r.split(":", 1)[0] for r in old["rejections"]
    )
    new_kinds = Counter(f.kind for f in result.failures)
    print("\n--- Xls replay: before (runs/Xls/coverage.json) vs after ---")
    print(f"before: {len(old['rejections'])} rejection strings; by place: {dict(old_dropped)}")
    print(f"after:  {len(result.failures)} structured failures; by kind: {dict(new_kinds)}")
    for sid, ids in proposed.items():
        print(f"  {sid}: proposed {len(ids)} face block(s), kept {len(kept.get(sid, []))}")
    for failure in result.failures:
        print(
            f"  - {failure.slide_id or 'message'} {failure.where} {failure.block_id or '-'} "
            f"[{failure.kind}] {failure.detail.get('chars', '')} "
            f"{failure.detail.get('best_coverage', '')}"
        )

    s5 = next(s for s in result.deck.slides if s.id == "s5")
    points = [b for b in s5.blocks if b.slot == "points"]
    assert len(points) == 2
    overflows = [
        f for f in result.failures if f.slide_id == "s5" and f.kind.startswith("overflow")
    ]
    [only] = overflows
    assert only.kind == "overflow_item" and only.detail["chars"] == 132
    assert only.proposed is not None and "Gastrointestinal" in only.proposed.claim.text

    assert all(f.kind for f in result.failures)
    json.dumps([f.to_dict() for f in result.failures])  # persistable as coverage.json


def test_the_s3_chart_quote_diagnosis_is_reported(replayed) -> None:  # type: ignore[no-untyped-def]
    _draft, result = replayed
    quote_failures = [f for f in result.failures if f.slide_id == "s3" and "quote" in f.kind]
    for failure in quote_failures:
        print(
            f"s3 {failure.where} {failure.block_id}: {failure.kind} "
            f"best_coverage={failure.detail.get('best_coverage')} "
            f"parts={failure.detail.get('parts')}"
        )
    # The diagnosis of a stitched quote is data to look at, not yet a fixed expectation.
    assert quote_failures, "the replay no longer fails any s3 quote at all"


def test_the_six_slide_deck_loses_its_divider(replayed) -> None:  # type: ignore[no-untyped-def]
    _draft, result = replayed
    assert "s2" not in {s.id for s in result.deck.slides}
    assert any("section divider 's2' removed" in c for c in result.corrections)
