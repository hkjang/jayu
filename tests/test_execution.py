import pandas as pd
import pytest

from jayu.execution import (
    AtrParticipationSlippageModel,
    ExecutionModel,
    FixedSlippageModel,
    LimitFillModel,
    QuotedSpreadModel,
    quote_aware_fill_price,
)


def test_quote_aware_fill_crosses_the_spread():
    # Buy pays the ask (above mid); sell hits the bid (below mid).
    assert quote_aware_fill_price("buy", 100.0, 0.001) == pytest.approx(100.1)
    assert quote_aware_fill_price("sell", 100.0, 0.001) == pytest.approx(99.9)


def test_quoted_spread_model_prefers_observed_and_floors():
    model = QuotedSpreadModel(floor_rate=0.0001, atr_weight=0.05, maximum_rate=0.02)
    # Observed relative spread is halved into a half-spread.
    assert model.half_spread_rate(relative_spread=0.004) == pytest.approx(0.002)
    # Falls back to ATR/close * weight when no quote is given.
    assert model.half_spread_rate(atr=2.0, close=100.0) == pytest.approx(0.001)
    # Floored so a fill never assumes a zero spread.
    assert model.half_spread_rate(atr=0.0, close=100.0) == pytest.approx(0.0001)
    # Capped at the maximum.
    assert model.half_spread_rate(relative_spread=0.2) == pytest.approx(0.02)


def test_limit_fill_requires_price_to_reach_the_level():
    model = LimitFillModel()
    # Buy limit fills only if the bar trades down to it.
    assert model.fills(side="buy", limit_price=99.0, bar_high=101.0, bar_low=98.5)
    assert not model.fills(side="buy", limit_price=99.0, bar_high=101.0, bar_low=99.5)
    # Sell limit fills only if the bar trades up to it.
    assert model.fills(side="sell", limit_price=101.0, bar_high=101.5, bar_low=100.0)
    assert not model.fills(side="sell", limit_price=101.0, bar_high=100.5, bar_low=100.0)


def test_limit_fill_probability_scales_with_penetration():
    model = LimitFillModel()
    # Never reached -> 0.
    assert (
        model.fill_probability(
            side="buy", limit_price=99.0, bar_open=100.0, bar_high=101.0, bar_low=99.5
        )
        == 0.0
    )
    # Gap through at the open -> certain.
    assert (
        model.fill_probability(
            side="buy", limit_price=99.0, bar_open=98.0, bar_high=99.5, bar_low=97.0
        )
        == 1.0
    )
    # Barely tagged (limit == low) -> ~0; deep penetration -> higher.
    shallow = model.fill_probability(
        side="buy", limit_price=99.0, bar_open=100.0, bar_high=100.0, bar_low=99.0
    )
    deep = model.fill_probability(
        side="buy", limit_price=99.5, bar_open=100.0, bar_high=100.0, bar_low=99.0
    )
    assert shallow == pytest.approx(0.0)
    assert deep > shallow
    assert 0.0 <= deep <= 1.0


def test_execution_model_spread_half_rate_defaults_to_zero():
    # Default keeps quote-aware spread crossing off (back-compatible behaviour).
    assert ExecutionModel().spread_half_rate == 0.0


def test_gap_stop_uses_open_price():
    model = ExecutionModel(path_mode="worst_case")

    decision = model.resolve_daily_exit(
        open_price=90,
        high=96,
        low=88,
        close=94,
        stop_price=95,
        target_price=110,
    )

    assert decision.price == 90
    assert decision.trigger == "gap_stop"


def test_same_bar_path_modes_are_explicit():
    worst = ExecutionModel(path_mode="worst_case").resolve_daily_exit(
        open_price=100,
        high=112,
        low=94,
        close=105,
        stop_price=95,
        target_price=110,
    )
    best = ExecutionModel(path_mode="best_case").resolve_daily_exit(
        open_price=100,
        high=112,
        low=94,
        close=105,
        stop_price=95,
        target_price=110,
    )

    assert worst.reason == "stop"
    assert best.reason == "target"


def test_intraday_mode_uses_first_bar_that_triggers():
    bars = pd.DataFrame(
        [
            {"Open": 100, "High": 104, "Low": 98, "Close": 103},
            {"Open": 103, "High": 111, "Low": 102, "Close": 109},
        ]
    )

    decision = ExecutionModel(path_mode="intraday").resolve_intraday_exit(
        bars,
        stop_price=95,
        target_price=110,
    )

    assert decision.reason == "target"


def test_participation_rate_caps_position_size():
    model = ExecutionModel(max_participation_rate=0.0005)

    fraction, fill_ratio = model.position_size_cap(
        capital=10_000_000,
        requested_fraction=0.30,
        average_dollar_volume=100_000_000,
    )

    assert fraction == 0.005
    assert fill_ratio < 0.02


def test_slippage_models_are_independent_from_execution_policy():
    fixed = ExecutionModel(slippage_model=FixedSlippageModel(0.002)).slippage_rate(
        atr=5,
        close=100,
        order_notional=100_000,
        average_dollar_volume=1_000_000,
    )
    dynamic = ExecutionModel(
        slippage_model=AtrParticipationSlippageModel(
            floor=0.0005,
            maximum=0.01,
        )
    ).slippage_rate(
        atr=5,
        close=100,
        order_notional=100_000,
        average_dollar_volume=1_000_000,
    )

    assert fixed == 0.002
    assert dynamic == 0.01
