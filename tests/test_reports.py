from __future__ import annotations

import json
from pathlib import Path

import pytest

from jayu.io import atomic_write_json
from jayu.reports import (
    equity_curve_svg,
    parameter_importance,
    post_signal_performance,
    risk_decision_rows,
    strategy_attribution,
    trade_cost_stats,
    train_oos_decay,
    write_cost_sensitivity_report,
    write_html_report,
    write_markdown_report,
    write_shadow_performance_report,
    write_signal_performance_report,
)


def test_risk_decision_rows_prefers_structured_codes():
    signals = {
        "SOXL": {
            "action": "buy",
            "eligible": False,
            "approved_position_pct": 0.0,
            "risk": {
                "requested_position_pct": 0.10,
                "violations": ["sector_exposure 65.0% > 50.0%"],
                "violation_details": [{"code": "SECTOR_EXPOSURE_EXCEEDED", "message": "x"}],
                "warnings": [{"code": "UNMAPPED_TICKER", "message": "y"}],
                "resized": False,
                "mapped": False,
            },
        },
        "HOLD1": {"action": "hold"},  # no risk block -> skipped
    }

    rows = risk_decision_rows(signals)

    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "SOXL"
    assert row["reasons"] == ["SECTOR_EXPOSURE_EXCEEDED"]  # structured code preferred
    assert row["warnings"] == ["UNMAPPED_TICKER"]
    assert row["eligible"] is False


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


def test_train_oos_decay_flags_overfitting():
    results = {
        "SOXL": {
            "bull": {
                "metrics": {"fitness": 2.0, "total_return": 30.0},
                "val_metrics": {"fitness": 1.6, "total_return": 24.0},
            },
            "bear": {
                "metrics": {"fitness": 2.0, "total_return": 40.0},
                "val_metrics": {"fitness": -0.1, "total_return": -5.0},
            },
        }
    }

    rows = {(r["ticker"], r["regime"]): r for r in train_oos_decay(results)}

    healthy = rows[("SOXL", "bull")]
    assert healthy["fitness_retention"] == pytest.approx(0.8)
    assert healthy["degraded"] is False

    overfit = rows[("SOXL", "bear")]
    assert overfit["degraded"] is True  # OOS fitness non-positive


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


def test_shadow_signal_performance_rows_include_shadow_fields(tmp_path: Path):
    output = tmp_path / "signal_performance.json"
    report = write_signal_performance_report(
        {
            "SOXL": {
                "action": "buy",
                "signal": "entry",
                "signal_date": "2026-06-01",
                "shadow_status": "pending",
                "shadow_reason": "mode=shadow",
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

    row = report["rows"][0]
    assert row["shadow_status"] == "partial"
    assert row["shadow_reason"] == "awaiting_remaining_horizons"
    assert row["future_return_1d"] == pytest.approx(0.05)


def test_shadow_signal_performance_completes_all_horizons():
    prices = [{"date": f"2026-06-{day:02d}", "close": 100 + day} for day in range(1, 22)]

    report = post_signal_performance(
        {
            "SOXL": {
                "action": "buy",
                "signal": "entry",
                "signal_date": "2026-06-01",
                "shadow_status": "pending",
                "shadow_reason": "mode=shadow",
            }
        },
        {"SOXL": prices},
    )

    row = report["rows"][0]
    assert row["shadow_status"] == "completed"
    assert row["shadow_reason"] == "all_horizons_evaluated"
    assert row["future_return_20d"] is not None


def test_future_signal_date_does_not_fall_back_to_old_prices():
    report = post_signal_performance(
        {
            "SOXL": {
                "action": "buy",
                "signal": "entry",
                "signal_date": "2026-07-01",
                "shadow_status": "pending",
            }
        },
        {
            "SOXL": [
                {"date": "2026-06-01", "close": 100},
                {"date": "2026-06-02", "close": 105},
            ]
        },
    )

    row = report["rows"][0]
    assert row["error"] == "signal_date_not_in_price_history"
    assert row["future_return_1d"] is None
    assert row["shadow_status"] == "pending"


def test_shadow_performance_rollup_updates_source_files(tmp_path: Path):
    shadow_dir = tmp_path / "signals" / "shadow"
    source = shadow_dir / "2026-06-01.json"
    atomic_write_json(
        source,
        {
            "SOXL": {
                "action": "buy",
                "signal": "entry",
                "signal_date": "2026-06-01",
                "shadow_status": "pending",
                "shadow_reason": "mode=shadow",
                "future_return_1d": None,
                "future_return_5d": None,
                "future_return_20d": None,
            }
        },
    )
    prices = {"SOXL": [{"date": f"2026-06-{day:02d}", "close": 100 + day} for day in range(1, 22)]}

    report = write_shadow_performance_report(
        shadow_dir,
        prices,
        tmp_path / "state" / "shadow_performance.json",
    )

    updated = json.loads(source.read_text(encoding="utf-8"))
    assert report["files_processed"] == 1
    assert report["history_signal_count"] == 1
    assert updated["SOXL"]["shadow_status"] == "completed"
    assert updated["SOXL"]["future_return_20d"] is not None


def test_write_cost_sensitivity_report_creates_artifact(tmp_path: Path):
    run_dir = tmp_path / "run"
    atomic_write_json(run_dir / "trades" / "SOXL_bull.json", _net_trades())

    report = write_cost_sensitivity_report(run_dir)

    assert (run_dir / "cost_sensitivity.json").exists()
    assert report["strategy_count"] == 1
    assert report["strategies"][0]["strategy"] == "SOXL_bull"
    assert report["strategies"][0]["fee_slippage_grid"]["combinations"]


def test_cost_sensitivity_report_does_not_approve_without_evidence(tmp_path: Path):
    report = write_cost_sensitivity_report(tmp_path / "run")

    assert report["cost_survival_status"] == "not_evaluated"


def test_cost_sensitivity_report_rejects_failed_signal_gate(tmp_path: Path):
    run_dir = tmp_path / "run"
    atomic_write_json(run_dir / "trades" / "SOXL_bull.json", _net_trades())

    report = write_cost_sensitivity_report(
        run_dir,
        current_round_trip_bps=20,
        approval_buffer_bps=10,
        signals={
            "SOXL": {
                "cost_survival": {
                    "checked": False,
                    "survives": False,
                    "status": "not_evaluated",
                }
            }
        },
    )

    assert report["cost_survival_status"] == "rejected"


def test_write_html_report_includes_equity_svg(tmp_path: Path):
    run_dir = tmp_path / "runs" / "20260613"
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "20260613",
            "status": "success",
            "result": {"signal_count": 2},
            "data_reports": {"SOXL": {"valid": True}},
        },
    )
    atomic_write_json(
        run_dir / "data_sources.json",
        {
            "sources": [
                {
                    "category": "price",
                    "provider": "tiingo",
                    "ticker": "SOXL",
                    "status": "success",
                    "rows": 100,
                    "hash": "abc",
                }
            ]
        },
    )
    atomic_write_json(
        run_dir / "provider_disagreement_report.json",
        {"disagreements": [{"ticker": "SOXL"}]},
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
    atomic_write_json(
        run_dir / "signals_risk.json",
        {
            "SOXL": {
                "action": "buy",
                "eligible": False,
                "approved_position_pct": 0.0,
                "risk": {
                    "requested_position_pct": 0.10,
                    "violation_details": [{"code": "SECTOR_EXPOSURE_EXCEEDED", "message": "x"}],
                    "warnings": [{"code": "UNMAPPED_TICKER", "message": "y"}],
                    "resized": False,
                    "mapped": False,
                },
            }
        },
    )
    write_cost_sensitivity_report(run_dir)
    atomic_write_json(
        run_dir / "risk_explanation.json",
        {
            "signals": [
                {
                    "ticker": "SOXL",
                    "eligible": False,
                    "passed": [{"metric": "cash_pct"}],
                    "failed": [
                        {
                            "code": "SECTOR_EXPOSURE_EXCEEDED",
                            "observed": 0.6,
                            "limit": 0.5,
                            "excess": 0.1,
                        }
                    ],
                }
            ]
        },
    )
    atomic_write_json(
        run_dir / "safety_verdict.json",
        {
            "overall": "blocked",
            "components": {
                "data": {"status": "pass", "reasons": []},
                "risk": {
                    "status": "fail",
                    "reasons": [{"code": "SECTOR_EXPOSURE_EXCEEDED"}],
                },
            },
        },
    )
    atomic_write_json(
        run_dir / "result.json",
        {
            "results": {
                "SOXL": {
                    "bull": {
                        "metrics": {"fitness": 2.0, "total_return": 30.0},
                        "val_metrics": {"fitness": 1.6, "total_return": 24.0},
                    }
                }
            }
        },
    )

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
    # The train->OOS decay section renders from result.json.
    assert "Train → OOS Decay" in content
    assert "Fitness retention" in content
    # The risk-decisions section renders structured block reasons (criterion #12).
    assert "Risk Decisions" in content
    assert "SECTOR_EXPOSURE_EXCEEDED" in content
    assert "UNMAPPED_TICKER" in content
    assert "Data Sources &amp; Quality" in content
    assert "tiingo" in content
    assert "1 provider disagreement reports" in content
    assert "Cost Sensitivity" in content
    assert "Risk Explanation" in content
    assert "Safety Verdict" in content
    assert "blocked" in content

    markdown = write_markdown_report(run_dir)
    markdown_content = markdown.read_text(encoding="utf-8")
    assert "# Jayu Run Summary" in markdown_content
    assert "Safety verdict: `blocked`" in markdown_content
    assert "## Safety Verdict" in markdown_content
    assert "Provider disagreement reports: 1" in markdown_content
