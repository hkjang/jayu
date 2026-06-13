from __future__ import annotations

import pytest

from jayu.performance import (
    FITNESS_VERSION,
    calc_metrics,
    cost_bridge,
    equity_curve_records,
)


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


def test_metrics_report_net_basis_with_cost_bridge():
    metrics = calc_metrics(
        _trades(),
        1040.1,
        [1000.0, 1020.0, 1009.8, 1040.1],
        min_trades=1,
    )

    assert metrics["returns_basis"] == "net"
    bridge = metrics["cost_bridge"]
    # _trades() carry only ``ret`` (already net), so cost detail is unavailable
    # and the bridge degrades to net-only rather than pretending costs were zero.
    assert bridge["has_cost_detail"] is False
    assert bridge["avg_gross_return_pct"] == bridge["avg_net_return_pct"]


def test_cost_bridge_is_exact_when_detail_present():
    trades = [
        {
            "raw_return_pct": 3.0,
            "slippage_cost_pct": 0.1,
            "fee_cost_pct": 0.3,
            "net_return_pct": 2.6,
            "ret": 2.6,
        },
        {
            "raw_return_pct": -1.0,
            "slippage_cost_pct": 0.1,
            "fee_cost_pct": 0.3,
            "net_return_pct": -1.4,
            "ret": -1.4,
        },
    ]

    bridge = cost_bridge(trades)

    assert bridge["has_cost_detail"] is True
    # gross − slippage − fee == net, exactly and additively.
    assert bridge["total_gross_return_pct"] == pytest.approx(2.0)
    assert bridge["total_slippage_cost_pct"] == pytest.approx(0.2)
    assert bridge["total_fee_cost_pct"] == pytest.approx(0.6)
    assert bridge["total_net_return_pct"] == pytest.approx(1.2)
    assert bridge["total_gross_return_pct"] - bridge["total_slippage_cost_pct"] - bridge[
        "total_fee_cost_pct"
    ] == pytest.approx(bridge["total_net_return_pct"])
    assert bridge["cost_drag_pct_of_gross"] == pytest.approx(40.0)


def test_metrics_surface_breakeven_and_cost_sensitivity():
    metrics = calc_metrics(
        _trades(),
        1040.1,
        [1000.0, 1020.0, 1009.8, 1040.1],
        min_trades=1,
    )

    assert "breakeven_round_trip_bps" in metrics
    assert "cost_sensitivity" in metrics
    assert "annual_turnover" in metrics
    # Turnover-adjusted fitness is reported but must not replace the canonical one.
    assert "fitness_turnover_adjusted" in metrics
    assert 0.0 < metrics["turnover_penalty"] <= 1.0
    assert metrics["fitness_turnover_adjusted"] <= metrics["fitness"]
    bps_levels = [level["round_trip_bps"] for level in metrics["cost_sensitivity"]["levels"]]
    assert bps_levels == [0, 5, 10, 20, 50]


def test_cost_bridge_handles_empty_trades():
    bridge = cost_bridge([])

    assert bridge["trades"] == 0
    assert bridge["has_cost_detail"] is False
    assert bridge["total_net_return_pct"] == 0.0


def test_equity_curve_is_daily_and_forward_filled():
    records = equity_curve_records(
        _trades(),
        [1000.0, 1020.0, 1009.8, 1040.1],
    )

    assert len(records) > len(_trades())
    assert records[0]["daily_return"] == 0.0
