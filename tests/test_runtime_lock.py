from datetime import UTC, datetime, timedelta

import pytest

from jayu.runtime_lock import OperationalRunConflict, OperationalRunLock


def test_operational_lock_blocks_concurrent_run_and_releases(tmp_path):
    path = tmp_path / "state" / "operational_run.lock"
    now = datetime(2026, 6, 14, 9, tzinfo=UTC)
    first = OperationalRunLock(path, "signal", "live", 180, now=lambda: now)
    second = OperationalRunLock(path, "signal", "shadow", 180, now=lambda: now)

    first.acquire()
    with pytest.raises(OperationalRunConflict):
        second.acquire()

    first.release()
    second.acquire()
    assert path.exists()
    second.release()
    assert not path.exists()


def test_operational_lock_recovers_stale_owner(tmp_path):
    path = tmp_path / "state" / "operational_run.lock"
    acquired_at = datetime(2026, 6, 14, 6, tzinfo=UTC)
    stale = OperationalRunLock(path, "signal", "live", 60, now=lambda: acquired_at)
    stale.acquire()

    current = OperationalRunLock(
        path,
        "signal",
        "live",
        60,
        now=lambda: acquired_at + timedelta(minutes=61),
    )
    payload = current.acquire()

    assert payload["owner_id"] == current.owner_id
    stale.release()
    assert path.exists()
    current.release()
    assert not path.exists()
