"""The reviewer: the contract, the `review` feedback loop, review-only mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    FINDING,
    FakeModel,
    fake_render,
    finding,
    no_findings,
    read_json,
    report_args,
    report_turn,
    run,
    scripted_qa,
    slide_args,
    text_turn,
    write_turn,
)

from autodeck.design.theme.tokens import DesignTokens

REVIEWER_PRICE = run.Price(10, 40)
REVIEW_COST = (1000 * 10 + 200 * 40) / 1e6  # report_turn's default usage


@pytest.fixture
def parts(bench_dir: Path, tmp_path: Path) -> dict[str, Any]:
    return {
        "case": run.load_case(bench_dir / "cases" / "c1.yaml"),
        "concept": run.load_concept(bench_dir / "concepts" / "ticket.yaml"),
        "tokens": DesignTokens.load(run.DEFAULT_TOKENS_PATH),
        "out": tmp_path / "out",
    }


def make_trial(
    parts: dict[str, Any],
    designer: FakeModel,
    reviewer_model: FakeModel,
    *,
    qa: Any = no_findings,
    ledger: Any = None,
) -> Any:
    ledger = ledger or run.Ledger(100.0)
    reviewer = run.Reviewer(
        "fake:rev", reviewer_model, "REVIEW SYS", REVIEWER_PRICE, ledger, reasoning="medium"
    )
    ctx = run.TrialContext(
        model_name="fake:cheap",
        model=designer,
        system="SYS",
        tokens=parts["tokens"],
        price=run.Price(3, 15),
        ledger=ledger,
        attempts=4,
        out=parts["out"],
        qa=qa,
        render=fake_render([]),
        reviewer=reviewer,
    )
    spec = run.TrialSpec("fake:cheap", parts["case"], parts["concept"], "review", 1)
    return run.Trial(ctx, spec)


# -- the reviewer's user message and image -----------------------------------------------


def test_review_user_text_is_plain_and_stable(parts: dict[str, Any]) -> None:
    case = parts["case"].model_copy(update={"notes": "Deliberately the densest slide."})
    text = run.build_review_user_text(case, parts["concept"])
    assert text.startswith("# Slide brief\nTalking header: Quantisation alone cuts")
    assert "Intent (what the slide must make the audience conclude):" in text
    assert "- 38%: lower serving cost" in text and "Chart (bar)" in text
    # notes come after the content, under their own label
    assert text.index("Notes from the brief's author:\nDeliberately") > text.index("Emphasised")
    assert text.index("Notes from") < text.index("# Design concept")
    assert "Name: Ticket" in text and "- One red block carries the number." in text
    assert "- accent1 #E4002B: the price ticket" in text
    assert "- lt1 #FFF8E1" in text
    assert text.rstrip().endswith("call report.")
    assert "Notes from" not in run.build_review_user_text(parts["case"], parts["concept"])


def test_review_user_text_without_a_concept(parts: dict[str, Any], bench_dir: Path) -> None:
    none = run.load_concept(bench_dir / "concepts" / "none.yaml")
    text = run.build_review_user_text(parts["case"], none)
    assert "# Design concept\nNone given." in text


def test_review_image_is_one_png_1600_wide(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "wide.png"
    Image.new("RGB", (2001, 1125), (10, 20, 30)).save(path)
    image, sent = run.review_image(path)
    assert image.data.startswith(b"\x89PNG") and image.media_type == "image/png"
    assert sent["width"] == 1600 and sent["height"] == 900


def test_the_reviewer_gets_system_text_and_one_image_message(parts: dict[str, Any]) -> None:
    reviewer_model = FakeModel([report_turn()])
    trial = make_trial(parts, FakeModel([write_turn()]), reviewer_model)
    trial.run()
    first = reviewer_model.calls[0]
    assert len(first) == 1 and first[0].role == "user" and len(first[0].images) == 1
    assert "# Slide brief" in first[0].content


# -- the loop ------------------------------------------------------------------------------


def test_pass_stops_and_records_the_review(parts: dict[str, Any]) -> None:
    designer = FakeModel([write_turn()])
    trial = make_trial(parts, designer, FakeModel([report_turn(report_args("pass"))]))
    record = trial.run()
    assert record["status"] == "clean" and record["revision"]["state"] == "not_needed"
    review = record["review"]
    assert review["first_verdict"] == "pass" and not review["revised"]
    assert review["second_verdict"] is None
    assert len(designer.calls) == 1
    d = trial.dir
    saved = read_json(d / "review-1.json")
    assert saved["verdict"] == "pass" and saved["raw_tool_call"]["name"] == "report"
    assert saved["image_file"] == "slide.png" and saved["image_sent"]["width"] == 1600
    assert not (d / "review-2.json").exists()
    transcript = read_json(d / "review-1.transcript.json")
    assert transcript["messages"][0]["images"] == ["slide.png"]
    assert "base64" not in json.dumps(transcript)


def test_revise_then_clean_revision_then_pass(parts: dict[str, Any]) -> None:
    findings = [finding("blocking", n=1), finding("minor", "footer", 2)]
    designer = FakeModel([write_turn(), write_turn(slide_args("Revised"), call_id="c2")])
    reviewer_model = FakeModel(
        [
            report_turn(report_args("revise", findings, "A rule strikes through a word.")),
            report_turn(report_args("pass"), call_id="rep_2"),
        ]
    )
    trial = make_trial(parts, designer, reviewer_model)
    record = trial.run()
    assert record["status"] == "clean" and record["revision"]["state"] == "revised"
    review = record["review"]
    assert review["first_verdict"] == "revise" and review["revised"]
    assert review["revision_clean"] and review["second_verdict"] == "pass"
    # the designer got the findings verbatim, the minor one marked optional, and no image
    sent = designer.calls[1][-1]
    assert sent.role == "user" and not getattr(sent, "images", ())
    assert "A rule runs through the word 1." in sent.content
    assert "Fix: Move the rule below the word 1." in sent.content
    blocking_at = sent.content.index("BLOCKING")
    assert blocking_at < sent.content.index("MINOR findings (optional)")
    assert sent.content.index("word 2.") > sent.content.index("MINOR")
    assert "A rule strikes through a word." in sent.content
    # both renders, both reports; the second review saw the revised render
    d = trial.dir
    for name in ("slide.before.png", "slide.png", "review-1.json", "review-2.json"):
        assert (d / name).is_file(), name
    assert read_json(d / "review-1.transcript.json")["messages"][0]["images"] == [
        "slide.before.png"
    ]
    assert read_json(d / "review-2.transcript.json")["messages"][0]["images"] == ["slide.png"]
    assert len(reviewer_model.calls) == 2
    # no third round: exactly one revision, one final review
    assert record["model_calls"] == 2
    # cost kept apart
    assert record["cost_usd"] == pytest.approx(2 * (100 * 3 + 50 * 15) / 1e6)
    assert record["review_cost_usd"] == pytest.approx(2 * REVIEW_COST)
    assert record["total_cost_usd"] == pytest.approx(record["cost_usd"] + 2 * REVIEW_COST)


def test_second_review_may_still_say_revise_and_the_loop_stops(parts: dict[str, Any]) -> None:
    designer = FakeModel([write_turn(), write_turn(slide_args("Rev"), call_id="c2")])
    reviewer_model = FakeModel(
        [
            report_turn(report_args("revise", [finding()])),
            report_turn(report_args("revise", [finding(n=2)]), call_id="rep_2"),
        ]
    )
    record = make_trial(parts, designer, reviewer_model).run()
    assert record["review"]["second_verdict"] == "revise"
    assert record["model_calls"] == 2 and len(reviewer_model.calls) == 2


def test_revision_that_fails_qa_falls_back_and_is_not_reviewed_again(
    parts: dict[str, Any],
) -> None:
    designer = FakeModel(
        [
            write_turn(),
            write_turn(slide_args("Worse 1"), call_id="r1"),
            write_turn(slide_args("Worse 2"), call_id="r2"),
        ]
    )
    reviewer_model = FakeModel([report_turn(report_args("revise", [finding()]))])
    trial = make_trial(
        parts, designer, reviewer_model, qa=scripted_qa([[], [FINDING], [FINDING]])
    )
    record = trial.run()
    assert record["revision"]["state"] == "failed" and record["status"] == "clean"
    assert record["review"]["revised"] is False and record["review"]["second"] is None
    assert read_json(trial.dir / "slide.json")["blocks"][0]["text"] == "Headline"
    assert not (trial.dir / "slide.before.png").exists()
    assert record["model_calls"] == 3 and len(reviewer_model.calls) == 1
    assert read_json(trial.dir / "review-1.transcript.json")["messages"][0]["images"] == [
        "slide.png"
    ]


def test_designer_answering_in_prose_keeps_the_original(parts: dict[str, Any]) -> None:
    designer = FakeModel([write_turn(), text_turn("I disagree.")])
    reviewer_model = FakeModel([report_turn(report_args("revise", [finding()]))])
    record = make_trial(parts, designer, reviewer_model).run()
    assert record["revision"]["state"] == "kept_original"
    assert record["review"]["second_verdict"] is None and len(reviewer_model.calls) == 1


def test_revise_with_only_minor_findings_counts_as_a_pass(parts: dict[str, Any]) -> None:
    designer = FakeModel([write_turn()])
    reviewer_model = FakeModel([report_turn(report_args("revise", [finding("minor")]))])
    trial = make_trial(parts, designer, reviewer_model)
    record = trial.run()
    first = record["review"]["first"]
    assert first["verdict"] == "pass" and first["raw_verdict"] == "revise"
    assert first["downgraded"] is True and first["n_minor"] == 1 and first["n_blocking"] == 0
    assert len(designer.calls) == 1 and record["revision"]["state"] == "not_needed"
    saved = read_json(trial.dir / "review-1.json")
    assert saved["downgraded"] and saved["raw_verdict"] == "revise"


def test_no_tool_call_is_nudged_once_then_recorded_as_failed(parts: dict[str, Any]) -> None:
    designer = FakeModel([write_turn()])
    reviewer_model = FakeModel([text_turn("Looks nice."), text_turn("Really nice.")])
    trial = make_trial(parts, designer, reviewer_model)
    record = trial.run()
    first = record["review"]["first"]
    assert first["status"] == "failed" and first["verdict"] is None
    assert "did not call report" in first["error"] and first["nudged"]
    assert len(reviewer_model.calls) == 2
    nudge = reviewer_model.calls[1][-1]
    assert nudge.role == "user" and "report" in nudge.content
    assert record["status"] == "clean" and len(designer.calls) == 1  # not a pass, no revision
    assert record["review_cost_usd"] > 0  # failed calls still cost money


def test_one_nudge_is_enough_for_the_reviewer(parts: dict[str, Any]) -> None:
    reviewer_model = FakeModel([text_turn("Hmm."), report_turn()])
    record = make_trial(parts, FakeModel([write_turn()]), reviewer_model).run()
    assert record["review"]["first"]["status"] == "ok"
    assert record["review"]["first"]["nudged"] is True


def test_invalid_report_arguments_are_nudged_with_the_reason(parts: dict[str, Any]) -> None:
    bad = {"verdict": "maybe", "findings": [], "summary": ""}
    reviewer_model = FakeModel([report_turn(bad), report_turn()])
    record = make_trial(parts, FakeModel([write_turn()]), reviewer_model).run()
    assert record["review"]["first"]["status"] == "ok"
    assert reviewer_model.calls[1][-1].role == "tool"
    assert "verdict" in reviewer_model.calls[1][-1].content


def test_budget_guard_stops_before_a_review_call(parts: dict[str, Any]) -> None:
    ledger = run.Ledger(0.0004)  # spent after the designer's one call
    designer = FakeModel([write_turn()])
    reviewer_model = FakeModel([report_turn()])
    record = make_trial(parts, designer, reviewer_model, ledger=ledger).run()
    assert record["status"] == "clean"
    assert record["review"]["first"]["status"] == "budget_stopped"
    assert len(reviewer_model.calls) == 0 and len(reviewer_model.replies) == 1
    assert record["review_cost_usd"] == 0.0


def test_a_reviewer_that_raises_is_a_failed_review_not_a_failed_trial(
    parts: dict[str, Any],
) -> None:
    reviewer_model = FakeModel([RuntimeError("boom sk-abcdefghijklmnop1234")])
    trial = make_trial(parts, FakeModel([write_turn()]), reviewer_model)
    record = trial.run()
    assert record["status"] == "clean"
    first = record["review"]["first"]
    assert first["status"] == "failed" and "sk-abcdef" not in first["error"]


# -- the whole run -------------------------------------------------------------------------


def config(bench_dir: Path, out: Path, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "models": ["fake:cheap"],
        "cases": run.resolve_cases("c1", bench_dir),
        "concepts": run.resolve_concepts("ticket", bench_dir),
        "feedback": ["review"],
        "attempts": 4,
        "budget": 100.0,
        "out": out,
        "bench_dir": bench_dir,
        "prices_path": bench_dir / "prices.yaml",
        "reviewer": "fake:rev",
    }
    base.update(kw)
    return run.RunConfig(**base)


def go(cfg: Any, models: dict[str, FakeModel], log: list[str] | None = None) -> Any:
    sink = log if log is not None else []
    return run.run(
        cfg,
        provider_factory=lambda m: models[m],
        qa=no_findings,
        render=fake_render([]),
        log=sink.append,
    )


def test_review_run_totals_sheets_and_csv(bench_dir: Path, tmp_path: Path) -> None:
    import csv

    out = tmp_path / "out"
    designer = FakeModel([write_turn(), write_turn(slide_args("After"), call_id="c2")])
    reviewer_model = FakeModel(
        [
            report_turn(report_args("revise", [finding(), finding("minor", n=2)], "Strike.")),
            report_turn(report_args("pass"), call_id="rep_2"),
        ]
    )
    summary = go(config(bench_dir, out), {"fake:cheap": designer, "fake:rev": reviewer_model})
    totals = summary["models"]["fake:cheap"]
    designer_cost = 2 * (100 * 3 + 50 * 15) / 1e6
    assert totals["cost_usd"] == pytest.approx(designer_cost)
    assert totals["review_cost_usd"] == pytest.approx(2 * REVIEW_COST)
    assert totals["total_cost_usd"] == pytest.approx(designer_cost + 2 * REVIEW_COST)
    assert totals["reviews"]["first_revise"] == 1 and totals["reviews"]["second_pass"] == 1
    assert totals["reviews"]["revisions"] == 1
    assert summary["budget"]["estimated_spend_usd"] == pytest.approx(
        designer_cost + 2 * REVIEW_COST, rel=1e-3
    )
    assert summary["config"]["reviewer"] == "fake:rev"
    rows = list(csv.DictReader((out / "summary.csv").open()))
    trial_row = rows[0]
    assert trial_row["review_first"] == "revise" and trial_row["review_second"] == "pass"
    assert trial_row["review_revised"] == "1" and trial_row["review_revision_clean"] == "1"
    assert float(rows[-1]["total_cost_usd"]) == pytest.approx(designer_cost + 2 * REVIEW_COST)
    from PIL import Image

    sheet = out / "sheet-reviewed-fake_cheap.png"
    assert sheet.is_file()
    with Image.open(sheet) as image:
        assert image.width > 1800  # two images side by side plus the text column
    assert (out / "sheet-fake_cheap.png").is_file()


def test_review_run_needs_a_reviewer_with_a_price_and_a_prompt(
    bench_dir: Path, tmp_path: Path
) -> None:
    models = {"fake:cheap": FakeModel([]), "fake:rev": FakeModel([])}
    with pytest.raises(run.BenchInputError, match="--reviewer"):
        go(config(bench_dir, tmp_path / "a", reviewer=None), models)
    with pytest.raises(run.BenchInputError, match="no assumed price"):
        go(config(bench_dir, tmp_path / "b", reviewer="fake:nopriceyet"), models)
    (bench_dir / "prompts" / "review.md").unlink()
    with pytest.raises(run.BenchInputError, match="reviewer prompt"):
        go(config(bench_dir, tmp_path / "c"), models)


def test_same_model_as_designer_is_refused_unless_allowed(
    bench_dir: Path, tmp_path: Path
) -> None:
    model = FakeModel([write_turn(), report_turn()])
    with pytest.raises(run.BenchInputError, match="allow-self-review"):
        go(config(bench_dir, tmp_path / "a", reviewer="fake:cheap"), {"fake:cheap": model})
    assert model.calls == []
    summary = go(
        config(bench_dir, tmp_path / "b", reviewer="fake:cheap", allow_self_review=True),
        {"fake:cheap": model},
    )
    assert summary["models"]["fake:cheap"]["reviews"]["first_pass"] == 1


def test_budget_guard_in_a_run_reports_skipped_reviews(bench_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    cfg = config(bench_dir, out, budget=0.0004)
    designer = FakeModel([write_turn()])
    reviewer_model = FakeModel([report_turn()])
    log: list[str] = []
    summary = go(cfg, {"fake:cheap": designer, "fake:rev": reviewer_model}, log)
    assert summary["budget"]["guard_tripped"] and summary["budget"]["reviews_skipped"]
    assert reviewer_model.calls == []
    assert any("BUDGET GUARD" in line for line in log)


def test_no_key_in_any_output(
    bench_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-proj-THISISASECRET0123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    out = tmp_path / "out"
    designer = FakeModel([write_turn()])
    reviewer_model = FakeModel(
        [report_turn(report_args("pass", [finding("minor")], f"My key is {secret}."))]
    )
    go(config(bench_dir, out), {"fake:cheap": designer, "fake:rev": reviewer_model})
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".csv", ".md", ".txt"}:
            assert secret not in path.read_text(encoding="utf-8"), path


def test_dry_run_with_a_reviewer_writes_the_prompt(bench_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    cfg = config(
        bench_dir,
        out,
        dry_run=True,
        models=["openai:gpt-5.4-mini"],
        reviewer="openai:gpt-5.6-terra",
    )
    result = run.run(cfg, log=lambda s: None)
    assert result["dry_run"]
    assert (out / "review-system.md").read_text() == "You review one slide. Call report once."
    assert "# Slide brief" in (out / "review-user-sample.md").read_text()


# -- review-only mode ----------------------------------------------------------------------


def make_trial_outputs(bench_dir: Path, out: Path, n: int = 2) -> None:
    cfg = config(
        bench_dir,
        out,
        feedback=["qa"],
        reviewer=None,
        cases=run.resolve_cases("c1,c2", bench_dir)[:n],
    )
    go(cfg, {"fake:cheap": FakeModel([write_turn() for _ in range(n)])})


def review_cfg(bench_dir: Path, items: list[Any], out: Path, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "reviewer": "fake:rev",
        "items": items,
        "budget": 100.0,
        "out": out,
        "bench_dir": bench_dir,
        "prices_path": bench_dir / "prices.yaml",
    }
    base.update(kw)
    return run.ReviewOnlyConfig(**base)


def test_review_only_over_a_directory_of_trial_outputs(bench_dir: Path, tmp_path: Path) -> None:
    import csv

    designs = tmp_path / "designs"
    make_trial_outputs(bench_dir, designs)
    items = run.discover_review_items([designs], bench_dir, log=lambda s: None)
    assert len(items) == 2 and {i.case.id for i in items} == {"c1", "c2"}
    assert all(i.designer_model == "fake:cheap" for i in items)
    out = tmp_path / "rev"
    reviewer_model = FakeModel(
        [
            report_turn(report_args("revise", [finding()], "Strike-through.")),
            report_turn(report_args("pass", [], "Clean."), call_id="rep_2"),
        ]
    )
    summary = run.run_review_only(
        review_cfg(bench_dir, items, out),
        provider_factory=lambda m: reviewer_model,
        log=lambda s: None,
    )
    assert summary["counts"]["pass"] == 1 and summary["counts"]["revise"] == 1
    assert summary["review_cost_usd"] == pytest.approx(2 * REVIEW_COST)
    reviews = sorted((out / "fake_rev").rglob("review.json"))
    assert len(reviews) == 2
    saved = read_json(reviews[0])
    assert saved["raw_tool_call"]["name"] == "report" and saved["image_file"] == "slide.png"
    assert all(p.with_name("review.transcript.json").is_file() for p in reviews)
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert sorted(r["verdict"] for r in rows) == ["pass", "revise"]
    assert (out / "sheet-review-fake_rev.png").is_file()
    # nothing was designed: the first message the reviewer saw is the brief
    assert reviewer_model.calls[0][0].content.startswith("# Slide brief")


def test_review_only_refuses_a_reviewer_that_designed_the_slides(
    bench_dir: Path, tmp_path: Path
) -> None:
    designs = tmp_path / "designs"
    make_trial_outputs(bench_dir, designs, 1)
    items = run.discover_review_items([designs], bench_dir)
    with pytest.raises(run.BenchInputError, match="allow-self-review"):
        run.run_review_only(
            review_cfg(bench_dir, items, tmp_path / "o", reviewer="fake:cheap"),
            provider_factory=lambda m: FakeModel([]),
            log=lambda s: None,
        )


def test_review_only_budget_guard(bench_dir: Path, tmp_path: Path) -> None:
    designs = tmp_path / "designs"
    make_trial_outputs(bench_dir, designs)
    items = run.discover_review_items([designs], bench_dir)
    reviewer_model = FakeModel([report_turn(), report_turn()])
    summary = run.run_review_only(
        review_cfg(bench_dir, items, tmp_path / "o", budget=0.001),
        provider_factory=lambda m: reviewer_model,
        log=lambda s: None,
    )
    assert summary["counts"]["budget_stopped"] == 1 and summary["counts"]["reviewed"] == 2
    assert summary["budget"]["guard_tripped"] and len(reviewer_model.calls) == 1


def test_a_directory_without_case_information_is_an_error(
    bench_dir: Path, tmp_path: Path
) -> None:
    from PIL import Image

    (tmp_path / "lone").mkdir()
    Image.new("RGB", (160, 90)).save(tmp_path / "lone" / "slide.png")
    with pytest.raises(run.BenchInputError, match="cannot be recovered"):
        run.discover_review_items([tmp_path / "lone"], bench_dir)


def test_triples(bench_dir: Path, tmp_path: Path) -> None:
    from PIL import Image

    image = tmp_path / "x.png"
    Image.new("RGB", (160, 90)).save(image)
    item = run.triple_item(f"{image},c1,ticket", bench_dir)
    assert item.case.id == "c1" and item.concept.id == "ticket"
    with pytest.raises(run.BenchInputError):
        run.triple_item(f"{image},c1", bench_dir)


def studio_deck(tmp_path: Path) -> tuple[Path, list[Path]]:
    from PIL import Image

    def slide(n: int) -> dict[str, Any]:
        return {
            "id": f"slide-{n}",
            "blocks": [{"id": "h", "kind": "text", "text": f"Header {n}"}],
            "brief": {
                "header": f"Header {n}",
                "intent": "Make the case.",
                "content": {
                    "points": ["A point"],
                    "figures": [{"value": "65%", "label": "of memory"}],
                    "chart": None,
                },
                "notes": f"Slide {n} is deliberately dense.",
            },
        }

    deck = {
        "id": "deck-x",
        "slides": [slide(1), slide(2)],
        "design_concept": None,
        "design_system": {
            "id": "control-room",
            "palette": {"dk1": "0B1117", "lt1": "F2F5F4", "accent1": "62F6B5"},
        },
    }
    path = tmp_path / "current.json"
    path.write_text(json.dumps(deck), encoding="utf-8")
    images = []
    for n in (1, 2):
        png = tmp_path / f"final-s{n}.png"
        Image.new("RGB", (2001, 1125), (20, 30, 40)).save(png)
        images.append(png)
    return path, images


def test_review_only_over_a_converted_studio_deck(bench_dir: Path, tmp_path: Path) -> None:
    deck, images = studio_deck(tmp_path)
    made = run.convert_studio_deck(deck, images, tmp_path / "conv")
    assert len(made) == 2 and (made[0] / "slide.png").is_file()
    assert (made[0] / "slide.json").is_file() and (made[0] / "review-input.json").is_file()
    items = run.discover_review_items([tmp_path / "conv"], bench_dir)
    assert [i.case.title for i in items] == ["Header 1", "Header 2"]
    assert items[0].concept.id == "control-room" and items[0].concept.palette["accent1"]
    reviewer_model = FakeModel([report_turn(), report_turn()])
    run.run_review_only(
        review_cfg(bench_dir, items, tmp_path / "rev"),
        provider_factory=lambda m: reviewer_model,
        log=lambda s: None,
    )
    text = reviewer_model.calls[0][0].content
    assert "Slide 1 is deliberately dense." in text  # the slide brief's own notes
    assert "Name: control-room" in text and "accent1 #62F6B5" in text
    assert reviewer_model.calls[0][0].images[0].data.startswith(b"\x89PNG")
    with pytest.raises(run.BenchInputError, match="2 slides but 1 images"):
        run.convert_studio_deck(deck, images[:1], tmp_path / "bad")


def test_cli_review_only_requires_a_reviewer(
    bench_dir: Path, tmp_path: Path, capsys: Any
) -> None:
    code = run.main(
        [
            "--review-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "o"),
            "--bench-dir",
            str(bench_dir),
        ]
    )
    assert code == 2 and "--reviewer" in capsys.readouterr().err
