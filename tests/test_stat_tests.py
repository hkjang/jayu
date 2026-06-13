from __future__ import annotations

import numpy as np
import pytest

from jayu.stat_tests import (
    _norm_cdf,
    _norm_ppf,
    candidate_selection_bias,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    observed_sharpe,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)


def test_norm_cdf_and_ppf_roundtrip():
    assert _norm_cdf(0.0) == pytest.approx(0.5)
    for x in (-2.0, -0.5, 0.3, 1.6):
        assert _norm_ppf(_norm_cdf(x)) == pytest.approx(x, abs=1e-6)


def test_observed_sharpe_sign_and_zero():
    assert observed_sharpe([0.01, 0.01, 0.01, 0.01]) == 0.0  # zero variance -> 0
    assert observed_sharpe([1.0]) == 0.0  # too few points
    rng = np.random.default_rng(0)
    positive = rng.normal(0.01, 0.01, 500)
    assert observed_sharpe(positive) > 0


def test_psr_half_at_benchmark_and_monotonic():
    rng = np.random.default_rng(1)
    returns = rng.normal(0.02, 0.05, 1000)
    sr = observed_sharpe(returns)

    # PSR against the observed Sharpe itself is ~0.5.
    assert probabilistic_sharpe_ratio(returns, sr) == pytest.approx(0.5, abs=0.02)
    # A strong positive series easily beats a zero benchmark.
    assert probabilistic_sharpe_ratio(returns, 0.0) > 0.9
    # Raising the benchmark lowers the probability (monotonic).
    assert probabilistic_sharpe_ratio(returns, 0.0) > probabilistic_sharpe_ratio(returns, sr * 1.5)


def test_psr_handles_tiny_sample():
    assert probabilistic_sharpe_ratio([0.01, 0.02], 0.0) == 0.0


def test_psr_handles_constant_return_series():
    assert probabilistic_sharpe_ratio([0.01, 0.01, 0.01], 0.0) == 1.0
    assert probabilistic_sharpe_ratio([-0.01, -0.01, -0.01], 0.0) == 0.0
    assert probabilistic_sharpe_ratio([0.0, 0.0, 0.0], 0.0) == 0.5


def test_expected_max_sharpe_grows_with_trials():
    low = expected_max_sharpe(10, 0.25)
    high = expected_max_sharpe(1000, 0.25)
    assert high > low > 0


def test_deflated_sharpe_drops_with_more_trials():
    rng = np.random.default_rng(2)
    returns = rng.normal(0.03, 0.05, 1000)

    few = deflated_sharpe_ratio(returns, trials=5, sharpe_variance=0.01)
    many = deflated_sharpe_ratio(returns, trials=5000, sharpe_variance=0.01)

    assert few["deflated_benchmark_sharpe"] < many["deflated_benchmark_sharpe"]
    assert few["dsr"] >= many["dsr"]


def test_pbo_low_when_one_strategy_dominates():
    # Strategy 0 beats the rest in every observation -> IS winner always wins OOS.
    rng = np.random.default_rng(3)
    noise = rng.normal(0.0, 0.001, (240, 4))
    matrix = noise.copy()
    matrix[:, 0] += 0.05  # a persistent, genuine edge
    result = probability_of_backtest_overfitting(matrix, blocks=8)

    assert result["pbo"] == pytest.approx(0.0, abs=1e-9)
    assert result["combinations"] == 70  # C(8, 4)


def test_pbo_high_for_pure_noise():
    rng = np.random.default_rng(4)
    matrix = rng.normal(0.0, 0.01, (240, 10))
    result = probability_of_backtest_overfitting(matrix, blocks=10)

    # Pure noise has no real cross-strategy edge, so the in-sample winner
    # systematically fails to generalize (CSCV: complementary splits make a
    # strategy's train and test means negatively dependent). PBO should be high.
    assert result["pbo"] > 0.5
    assert result["mean_logit"] < 0.0


def test_pbo_validates_inputs():
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting(np.zeros((100, 1)))  # need >= 2 strategies
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting(np.zeros((100, 3)), blocks=7)  # odd blocks


def test_candidate_selection_bias_combines_dsr_and_pbo():
    candidates = [
        [0.03, 0.03, 0.03],
        [0.01, 0.00, -0.01],
        [-0.01, 0.01, 0.00],
        [0.00, -0.01, 0.01],
        [-0.03, -0.02, -0.01],
    ]

    evidence = candidate_selection_bias(
        candidates,
        candidates[0],
        trials=500,
        minimum_candidates=5,
        pbo_blocks=2,
    )

    assert evidence["sufficient_candidates"] is True
    assert evidence["candidate_count"] == 5
    assert evidence["evaluated_trials"] == 500
    assert evidence["dsr"] > 0.5
    assert evidence["pbo"] == 0.0


def test_candidate_selection_bias_marks_small_candidate_set_insufficient():
    evidence = candidate_selection_bias(
        [[0.03, 0.02, 0.01], [0.01, 0.00, -0.01]],
        [0.03, 0.02, 0.01],
        trials=10,
        minimum_candidates=5,
        pbo_blocks=2,
    )

    assert evidence["sufficient_candidates"] is False
    assert evidence["pbo"] is None
