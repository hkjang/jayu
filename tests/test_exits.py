from __future__ import annotations

import pandas as pd
import pytest

from jayu.execution import ExecutionModel
from jayu.exits import resolve_trade_exit


def _frame(rows):
    """rows: list of dicts with OHLC (+ optional indicator) columns."""
    base = {"rsi": 50.0, "macd_hist": 0.0, "sma5": 0.0}
    return pd.DataFrame([{**base, **row} for row in rows])


def _resolve(df, *, params, strategy_mode="ensemble", entry=100.0, stop=95.0, target=110.0):
    return resolve_trade_exit(
        df,
        signal_index=0,
        entry=entry,
        stop_price=stop,
        target_price=target,
        target_dist=target - entry,
        params=params,
        execution_model=ExecutionModel(path_mode="worst_case"),
        strategy_mode=strategy_mode,
        transaction_fee=0.0015,
    )


def test_target_hit_exits_at_target():
    # Exit scan starts at index 2 (entry sits at index 1).
    df = _frame(
        [
            {"Open": 100, "High": 100, "Low": 100, "Close": 100},  # 0 signal
            {"Open": 100, "High": 100, "Low": 100, "Close": 100},  # 1 entry
            {"Open": 101, "High": 111, "Low": 100, "Close": 105},  # 2 -> target
            {"Open": 105, "High": 106, "Low": 104, "Close": 105},
        ]
    )
    outcome = _resolve(df, params={"hold_days": 2, "trail_stop": False})
    assert outcome.exit_reason == "target"
    assert outcome.exit_price == pytest.approx(110.0)
    assert outcome.exit_idx == 2


def test_stop_hit_exits_at_stop():
    df = _frame(
        [
            {"Open": 100, "High": 100, "Low": 100, "Close": 100},
            {"Open": 100, "High": 100, "Low": 100, "Close": 100},
            {"Open": 99, "High": 100, "Low": 94, "Close": 96},  # 2 -> stop
            {"Open": 96, "High": 97, "Low": 95, "Close": 96},
        ]
    )
    outcome = _resolve(df, params={"hold_days": 2, "trail_stop": False})
    assert outcome.exit_reason == "stop"
    assert outcome.exit_price == pytest.approx(95.0)


def test_time_barrier_when_nothing_triggers():
    # Drift up >0.5%/bar so the stagnation timeout never fires; stay between the
    # 90 stop and 120 target; rsi<80 so the overbought exit never fires.
    df = _frame(
        [
            {"Open": 100, "High": 100, "Low": 100, "Close": 100.0},
            {"Open": 100, "High": 101, "Low": 100, "Close": 101.5},
            {"Open": 101, "High": 104, "Low": 101, "Close": 103.0},
            {"Open": 103, "High": 106, "Low": 103, "Close": 104.5},
            {"Open": 104, "High": 107, "Low": 104, "Close": 106.0},
        ]
    )
    outcome = _resolve(df, params={"hold_days": 2, "trail_stop": False}, stop=90.0, target=120.0)
    assert outcome.exit_reason == "time"
    # Fallback closes at index min(0+1+hold_days, len-1) = 3.
    assert outcome.exit_idx == 3
    assert outcome.exit_price == pytest.approx(104.5)


def test_connors_exit_on_close_above_sma5():
    df = _frame(
        [
            {"Open": 100, "High": 100, "Low": 100, "Close": 100, "sma5": 100},
            {"Open": 100, "High": 100, "Low": 100, "Close": 100, "sma5": 100},
            {"Open": 105, "High": 108, "Low": 104, "Close": 106, "sma5": 105},  # close > sma5
            {"Open": 106, "High": 107, "Low": 105, "Close": 106, "sma5": 105},
        ]
    )
    outcome = _resolve(
        df,
        params={"hold_days": 3, "trail_stop": False},
        strategy_mode="connors_rsi2",
        stop=90.0,
        target=120.0,
    )
    assert outcome.exit_reason == "connors_exit"
    assert outcome.exit_price == pytest.approx(106.0)


def test_worst_lo_tracks_lowest_low():
    df = _frame(
        [
            {"Open": 100, "High": 100, "Low": 100, "Close": 100},
            {"Open": 100, "High": 100, "Low": 100, "Close": 100},
            {"Open": 100, "High": 101, "Low": 92, "Close": 100},  # dip but no stop (stop 90)
            {"Open": 100, "High": 120, "Low": 99, "Close": 100},  # target hit
        ]
    )
    outcome = _resolve(df, params={"hold_days": 3, "trail_stop": False}, stop=90.0, target=110.0)
    assert outcome.worst_lo == pytest.approx(92.0)
