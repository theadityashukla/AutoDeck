"""Task 23.4: per-turn layer and cost records (`usage.py` below the marker)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from autodeck.providers.base import Message
from autodeck.studio.bindings import BoundModel
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.usage import (
    DEFAULT_PRICES_PATH,
    PRICE_NOTE,
    MeteredModel,
    Price,
    Prices,
    UsageMeter,
    load_prices,
    metered,
)

PRICES = Prices({"openai/gpt-5.6-luna": Price(5, 25), "openai/gpt-5.4-mini": Price(3, 15)})


def test_cost_is_per_million_tokens_and_none_when_unpriced() -> None:
    assert PRICES.cost("openai/gpt-5.6-luna", 1_000_000, 200_000) == 10.0
    assert PRICES.cost("openai/gpt-5.4-mini", 1234, 567) == round(
        (1234 * 3 + 567 * 15) / 1_000_000, 6
    )
    assert PRICES.cost("scripted/lead", 10, 10) is None


def test_the_repository_price_file_holds_the_benchs_assumed_prices() -> None:
    prices = load_prices(DEFAULT_PRICES_PATH)
    assert prices.by_model["openai/gpt-5.6-luna"] == Price(5, 25)
    assert prices.by_model["openai/gpt-5.6-terra"] == Price(12, 60)
    assert prices.by_model["openai/gpt-5.4-mini"] == Price(3, 15)
    assert "ASSUMPTIONS, NOT CONFIRMED" in DEFAULT_PRICES_PATH.read_text(encoding="utf-8")


def test_bad_price_files(tmp_path: Path) -> None:
    with pytest.raises(StudioConfigError, match="missing"):
        load_prices(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("models:\n  a/b: {input: x, output: 1}\n", encoding="utf-8")
    with pytest.raises(StudioConfigError, match="a/b"):
        load_prices(bad)
    none = tmp_path / "none.yaml"
    none.write_text("prices: {}\n", encoding="utf-8")
    with pytest.raises(StudioConfigError, match="models"):
        load_prices(none)
    negative = tmp_path / "neg.yaml"
    negative.write_text("models:\n  a/b: {input: -1, output: 1}\n", encoding="utf-8")
    with pytest.raises(StudioConfigError):
        load_prices(negative)


def test_the_meter_orders_layers_by_the_flow_of_a_turn_and_sums_costs() -> None:
    meter = UsageMeter()
    meter.record("designer", "openai/gpt-5.6-luna", 1000, 500)
    meter.record("lead", "openai/gpt-5.4-mini", 2000, 100)
    meter.record("designer", "openai/gpt-5.6-luna", 1000, 500)
    meter.record("router", "openai/gpt-5.4-mini", 300, 10)
    assert meter.calls("designer") == 2 and meter.calls("mechanic") == 0
    usage = meter.snapshot(PRICES)
    assert usage.roles() == ["router", "lead", "designer"]
    designer = usage.layer("designer")
    assert designer is not None
    assert (designer.layer, designer.calls, designer.input_tokens, designer.output_tokens) == (
        "composition",
        2,
        2000,
        1000,
    )
    assert designer.cost_usd == PRICES.cost("openai/gpt-5.6-luna", 2000, 1000)
    assert usage.layer("router").layer == "mechanics"  # type: ignore[union-attr]
    total = sum(layer.cost_usd or 0 for layer in usage.layers)
    assert usage.total_cost_usd == round(total, 6)
    assert usage.prices_assumed and usage.price_note == PRICE_NOTE
    assert usage.layer("mechanic") is None


def test_an_unpriced_layer_makes_the_total_unknown() -> None:
    meter = UsageMeter()
    meter.record("lead", "scripted/lead", 10, 2)
    meter.record("designer", "openai/gpt-5.6-luna", 10, 2)
    usage = meter.snapshot(PRICES)
    assert usage.layer("lead").cost_usd is None  # type: ignore[union-attr]
    assert usage.total_cost_usd is None
    assert UsageMeter().snapshot(PRICES).layers == []


def test_the_meter_is_thread_safe() -> None:
    meter = UsageMeter()
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: meter.record("designer", "m", 1, 1), range(400)))
    usage = meter.snapshot(Prices())
    assert usage.layers[0].calls == 400 and usage.layers[0].input_tokens == 400


def test_metered_models_record_each_call_and_nothing_on_failure() -> None:
    script = ScriptedModel.from_steps([{"role": "designer", "text": "12345678"}])
    bound = BoundModel(
        role="designer",
        model_id="scripted/designer",
        model=script.for_role("designer"),
        env="s",
    )
    meter = UsageMeter()
    wrapped = metered(bound, meter)
    assert isinstance(wrapped, BoundModel) and wrapped.model_id == "scripted/designer"
    assert isinstance(wrapped.model, MeteredModel)
    wrapped.model.converse([Message(role="user", content="x" * 40)], [])
    layer = meter.snapshot(Prices()).layer("designer")
    assert layer is not None and (layer.calls, layer.input_tokens, layer.output_tokens) == (
        1,
        10,
        2,
    )

    class Boom:
        def converse(self, messages, tools, *, system=None):
            raise RuntimeError("down")

    broken = MeteredModel(Boom(), role="lead", model_id="x", meter=meter)
    with pytest.raises(RuntimeError):
        broken.converse([Message(role="user", content="x")], [])
    assert meter.calls("lead") == 0
