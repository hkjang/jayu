import pandas as pd

from jayu.execution import (
    AtrParticipationSlippageModel,
    ExecutionModel,
    FixedSlippageModel,
)


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
