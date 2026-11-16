"""One trial, with a fake model: no network, no LibreOffice."""

from __future__ import annotations

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
    slide_args,
    text_turn,
    write_turn,
)

from autodeck.design.theme.tokens import DesignTokens


@pytest.fixture
def parts(bench_dir: Path, tmp_path: Path) -> dict[str, Any]:
    case = run.load_case(bench_dir / "cases" / "c1.yaml")
    concept = run.load_concept(bench_dir / "concepts" / "none.yaml")
    return {
        "case": case,
        "concept": concept,
        "tokens": DesignTokens.load(run.DEFAULT_TOKENS_PATH),
        "out": tmp_path / "out",
    }


def make_trial(
    parts: dict[str, Any],
    model: FakeModel,
    *,
    feedback: str = "qa",
    attempts: int = 4,
    qa: Any = no_findings,
    render_calls: list[Any] | None = None,
    ledger: Any = None,
    price: Any = "default",
) -> Any:
    ctx = run.TrialContext(
        model_name="fake:cheap",
        model=model,
        system="SYS",
        tokens=parts["tokens"],
        price=run.Price(3, 15) if price == "default" else price,
        ledger=ledger or run.Ledger(100.0),
        attempts=attempts,
        out=parts["out"],
        qa=qa,
        render=fake_render(render_calls if render_calls is not None else []),
    )
    spec = run.TrialSpec("fake:cheap", parts["case"], parts["concept"], feedback, 1)
    return run.Trial(ctx, spec)


def test_clean_first_attempt(parts: dict[str, Any]) -> None:
    model = FakeModel([write_turn()])
    trial = make_trial(parts, model)
    record = trial.run()
    assert record["status"] == "clean" and record["clean"]
    assert record["attempts_used"] == 1 and record["model_calls"] == 1
    assert record["input_tokens"] == 100 and record["output_tokens"] == 50
    assert record["cost_usd"] == pytest.approx((100 * 3 + 50 * 15) / 1e6)
    assert record["element_counts"]["text"] == 1
    d = trial.dir
    for name in ("slide.json", "slide.png", "trial.json", "transcript.json", "slide.pptx"):
        assert (d / name).is_file(), name
    # the slide id is the case id, whatever the model wrote
    assert read_json(d / "slide.json")["id"] == "c1"


def test_validation_error_is_fed_back_and_corrected(parts: dict[str, Any]) -> None:
    bad = {"slide": {"id": "x", "blocks": [{"id": "t", "kind": "text"}]}}
    model = FakeModel([write_turn(bad), write_turn()])
    record = make_trial(parts, model).run()
    assert record["status"] == "clean" and record["attempts_used"] == 2
    assert record["attempts"][0]["outcome"] == "validation_error"
    tool_msg = model.calls[1][-1]
    assert tool_msg.role == "tool" and tool_msg.tool_call_id == "call_1"
    assert "rejected" in tool_msg.content and "slide.blocks" in tool_msg.content


def test_invalid_json_arguments_are_fed_back(parts: dict[str, Any]) -> None:
    model = FakeModel([write_turn({"__invalid__": "{oops"}), write_turn()])
    record = make_trial(parts, model).run()
    assert record["status"] == "clean"
    assert "not valid JSON" in model.calls[1][-1].content


def test_qa_findings_are_fed_back_and_corrected(parts: dict[str, Any]) -> None:
    model = FakeModel([write_turn(), write_turn()])
    record = make_trial(parts, model, qa=scripted_qa([[FINDING], []])).run()
    assert record["status"] == "clean" and record["attempts_used"] == 2
    assert record["attempts"][0]["findings"] == [FINDING]
    assert "[text_fit] t: needs 90pt" in model.calls[1][-1].content


def test_attempts_exhausted_is_unclean_with_findings_and_no_render(
    parts: dict[str, Any],
) -> None:
    renders: list[Any] = []
    model = FakeModel([write_turn() for _ in range(3)])
    trial = make_trial(
        parts, model, attempts=3, qa=scripted_qa([[FINDING]] * 3), render_calls=renders
    )
    record = trial.run()
    assert record["status"] == "unclean" and not record["clean"]
    assert record["attempts_used"] == 3 and record["findings"] == [FINDING]
    assert renders == [] and not (trial.dir / "slide.png").exists()
    assert (trial.dir / "slide.json").is_file()  # the last valid slide is kept for inspection


def test_model_not_calling_the_tool_gets_one_nudge_then_fails(parts: dict[str, Any]) -> None:
    model = FakeModel([text_turn("I would use a blue bar."), text_turn("Still prose.")])
    record = make_trial(parts, model).run()
    assert record["status"] == "failed" and "did not call write_slide" in record["error"]
    assert record["model_calls"] == 2
    nudge = model.calls[1][-1]
    assert nudge.role == "user" and "write_slide" in nudge.content


def test_one_nudge_is_enough_when_the_model_then_complies(parts: dict[str, Any]) -> None:
    model = FakeModel([text_turn("Thinking out loud."), write_turn()])
    record = make_trial(parts, model).run()
    assert record["status"] == "clean" and record["attempts"][0]["outcome"] == "no_tool_call"


def test_extra_and_unknown_tool_calls_still_get_a_tool_message(parts: dict[str, Any]) -> None:
    from autodeck.providers.base import AssistantTurn, ToolCall, Usage

    turn = AssistantTurn(
        tool_calls=[
            ToolCall("a", "search", {}),
            ToolCall("b", "write_slide", slide_args()),
            ToolCall("c", "write_slide", slide_args()),
        ],
        usage=Usage(10, 10),
    )
    model = FakeModel([turn])
    trial = make_trial(parts, model)
    trial.run()
    tool_ids = [m.tool_call_id for m in trial.messages if m.role == "tool"]
    assert tool_ids == ["a", "b", "c"]


def test_a_raising_model_is_a_failed_trial_with_scrubbed_error(parts: dict[str, Any]) -> None:
    model = FakeModel([RuntimeError("boom with key sk-abcdefghijklmnop1234")])
    trial = make_trial(parts, model)
    record = trial.run()
    assert record["status"] == "failed"
    assert "boom" in record["error"] and "sk-abcdef" not in record["error"]
    assert (trial.dir / "trial.json").is_file() and (trial.dir / "traceback.txt").is_file()
    assert "sk-abcdef" not in (trial.dir / "traceback.txt").read_text()


# -- visual feedback -------------------------------------------------------------------


def test_visual_revision_accepted(parts: dict[str, Any]) -> None:
    renders: list[Any] = []
    revised = slide_args("Revised headline")
    model = FakeModel([write_turn(), write_turn(revised, call_id="call_2")])
    trial = make_trial(parts, model, feedback="visual", render_calls=renders)
    record = trial.run()
    assert record["status"] == "clean" and record["revision"]["state"] == "revised"
    d = trial.dir
    assert (d / "slide.before.png").is_file() and (d / "slide.png").is_file()
    assert (d / "slide.before.json").is_file()
    assert read_json(d / "slide.json")["blocks"][0]["text"] == "Revised headline"
    assert read_json(d / "slide.before.json")["blocks"][0]["text"] == "Headline"
    sent = model.calls[1][-1]
    assert sent.role == "user" and len(sent.images) == 1 and "rendered slide" in sent.content
    assert sent.images[0].data.startswith(b"\x89PNG")
    # the tool result for the first call precedes the image message
    assert model.calls[1][-2].role == "tool"
    transcript = read_json(d / "transcript.json")
    assert transcript["messages"][3]["images"] == ["slide.before.png"]
    assert record["model_calls"] == 2


def test_visual_done_keeps_the_original(parts: dict[str, Any]) -> None:
    model = FakeModel([write_turn(), text_turn("DONE")])
    trial = make_trial(parts, model, feedback="visual")
    record = trial.run()
    assert record["revision"]["state"] == "kept_original" and record["clean"]
    assert not (trial.dir / "slide.before.png").exists()


def test_visual_revision_that_fails_falls_back_to_the_earlier_slide(
    parts: dict[str, Any],
) -> None:
    renders: list[Any] = []
    model = FakeModel(
        [
            write_turn(),
            write_turn(slide_args("Worse 1"), call_id="r1"),
            write_turn(slide_args("Worse 2"), call_id="r2"),
        ]
    )
    # attempt 1 clean; the revision then fails QA twice (one retry allowed)
    qa = scripted_qa([[], [FINDING], [FINDING]])
    trial = make_trial(parts, model, feedback="visual", qa=qa, render_calls=renders)
    record = trial.run()
    assert record["revision"]["state"] == "failed"
    assert record["status"] == "clean" and record["clean"]
    assert read_json(trial.dir / "slide.json")["blocks"][0]["text"] == "Headline"
    assert (trial.dir / "slide.png").is_file() and not (trial.dir / "slide.before.png").exists()
    assert len(renders) == 1  # the failed revision was never rendered
    assert record["model_calls"] == 3  # one revision, one retry


def test_visual_revision_retry_can_succeed(parts: dict[str, Any]) -> None:
    model = FakeModel(
        [
            write_turn(),
            write_turn(slide_args("Try 1"), call_id="r1"),
            write_turn(slide_args("Try 2"), call_id="r2"),
        ]
    )
    qa = scripted_qa([[], [FINDING], []])
    record = make_trial(parts, model, feedback="visual", qa=qa).run()
    assert record["revision"]["state"] == "revised"


def test_visual_step_respects_the_budget_guard(parts: dict[str, Any]) -> None:
    ledger = run.Ledger(0.0004)  # one call's cost is 0.00098: spent after the first call
    model = FakeModel([write_turn()])
    record = make_trial(parts, model, feedback="visual", ledger=ledger).run()
    assert record["status"] == "clean" and record["revision"]["state"] == "skipped_budget"
    assert record["model_calls"] == 1


def test_qa_mode_never_sends_an_image(parts: dict[str, Any]) -> None:
    model = FakeModel([write_turn()])
    record = make_trial(parts, model, feedback="qa").run()
    assert record["revision"]["state"] == "n/a" and len(model.calls) == 1


# -- the budget guard inside a trial ------------------------------------------------------


def test_budget_guard_stops_before_the_next_call(parts: dict[str, Any]) -> None:
    ledger = run.Ledger(0.0004)
    model = FakeModel([write_turn(), write_turn()])  # the second reply must never be asked for
    trial = make_trial(parts, model, qa=scripted_qa([[FINDING]]), ledger=ledger)
    record = trial.run()
    assert record["status"] == "budget_stopped" and "budget" in record["error"]
    assert len(model.calls) == 1 and len(model.replies) == 1
    assert not (trial.dir / "slide.png").exists()
