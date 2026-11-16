"""Shared fixtures: `run.py` loaded by path, a stand-in bench directory, a fake model."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from autodeck.providers.base import AssistantTurn, Message, ToolCall, ToolSpec, Usage

BENCH = Path(__file__).resolve().parents[1]


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("slide_bench_run", BENCH / "run.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["slide_bench_run"] = module
    spec.loader.exec_module(module)
    return module


run = _load()


@pytest.fixture(scope="session")
def bench_run() -> Any:
    return run


CASE_YAML = """\
id: c1
title: Quantisation alone cuts serving cost by 38%
intent: One technique is the biggest saving.
content:
  points: ["Monthly cost falls from $412k to $255k"]
  figures:
    - {value: "38%", label: "lower serving cost"}
  chart:
    kind: bar
    categories: ["Before", "After"]
    series:
      - {name: "Monthly cost ($k)", values: [412, 255]}
    emphasis: ["After"]
notes: ""
"""

CONCEPT_NONE = "id: none\nname: None\nconcept: ''\nrules: []\npalette: {}\nroles: {}\n"
CONCEPT_TICKET = """\
id: ticket
name: Ticket
concept: A shelf ticket.
rules: ["One red block carries the number."]
palette:
  lt1: "#FFF8E1"
  accent1: "#E4002B"
roles:
  accent1: "the price ticket"
"""

PRICES = """\
models:
  "fake:cheap": {input: 3, output: 15}
  "fake:dear": {input: 1000, output: 1000}
  "openai:gpt-5.4-mini": {input: 3, output: 15}
  "openai:gpt-5.6-terra": {input: 12, output: 60}
  "fake:rev": {input: 10, output: 40}
  "fake:revdear": {input: 100000, output: 100000}
"""

REVIEW_PROMPT = "You review one slide. Call report once."


@pytest.fixture
def bench_dir(tmp_path: Path) -> Path:
    root = tmp_path / "bench"
    (root / "prompts").mkdir(parents=True)
    (root / "cases").mkdir()
    (root / "concepts").mkdir()
    (root / "prompts" / "slide.md").write_text(
        "SYSTEM\n{{MASTER}}\n{{PALETTE}}\n{{VOCABULARY}}\n", encoding="utf-8"
    )
    (root / "cases" / "c1.yaml").write_text(CASE_YAML, encoding="utf-8")
    (root / "cases" / "c2.yaml").write_text(
        CASE_YAML.replace("id: c1", "id: c2"), encoding="utf-8"
    )
    (root / "concepts" / "none.yaml").write_text(CONCEPT_NONE, encoding="utf-8")
    (root / "concepts" / "ticket.yaml").write_text(CONCEPT_TICKET, encoding="utf-8")
    (root / "prompts" / "review.md").write_text(REVIEW_PROMPT, encoding="utf-8")
    (root / "prices.yaml").write_text(PRICES, encoding="utf-8")
    return root


def slide_args(title: str = "Headline", **layout: Any) -> dict[str, Any]:
    """Arguments of one valid write_slide call (one text block, one text element)."""
    return {
        "slide": {
            "id": "whatever",
            "blocks": [{"id": "t", "kind": "text", "text": title}],
            "layout": {
                "elements": [
                    {
                        "type": "text",
                        "block_id": "t",
                        "frame": {"x": 5, "y": 5, "w": 90, "h": 20},
                        "role": "title",
                        **layout,
                    }
                ]
            },
        }
    }


def write_turn(
    args: dict[str, Any] | None = None,
    *,
    usage: tuple[int, int] = (100, 50),
    call_id: str = "call_1",
    text: str = "",
) -> AssistantTurn:
    calls = [ToolCall(id=call_id, name="write_slide", arguments=args or slide_args())]
    return AssistantTurn(text=text, tool_calls=calls, usage=Usage(*usage))


def text_turn(text: str = "DONE", usage: tuple[int, int] = (100, 5)) -> AssistantTurn:
    return AssistantTurn(text=text, usage=Usage(*usage))


class FakeModel:
    """Same `converse` interface as a provider; replies are scripted, calls are recorded."""

    def __init__(self, replies: list[AssistantTurn | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[list[Message]] = []

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn:
        self.calls.append(list(messages))
        if not self.replies:
            raise AssertionError("the fake model was called more often than scripted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def fake_render(calls: list[Any] | None = None) -> Any:
    from PIL import Image

    def render(slide: Any, tokens: Any, *, pptx_path: Path, png_path: Path) -> str:
        if calls is not None:
            calls.append(slide)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        pptx_path.write_bytes(b"pptx")
        shade = 40 * (len(calls) if calls is not None else 1)
        Image.new("RGB", (160, 90), (shade, 120, 200)).save(png_path)
        return ""

    return render


def no_findings(slide: Any, tokens: Any) -> list[dict[str, str]]:
    return []


def scripted_qa(results: list[list[dict[str, str]]]) -> Any:
    queue = list(results)

    def qa(slide: Any, tokens: Any) -> list[dict[str, str]]:
        return queue.pop(0) if queue else []

    return qa


FINDING = {"block": "t", "check": "text_fit", "message": "needs 90pt of height, box has 50pt"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def report_args(
    verdict: str = "pass",
    findings: list[dict[str, str]] | None = None,
    summary: str = "Fine.",
) -> dict[str, Any]:
    return {"verdict": verdict, "findings": findings or [], "summary": summary}


def finding(severity: str = "blocking", where: str = "title", n: int = 1) -> dict[str, str]:
    return {
        "severity": severity,
        "where": f"{where} {n}",
        "problem": f"A rule runs through the word {n}.",
        "fix": f"Move the rule below the word {n}.",
    }


def report_turn(
    args: dict[str, Any] | None = None,
    *,
    usage: tuple[int, int] = (1000, 200),
    call_id: str = "rep_1",
) -> AssistantTurn:
    calls = [ToolCall(id=call_id, name="report", arguments=args or report_args())]
    return AssistantTurn(tool_calls=calls, usage=Usage(*usage))
