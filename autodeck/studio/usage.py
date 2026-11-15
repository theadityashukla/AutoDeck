"""Which layers ran in a turn, with which model, how many calls and tokens, and at what
estimated cost (Phase 2-3; plan §6.4, V5).

Every model call a turn makes goes through a `MeteredModel` (a `BoundModel` whose `converse`
also records the call in the turn's `UsageMeter`): the router, the mechanic, the lead, the
system layer and the designer alike. At the end of the turn the session takes a
`TurnUsage` snapshot and stores it on the turn's `TurnEndLine` and `TurnFinished`, where
the interface shows it as the routing line under the assistant message.

**Prices are assumed.** `config/studio_prices.yaml` holds US dollars per million tokens
per model id, copied from the bench's deliberately high assumptions
(`bench/slides/prices.yaml`). Every cost the studio reports is an estimate from that file,
labelled as such (`PRICE_NOTE`), never an invoice. A model missing from the file is
unpriced: its layer's `cost_usd` is None and so is the turn's total.

Implementer: the models and constants above the marker are lead-owned; implement the
functions and classes below it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field

from autodeck.providers.base import AssistantTurn, Message, ToolSpec
from autodeck.studio.models import Layer, StudioModel
from autodeck.studio.paths import REPO_ROOT

DEFAULT_PRICES_PATH = REPO_ROOT / "config" / "studio_prices.yaml"

PRICE_NOTE = (
    "Estimated from assumed prices in config/studio_prices.yaml; not confirmed, not an invoice."
)
"""Shown wherever a cost is shown."""

RoleName = Literal["router", "mechanic", "lead", "system", "designer", "reviewer"]
"""The studio roles (`bindings.StudioRole`), repeated here to keep this module import-light."""

ROLE_ORDER: tuple[RoleName, ...] = ("router", "mechanic", "lead", "system", "designer")
"""The order layers are listed in a `TurnUsage`: the order work flows in a turn."""

ROLE_LAYER: dict[str, Layer] = {
    "router": "mechanics",
    "mechanic": "mechanics",
    "lead": "direction",
    "system": "system",
    "designer": "composition",
    "reviewer": "review",
}
"""The plan §6.1 layer each role works at. The designer also does Placement in this phase;
its layer is recorded as `composition`."""

RouteName = Literal["lead", "mechanic"]
RouteRequest = Literal["auto", "lead"]
"""The owner's per-message override: `auto` lets the router decide; `lead` pins the turn."""
RouteBy = Literal["rule", "model", "override", "origin", "fallback"]
"""How a route was decided: a certain rule; the router model; the owner's override; the
turn's origin (a recap or a pick always goes to the lead); or a fallback to the lead (no
router model, an unreadable answer, or a router error)."""


class LayerUsage(StudioModel):
    """One role's work in one turn."""

    role: RoleName
    layer: Layer
    model_id: str = Field(min_length=1)
    calls: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0, description="None when unpriced.")


class RouteRecord(StudioModel):
    """How the turn was routed. `handed_off` is True when the mechanic handed the turn to
    the lead (`route` stays `mechanic`: that is where it was sent)."""

    requested: RouteRequest = "auto"
    route: RouteName
    by: RouteBy
    reason: str = ""
    handed_off: bool = False


class TurnUsage(StudioModel):
    """The per-turn layer and cost record. `layers` lists only roles that made at least one
    call, in `ROLE_ORDER`. `total_cost_usd` is the sum of the layers' costs (rounded to 6
    decimals), or None when any layer is unpriced. `prices_assumed` is always True in this
    phase; `price_note` is `PRICE_NOTE`."""

    layers: list[LayerUsage] = Field(default_factory=list)
    total_cost_usd: float | None = None
    prices_assumed: bool = True
    price_note: str = PRICE_NOTE

    def roles(self) -> list[str]:
        """The roles that ran, in order."""
        return [layer.role for layer in self.layers]

    def layer(self, role: str) -> LayerUsage | None:
        """The usage of one role, or None when it did not run."""
        return next((layer for layer in self.layers if layer.role == role), None)


@dataclass(frozen=True)
class Price:
    """Assumed US dollars per million tokens."""

    input: float
    output: float


# ---------------------------------------------------------------------------
# Implementer: everything below this line.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Prices:
    """Assumed prices by model id (`"<provider>/<model>"`, the studio's `model_id`)."""

    by_model: dict[str, Price] = field(default_factory=dict)

    def cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float | None:
        """`(input_tokens * price.input + output_tokens * price.output) / 1_000_000`,
        rounded to 6 decimals; None when `model_id` has no price."""
        raise NotImplementedError


def load_prices(path: Path = DEFAULT_PRICES_PATH) -> Prices:
    """Read the price file (YAML, `yaml.safe_load`): a mapping with a `models` mapping of
    model id → `{input: number, output: number}`.

    Raises:
        StudioConfigError: the file is missing, not YAML, not a mapping, has no `models`
            mapping, or an entry lacks a numeric non-negative `input` or `output` (the
            message names the path and the entry).
    """
    raise NotImplementedError


class UsageMeter:
    """Counts the calls of one turn, by role. Thread-safe (the designer runs slides in
    parallel). Records arrive in any order; the snapshot orders them by `ROLE_ORDER`."""

    def __init__(self) -> None:
        raise NotImplementedError

    def record(self, role: str, model_id: str, input_tokens: int, output_tokens: int) -> None:
        """Add one call. If a role is recorded under two model ids in one turn (it cannot
        be, in this phase), the first model id is kept and the tokens are added."""
        raise NotImplementedError

    def calls(self, role: str) -> int:
        """Calls recorded for `role` so far (0 when none)."""
        raise NotImplementedError

    def snapshot(self, prices: Prices) -> TurnUsage:
        """A `TurnUsage` of everything recorded: one `LayerUsage` per role with at least
        one call, in `ROLE_ORDER` (roles not in it, e.g. `reviewer`, after them), layer
        from `ROLE_LAYER`, cost from `prices.cost`; total as `TurnUsage` describes."""
        raise NotImplementedError


class MeteredModel:
    """A `bindings.ConverseModel` that forwards to `inner` and records each call (its
    reported `usage.input_tokens` / `output_tokens`) under `role` and `model_id` in
    `meter`. A call that raises records nothing and re-raises."""

    def __init__(self, inner: object, *, role: str, model_id: str, meter: UsageMeter) -> None:
        raise NotImplementedError

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn:
        raise NotImplementedError


def metered(bound: object, meter: UsageMeter) -> object:
    """A copy of the `bindings.BoundModel` `bound` whose `model` is
    `MeteredModel(bound.model, role=bound.role, model_id=bound.model_id, meter=meter)`
    (`dataclasses.replace`). Typed loosely to avoid an import cycle with `bindings`; it
    returns a `BoundModel`."""
    raise NotImplementedError
