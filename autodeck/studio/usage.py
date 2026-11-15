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
    by_model: dict[str, Price] = field(default_factory=dict)

    def cost(self, model_id, input_tokens, output_tokens):
        p = self.by_model.get(model_id)
        if p is None:
            return None
        return round((input_tokens * p.input + output_tokens * p.output) / 1_000_000, 6)


def load_prices(path=DEFAULT_PRICES_PATH):
    import yaml
    from autodeck.studio.errors import StudioConfigError
    if not path.is_file():
        raise StudioConfigError(f"price file missing: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("models"), dict):
        raise StudioConfigError(f"{path}: needs a models mapping")
    out = {}
    for k, v in raw["models"].items():
        try:
            i, o = float(v["input"]), float(v["output"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StudioConfigError(f"{path}: {k}: bad") from exc
        if i < 0 or o < 0:
            raise StudioConfigError(f"{path}: {k}: negative")
        out[str(k)] = Price(i, o)
    return Prices(out)


class UsageMeter:
    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self._d = {}

    def record(self, role, model_id, input_tokens, output_tokens):
        with self._lock:
            e = self._d.setdefault(role, [model_id, 0, 0, 0])
            e[1] += 1; e[2] += input_tokens; e[3] += output_tokens

    def calls(self, role):
        with self._lock:
            return self._d.get(role, [None, 0])[1]

    def snapshot(self, prices):
        with self._lock:
            roles = [r for r in ROLE_ORDER if r in self._d] + [r for r in self._d if r not in ROLE_ORDER]
            layers = [LayerUsage(role=r, layer=ROLE_LAYER[r], model_id=self._d[r][0], calls=self._d[r][1], input_tokens=self._d[r][2], output_tokens=self._d[r][3], cost_usd=prices.cost(self._d[r][0], self._d[r][2], self._d[r][3])) for r in roles]
        costs = [l.cost_usd for l in layers]
        total = None if any(c is None for c in costs) else round(sum(costs), 6)
        return TurnUsage(layers=layers, total_cost_usd=total)


class MeteredModel:
    def __init__(self, inner, *, role, model_id, meter):
        self.inner, self.role, self.model_id, self.meter = inner, role, model_id, meter

    def converse(self, messages, tools, *, system=None):
        turn = self.inner.converse(messages, tools, system=system)
        self.meter.record(self.role, self.model_id, turn.usage.input_tokens, turn.usage.output_tokens)
        return turn


def metered(bound, meter):
    import dataclasses
    return dataclasses.replace(bound, model=MeteredModel(bound.model, role=bound.role, model_id=bound.model_id, meter=meter))
