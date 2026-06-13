from __future__ import annotations

from pathlib import Path

import pytest

from jayu.io import atomic_write_json
from jayu.reports import (
    equity_curve_svg,
    parameter_importance,
    post_signal_performance,
    strategy_attribution,
    trade_cost_stats,
    write_html_report,
    write_signal_performance_report,
)


def _net_trades():
    return [
        {"gross_return_pct": 3.0, "net_return_pct": 2.7, "fee_cost_pct": 0.3, "position_pct": 10.0},
        {
            "gross_return_pct": -1.0,
            "net_return_pct": -1.3,
            "fee_cost_pct": 0.3,
            "position_pct": 10.0,
        },
        {"gross_return_pct": 2.0, "net_return_pct": 1.7, "fee_cost_pct": 0.3, "position_pct": 10.0},
    ]


def test_trade_cost_stats_summarizes_net_and_psr():
    stats = trade_cost_stats(_net_trades())

    assert stats["trades"] == 3
    assert stats["breakeven_round_trip_bps"] is not None
    assert stats["cost_drag_pct_of_gross"] == pytest.approx(22.5)
    # 3 trades with net_return_pct present -> PSR computed.
    assert stats["psr_vs_zero"] is not None
    assert 0.0 <= stats["psr_vs_zero"] <= 1.0


def test_parameter_importance_ranks_parameter_spread():
    results = {
        "SOXL": {
            "bull": {
                "params": {"strategy_mode": "ensemble", "rsi": 30},
                "val_metrics": {"fitness": 1.0},
            },
            "bear": {
                "params": {"strategy_mode": "ensemble", "rsi": 70},
                "val_metrics": {"fitness": 0.2},
            },
        }
    }

    rows = parameter_importance(results)

    assert rows[0]["parameter"] == "rsi"
    assert rows[0]["importance"] == pytest.approx(0.8)


def test_strategy_attribution_separates_modes():
    rows = strategy_attribution(
        [
            {"strategy_mode": "ensemble", "ret": 0.1},
            {"strategy_mode": "ensemble", "ret": -0.02},
            {"strategy_mode": "connors_rsi2", "net_return_pct": 3.0},
        ]
    )

    by_mode = {row["strategy_mode"]: row for row in rows}
    assert by_mode["ensemble"]["trade_count"] == 2
    assert by_mode["connors_rsi2"]["total_return"] == pytest.approx(0.03)


def test_post_signal_performance_uses_future_horizons():
    report = post_signal_performance(
        {"SOXL": {"action": "buy", "signal_date": "2026-06-01"}},
        {
            "SOXL": [
                {"date": "2026-06-01", "close": 100},
                {"date": "2026-06-02", "close": 105},
                {"date": "2026-06-03", "close": 103},
                {"date": "2026-06-04", "close": 110},
                {"date": "2026-06-05", "close": 111},
                {"date": "2026-06-06", "close": 120},
            ]
        },
        horizons=(1, 5),
    )

    assert report["signals_evaluated"] == 1
    assert report["aggregate"]["1d"] == pytest.approx(0.05)
    assert report["aggregate"]["5d"] == pytest.approx(0.20)


def test_signal_performance_report_accumulates_and_updates_horizons(tmp_path: Path):
    output = tmp_path / "signal_performance.json"
    first = write_signal_performance_report(
        {
            "SOXL": {
                "action": "buy",
                "signal": "entry",
                "signal_date": "2026-06-01",
            }
        },
        {
            "SOXL": [
                {"date": "2026-06-01", "close": 100},
                {"date": "2026-06-02", "close": 105},
            ]
        },
        output,
    )
    second = write_signal_performance_report(
        {
            "SOXL": {
                "action": "buy",
                "signal": "entry",
                "signal_date": "2026-06-01",
            },
            "TQQQ": {
                "action": "buy",
                "signal": "entry",
                "signal_date": "2026-06-02",
            },
        },
        {
            "SOXL": [
                {"date": "2026-06-01", "close": 100},
                {"date": "2026-06-02", "close": 105},
                {"date": "2026-06-03", "close": 110},
                {"date": "2026-06-04", "close": 115},
                {"date": "2026-06-05", "close": 118},
                {"date": "2026-06-06", "close": 120},
            ],
            "TQQQ": [
                {"date": "2026-06-02", "close": 50},
                {"date": "2026-06-03", "close": 51},
            ],
        },
        output,
    )

    assert first["history_signal_count"] == 1
    assert second["history_signal_count"] == 2
    soxl = next(row for row in second["history_rows"] if row["ticker"] == "SOXL")
    assert soxl["returns"]["1d"] == pytest.approx(0.05)
    assert soxl["returns"]["5d"] == pytest.approx(0.20)
    assert second["cumulative_aggregate"]["1d"] == pytest.approx(0.035)


def test_write_html_report_includes_equity_svg(tmp_path: Path):
    run_dir = tmp_path / "runs" / "20260613"
    atomic_write_json(
        run_dir / "manifest.json",
        {"run_id": "20260613", "status": "success", "result": {"signal_count": 2}},
    )
    atomic_write_json(
        run_dir / "equity" / "SOXL_bull.json",
        [{"date": "2026-06-01", "equity": 100}, {"date": "2026-06-02", "equity": 110}],
    )
    atomic_write_json(
        run_dir / "parameter_importance.json",
        [{"parameter": "rsi", "importance": 0.5, "best_value": "30", "sample_count": 2}],
    )
    atomic_write_json(
        run_dir / "validation_report.json",
        {
            "SOXL": {
                "bull": {
                    "approved": True,
                    "reasons": [],
                    "statistical_evidence": {"psr_vs_zero": 0.91},
                    "selection_bias": {
                        "approved": True,
                        "evidence": {
                            "dsr": 0.87,
                            "pbo": 0.25,
                            "candidate_count": 12,
                        },
                    },
                    "final_lockbox": {
                        "approved": True,
                        "lockbox_retention": 0.72,
                        "reused": False,
                    },
                }
            }
        },
    )

    atomic_write_json(run_dir / "trades" / "SOXL_bull.json", _net_trades())

    output = write_html_report(run_dir)

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Jayu Run Report" in content
    assert "<svg" in equity_curve_svg([{"equity": 100}, {"equity": 110}])
    assert "SOXL_bull.json" in content
    # The net/overfitting section renders from the trades artifact.
    assert "Net &amp; Overfitting" in content
    assert "PSR vs 0" in content
    assert "OOS Validation" in content
    assert "0.91" in content
    assert "0.87" in content
    assert "0.25" in content
    assert "0.72" in content
