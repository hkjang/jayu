from __future__ import annotations

import pytest

from jayu.sizing import resolve_position_fraction

BASE_PARAMS = {
    "pos_size": 0.20,
    "kelly_fraction": 0.50,
    "use_atr_stop": True,
    "stop_pct": 0.05,
}


def test_base_sizing_scales_with_confidence_and_kelly():
    # All optionals met -> confidence 1.0; 0.20 * 1.0 * 0.5 = 0.10.
    size = resolve_position_fraction(
        BASE_PARAMS, optional_met=4, optional_count=4, atr=2.0, close=100.0, max_position=0.30
    )
    assert size == pytest.approx(0.10)


def test_confidence_floor_when_no_optionals_met():
    # 0 of 5 met -> confidence floored at 0.2; 0.20 * 0.2 * 0.5 = 0.02 -> clamped to min 0.05.
    size = resolve_position_fraction(
        BASE_PARAMS, optional_met=0, optional_count=5, atr=2.0, close=100.0, max_position=0.30
    )
    assert size == pytest.approx(0.05)


def test_max_position_clamp():
    params = {**BASE_PARAMS, "pos_size": 2.0}
    size = resolve_position_fraction(
        params, optional_met=4, optional_count=4, atr=2.0, close=100.0, max_position=0.30
    )
    assert size == pytest.approx(0.30)


def test_volatility_sizing_caps_by_risk_budget():
    params = {
        **BASE_PARAMS,
        "pos_size": 1.0,
        "use_volatility_sizing": True,
        "atr_mult_stop": 2.0,
        "max_risk_per_trade_pct": 0.015,
    }
    # base = 1.0*1.0*0.5 = 0.5; risk-adjusted = 0.015/(2.0*0.02) = 0.375 -> min -> 0.375.
    size = resolve_position_fraction(
        params,
        optional_met=4,
        optional_count=4,
        atr=2.0,
        close=100.0,
        atr_pct=0.02,
        max_position=0.50,
    )
    assert size == pytest.approx(0.375)


def test_atr_pct_falls_back_to_atr_over_close():
    params = {**BASE_PARAMS, "pos_size": 1.0, "use_volatility_sizing": True, "atr_mult_stop": 2.0}
    # atr_pct=None -> uses atr/close = 4/100 = 0.04; risk-adjusted = 0.015/(2*0.04)=0.1875.
    size = resolve_position_fraction(
        params,
        optional_met=4,
        optional_count=4,
        atr=4.0,
        close=100.0,
        atr_pct=None,
        max_position=0.50,
    )
    assert size == pytest.approx(0.1875)
