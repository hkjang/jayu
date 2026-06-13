from __future__ import annotations

import random

import pytest

from jayu import engine
from jayu.strategy_space import (
    StrategyMode,
    active_parameter_space,
    infer_strategy_mode,
    load_strategy_spaces,
    normalize_strategy_params,
    validate_params,
    validate_strategy_spaces,
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


def test_validate_strategy_spaces_reports_inventory():
    report = validate_strategy_spaces(load_strategy_spaces())

    assert report["valid"] is True
    assert report["space_count"] == 5
    assert report["parameter_count"] > 0
    assert report["choice_count"] > report["parameter_count"]


def test_validate_strategy_spaces_rejects_empty_and_duplicate_choices():
    spaces = load_strategy_spaces()
    spaces["common"]["hold_days"] = []
    spaces["common"]["vol_mult"] = [1.5, 1.5]

    with pytest.raises(
        ValueError,
        match=r"common\.hold_days must be a non-empty list.*duplicate choices",
    ):
        validate_strategy_spaces(spaces)


def test_validate_strategy_spaces_rejects_missing_mode_parameter():
    spaces = load_strategy_spaces()
    del spaces["volume_breakout"]["volume_breakout_period"]

    with pytest.raises(ValueError, match="volume_breakout_period"):
        validate_strategy_spaces(spaces)


def test_validate_strategy_spaces_rejects_unknown_parameter():
    spaces = load_strategy_spaces()
    spaces["ensemble"]["rsi_low_typo"] = [40]

    with pytest.raises(ValueError, match="unknown parameter: rsi_low_typo"):
        validate_strategy_spaces(spaces)
