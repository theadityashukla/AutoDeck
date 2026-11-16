"""B55 wired into the CLI, the draft preview, the manifest, the validator and the UI.

Reuses the draft-first fakes of `test_cli_draft.py` (`World`, `Counting`, `Judge`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autodeck.agents.compose import ComposedMessage, ComposeDraft, ComposedSlide
from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
from autodeck.agents.validation import (
    ClaimJudgement,
    ValidationDraft,
    conversation_spans_for,
    gather_validator_evidence,
)
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.ir.models import Deck
from autodeck.pipeline.orchestrator import Orchestrator
from autodeck.render.draft import slide_flags
from tests.test_cli_draft import CLARIFIED, World, claim_slide
from tests.test_cli_gate2 import DOC_ID, QUOTE

TYPED = "We chose the quokka architecture for the new scheduler."
CONVERSATION_ID = "conversation--r1"


def _slide(sid: str, block: ProposedBlock) -> ComposedSlide:
    return ComposedSlide(
        id=sid,
        narrative_role="evidence",
        component="quote",
        intent=f"Land {sid}.",
        message_ids=["km1"],
        blocks=[block],
        speaker_notes=[],
    )


def _composed(*slides: ComposedSlide) -> ComposeDraft:
    return ComposeDraft(
        objective="Decide whether to ship the kernel rewrite.",
        audience="CTO",
        length_target=len(slides),
        key_messages=[
            ComposedMessage(
                id="km1",
                text="The kernel rewrite raised training throughput.",
                origin="prompt",
                citations=[ProposedCitation(doc_id=DOC_ID, quote=QUOTE)],
            )
        ],
        must_include=[],
        must_avoid=[],
        slides=list(slides),
        coverage=[],
        notes="",
    )


def _from_you_slide() -> ComposedSlide:
    return _slide(
        "s1",
        ProposedBlock(
            id="b1",
            kind="claim",
            slot="headline",
            claim=ProposedClaim(
                text="The team chose the quokka architecture for the scheduler.",
                citations=[ProposedCitation(doc_id=CONVERSATION_ID, quote=TYPED)],
            ),
        ),
    )


def _unsourced_slide() -> ComposedSlide:
    return _slide(
        "s2",
        ProposedBlock(
            id="b1",
            kind="unsourced",
            slot="headline",
            text="Schedulers usually trade some fairness for throughput.",
        ),
    )


def _drafted(world: World, *, provenance: str | None = None) -> None:
    extra = ["--provenance", provenance] if provenance else []
    result = world.run(
        "clarify", "r1", "--client", "acme", "--project", "attention-efficiency",
        "--prompt", "Show that the kernel rewrite raised training throughput.",
        *extra, *world.data_roots,
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    result = world.run("answer", "r1", "--answer", f"q1={TYPED}", *world.roots)
    assert result.exit_code == 0, result.output


def _coverage(world: World) -> dict[str, Any]:
    return json.loads((world.runs / "r1" / "coverage.json").read_text(encoding="utf-8"))


def test_normal_draft_makes_a_typed_answer_citable_from_you(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    composed = _composed(_from_you_slide(), claim_slide("s3", "Throughput rose.", ["km1"]))
    w = World(tmp_path, monkeypatch, CLARIFIED, composed)
    _drafted(w)  # the project default is normal

    assert json.loads((w.runs / "r1" / "provenance.json").read_text())["provenance"] == "normal"
    result = w.run("draft", "r1", *w.data_roots)
    assert result.exit_code == 0, result.output

    compose_prompt = w.composer.prompts[1]
    assert CONVERSATION_ID in compose_prompt and TYPED in compose_prompt
    assert (w.runs / "r1" / "source" / f"{CONVERSATION_ID}.json").exists()

    deck = Orchestrator("r1", runs_root=w.runs).ir.load()
    assert deck.provenance == "normal"
    cited = [c for site in deck.claim_sites() for c in site.claim.citations]
    assert any(c.source_class == "conversation" for c in cited)
    assert slide_flags(deck)["s1"] == "blocking"  # not validated yet, so it outranks from_you

    coverage = _coverage(w)
    for key in ("advisories", "repairs", "repair_ran", "provider_calls", "provenance"):
        assert key in coverage
    assert coverage["provenance"] == "normal" and coverage["repair_ran"] is False
    assert coverage["advisories"] == [] or isinstance(coverage["advisories"][0], dict)


def test_strict_draft_leaves_the_conversation_out_of_the_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, _composed(claim_slide("s1", "Rose.", ["km1"])))
    _drafted(w, provenance="strict")

    result = w.run("draft", "r1", *w.data_roots)
    assert result.exit_code == 0, result.output
    assert CONVERSATION_ID not in w.composer.prompts[1]
    assert not (w.runs / "r1" / "source").exists()
    assert Orchestrator("r1", runs_root=w.runs).ir.load().provenance == "strict"
    assert _coverage(w)["provenance"] == "strict"


def test_provenance_option_is_refused_once_the_mode_is_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, CLARIFIED)
    _drafted(w)

    result = w.run(
        "clarify", "r1", "--client", "acme", "--project", "attention-efficiency",
        "--prompt", "Again.", "--provenance", "strict", *w.data_roots,
    )  # fmt: skip
    assert result.exit_code == 1
    assert "already fixed" in result.output
    assert json.loads((w.runs / "r1" / "provenance.json").read_text())["provenance"] == "normal"

    bad = w.run(
        "clarify", "r2", "--client", "acme", "--project", "attention-efficiency",
        "--prompt", "x", "--provenance", "loose", *w.data_roots,
    )  # fmt: skip
    assert bad.exit_code == 1 and "strict" in bad.output


def test_answer_accept_option_marks_the_answer_as_the_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED)
    assert w.clarify().exit_code == 0
    result = w.run("answer", "r1", "--accept", "q1", *w.roots)
    assert result.exit_code == 0, result.output
    saved = json.loads((w.runs / "r1" / "clarify.json").read_text())
    assert saved["answer_sources"] == {"q1": "accepted"} and saved["typed_order"] == []


def test_revise_records_the_instruction_before_ingesting_and_keeps_the_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_cli_draft import REVISED

    instruction = "Soften slide two because the quokka rollout is only a pilot."
    composed = _composed(_from_you_slide(), claim_slide("s2", "Shipping is low risk.", ["km1"]))
    w = World(tmp_path, monkeypatch, CLARIFIED, composed, REVISED)
    _drafted(w)
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0

    result = w.run("revise", "r1", "--instruction", instruction, *w.data_roots)
    assert result.exit_code == 0, result.output
    assert instruction in w.composer.prompts[2]  # it reached the pack as "from you"
    assert instruction in (w.runs / "r1" / "source" / f"{CONVERSATION_ID}.json").read_text()
    lines = (w.runs / "r1" / "revisions.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["reply"] == "Softened slide two."
    assert Orchestrator("r1", runs_root=w.runs).ir.load().provenance == "normal"


def test_manifest_records_mode_and_run_source_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autodeck.audit.manifest import file_sha256
    from autodeck.cli import run_source_hashes

    composed = _composed(_from_you_slide())
    w = World(tmp_path, monkeypatch, CLARIFIED, composed)
    _drafted(w)
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0

    hashes = run_source_hashes(w.runs / "r1")
    stored = w.runs / "r1" / "source" / f"{CONVERSATION_ID}.json"
    assert hashes == {CONVERSATION_ID: file_sha256(stored)}
    assert run_source_hashes(w.runs / "nothing") == {}


def _deck_with_flags() -> Deck:
    from tests.test_renderer import _claim_block, _deck
    from tests.test_renderer import _slide as plain_slide

    deck = _deck(
        plain_slide("s1", "bullets_supporting", [_claim_block("headline", "A.")]),
        plain_slide("s2", "bullets_supporting", [_claim_block("headline", "B.")]),
        plain_slide("s3", "bullets_supporting", [_claim_block("headline", "C.")]),
    )
    return deck


def test_slide_flags_name_unsourced_and_from_you() -> None:
    from autodeck.ir.models import Citation

    deck = _deck_with_flags()
    first, second, _third = deck.slides
    claim = first.blocks[0].claim
    assert claim is not None
    cite = claim.citations[0]
    conversation = Citation.model_validate({**cite.model_dump(), "doc_id": CONVERSATION_ID})
    first.blocks[0] = first.blocks[0].model_copy(
        update={"claim": claim.model_copy(update={"citations": [conversation]})}
    )
    unsourced_claim = second.blocks[0].claim.model_copy(  # type: ignore[union-attr]
        update={"citations": [], "basis": "unsourced", "verdict": "uncorroborated"}
    )
    second.blocks[0] = second.blocks[0].model_copy(update={"claim": unsourced_claim})

    flags = slide_flags(deck)
    assert flags["s1"] == "from_you" and flags["s2"] == "unsourced" and flags["s3"] == ""


def test_validator_is_offered_the_conversation_spans(tmp_path: Path) -> None:
    from autodeck.ingest.conversation_source import ingest_conversation
    from autodeck.ingest.document_store import DocumentStore
    from autodeck.ingest.multi_store import MultiStore
    from autodeck.pipeline.clarify_state import new_clarify, save_clarify
    from autodeck.retrieval.hybrid import build_index

    run_root = tmp_path / "runs" / "r1"
    save_clarify(
        run_root,
        new_clarify(prompt=TYPED, client="acme", project="p", assumptions=[], questions=[]),
    )
    assert ingest_conversation(run_root, "r1") == CONVERSATION_ID
    store = MultiStore(run_root / "source", tmp_path / "corpus")
    index = build_index([], project="p")

    deck = _deck_with_flags()
    first = deck.slides[0]
    claim = first.blocks[0].claim
    assert claim is not None
    conversation = claim.citations[0].model_copy(update={"doc_id": CONVERSATION_ID})
    first.blocks[0] = first.blocks[0].model_copy(
        update={"claim": claim.model_copy(update={"citations": [conversation]})}
    )

    assert conversation_spans_for(deck, store=store) == ()  # a strict deck sees nothing
    deck = deck.model_copy(update={"provenance": "normal"})
    spans = conversation_spans_for(deck, store=store)
    assert spans and all(s.doc_id == CONVERSATION_ID for s in spans)

    evidence = gather_validator_evidence(claim, index=index, store=store, extra_spans=spans)
    assert [c.quote for c in evidence.spans] == [TYPED]
    assert all(c.retrieved_by == "validator" for c in evidence.spans)
    assert DocumentStore  # imported for the typing of `store`


def test_ui_project_settings_round_trip(tmp_path: Path) -> None:
    from autodeck.ui import api
    from tests.test_knowledge import build_knowledge

    knowledge = build_knowledge(tmp_path)
    roots = api.Roots(
        runs=tmp_path / "runs",
        knowledge=knowledge,
        corpus=tmp_path / "corpus",
        profile=tmp_path / "profile.json",
        env="dev",
    )
    first = api.project_settings_view(roots, "attention-efficiency")
    assert first["provenance"] == "normal" and first["named_terms"] == []

    saved = api.save_project_settings_view(
        roots,
        "attention-efficiency",
        provenance="strict",
        named_terms=["Type 2 diabetes", "  ", "GLP-1"],
    )
    assert saved["provenance"] == "strict"
    assert saved["named_terms"] == ["Type 2 diabetes", "GLP-1"]
    assert api.project_settings_view(roots, "attention-efficiency") == saved

    with pytest.raises(api.UIError):
        api.save_project_settings_view(
            roots, "attention-efficiency", provenance="x", named_terms=None
        )
    with pytest.raises(api.UIError):
        api.project_settings_view(roots, "no-such-project")


def test_ui_draft_view_carries_mode_and_advisories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autodeck.ui import api

    composed = _composed(_from_you_slide())
    w = World(tmp_path, monkeypatch, CLARIFIED, composed)
    _drafted(w)
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0

    roots = api.Roots(
        runs=w.runs,
        knowledge=w.knowledge,
        corpus=w.corpus,
        profile=tmp_path / "p.json",
        env="dev",
    )
    view = api.draft_view(roots, "r1")
    assert view["provenance"] == "normal"
    assert "advisories" in view and "repairs" in view and view["repair_ran"] is False
    cites = view["slides"][0]["blocks"][0]["citations"]
    assert cites[0]["source_class"] == "conversation"
    assert view["slides"][0]["blocks"][0]["basis"] == "cited"
    assert view["flags"]["s1"] == "blocking"


def test_the_unused_helpers_stay_importable() -> None:
    # `ValidationDraft`, `ClaimJudgement`, `VerdictJudgement`, `_unsourced_slide` are kept for
    # the live-run replay; referencing them keeps the module import honest.
    assert ValidationDraft and ClaimJudgement and VerdictJudgement and _unsourced_slide


def test_draft_passes_the_project_glossary_to_the_deck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, _composed(claim_slide("s1", "Rose.", ["km1"])))
    settings = w.knowledge / "projects" / "attention-efficiency" / "settings.yaml"
    settings.write_text("provenance: normal\nnamed_terms:\n  - Type 2 diabetes\n", "utf-8")
    _drafted(w)
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0
    deck = Orchestrator("r1", runs_root=w.runs).ir.load()
    assert deck.named_terms == ["Type 2 diabetes"]
