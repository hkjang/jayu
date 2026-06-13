from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json


def classify_failure(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    module = type(exc).__module__.lower()
    if "kakao" in text or "notification" in text or "notifications" in module:
        return "NOTIFICATION_FAILURE"
    if "config" in text or "settings" in module or "validationerror" in text:
        return "CONFIG_FAILURE"
    if any(token in text for token in ("market data", "provider", "ohlcv", "download")):
        return "DATA_FAILURE"
    if any(token in text for token in ("backtest", "strategy", "parameter")):
        return "BACKTEST_FAILURE"
    return "INTERNAL_FAILURE"


def prune_runs(
    runs_dir: Path,
    *,
    max_age_days: int,
    max_runs: int,
    keep: Path | None = None,
) -> list[str]:
    if not runs_dir.exists():
        return []
    root = runs_dir.resolve()
    keep_resolved = keep.resolve() if keep else None
    directories = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    removed = []
    for index, path in enumerate(directories):
        resolved = path.resolve()
        if resolved.parent != root or resolved == keep_resolved:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if index >= max_runs or modified < cutoff:
            shutil.rmtree(resolved)
            removed.append(path.name)
    return removed


def update_health(
    path: Path,
    *,
    run_id: str,
    status: str,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
    failure_code: str | None = None,
) -> dict[str, Any]:
    health = read_json(path, default={}) or {}
    now = datetime.now(UTC).isoformat()
    health["last_run"] = {
        "run_id": run_id,
        "status": status,
        "timestamp": now,
        "summary": summary,
        "error": error,
        "failure_code": failure_code,
    }
    if status == "success":
        health["last_success"] = health["last_run"]
    else:
        health["last_failure"] = health["last_run"]
    atomic_write_json(path, health)
    return health
