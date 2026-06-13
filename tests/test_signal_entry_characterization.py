"""Characterization tests for the live signal entry decision.

Locks the current ``check_today_signals`` entry behaviour on a deterministic
fixture *before* the entry logic is unified onto ``jayu.entries.evaluate_entry``
(removing the duplication with backtest_core). The action must be unchanged by
that migration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from jayu.engine import add_indicators
from jayu.signal_generation import check_today_signals, configure

_PERMISSIVE = {
    "rsi_lo": 0,
    "rsi_hi": 100,
    "ema_span": 20,
    "vol_mult": 0.0,
    "gap_min": -5,
    "stop_pct": 0.05,
    "target_pct": 0.10,
    "hold_days": 5,
    "ensemble_min": 1,
    "pos_size": 0.2,
    "require_macd": False,
    "require_bb": False,
    "regime_filter": False,
    "min_dollar_volume": 1000,
}


def _fixture_df() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(20260613)
    n = 600
    returns = rng.normal(0.0008, 0.02, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    index = pd.bdate_range("2022-01-03", periods=n)
    raw = pd.DataFrame(
        {
            "Open": close * (1 - 0.001),
            "High": close * (1 + 0.012),
            "Low": close * (1 - 0.012),
            "Close": close,
            "Volume": 5_000_000,
        },
        index=index,
    )
    return {"TEST": add_indicators(raw)}


def _best_all(params: dict) -> dict:
    return {"TEST": {regime: {"params": params} for regime in ("bull", "bear", "sideways")}}


def test_permissive_params_yield_buy():
    configure(tickers=["TEST"])
    signals = check_today_signals(_fixture_df(), _best_all(_PERMISSIVE))
    assert signals["TEST"]["action"] == "buy"
    assert signals["TEST"]["regime"] == "bull"


def test_unmet_mandatory_yields_hold():
    # An impossible gap threshold fails the mandatory gap condition -> hold.
    params = {**_PERMISSIVE, "gap_min": 100.0}
    configure(tickers=["TEST"])
    signals = check_today_signals(_fixture_df(), _best_all(params))
    assert signals["TEST"]["action"] == "hold"
