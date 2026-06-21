from __future__ import annotations

from pathlib import Path

import pytest

from jayu.io import read_json
from jayu.signal_outcome import evaluate_signal_outcomes, write_signal_outcome_report


def test_signal_outcome_groups_buy_hold_blocked_and_strategy() -> None:
    report = evaluate_signal_outcomes(
        {
            "SOXL": {
                "action": "buy",
                "eligible": True,
                "signal_date": "2026-06-01",
                "strategy_mode": "momentum",
            },
            "TQQQ": {
                "action": "buy",
                "eligible": False,
                "blocked": True,
                "signal_date": "2026-06-01",
                "strategy_mode": "momentum",
            },
            "QQQ": {
                "action": "hold",
                "signal_date": "2026-06-01",
                "strategy_mode": "baseline",
            },
        },
        {
            "SOXL": [
                {"date": "2026-06-01", "close": 100},
                {"date": "2026-06-02", "close": 105},
                {"date": "2026-06-03", "close": 106},
                {"date": "2026-06-04", "close": 108},
                {"date": "2026-06-05", "close": 110},
                {"date": "2026-06-06", "close": 120},
            ],
            "TQQQ": [
                {"date": "2026-06-01", "close": 50},
                {"date": "2026-06-02", "close": 45},
                {"date": "2026-06-03", "close": 44},
                {"date": "2026-06-04", "close": 42},
                {"date": "2026-06-05", "close": 41},
                {"date": "2026-06-06", "close": 40},
            ],
            "QQQ": [
                {"date": "2026-06-01", "close": 100},
                {"date": "2026-06-02", "close": 101},
                {"date": "2026-06-03", "close": 99},
                {"date": "2026-06-04", "close": 102},
                {"date": "2026-06-05", "close": 104},
                {"date": "2026-06-06", "close": 103},
            ],
        },
        horizons=(1, 5),
    )

    assert report["status"] == "success"
    assert report["summary"]["buy_candidate_count"] == 1
    assert report["summary"]["blocked_buy_count"] == 1
    assert report["summary"]["hold_count"] == 1
    by_group = {item["key"]: item for item in report["by_decision_group"]}
    assert by_group["buy_candidate"]["horizons"]["1d"]["avg_return"] == pytest.approx(0.05)
    assert by_group["blocked_buy"]["horizons"]["1d"]["avg_return"] == pytest.approx(-0.10)
    assert by_group["hold"]["horizons"]["5d"]["avg_return"] == pytest.approx(0.03)
    by_strategy = {item["key"]: item for item in report["by_strategy"]}
    assert by_strategy["momentum"]["signal_count"] == 2
    assert report["blocked_avoidance"]["1d"]["avoided_loss_count"] == 1
    assert report["blocked_avoidance"]["1d"]["avg_avoided_loss"] == pytest.approx(0.10)


def test_write_signal_outcome_report_accumulates_history(tmp_path: Path) -> None:
    output = tmp_path / "signal_outcome.json"
    first = write_signal_outcome_report(
        {
            "SOXL": {
                "action": "buy",
                "eligible": True,
                "signal_date": "2026-06-01",
                "strategy_mode": "momentum",
            }
        },
        {
            "SOXL": [
                {"date": "2026-06-01", "close": 100},
                {"date": "2026-06-02", "close": 105},
            ]
        },
        output,
        horizons=(1, 5),
    )
    second = write_signal_outcome_report(
        {
            "SOXL": {
                "action": "buy",
                "eligible": True,
                "signal_date": "2026-06-01",
                "strategy_mode": "momentum",
            },
            "TQQQ": {
                "action": "buy",
                "eligible": False,
                "blocked": True,
                "signal_date": "2026-06-02",
                "strategy_mode": "momentum",
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
                {"date": "2026-06-03", "close": 45},
                {"date": "2026-06-04", "close": 44},
                {"date": "2026-06-05", "close": 42},
                {"date": "2026-06-06", "close": 41},
                {"date": "2026-06-07", "close": 40},
            ],
        },
        output,
        horizons=(1, 5),
    )

    assert first["history_signal_count"] == 1
    assert second["history_signal_count"] == 2
    assert second["cumulative"]["aggregate"]["5d"]["sample_count"] == 2
    assert second["blocked_avoidance"]["1d"]["avg_avoided_loss"] == pytest.approx(0.10)
    saved = read_json(output)
    assert saved["history_signal_count"] == 2
