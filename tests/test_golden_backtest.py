"""Golden / reproducibility regression for the backtest engine.

This is the safety net that must pass *unchanged* across the planned
engine/backtest_core responsibility-split refactors. It pins two guarantees
required by the project's constraints:

* **Reproducibility** (completion criterion #11): the same fixture + params +
  execution model produce byte-identical trades on repeated runs.
* **Golden snapshot** (constraint #5): the core outputs (trade count, final
  capital, net-return sequence) are frozen to known values, so any behavioural
  change to the strategy/fill logic is caught and must be accompanied by an
  intentional golden update with before/after numbers.

The fixture is a seeded geometric random walk — fully deterministic and offline
(no network, no live data), so it is safe for the default CI run.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from jayu.engine import add_indicators, backtest
from jayu.execution import ExecutionModel, FixedRateFeeModel, FixedSlippageModel

GOLDEN_SEED = 20260613
GOLDEN_PARAMS = {
    "rsi_lo": 30,
    "rsi_hi": 75,
    "ema_span": 20,
    "vol_mult": 0.0,
    "gap_min": -5,
    "stop_pct": 0.05,
    "target_pct": 0.10,
    "hold_days": 5,
    "ensemble_min": 1,
    "pos_size": 0.2,
}


def _golden_fixture() -> pd.DataFrame:
    rng = np.random.default_rng(GOLDEN_SEED)
    n = 600
    returns = rng.normal(0.0006, 0.02, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    index = pd.bdate_range("2022-01-03", periods=n)
    raw = pd.DataFrame(
        {
            "Open": close * (1 - 0.001),
            "High": close * (1 + 0.012),
            "Low": close * (1 - 0.012),
            "Close": close,
            "Volume": 3_000_000,
        },
        index=index,
    )
    return add_indicators(raw)


def _golden_execution_model() -> ExecutionModel:
    # Fixed fee + slippage so the snapshot does not depend on settings defaults.
    return ExecutionModel(
        max_participation_rate=1.0,
        fee_model=FixedRateFeeModel(0.0015),
        slippage_model=FixedSlippageModel(0.0005),
    )


def _run() -> tuple[list, float]:
    df = _golden_fixture()
    trades, final_capital, _ = backtest(
        df, GOLDEN_PARAMS, execution_model=_golden_execution_model(), initial_skip=0
    )
    return trades, final_capital


def test_backtest_is_deterministic():
    first_trades, first_capital = _run()
    second_trades, second_capital = _run()

    assert first_capital == second_capital
    assert [t["net_return_pct"] for t in first_trades] == [
        t["net_return_pct"] for t in second_trades
    ]


def test_backtest_golden_snapshot():
    trades, final_capital = _run()
    net_sequence = [round(t["net_return_pct"], 4) for t in trades]
    sequence_hash = hashlib.sha256(json.dumps(net_sequence).encode()).hexdigest()[:16]

    # GOLDEN VALUES — update intentionally with before/after numbers when the
    # strategy or fill logic changes (constraint #5). Do not "fix" by editing.
    assert len(trades) == 41
    assert final_capital == pytest.approx(10_483_818.51, abs=0.01)
    assert sequence_hash == "248af2c0bbaf7579"
    assert trades[0]["net_return_pct"] == pytest.approx(2.0755, abs=1e-4)
    assert trades[-1]["net_return_pct"] == pytest.approx(10.6698, abs=1e-4)
