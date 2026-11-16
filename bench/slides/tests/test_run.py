"""The whole run: budget guard, prices, dry run, summaries, contact sheets."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    FINDING,
    FakeModel,
    fake_render,
    no_findings,
    read_json,
    run,
    scripted_qa,
    text_turn,
    write_turn,
)


def config(bench_dir: Path, out: Path, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "models": ["fake:cheap"],
        "cases": run.resolve_cases("all", bench_dir),
        "concepts": run.resolve_concepts("none", bench_dir),
        "feedback": ["qa"],
        "attempts": 4,
        "budget": 100.0,
        "out": out,
        "bench_dir": bench_dir,
        "prices_path": bench_dir / "prices.yaml",
    }
    base.update(kw)
    return run.RunConfig(**base)


def go(cfg: Any, model: FakeModel, qa: Any = no_findings, log: list[str] | None = None) -> Any:
    sink = log if log is not None else []
    return run.run(
        cfg,
        provider_factory=lambda m: model,
        qa=qa,
        render=fake_render([]),
        log=sink.append,
    )


def test_summary_json_csv_and_sheet(bench_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    cfg = config(bench_dir, out, concepts=run.resolve_concepts("none,ticket", bench_dir))
    model = FakeModel([write_turn() for _ in range(4)])
    summary = go(cfg, model)
    totals = summary["models"]["fake:cheap"]
    assert totals["trials"] == 4 and totals["clean_rate"] == 1.0
    assert totals["input_tokens"] == 400 and totals["output_tokens"] == 200
    assert totals["mean_element_counts"]["text"] == 1
    assert totals["reasoning"] == ["default"]
    assert totals["cost_usd"] == pytest.approx(4 * (100 * 3 + 50 * 15) / 1e6)
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert [r["row_type"] for r in rows] == ["trial"] * 4 + ["model_total"]
    assert rows[-1]["clean_rate"] == "1.0" and rows[-1]["model"] == "fake:cheap"
    assert read_json(out / "summary.json")["models"]["fake:cheap"]["trials"] == 4
    sheet = out / "sheet-fake_cheap.png"
    assert sheet.is_file()
    from PIL import Image

    with Image.open(sheet) as image:
        assert image.width > 1000 and image.height > 500
    for trial in (out / "fake_cheap").rglob("trial.json"):
        assert read_json(trial)["reasoning"] == "default"


def test_unclean_and_failed_cells_render_text(bench_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    cfg = config(bench_dir, out, attempts=1)
    model = FakeModel([write_turn(), RuntimeError("provider exploded")])
    summary = go(cfg, model, qa=scripted_qa([[FINDING]]))
    statuses = sorted(t["status"] for t in summary["trials"])
    assert statuses == ["failed", "unclean"]  # the failure did not stop the run
    assert summary["models"]["fake:cheap"]["clean_rate"] == 0.0
    assert (out / "sheet-fake_cheap.png").is_file()
    csv_text = (out / "summary.csv").read_text()
    assert "text_fit" in csv_text and "provider exploded" in csv_text


def test_a_failing_trial_does_not_stop_the_run(bench_dir: Path, tmp_path: Path) -> None:
    cfg = config(bench_dir, tmp_path / "out")
    model = FakeModel([RuntimeError("network down"), write_turn()])
    summary = go(cfg, model)
    assert [t["status"] for t in summary["trials"]] == ["failed", "clean"]


def test_budget_guard_skips_remaining_trials_and_reports(
    bench_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    cfg = config(bench_dir, out, models=["fake:dear"], budget=0.01)
    model = FakeModel([write_turn()])  # one call costs far more than the budget
    log: list[str] = []
    summary = go(cfg, model, log=log)
    assert [t["status"] for t in summary["trials"]] == ["clean", "skipped"]
    budget = summary["budget"]
    assert budget["guard_tripped"] and len(budget["trials_not_started"]) == 1
    assert "c2" in budget["trials_not_started"][0]
    assert any("BUDGET GUARD" in line and "1 trials not started" in line for line in log)
    assert len(model.calls) == 1


def test_budget_guard_stops_mid_trial_before_a_call(bench_dir: Path, tmp_path: Path) -> None:
    cfg = config(bench_dir, tmp_path / "out", models=["fake:dear"], budget=0.01)
    model = FakeModel([write_turn()])
    summary = go(cfg, model, qa=scripted_qa([[FINDING]]))
    first = summary["trials"][0]
    assert first["status"] == "budget_stopped"
    assert summary["budget"]["trials_stopped_mid_trial"]
    assert len(model.calls) == 1


def test_unpriced_model_is_refused(bench_dir: Path, tmp_path: Path) -> None:
    cfg = config(bench_dir, tmp_path / "out", models=["fake:unknown"])
    model = FakeModel([])
    with pytest.raises(run.BenchInputError, match="no assumed price"):
        go(cfg, model)
    assert model.calls == []
    assert not (tmp_path / "out" / "summary.json").exists()


def test_unpriced_model_allowed_with_flag_is_flagged(bench_dir: Path, tmp_path: Path) -> None:
    cfg = config(bench_dir, tmp_path / "out", models=["fake:unknown"], allow_unpriced=True)
    log: list[str] = []
    summary = go(cfg, FakeModel([write_turn(), write_turn()]), log=log)
    assert any("unpriced" in line for line in log)
    assert all(t["priced"] is False and t["cost_usd"] == 0 for t in summary["trials"])


def test_dry_run_writes_requests_and_calls_nothing(
    bench_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # a dry run needs no key
    out = tmp_path / "out"
    cfg = config(
        bench_dir,
        out,
        models=["openai:gpt-5.4-mini", "openai:gpt-5.6-luna"],
        allow_unpriced=True,
        concepts=run.resolve_concepts("none,ticket", bench_dir),
        dry_run=True,
    )

    def never(model: str) -> Any:
        raise AssertionError("a model was constructed for a call")

    run.run(cfg, provider_factory=never, log=lambda _m: None)
    files = list(out.rglob("request.json"))
    assert len(files) == 2 * 2 * 2
    chat = read_json(out / "openai_gpt-5.4-mini/c1/ticket/qa/r1/request.json")
    assert chat["url"].endswith("/chat/completions")
    system = chat["body"]["messages"][0]["content"]
    assert "#FFF8E1" in system and "the price ticket" in system  # palette and role shown
    assert chat["body"]["tools"][0]["function"]["name"] == "write_slide"
    resp = read_json(out / "openai_gpt-5.6-luna/c1/none/qa/r1/request.json")
    assert resp["url"].endswith("/responses") and resp["body"]["reasoning"] == {
        "effort": "medium"
    }
    assert not (out / "summary.json").exists()
    blob = "".join(p.read_text() for p in out.rglob("*.json"))
    assert "dry-run" not in blob and "authorization" not in blob.lower()


def test_reasoning_is_recorded_for_responses_models(bench_dir: Path, tmp_path: Path) -> None:
    (bench_dir / "prices.yaml").write_text(
        'models:\n  "openai:gpt-5.6-luna": {input: 5, output: 25}\n', encoding="utf-8"
    )
    cfg = config(bench_dir, tmp_path / "out", models=["openai:gpt-5.6-luna"], reasoning="high")
    summary = go(cfg, FakeModel([write_turn(), write_turn()]))
    assert all(t["reasoning"] == "high" for t in summary["trials"])
    assert summary["config"]["reasoning_by_model"] == {"openai:gpt-5.6-luna": "high"}
    assert summary["config"]["endpoint_by_model"] == {"openai:gpt-5.6-luna": "responses"}


def test_skip_existing_reuses_finished_trials_and_counts_their_cost(
    bench_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    go(config(bench_dir, out), FakeModel([write_turn(), write_turn()]))
    again = FakeModel([])
    summary = go(config(bench_dir, out, skip_existing=True), again)
    assert again.calls == [] and summary["models"]["fake:cheap"]["trials"] == 2
    assert summary["budget"]["estimated_spend_usd"] > 0


def test_nudge_failure_is_a_failed_row(bench_dir: Path, tmp_path: Path) -> None:
    cfg = config(bench_dir, tmp_path / "out", cases=run.resolve_cases("c1", bench_dir))
    summary = go(cfg, FakeModel([text_turn("prose"), text_turn("more prose")]))
    assert summary["trials"][0]["status"] == "failed"


def test_no_key_in_any_output(
    bench_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-test-0123456789abcdefSECRET"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    cfg = config(bench_dir, tmp_path / "out", cases=run.resolve_cases("c1", bench_dir))
    go(cfg, FakeModel([RuntimeError(f"401 for key {secret}")]))
    for path in (tmp_path / "out").rglob("*"):
        if path.is_file() and path.suffix in {".json", ".csv", ".txt", ".md"}:
            assert secret not in path.read_text(), path
