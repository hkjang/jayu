from __future__ import annotations

from datetime import UTC, datetime

from jayu.failure_patterns import build_failure_patterns_report, write_failure_patterns_report
from jayu.io import atomic_write_json


def _write_pattern_run(
    runs_dir,
    run_id: str,
    *,
    status: str,
    code: str | None,
    finished_at: str,
) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_id,
            "command": "signal",
            "execution_mode": "shadow",
            "status": status,
            "started_at": finished_at,
            "finished_at": finished_at,
            "failure_code": code,
            "result": {"mode": "shadow"},
        },
    )
    if code:
        atomic_write_json(
            run_dir / "safety_verdict.json",
            {"overall": "blocked", "reasons": [{"code": code}]},
        )
        atomic_write_json(
            run_dir / "risk_explanation.json",
            {"top_block_reasons": [{"code": code, "count": 1}]},
        )


def test_failure_patterns_detects_repeated_latest_streak(tmp_path):
    runs_dir = tmp_path / "runs"
    _write_pattern_run(
        runs_dir,
        "run-001",
        status="failed",
        code="SURVIVORSHIP_GATE_FAILED",
        finished_at="2026-06-21T00:00:00+00:00",
    )
    _write_pattern_run(
        runs_dir,
        "run-002",
        status="failed",
        code="SURVIVORSHIP_GATE_FAILED",
        finished_at="2026-06-22T00:00:00+00:00",
    )
    _write_pattern_run(
        runs_dir,
        "run-000",
        status="success",
        code=None,
        finished_at="2026-06-20T00:00:00+00:00",
    )

    report = build_failure_patterns_report(
        runs_dir,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["summary"]["active_streak_code"] == "SURVIVORSHIP_GATE_FAILED"
    assert report["summary"]["active_streak_count"] == 2
    assert report["summary"]["repeated_code_count"] == 1
    pattern = report["patterns"][0]
    assert pattern["code"] == "SURVIVORSHIP_GATE_FAILED"
    assert pattern["count"] == 2
    assert pattern["action"]["page"] == "settings"


def test_failure_patterns_write_report(tmp_path):
    runs_dir = tmp_path / "runs"
    _write_pattern_run(
        runs_dir,
        "run-001",
        status="failed",
        code="DATA_DISAGREEMENT",
        finished_at="2026-06-22T00:00:00+00:00",
    )
    output = tmp_path / "failure_patterns.json"

    report = write_failure_patterns_report(runs_dir, output)

    assert output.exists()
    assert report["summary"]["latest_failure_code"] == "DATA_DISAGREEMENT"
