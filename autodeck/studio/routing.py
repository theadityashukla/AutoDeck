"""Routing a message: a small local edit goes to the mechanic, everything else to the lead
(Phase 2-3; plan §6.4, V5).

Before a turn, `decide_route` decides who answers the owner's message. In order:

1. **Origin.** A recap, a pick (`choice`) or any origin other than `owner` → the lead
   (`by="origin"`).
2. **Override.** The owner pinned the turn to the lead (`request="lead"`) → the lead
   (`by="override"`).
3. **Rules,** where a rule is certain (`rule_route`). A message that matches one of the
   small-edit patterns exactly → the mechanic; a message that is certainly not a small edit
   (long, several lines, or a question) → the lead. Both `by="rule"`, with no model call.
4. **The router model,** only when no rule decides: one call with the router prompt, the
   deck's compact outline and the message, and one tool, `route`. A valid `route` call →
   its answer (`by="model"`).
5. **Fallback.** No router model, no valid `route` call, or an exception → the lead
   (`by="fallback"`, the reason says which). When unsure, the lead gets it.

The rules are deliberately narrow. A false "small edit" costs the owner a wrong edit; a
false "lead" costs one lead turn. The mechanic can also hand a turn back (`hand_to_lead`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from autodeck.providers.base import ToolSpec
from autodeck.studio.bindings import BoundModel
from autodeck.studio.tool_args import RouteArgs
from autodeck.studio.usage import RouteName, RouteRecord, RouteRequest

ROUTE_TOOL = ToolSpec(
    name="route",
    description="Say who handles the owner's message: the mechanic or the lead.",
    args_model=RouteArgs,
)

MAX_RULE_CHARS = 240
"""A message longer than this is certainly for the lead."""

_PLEASE = r"(?:please\s+)?"
_END = r"\s*[.!]?"

MECHANIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "retitle a slide",
        re.compile(
            rf"{_PLEASE}(?:retitle|rename)\s+slide\s+\d+\s+(?:to|as)\s+\S.*", re.I | re.S
        ),
    ),
    (
        "retitle a slide",
        re.compile(
            rf"{_PLEASE}change\s+the\s+(?:title|header|headline)\s+of\s+slide\s+\d+\s+to\s+\S.*",
            re.I | re.S,
        ),
    ),
    (
        "swap two slides",
        re.compile(
            rf"{_PLEASE}(?:swap|switch)\s+slides?\s+\d+\s+(?:and|with)\s+\d+{_END}", re.I
        ),
    ),
    (
        "move a slide",
        re.compile(rf"{_PLEASE}move\s+slide\s+\d+\s+to\s+(?:position\s+)?\d+{_END}", re.I),
    ),
    (
        "mark a slide",
        re.compile(
            rf"{_PLEASE}mark\s+slide\s+\d+\s+(?:as\s+)?(?:decided|provisional){_END}", re.I
        ),
    ),
)
"""Full-match patterns (on the stripped message) that are certainly a small local edit, with
the reason recorded. A retitle's new header may contain anything but a newline."""


@dataclass(frozen=True)
class RuleDecision:
    route: RouteName
    reason: str


def rule_route(text: str) -> RuleDecision | None:
    """The certain cases, or None when a rule cannot tell.

    On `stripped = text.strip()`, in order: more than `MAX_RULE_CHARS` characters →
    lead, reason `"long message"`; a newline → lead, `"several lines"`; a `?` anywhere →
    lead, `"a question"`; a full match (`re.fullmatch`) of one of `MECHANIC_PATTERNS` →
    mechanic with that pattern's reason; else None.
    """
    raise NotImplementedError


def router_user_text(text: str, outline: str) -> str:
    """The router model's user message, exactly
    `"# The deck\\n\\n<outline or '(no deck yet)'>\\n\\n# The owner's message\\n\\n<text>"`.
    """
    raise NotImplementedError


def ask_router(
    model: BoundModel, text: str, outline: str, *, system: str
) -> RuleDecision | None:
    """One router call: `model.model.converse([Message("user", router_user_text(...))],
    [ROUTE_TOOL], system=system)`. The first tool call named `route` whose arguments
    validate as `RouteArgs` → `RuleDecision(args.to, args.reason or "router")`; anything
    else → None. Exceptions propagate (the caller falls back)."""
    raise NotImplementedError


def decide_route(
    text: str,
    *,
    origin: str,
    request: RouteRequest,
    router: BoundModel | None,
    outline: str,
    system: str = "",
) -> RouteRecord:
    """Who answers this message, as the module docstring orders it. Never raises.

    Returns `RouteRecord(requested=request, route=..., by=..., reason=...)` with these
    reasons: origin → `f"{origin} turns go to the lead"`; override → `"pinned to the lead"`;
    rule → the rule's reason; model → the model's reason; fallback → `"no router model"`,
    `"router gave no answer"`, or `f"router failed: {type(exc).__name__}"`. `system` is the
    router prompt (`prompt.role_prompt(prompt.ROUTER_PROMPT_PATH)` from the session).
    """
    raise NotImplementedError
