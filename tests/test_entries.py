from __future__ import annotations

from jayu.entries import evaluate_entry

BASE_PARAMS = {
    "rsi_lo": 30,
    "rsi_hi": 70,
    "vol_mult": 1.0,
    "gap_min": -1.0,
    "require_macd": False,
    "require_bb": False,
    "regime_filter": True,
    "ensemble_min": 2,
}


def _row(**overrides):
    row = {
        "rsi": 50.0,
        "vol_ratio": 2.0,
        "gap": 0.5,
        "macd_cross": True,
        "bb_pct": 0.2,
        "regime": "bull",
        "obv_trend": True,
        "stoch_rsi": 0.5,
        # extra columns used by other modes (ignored by ensemble)
        "Open": 100.0,
        "prev_range": 2.0,
        "k_dynamic": 0.5,
        "sma200": 90.0,
        "Volume": 3_000_000.0,
        "volume_ma20": 1_000_000.0,
        "rsi2": 5.0,
    }
    row.update(overrides)
    return row


def test_ensemble_entry_passes_with_full_optionals():
    decision = evaluate_entry(
        _row(), BASE_PARAMS, close=100.0, ema=95.0, strategy_mode="ensemble", market_ok=True
    )
    assert decision.entered is True
    assert decision.optional_met == 5
    assert decision.optional_count == 5


def test_ensemble_rejected_when_mandatory_fails():
    # vol_ratio below vol_mult -> mandatory volume condition fails.
    decision = evaluate_entry(
        _row(vol_ratio=0.5),
        BASE_PARAMS,
        close=100.0,
        ema=95.0,
        strategy_mode="ensemble",
        market_ok=True,
    )
    assert decision.entered is False


def test_ensemble_rejected_when_market_not_ok():
    decision = evaluate_entry(
        _row(), BASE_PARAMS, close=100.0, ema=95.0, strategy_mode="ensemble", market_ok=False
    )
    assert decision.entered is False


def test_ensemble_rejected_when_optionals_below_threshold():
    params = {**BASE_PARAMS, "ensemble_min": 6}  # more than the 5 optionals available
    decision = evaluate_entry(
        _row(), params, close=100.0, ema=95.0, strategy_mode="ensemble", market_ok=True
    )
    assert decision.entered is False


def test_close_below_ema_drops_an_optional_but_not_mandatory():
    # In basic mode 'ema' is mandatory; close<=ema fails entry.
    decision = evaluate_entry(
        _row(), BASE_PARAMS, close=90.0, ema=95.0, strategy_mode="ensemble", market_ok=True
    )
    assert decision.entered is False


def test_williams_mode_breakout():
    # target = Open + prev_range*k_dynamic*mult = 100 + 2*0.5*1 = 101; close 102 > target, > sma200.
    decision = evaluate_entry(
        _row(),
        {**BASE_PARAMS, "williams_k_multiplier": 1.0},
        close=102.0,
        ema=95.0,
        strategy_mode="williams_breakout",
        market_ok=True,
    )
    assert decision.entered is True
    assert decision.optional_count == 0


def test_connors_mode():
    decision = evaluate_entry(
        _row(rsi2=5.0),
        {**BASE_PARAMS, "connors_rsi2_limit": 10},
        close=100.0,
        ema=95.0,
        strategy_mode="connors_rsi2",
        market_ok=True,
    )
    assert decision.entered is True  # close>sma200 and rsi2<limit
    assert decision.optional_count == 0
