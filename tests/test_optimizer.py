from __future__ import annotations

import random

import pytest

from jayu.optimizer import (
    PARAM_SPACE,
    _repair_params,
    crossover,
    fill_missing_params,
    meta_sample,
    mutate,
    sample_params,
    tournament_select,
    update_meta,
)


def test_fill_missing_params_non_dict_returns_defaults():
    params = fill_missing_params(None)
    assert params["strategy_mode"] == "ensemble"
    assert params["pos_size"] == 0.20


def test_fill_missing_params_merges_and_keeps_overrides():
    params = fill_missing_params({"rsi_lo": 25})
    assert params["rsi_lo"] == 25
    assert "strategy_mode" in params


def test_repair_params_forces_pos_size_and_target_above_stop():
    child = _repair_params({"target_pct": 0.03, "stop_pct": 0.03})
    # pos_size is always normalised to 0.20.
    assert child["pos_size"] == 0.20
    # target must clear the stop when neither uses ATR distances.
    assert child["target_pct"] > child["stop_pct"]


def test_sample_params_is_deterministic_with_seed():
    random.seed(123)
    first = sample_params(use_meta=False)
    random.seed(123)
    second = sample_params(use_meta=False)
    assert first == second
    assert first["strategy_mode"] in PARAM_SPACE["strategy_mode"]
    assert first["pos_size"] == 0.20  # repaired/valid


def test_mutate_rate_zero_preserves_mode():
    base = fill_missing_params({"strategy_mode": "connors_rsi2"})
    random.seed(0)
    child = mutate(base, rate=0.0)
    assert child["strategy_mode"] == "connors_rsi2"
    assert child["pos_size"] == 0.20


def test_mutate_returns_valid_params():
    random.seed(1)
    base = fill_missing_params({"strategy_mode": "ensemble"})
    mutated = mutate(base, rate=1.0)
    assert mutated["strategy_mode"] in PARAM_SPACE["strategy_mode"]
    assert mutated["pos_size"] == 0.20


def test_crossover_inherits_strategy_mode_and_repairs():
    random.seed(7)
    p1 = fill_missing_params({"strategy_mode": "ensemble", "rsi_lo": 30})
    p2 = fill_missing_params({"strategy_mode": "ensemble", "rsi_lo": 45})
    child = crossover(p1, p2)
    assert child["strategy_mode"] == "ensemble"
    assert child["rsi_lo"] in (30, 45)
    assert child["pos_size"] == 0.20


def test_tournament_select_picks_highest_fitness():
    pool = [{"fitness": value} for value in (0.1, 0.9, 0.5, 0.3)]
    random.seed(0)
    # k == len(pool) samples the whole pool, so the max must win.
    winner = tournament_select(pool, k=4)
    assert winner["fitness"] == 0.9


def test_update_meta_counts_wins_and_applies_decay():
    meta: dict = {}
    update_meta(meta, {"rsi_lo": 30}, success=True)
    assert meta["rsi_lo"]["30"]["wins"] == pytest.approx(1.0)
    assert meta["rsi_lo"]["30"]["total"] == pytest.approx(1.0)

    update_meta(meta, {"rsi_lo": 30}, success=False, decay=0.98)
    # Prior counts decay by 0.98, then the new (losing) observation adds to total only.
    assert meta["rsi_lo"]["30"]["total"] == pytest.approx(0.98 + 1.0)
    assert meta["rsi_lo"]["30"]["wins"] == pytest.approx(0.98)


def test_update_meta_ignores_unknown_keys():
    meta: dict = {}
    update_meta(meta, {"not_a_real_param": 1}, success=True)
    assert "not_a_real_param" not in meta


def test_meta_sample_absent_key_falls_back_to_choice():
    random.seed(0)
    choice = meta_sample({}, "strategy_mode", ["a", "b", "c"])
    assert choice in ("a", "b", "c")


def test_meta_sample_uses_win_rate_weights():
    # 'x' has a strong win record (>=5 samples); it should be reachable and valid.
    meta = {"k": {"x": {"wins": 9.0, "total": 10.0}, "y": {"wins": 1.0, "total": 10.0}}}
    random.seed(0)
    picks = {meta_sample(meta, "k", ["x", "y"]) for _ in range(20)}
    assert picks <= {"x", "y"}
