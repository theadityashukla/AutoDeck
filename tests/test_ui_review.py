"""The review UI's read models (B42): outline, claims and final deck.

Fixtures reuse the CLI tests' seeding (scripted fake models, no live calls, no LibreOffice).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import autodeck
from autodeck.audit.gate3 import FinalAssessment
from autodeck.audit.manifest import canonical_pptx_digest
from autodeck.audit.numeric_linter import NumericReport
from autodeck.audit.post_render import PostRenderReport
from autodeck.design.grammar import GrammarFinding
from autodeck.design.headers.flow import FlowFinding, HeaderFlowReport, HeaderLine
from autodeck.pipeline.orchestrator import Gate, Orchestrator
from autodeck.pipeline.send_back import load_send_backs
from autodeck.ui import review
from autodeck.ui.api import Roots, UIError
from tests.gate_artifacts import seed_artifact
from tests.test_cli_gate2 import _validated_run, make_run
from tests.test_gate3 import make_gate3_run


def roots_for(runs_root: Path, knowledge: Path | None = None) -> Roots:
    return Roots(
        knowledge=knowledge or runs_root.parent / "knowledge",
        corpus=runs_root.parent / "corpus",
        runs=runs_root,
        env="dev",
    )


# --------------------------------------------------------------------------- outline


def test_outline_view_shape(tmp_path: Path) -> None:
    _knowledge, _corpus, runs_root = make_run(tmp_path)
    view = review.outline_view(roots_for(runs_root), "r1")

    assert view["version"] == 1
    assert view["approval"]["approved"] is True
    assert view["approval"]["state"] == "current"
    [slide] = view["slides"]
    assert slide == {
        "id": "s1",
        "n": 1,
        "role": "evidence",
        "component": "quote",
        "message_ids": ["km1"],
        "intent": "State that the kernel rewrite raised training throughput.",
    }
    assert view["messages"] == {"km1": "The kernel rewrite raised training throughput."}
    assert isinstance(view["checks_pass"], bool)
    for finding in view["findings"]:
        assert set(finding) == {"severity", "label", "text"}
        assert finding["severity"] in ("blocking", "advisory")
    assert view["notes"] == "" and view["corrections"] == []


def test_outline_view_409_without_an_outline_and_404_for_unknown(tmp_path: Path) -> None:
    roots = roots_for(tmp_path / "runs")
    Orchestrator("fresh", runs_root=roots.runs)
    with pytest.raises(UIError) as fresh:
        review.outline_view(roots, "fresh")
    assert fresh.value.status == 409
    with pytest.raises(UIError) as unknown:
        review.outline_view(roots, "nope")
    assert unknown.value.status == 404


# --------------------------------------------------------------------------- claims


def test_claims_view_before_validate_is_409(tmp_path: Path) -> None:
    _k, _c, runs_root = make_run(tmp_path)
    with pytest.raises(UIError) as refused:
        review.claims_view(roots_for(runs_root), "r1")
    assert refused.value.status == 409


def test_claims_view_shape_and_writes_the_audit_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = _validated_run(tmp_path, monkeypatch, "supported")
    paths = Orchestrator("r1", runs_root=runs_root).paths
    assert not paths.audit_report.exists()

    view = review.claims_view(roots_for(runs_root), "r1")

    assert paths.audit_report.read_text(encoding="utf-8").strip()
    assert view["approval"]["approved"] is False
    [claim] = view["claims"]
    assert claim["id"] == "s1:b1"
    assert claim["slide_n"] == 1 and claim["role"] == "evidence"
    assert claim["verdict"] == "supported" and claim["blocking"] is False
    [citation] = claim["citations"]
    assert set(citation) == {"doc_id", "page", "quote", "sha256", "retrieved_by"}
    assert len(citation["sha256"]) == 64
    assert claim["contradicting"] == []
    assert len(view["checks"]) == 6
    assert all(set(c) == {"label", "passed", "detail"} for c in view["checks"])
    assert view["send_backs"] == []
    assert isinstance(view["risks"], list)


def test_claims_view_flags_a_blocking_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = _validated_run(tmp_path, monkeypatch, "unsupported")
    view = review.claims_view(roots_for(runs_root), "r1")
    assert view["claims"][0]["blocking"] is True
    assert view["checks"][0]["passed"] is False


def test_send_back_records_and_never_approves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = _validated_run(tmp_path, monkeypatch, "supported")
    roots = roots_for(runs_root)

    result = review.send_back(
        roots, "r1", [{"claim_id": "s1:b1", "reason": "  too strong  "}], "Ada"
    )

    assert result["sent"] == ["s1:b1"]
    orch = Orchestrator("r1", runs_root=runs_root)
    [record] = load_send_backs(orch.paths.root)
    assert (record.claim_id, record.reason, record.by, record.ir_version) == (
        "s1:b1",
        "too strong",
        "Ada",
        orch.ir.latest_version(),
    )
    assert result["path"].endswith("send_backs.json")
    assert not orch.state.is_approved(Gate.CLAIMS)

    view = review.claims_view(roots, "r1")
    assert [s["claim_id"] for s in view["send_backs"]] == ["s1:b1"]


@pytest.mark.parametrize(
    ("items", "by", "status"),
    [
        ([{"claim_id": "s9:zz", "reason": "x"}], "Ada", 409),
        ([{"claim_id": "s1:b1", "reason": "   "}], "Ada", 400),
        ([], "Ada", 400),
        ([{"claim_id": "s1:b1", "reason": "x"}], " ", 400),
        (["s1:b1"], "Ada", 400),
    ],
)
def test_send_back_refusals_write_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    items: list,
    by: str,
    status: int,  # type: ignore[type-arg]
) -> None:
    runs_root = _validated_run(tmp_path, monkeypatch, "supported")
    with pytest.raises(UIError) as refused:
        review.send_back(roots_for(runs_root), "r1", items, by)
    assert refused.value.status == status
    assert load_send_backs(Orchestrator("r1", runs_root=runs_root).paths.root) == []


# --------------------------------------------------------------------------- final


def _rendered_run(tmp_path: Path) -> tuple[Roots, Orchestrator]:
    """A claims-approved run with a stand-in `deck.pptx` and a completed render stage.

    The deck is a placeholder zip: real rendering needs the design fonts, and the final
    assessment is stubbed where a test needs one (`_stub_assessment`).
    """
    runs_root, knowledge = make_gate3_run(tmp_path)
    orch = Orchestrator("r1", runs_root=runs_root, env="dev")
    seed_artifact(orch, Gate.FINAL_RENDER, marker="v1")
    orch.run_stage("render", lambda: "rendered", force=True)
    return roots_for(runs_root, knowledge), orch


def _stub_assessment(monkeypatch: pytest.MonkeyPatch, orch: Orchestrator, **kw: Any) -> None:
    flow = HeaderFlowReport(
        lines=[
            HeaderLine(slide_id="s1", component="title", kind="claim", text="Cost fell"),
            HeaderLine(slide_id="s2", component="plan", kind="section_header", text="Rollout"),
        ],
        findings=[FlowFinding(slide_id="s2", detail="reads as a topic label")],
    )
    assessment = FinalAssessment(
        pptx=orch.paths.deck_pptx,
        deck_digest=canonical_pptx_digest(orch.paths.deck_pptx),
        post_render=PostRenderReport(numeric=NumericReport(), **kw),
        qa=[],
        grammar=[GrammarFinding(check="word budget", severity="advisory", detail="long")],
        flow=flow,
        chart_count=1,
        diagram_count=1,
        icon_count=3,
    )
    monkeypatch.setattr(review, "_final_assessment", lambda *a, **k: assessment)


def test_final_view_409_before_render(tmp_path: Path) -> None:
    runs_root, knowledge = make_gate3_run(tmp_path)
    with pytest.raises(UIError) as refused:
        review.final_view(roots_for(runs_root, knowledge), "r1")
    assert refused.value.status == 409


def test_final_view_before_gate3_says_the_audit_has_not_run(tmp_path: Path) -> None:
    roots, orch = _rendered_run(tmp_path)
    view = review.final_view(roots, "r1")
    assert view["passes"] is False
    assert "not run yet" in view["criteria"][0]["detail"]
    assert view["digest"] == canonical_pptx_digest(orch.paths.deck_pptx)
    assert view["deck_path"] == str(orch.paths.deck_pptx)
    assert view["critique"] == {"score": None, "looks": None}
    assert [c["n"] for c in view["human_checks"]] == [1, 2, 3, 4, 5]
    assert all(c["title"] and c["steps"] for c in view["human_checks"])
    assert view["previews"] == []


def test_final_view_after_gate3_lists_criteria_flow_and_previews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots, orch = _rendered_run(tmp_path)
    _stub_assessment(monkeypatch, orch)
    orch.record_final_assessment(canonical_pptx_digest(orch.paths.deck_pptx), True)
    folder = orch.paths.previews / "final"
    folder.mkdir(parents=True)
    (folder / "deck-1.png").write_bytes(b"\x89PNG one")
    (folder / "deck-2.png").write_bytes(b"\x89PNG two")

    view = review.final_view(roots, "r1")

    assert view["passes"] is True
    assert [c["passed"] for c in view["criteria"]] == [True] * 4
    assert all(set(c) == {"label", "passed", "detail"} for c in view["criteria"])
    assert [f["section"] for f in view["findings"]] == ["Grammar"]
    assert view["header_flow"] == [
        {"slide_id": "s1", "n": 1, "text": "Cost fell", "kind": "claim"},
        {"slide_id": "s2", "n": 2, "text": "Rollout", "kind": "section_header"},
    ]
    assert view["header_notes"] == ["s2: reads as a topic label"]
    assert view["approval"]["approved"] is False
    assert [p["n"] for p in view["previews"]] == [1, 2]
    assert view["previews"][0]["url"] == "/api/runs/r1/preview/1"
    assert view["previews"][0]["slide_id"] == "s1"
    # Nothing in the view ticks a human check.
    assert all(set(c) == {"n", "title", "steps"} for c in view["human_checks"])


def test_final_view_falls_back_to_the_recorded_result_when_it_cannot_recompute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots, orch = _rendered_run(tmp_path)
    orch.record_final_assessment(
        canonical_pptx_digest(orch.paths.deck_pptx), False, failed=["No QA findings"]
    )

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("fonts missing")

    monkeypatch.setattr(review, "_final_assessment", boom)
    view = review.final_view(roots, "r1")
    assert view["passes"] is False
    assert "fonts missing" in view["criteria"][0]["detail"]
    assert "No QA findings" in view["criteria"][0]["detail"]


def test_final_view_flags_a_deck_changed_since_the_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots, orch = _rendered_run(tmp_path)
    _stub_assessment(monkeypatch, orch)
    orch.record_final_assessment("0" * 64, True)
    view = review.final_view(roots, "r1")
    assert view["passes"] is False
    assert any(c["label"] == "Final audit is current" for c in view["criteria"])


# --------------------------------------------------------------------------- previews


def test_preview_file_serves_only_final_pngs_by_number(tmp_path: Path) -> None:
    roots, orch = _rendered_run(tmp_path)
    folder = orch.paths.previews / "final"
    folder.mkdir(parents=True)
    (folder / "deck-01.png").write_bytes(b"one")
    (orch.paths.previews / "secret-1.png").write_bytes(b"secret")
    (orch.paths.root / "deck-3.png").write_bytes(b"outside")

    assert review.preview_file(roots, "r1", 1) == (b"one", "image/png")
    for bad in (0, -1, 2, 3, True, "1", "../x", 1.0):
        with pytest.raises(UIError) as refused:
            review.preview_file(roots, "r1", bad)  # type: ignore[arg-type]
        assert refused.value.status == 404
    with pytest.raises(UIError) as unknown:
        review.preview_file(roots, "nope", 1)
    assert unknown.value.status == 404


# --------------------------------------------------------------------------- open copy


def test_open_deck_copy_copies_to_the_desktop_and_opens_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots, orch = _rendered_run(tmp_path)
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    opened: list[Path] = []
    monkeypatch.setattr(review, "_open_with_os", opened.append)

    result = review.open_deck_copy(roots, "r1")

    target = home / "Desktop" / "r1-check.pptx"
    assert result == {"path": str(target)}
    assert target.read_bytes() == orch.paths.deck_pptx.read_bytes()
    assert opened == [target]


def test_open_deck_copy_falls_back_to_home_and_needs_a_deck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots, _orch = _rendered_run(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(review, "_open_with_os", lambda path: None)
    assert review.open_deck_copy(roots, "r1")["path"] == str(home / "r1-check.pptx")

    runs_root, knowledge = make_gate3_run(tmp_path / "other")
    with pytest.raises(UIError) as refused:
        review.open_deck_copy(roots_for(runs_root, knowledge), "r1")
    assert refused.value.status == 409


# --------------------------------------------------------------------------- A7


def test_review_module_cannot_approve() -> None:
    source = (Path(autodeck.__file__).parent / "ui" / "review.py").read_text(encoding="utf-8")
    assert ".approve(" not in source
    assert ".sign_off(" not in source
    assert "ui.approvals" not in source and "import approvals" not in source
