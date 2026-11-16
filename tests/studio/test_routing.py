"""Task 23.9: routing a message (`routing.py`): rules where certain, the router model
otherwise, the lead when unsure; the owner's override; never raises."""

from __future__ import annotations

import pytest

from autodeck.studio.bindings import BoundModel
from autodeck.studio.routing import ROUTE_TOOL, decide_route, router_user_text, rule_route
from autodeck.studio.scripted import EXHAUSTED_TEXT, ScriptedModel

RETITLE = "Retitle slide 2 to Quantisation cuts the bill by 38%"


@pytest.mark.parametrize(
    ("text", "route", "reason"),
    [
        (RETITLE, "mechanic", "retitle a slide"),
        ("please rename slide 3 as The ask.", "mechanic", "retitle a slide"),
        ("Change the title of slide 1 to Serving for less", "mechanic", "retitle a slide"),
        ("Swap slides 1 and 3.", "mechanic", "swap two slides"),
        ("switch slide 2 with 4", "mechanic", "swap two slides"),
        ("Move slide 3 to position 1", "mechanic", "move a slide"),
        ("mark slide 2 as decided", "mechanic", "mark a slide"),
        ("Mark slide 4 provisional!", "mechanic", "mark a slide"),
        ("Can you retitle slide 2 to something punchier?", "lead", "a question"),
        ("Retitle slide 2 to X\nand slide 3 to Y", "lead", "several lines"),
        ("x" * 241, "lead", "long message"),
    ],
)
def test_rules_decide_the_certain_cases(text: str, route: str, reason: str) -> None:
    decision = rule_route(text)
    assert decision is not None and (decision.route, decision.reason) == (route, reason)


@pytest.mark.parametrize(
    "text", ["It looks generic.", "Make slide 2 punchier", "Swap the order of the argument"]
)
def test_rules_do_not_guess(text: str) -> None:
    assert rule_route(text) is None


def router(steps: list[dict]) -> tuple[ScriptedModel, BoundModel]:  # type: ignore[type-arg]
    model = ScriptedModel.from_steps(steps, model_ids={"router": "scripted/router"})
    return model, BoundModel("router", "scripted/router", model.for_role("router"), "s")


def test_origin_and_override_go_to_the_lead_without_a_call() -> None:
    model, bound = router([{"role": "router", "text": "unused"}])
    recap = decide_route(RETITLE, origin="recap", request="auto", router=bound, outline="")
    assert (recap.route, recap.by, recap.reason) == (
        "lead",
        "origin",
        "recap turns go to the lead",
    )
    pinned = decide_route(RETITLE, origin="owner", request="lead", router=bound, outline="")
    assert (pinned.route, pinned.by, pinned.reason, pinned.requested) == (
        "lead",
        "override",
        "pinned to the lead",
        "lead",
    )
    ruled = decide_route(RETITLE, origin="owner", request="auto", router=bound, outline="")
    assert (ruled.route, ruled.by, ruled.reason) == ("mechanic", "rule", "retitle a slide")
    assert model.calls == []


def test_the_router_model_decides_what_no_rule_can() -> None:
    model, bound = router(
        [
            {
                "role": "router",
                "tool_calls": [
                    {"name": "route", "arguments": {"to": "mechanic", "reason": "a reword"}}
                ],
            }
        ]
    )
    decision = decide_route(
        "Make slide 2 say 'quarter' not 'Q'",
        origin="owner",
        request="auto",
        router=bound,
        outline="Deck `d`: x (1 slide)",
        system="ROUTER",
    )
    assert (decision.route, decision.by, decision.reason) == ("mechanic", "model", "a reword")
    (call,) = model.calls
    assert call.tool_names == [ROUTE_TOOL.name] and call.system == "ROUTER"
    assert call.messages[0].content == router_user_text(
        "Make slide 2 say 'quarter' not 'Q'", "Deck `d`: x (1 slide)"
    )
    assert router_user_text("hi", "") == (
        "# The deck\n\n(no deck yet)\n\n# The owner's message\n\nhi"
    )


def test_when_unsure_the_lead_gets_it() -> None:
    model, bound = router([{"role": "router", "text": "mechanic, I think"}])
    prose = decide_route(
        "Tidy slide 2", origin="owner", request="auto", router=bound, outline=""
    )
    assert (prose.route, prose.by, prose.reason) == (
        "lead",
        "fallback",
        "router gave no answer",
    )
    assert model.calls[0].step_label is not None
    exhausted = decide_route(
        "Tidy slide 2", origin="owner", request="auto", router=bound, outline=""
    )
    assert exhausted.by == "fallback" and model.overrun == 1 and EXHAUSTED_TEXT
    none = decide_route("Tidy slide 2", origin="owner", request="auto", router=None, outline="")
    assert (none.route, none.by, none.reason) == ("lead", "fallback", "no router model")

    class Down:
        def converse(self, messages, tools, *, system=None):
            raise TimeoutError("slow")

    failed = decide_route(
        "Tidy slide 2",
        origin="owner",
        request="auto",
        router=BoundModel("router", "x", Down(), "s"),
        outline="",
    )
    assert (failed.route, failed.by, failed.reason) == (
        "lead",
        "fallback",
        "router failed: TimeoutError",
    )
    bad_args = router(
        [{"role": "router", "tool_calls": [{"name": "route", "arguments": {"to": "nobody"}}]}]
    )[1]
    assert decide_route(
        "Tidy", origin="owner", request="auto", router=bad_args, outline=""
    ).by == ("fallback")
