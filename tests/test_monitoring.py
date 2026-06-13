from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from jayu.monitoring import classify_failure, prune_runs, update_health


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
    assert classify_failure(RuntimeError("market data download failed")) == "DATA_FAILURE"
