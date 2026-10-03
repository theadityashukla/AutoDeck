"""The draft-first commands end to end (3c.10): clarify, answer, draft, validate, revise.

Fake providers only (`ModelRegistry.provider_for` is patched, as in `test_cli_gate2.py`).
The headline: the first visible draft costs exactly three model calls - clarify, compose
and validate - and the preview that follows costs none. A revision costs one call to write
and one to validate, and validation re-judges only the slide that changed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation
from typer.testing import CliRunner

import autodeck.providers.registry as registry_module
from autodeck.agents.compose import (
    Assumption,
    ClarifyingQuestion,
    ClarifyResult,
    ComposedMessage,
    ComposeDraft,
    ComposedSlide,
    ReviseDraft,
)
from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
from autodeck.agents.validation import ClaimJudgement, ValidationDraft
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.cli import app
from autodeck.ir.models import Deck
from autodeck.ir.store import IRStore
from autodeck.pipeline.orchestrator import Orchestrator
from autodeck.render import draft as draft_module
from autodeck.render.qa.libreoffice import RenderError
from tests.test_cli_gate2 import CLIENT, DOC_ID, PROJECT, QUOTE, element
from tests.test_knowledge import build_knowledge

runner = CliRunner()


class Counting:
    """A fake for one role that returns scripted answers in order and counts calls."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        return self.answers.pop(0)


class Judge:
    """A validation fake: every claim named in the prompt is supported."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        ids = [c for c in ("s1:b1", "s2:b1", "s3:b1") if c in prompt]
        verdict = VerdictJudgement(
            verdict="supported", verdict_notes="matches", supporting_quote=QUOTE
        )
        return ValidationDraft(
            judgements=[ClaimJudgement(claim_id=i, judgement=verdict) for i in ids]
        )


def claim_slide(sid: str, text: str, message_ids: list[str]) -> ComposedSlide:
    return ComposedSlide(
        id=sid,
        narrative_role="evidence",
        component="quote",
        intent=f"Land {sid}.",
        message_ids=message_ids,
        blocks=[
            ProposedBlock(
                id="b1",
                kind="claim",
                slot="figure",
                claim=ProposedClaim(
                    text=text, citations=[ProposedCitation(doc_id=DOC_ID, quote=QUOTE)]
                ),
            )
        ],
        speaker_notes=[],
    )


CLARIFIED = ClarifyResult(
    assumptions=[Assumption(topic="audience", statement="Two slides for the CTO.")],
    questions=[
        ClarifyingQuestion(
            id="q1",
            question="Neutral summary or recommendation?",
            why="Changes the last slide.",
            suggested_answer="Recommendation.",
            options=["Recommendation.", "Neutral."],
        )
    ],
)
COMPOSED = ComposeDraft(
    objective="Decide whether to ship the kernel rewrite.",
    audience="CTO",
    length_target=2,
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
    slides=[
        claim_slide("s1", "The kernel rewrite raised throughput, per the benchmark.", ["km1"]),
        claim_slide("s2", "Shipping it is low risk, per the same benchmark.", ["km1"]),
    ],
    coverage=[],
    notes="",
)
REVISED = ReviseDraft(
    objective=COMPOSED.objective,
    audience="CTO",
    length_target=2,
    key_messages=COMPOSED.key_messages,
    must_include=[],
    must_avoid=[],
    changed_slides=[
        claim_slide("s2", "Shipping it carries modest risk, per the benchmark.", ["km1"])
    ],
    removed_slide_ids=[],
    order=["s1", "s2"],
    coverage=[],
    reply="Softened slide two.",
)


class World:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *answers: Any) -> None:
        from autodeck.ingest.document_store import Document, DocumentStore

        self.knowledge = build_knowledge(tmp_path)
        self.corpus = tmp_path / "corpus"
        self.runs = tmp_path / "runs"
        DocumentStore(self.corpus / PROJECT).add(
            Document(
                doc_id=DOC_ID,
                source_path=f"{DOC_ID}.pdf",
                page_count=6,
                elements=[element(DOC_ID, QUOTE)],
            )
        )
        self.composer = Counting(*answers)
        self.judge = Judge()
        roles = {"composer": self.composer, "validation": self.judge}
        monkeypatch.setattr(
            registry_module.ModelRegistry,
            "provider_for",
            lambda self, role, **kw: roles[role],
        )

        def build(deck: Deck, tokens: object, out_path: Path) -> dict[str, str]:
            presentation = Presentation()
            for _ in deck.slides:
                presentation.slides.add_slide(presentation.slide_layouts[6])
            presentation.save(str(out_path))
            return {}

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

    def clarify(self):  # type: ignore[no-untyped-def]
        return self.run(
            "clarify", "r1", "--client", CLIENT, "--project", PROJECT,
            "--prompt", "Show that the kernel rewrite raised training throughput.",
            *self.data_roots,
        )  # fmt: skip

    def calls(self) -> int:
        return len(self.composer.prompts) + len(self.judge.prompts)


def test_clarify_answer_draft_validate_preview_is_three_model_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)

    result = w.clarify()
    assert result.exit_code == 0, result.output
    saved = json.loads((w.runs / "r1" / "clarify.json").read_text())
    assert saved["answers"] is None and saved["questions"][0]["id"] == "q1"
    assert saved["prompt"].startswith("Show that")
    assert "Neutral summary or recommendation?" in result.output

    result = w.run("answer", "r1", "--accept-all", "--correct", "Make it two slides.", *w.roots)
    assert result.exit_code == 0, result.output
    saved = json.loads((w.runs / "r1" / "clarify.json").read_text())
    assert saved["answers"] == {"q1": "Recommendation."}
    assert saved["corrections"] == ["Make it two slides."]

    result = w.run("draft", "r1", *w.data_roots)
    assert result.exit_code == 0, result.output
    assert "Key messages:" in result.output and "SUPPORTED" in result.output
    compose_prompt = w.composer.prompts[1]
    assert "Recommendation." in compose_prompt and "Make it two slides." in compose_prompt

    orch = Orchestrator("r1", runs_root=w.runs)
    assert orch.state.is_complete("compose") and orch.is_draft_first
    assert orch.paths.draft_brief.exists()
    coverage = json.loads((orch.paths.root / "coverage.json").read_text())
    assert coverage["coverage"][0]["status"] == "covered"
    assert coverage["origins"] == {"km1": "prompt"}

    result = w.run("validate", "r1", "--corpus-root", str(w.corpus), *w.roots)
    assert result.exit_code == 0, result.output
    assert w.calls() == 3

    before = dict(Orchestrator("r1", runs_root=w.runs).state.approvals)
    result = w.run("preview", "r1", *w.roots)
    assert result.exit_code == 0, result.output
    assert w.calls() == 3  # the preview costs no model call
    orch = Orchestrator("r1", runs_root=w.runs)
    assert orch.state.is_complete("preview") and not orch.paths.deck_pptx.exists()
    assert orch.state.approvals == before == {}


def test_draft_refuses_without_recorded_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    assert w.clarify().exit_code == 0

    result = w.run("draft", "r1", *w.data_roots)
    assert result.exit_code == 3
    assert "answer" in result.output
    assert len(w.composer.prompts) == 1  # no compose call was made
    assert not Orchestrator("r1", runs_root=w.runs).state.is_complete("compose")

    # An answer to a question that does not exist, or a missing answer, is refused.
    assert w.run("answer", "r1", "--answer", "q9=x", *w.roots).exit_code == 1
    assert w.run("answer", "r1", *w.roots).exit_code == 1


def test_answering_by_hand_works_and_draft_needs_a_clarify_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    Orchestrator("r2", runs_root=w.runs)  # a run that never clarified
    result = w.run("draft", "r2", *w.data_roots)
    assert result.exit_code == 3 and "clarify" in result.output

    assert w.clarify().exit_code == 0
    assert w.run("answer", "r1", "--answer", "q1=Neutral.", *w.roots).exit_code == 0
    saved = json.loads((w.runs / "r1" / "clarify.json").read_text())
    assert saved["answers"] == {"q1": "Neutral."}


def test_revise_changes_one_slide_and_validation_reuses_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, COMPOSED, REVISED)
    assert w.clarify().exit_code == 0
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0
    assert w.run("validate", "r1", "--corpus-root", str(w.corpus), *w.roots).exit_code == 0
    store = IRStore(w.runs, "r1")
    validated = store.load()
    assert [s.blocks[0].claim.verdict for s in validated.slides] == ["supported"] * 2

    result = w.run("revise", "r1", "--instruction", "Soften slide two.", *w.data_roots)
    assert result.exit_code == 0, result.output
    assert "Softened slide two." in result.output
    revised = store.load()
    assert revised.version == validated.version + 1
    assert revised.slides[0].blocks == validated.slides[0].blocks  # identical, verdict included
    assert revised.slides[0].blocks[0].claim.verdict == "supported"
    assert revised.slides[1].blocks[0].claim.verdict == "unverified"
    log = [
        json.loads(line)
        for line in (w.runs / "r1" / "revisions.jsonl").read_text().splitlines()
    ]
    assert (
        log[0]["instruction"] == "Soften slide two."
        and log[0]["reply"] == "Softened slide two."
    )
    assert "at" in log[0]

    calls_before = w.calls()
    result = w.run("validate", "r1", "--corpus-root", str(w.corpus), *w.roots)
    assert result.exit_code == 0, result.output
    assert w.calls() == calls_before + 1  # one validation call ...
    assert (
        "s1:b1" not in w.judge.prompts[-1] and "s2:b1" in w.judge.prompts[-1]
    )  # ... one claim
    final = store.load()
    assert [s.blocks[0].claim.verdict for s in final.slides] == ["supported"] * 2


def test_revise_needs_a_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED)
    assert w.clarify().exit_code == 0
    result = w.run("revise", "r1", "--instruction", "x", *w.data_roots)
    assert result.exit_code == 3


def test_a_missing_run_is_an_error_not_a_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch)
    for command in (
        ["draft", "nope", *w.data_roots],
        ["answer", "nope", "--accept-all", *w.roots],
    ):
        result = w.run(*command)
        assert result.exit_code == 1
    assert not (w.runs / "nope").exists()
