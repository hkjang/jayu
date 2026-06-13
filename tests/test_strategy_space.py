from __future__ import annotations

import random

import pytest

from jayu import engine
from jayu.strategy_space import (
    StrategyMode,
    active_parameter_space,
    infer_strategy_mode,
    normalize_strategy_params,
    validate_params,
)


def test_strategy_mode_is_a_single_string_enum():
    assert StrategyMode("ensemble") is StrategyMode.ENSEMBLE
    assert {mode.value for mode in StrategyMode} == {
        "ensemble",
        "connors_rsi2",
        "williams_breakout",
        "volume_breakout",
    }


def test_legacy_strategy_flags_migrate_with_existing_priority():
    legacy = {
        "use_connors_rsi2": True,
        "use_williams_breakout": True,
        "use_volume_breakout": True,
    }

    assert infer_strategy_mode(legacy) == "williams_breakout"
    normalized = normalize_strategy_params(legacy)
    assert normalized["use_williams_breakout"] is True
    assert normalized["use_connors_rsi2"] is False
    assert normalized["use_volume_breakout"] is False


def test_active_space_excludes_inactive_conditional_parameters():
    params = normalize_strategy_params(
        {
            "strategy_mode": "connors_rsi2",
            "use_atr_stop": False,
            "use_atr_target": True,
            "trail_stop": False,
            "use_breakeven_stop": False,
            "use_volatility_sizing": False,
        }
    )

    active = active_parameter_space(params)

    assert "connors_rsi2_limit" in active
    assert "williams_k_multiplier" not in active
    assert "atr_mult_stop" not in active
    assert "stop_pct" in active
    assert "atr_mult_target" in active
    assert "target_pct" not in active
    assert "trail_pct" not in active


@pytest.mark.parametrize(
    "mode",
    ["ensemble", "connors_rsi2", "williams_breakout", "volume_breakout"],
)
def test_sampled_params_have_exactly_one_strategy_mode(mode, monkeypatch):
    random.seed(7)
    monkeypatch.setitem(engine.PARAM_SPACE, "strategy_mode", [mode])

    params = engine.sample_params(use_meta=False)

    assert params["strategy_mode"] == mode
    assert sum(
        bool(params[name])
        for name in (
            "use_connors_rsi2",
            "use_williams_breakout",
            "use_volume_breakout",
        )
    ) == (0 if mode == "ensemble" else 1)
    validate_params(params)


def test_validate_params_rejects_impossible_legacy_combination():
    params = engine.fill_missing_params(
        {
            "strategy_mode": "connors_rsi2",
            "use_connors_rsi2": False,
            "use_williams_breakout": True,
        }
    )
    params["use_connors_rsi2"] = False
    params["use_williams_breakout"] = True

    with pytest.raises(ValueError, match="legacy strategy flag"):
        validate_params(params)
