import numpy as np
import pandas as pd
import pytest

from jayu.engine import add_indicators, backtest


def test_backtest_emits_standard_trade_fields():
    dates = pd.bdate_range("2023-01-01", periods=600)
    close = pd.Series(np.linspace(100, 180, len(dates)), index=dates)
    raw = pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 2_000_000,
        }
    )
    params = {
        "rsi_lo": 0,
        "rsi_hi": 100,
        "ema_span": 10,
        "vol_mult": 0,
        "gap_min": -1,
        "stop_pct": 0.2,
        "target_pct": 0.3,
        "hold_days": 2,
        "ensemble_min": 1,
        "pos_size": 0.1,
    }

    trades, _, _ = backtest(add_indicators(raw), params, initial_skip=0)

    assert trades
    assert {
        "trade_id",
        "signal_date",
        "entry_date",
        "exit_date",
        "entry_price",
        "exit_price",
        "gross_return_pct",
        "net_return_pct",
        "raw_return_pct",
        "slippage_cost_pct",
        "fee_cost_pct",
        "fee_rate_pct",
        "slippage_rate_pct",
        "position_pct",
        "capital_before",
        "capital_after",
        "reason",
        "trigger",
        "holding_days",
        "fill_ratio",
    } <= trades[0].keys()


def test_backtest_cost_bridge_fields_are_additive():
    dates = pd.bdate_range("2023-01-01", periods=600)
    close = pd.Series(np.linspace(100, 180, len(dates)), index=dates)
    raw = pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 2_000_000,
        }
    )
    params = {
        "rsi_lo": 0,
        "rsi_hi": 100,
        "ema_span": 10,
        "vol_mult": 0,
        "gap_min": -1,
        "stop_pct": 0.2,
        "target_pct": 0.3,
        "hold_days": 2,
        "ensemble_min": 1,
        "pos_size": 0.1,
    }

    trades, _, _ = backtest(add_indicators(raw), params, initial_skip=0)

    assert trades
    for trade in trades:
        reconstructed = trade["raw_return_pct"] - trade["slippage_cost_pct"] - trade["fee_cost_pct"]
        # Each field is rounded to 4 decimals independently, so allow rounding noise.
        assert reconstructed == pytest.approx(trade["net_return_pct"], abs=5e-4)
