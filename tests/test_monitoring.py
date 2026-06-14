from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from jayu.data import DataFailureError
from jayu.failure_codes import FailureCode, ProcessExitCode, process_exit_code
from jayu.monitoring import classify_failure, compute_health_score, prune_runs, update_health
from jayu.safety import SafetyGateError


class StringCodedError(RuntimeError):
    code = "DATA_DISAGREEMENT"


def test_prune_runs_keeps_newest_count(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    now = datetime.now(UTC)
    for index in range(3):
        path = runs / f"run-{index}"
        path.mkdir()
        timestamp = (now - timedelta(days=index)).timestamp()
        os.utime(path, (timestamp, timestamp))

    removed = prune_runs(runs, max_age_days=30, max_runs=2)

    assert removed == ["run-2"]
    assert not (runs / "run-2").exists()


def test_health_tracks_last_success_and_failure(tmp_path):
    path = tmp_path / "health.json"
    update_health(path, run_id="ok", status="success", summary={"signal_count": 2})
    health = update_health(
        path,
        run_id="bad",
        status="failed",
        error="download failed",
        failure_code="DATA_FAILURE",
    )

    assert health["last_success"]["run_id"] == "ok"
    assert health["last_failure"]["failure_code"] == "DATA_FAILURE"
    assert 0 <= health["health_score"] <= 100
    assert health["health_score"] < health["last_success"]["health_score"]
    assert health["health_components"]
    assert classify_failure(RuntimeError("market data download failed")) == "DATA_FAILURE"
    assert (
        classify_failure(RuntimeError("DATA_CONTRACT_FAILED: signal_dataframe"))
        == "DATA_CONTRACT_FAILED"
    )
    assert (
        classify_failure(
            SafetyGateError(
                FailureCode.SHADOW_PROMOTION_FAILED,
                ["shadow_days"],
            )
        )
        == "SHADOW_PROMOTION_FAILED"
    )
    assert (
        classify_failure(
            DataFailureError(
                "provider values disagree",
                reason_code=FailureCode.DATA_DISAGREEMENT,
            )
        )
        == "DATA_FAILURE"
    )
    assert classify_failure(StringCodedError("provider mismatch")) == "DATA_DISAGREEMENT"


def test_health_score_penalizes_recent_failure_after_recovery():
    now = datetime(2026, 6, 13, 12, tzinfo=UTC)
    recent = {
        "timestamp": (now - timedelta(hours=2)).isoformat(),
        "failure_code": "DATA_FAILURE",
    }
    old = {
        "timestamp": (now - timedelta(days=2)).isoformat(),
        "failure_code": "DATA_FAILURE",
    }

    recent_score = compute_health_score(
        status="success",
        summary={"signal_count": 2, "risk_status": "passed"},
        failure_code=None,
        previous_failure=recent,
        now=now,
    )
    old_score = compute_health_score(
        status="success",
        summary={"signal_count": 2, "risk_status": "passed"},
        failure_code=None,
        previous_failure=old,
        now=now,
    )

    assert recent_score == 90
    assert old_score == 100


def test_process_exit_code_groups_failure_taxonomy_for_operators():
    assert process_exit_code(FailureCode.CONFIG_FAILURE) == ProcessExitCode.CONFIG_FAILURE
    assert process_exit_code(FailureCode.DATA_DISAGREEMENT) == ProcessExitCode.DATA_FAILURE
    assert process_exit_code(FailureCode.BACKTEST_FAILURE) == ProcessExitCode.BACKTEST_FAILURE
    assert (
        process_exit_code(FailureCode.SHADOW_PROMOTION_FAILED) == ProcessExitCode.SAFETY_GATE_FAILED
    )
    assert (
        process_exit_code(FailureCode.NOTIFICATION_FAILURE) == ProcessExitCode.NOTIFICATION_FAILURE
    )
    assert process_exit_code("unknown") == ProcessExitCode.INTERNAL_FAILURE
