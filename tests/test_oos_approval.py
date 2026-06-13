import pandas as pd

import jayu.backtest_core as backtest_core
from jayu.settings import ResearchSettings
from jayu.validation import WalkForwardFold


def _validation_metrics(returns):
    folds = [
        {
            "fold": index,
            "validation": {"total_return": value},
        }
        for index, value in enumerate(returns)
    ]
    return {
        "total_return": sum(returns) / len(returns),
        "windows": len(returns),
        "pass_rate": sum(value > 0 for value in returns) / len(returns),
        "folds": folds,
        "statistical_evidence": backtest_core.oos_statistical_evidence(
            [fold["validation"] for fold in folds],
            minimum_observations=3,
        ),
    }


def test_oos_statistical_evidence_reports_psr():
    evidence = backtest_core.oos_statistical_evidence(
        [{"total_return": 3.0}, {"total_return": 2.0}, {"total_return": 1.0}],
        minimum_observations=3,
    )

    assert evidence["return_observations"] == 3
    assert evidence["psr_vs_zero"] > 0.5


def test_assess_validation_rejects_low_psr(monkeypatch):
    monkeypatch.setattr(backtest_core, "_ACTIVE_RESEARCH", ResearchSettings())
    result = backtest_core.assess_validation(
        {"total_return": 10.0},
        _validation_metrics([4.0, 3.0, -20.0]),
    )

    assert result["approved"] is False
    assert "out_of_sample_psr_below_threshold" in result["reasons"]


def test_assess_validation_accepts_consistent_positive_oos(monkeypatch):
    monkeypatch.setattr(backtest_core, "_ACTIVE_RESEARCH", ResearchSettings())
    result = backtest_core.assess_validation(
        {"total_return": 10.0},
        _validation_metrics([3.0, 2.0, 1.0]),
    )

    assert result["approved"] is True
    assert result["statistical_evidence"]["psr_vs_zero"] > 0.5


def test_multi_window_validation_requires_every_fold(monkeypatch):
    monkeypatch.setattr(backtest_core, "_ACTIVE_RESEARCH", ResearchSettings())
    splits = [
        WalkForwardFold(index, index * 10, index * 10 + 5, index * 10 + 6, index * 10 + 9, 1, 0)
        for index in range(3)
    ]
    monkeypatch.setattr(backtest_core, "purged_walk_forward_splits", lambda *args, **kwargs: splits)
    monkeypatch.setattr(backtest_core, "backtest", lambda *args, **kwargs: ([], 100.0, [100.0]))
    train = {"fitness": 1.0, "win_rate": 60.0, "profit_factor": 2.0, "total_return": 5.0}
    validation = {
        "fitness": 1.0,
        "total_return": 2.0,
        "win_rate": 55.0,
        "daily_sharpe": 1.0,
        "max_drawdown": 2.0,
    }
    metrics = iter([train, validation, train, None, train, validation])
    monkeypatch.setattr(backtest_core, "calc_metrics", lambda *args, **kwargs: next(metrics))

    result = backtest_core.multi_window_validate(pd.DataFrame({"Close": range(40)}), {})

    assert result == (None, None)


def test_candidate_selection_approval_uses_dsr_and_pbo(monkeypatch):
    monkeypatch.setattr(backtest_core, "_ACTIVE_RESEARCH", ResearchSettings())
    candidates = [
        [0.03, 0.03, 0.03],
        [0.01, 0.00, -0.01],
        [-0.01, 0.01, 0.00],
        [0.00, -0.01, 0.01],
        [-0.03, -0.02, -0.01],
    ]

    result = backtest_core.assess_candidate_selection(
        candidates,
        candidates[0],
        evaluated_trials=500,
    )

    assert result["approved"] is True
    assert result["evidence"]["dsr"] > 0.5
    assert result["evidence"]["pbo"] == 0.0


def test_candidate_selection_rejects_insufficient_candidates(monkeypatch):
    monkeypatch.setattr(backtest_core, "_ACTIVE_RESEARCH", ResearchSettings())

    result = backtest_core.assess_candidate_selection(
        [[0.03, 0.02, 0.01], [0.01, 0.00, -0.01]],
        [0.03, 0.02, 0.01],
        evaluated_trials=10,
    )

    assert result["approved"] is False
    assert "insufficient_candidates_for_selection_bias_test" in result["reasons"]
