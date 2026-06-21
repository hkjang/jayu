from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jayu.io import atomic_write_json, read_json
from jayu.signal_stability import (
    build_signal_stability_from_runs,
    build_signal_stability_report,
    write_signal_stability_report,
)


def test_signal_stability_scores_flipping_tickers() -> None:
    snapshots = [
        {"ticker": "SOXL", "occurred_at": "2026-06-20T00:00:00+00:00", "signal_state": "buy"},
        {"ticker": "SOXL", "occurred_at": "2026-06-21T00:00:00+00:00", "signal_state": "hold"},
        {"ticker": "SOXL", "occurred_at": "2026-06-22T00:00:00+00:00", "signal_state": "buy"},
        {"ticker": "TQQQ", "occurred_at": "2026-06-20T00:00:00+00:00", "signal_state": "buy"},
        {"ticker": "TQQQ", "occurred_at": "2026-06-21T00:00:00+00:00", "signal_state": "buy"},
        {"ticker": "TQQQ", "occurred_at": "2026-06-22T00:00:00+00:00", "signal_state": "buy"},
    ]

    report = build_signal_stability_report(
        snapshots,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    items = {item["ticker"]: item for item in report["items"]}
    assert items["SOXL"]["status"] == "unstable"
    assert items["SOXL"]["signal_stability_score"] == 0
    assert items["SOXL"]["auto_candidate_excluded"] is True
    assert items["SOXL"]["windows"]["5d"]["transition_count"] == 2
    assert items["TQQQ"]["status"] == "stable"
    assert items["TQQQ"]["signal_stability_score"] == 100
    assert report["summary"]["auto_candidate_excluded_count"] == 1


def test_signal_stability_from_runs_and_writer(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for index, state in enumerate(["buy", "hold", "buy"], start=1):
        run = runs / f"run-00{index}"
        run.mkdir(parents=True)
        atomic_write_json(
            run / "manifest.json",
            {
                "run_id": run.name,
                "status": "success",
                "finished_at": f"2026-06-2{index}T00:00:00+00:00",
            },
        )
        atomic_write_json(
            run / "signals_risk.json",
            {
                "SOXL": {
                    "action": state,
                    "eligible": state == "buy",
                    "blocked": False,
                }
            },
        )

    report = build_signal_stability_from_runs(
        runs,
        now=datetime(2026, 6, 23, tzinfo=UTC),
    )
    output = tmp_path / "state" / "signal_stability.json"
    saved = write_signal_stability_report(
        runs,
        output,
        now=datetime(2026, 6, 23, tzinfo=UTC),
    )

    assert report["items"][0]["ticker"] == "SOXL"
    assert report["items"][0]["status"] == "unstable"
    assert saved["items"][0]["auto_candidate_allowed"] is False
    assert read_json(output)["summary"]["unstable_count"] == 1
