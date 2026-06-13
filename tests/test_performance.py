from __future__ import annotations

from jayu.performance import FITNESS_VERSION, calc_metrics, equity_curve_records


def _trades():
    return [
        {
            "ret": 2.0,
            "pnl": 20.0,
            "mae": -1.0,
            "exit_date": "2026-01-05",
            "capital_after": 1020.0,
        },
        {
            "ret": -1.0,
            "pnl": -10.2,
            "mae": -2.0,
            "exit_date": "2026-01-08",
            "capital_after": 1009.8,
        },
        {
            "ret": 3.0,
            "pnl": 30.3,
            "mae": -0.5,
            "exit_date": "2026-01-12",
            "capital_after": 1040.1,
        },
    ]


def test_daily_and_trade_sharpe_are_separate_and_versioned():
    metrics = calc_metrics(
        _trades(),
        1040.1,
        [1000.0, 1020.0, 1009.8, 1040.1],
        min_trades=1,
    )

    assert metrics["fitness_version"] == FITNESS_VERSION
    assert "daily_sharpe" in metrics
    assert "trade_sharpe" in metrics
    assert metrics["sortino_basis"].startswith("daily returns")
    assert metrics["calmar_basis"].startswith("annualized return")
    assert metrics["mdd_peak"] is not None
    assert metrics["mdd_trough"] is not None


def test_equity_curve_is_daily_and_forward_filled():
    records = equity_curve_records(
        _trades(),
        [1000.0, 1020.0, 1009.8, 1040.1],
    )

    assert len(records) > len(_trades())
    assert records[0]["daily_return"] == 0.0
