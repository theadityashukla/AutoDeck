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
        price = self.by_model.get(model_id)
        if price is None:
            return None
        total = input_tokens * price.input + output_tokens * price.output
        return round(total / 1_000_000, 6)


def load_prices(path: Path = DEFAULT_PRICES_PATH) -> Prices:
    """Read the price file (YAML, `yaml.safe_load`): a mapping with a `models` mapping of
    model id → `{input: number, output: number}`.

    Raises:
        StudioConfigError: the file is missing, not YAML, not a mapping, has no `models`
            mapping, or an entry lacks a numeric non-negative `input` or `output` (the
            message names the path and the entry).
    """
    import math

    import yaml

    from autodeck.studio.errors import StudioConfigError

    if not path.is_file():
        raise StudioConfigError(f"price file missing: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StudioConfigError(f"price file {path} is not readable YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise StudioConfigError(f"price file {path} must be a mapping")
    models = data.get("models")
    if not isinstance(models, dict):
        raise StudioConfigError(f"price file {path} must have a 'models' mapping")

    def number(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return float(value)

    by_model: dict[str, Price] = {}
    for model_id, entry in models.items():
        if not isinstance(entry, dict):
            raise StudioConfigError(f"price file {path}: entry {model_id!r} must be a mapping")
        input_price = number(entry.get("input"))
        output_price = number(entry.get("output"))
        if input_price is None or output_price is None:
            raise StudioConfigError(
                f"price file {path}: entry {model_id!r} needs non-negative numeric "
                "'input' and 'output'"
            )
        by_model[str(model_id)] = Price(input_price, output_price)
    return Prices(by_model)


@dataclass
class _RoleTotals:
    """What the meter holds for one role: its first model id and the running sums."""

    model_id: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class UsageMeter:
    """Counts the calls of one turn, by role. Thread-safe (the designer runs slides in
    parallel). Records arrive in any order; the snapshot orders them by `ROLE_ORDER`."""

    def __init__(self) -> None:
        from threading import Lock

        self._lock = Lock()
        self._by_role: dict[str, _RoleTotals] = {}

    def record(self, role: str, model_id: str, input_tokens: int, output_tokens: int) -> None:
        """Add one call. If a role is recorded under two model ids in one turn (it cannot
        be, in this phase), the first model id is kept and the tokens are added."""
        with self._lock:
            totals = self._by_role.get(role)
            if totals is None:
                totals = self._by_role[role] = _RoleTotals(model_id)
            totals.calls += 1
            totals.input_tokens += input_tokens
            totals.output_tokens += output_tokens

    def calls(self, role: str) -> int:
        """Calls recorded for `role` so far (0 when none)."""
        with self._lock:
            totals = self._by_role.get(role)
            return 0 if totals is None else totals.calls

    def snapshot(self, prices: Prices) -> TurnUsage:
        """A `TurnUsage` of everything recorded: one `LayerUsage` per role with at least
        one call, in `ROLE_ORDER` (roles not in it, e.g. `reviewer`, after them), layer
        from `ROLE_LAYER`, cost from `prices.cost`; total as `TurnUsage` describes."""
        from dataclasses import replace
        from typing import cast

        with self._lock:
            recorded = [(role, replace(totals)) for role, totals in self._by_role.items()]

        rank: dict[str, int] = {role: index for index, role in enumerate(ROLE_ORDER)}

        def order(item: tuple[str, _RoleTotals]) -> int:
            return rank.get(item[0], len(rank))

        layers = [
            LayerUsage(
                role=cast(RoleName, role),
                layer=ROLE_LAYER[role],
                model_id=totals.model_id,
                calls=totals.calls,
                input_tokens=totals.input_tokens,
                output_tokens=totals.output_tokens,
                cost_usd=prices.cost(
                    totals.model_id, totals.input_tokens, totals.output_tokens
                ),
            )
            for role, totals in sorted(recorded, key=order)
        ]
        costs = [layer.cost_usd for layer in layers]
        total: float | None = None
        if all(cost is not None for cost in costs):
            total = round(sum(cost for cost in costs if cost is not None), 6)
        return TurnUsage(layers=layers, total_cost_usd=total)


class MeteredModel:
    """A `bindings.ConverseModel` that forwards to `inner` and records each call (its
    reported `usage.input_tokens` / `output_tokens`) under `role` and `model_id` in
    `meter`. A call that raises records nothing and re-raises."""

    def __init__(self, inner: object, *, role: str, model_id: str, meter: UsageMeter) -> None:
        from typing import cast

        from autodeck.studio.bindings import ConverseModel

        self._inner = cast(ConverseModel, inner)
        self._role = role
        self._model_id = model_id
        self._meter = meter

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn:
        turn = self._inner.converse(messages, tools, system=system)
        self._meter.record(
            self._role,
            self._model_id,
            turn.usage.input_tokens,
            turn.usage.output_tokens,
        )
        return turn


def metered(bound: object, meter: UsageMeter) -> object:
    """A copy of the `bindings.BoundModel` `bound` whose `model` is
    `MeteredModel(bound.model, role=bound.role, model_id=bound.model_id, meter=meter)`
    (`dataclasses.replace`). Typed loosely to avoid an import cycle with `bindings`; it
    returns a `BoundModel`."""
    from dataclasses import replace

    from autodeck.studio.bindings import BoundModel

    if not isinstance(bound, BoundModel):
        raise TypeError(f"metered() needs a BoundModel, not {type(bound).__name__}")
    wrapped = MeteredModel(bound.model, role=bound.role, model_id=bound.model_id, meter=meter)
    return replace(bound, model=wrapped)
