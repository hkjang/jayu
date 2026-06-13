from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json


def classify_failure(exc: Exception) -> str:
    explicit_code = getattr(exc, "code", None)
    if isinstance(explicit_code, FailureCode):
        return explicit_code.value
    text = f"{type(exc).__name__}: {exc}".lower()
    module = type(exc).__module__.lower()
    if FailureCode.DATA_CONTRACT_FAILED.value.lower() in text or "datacontracterror" in text:
        return FailureCode.DATA_CONTRACT_FAILED.value
    if FailureCode.DATA_DISAGREEMENT.value.lower() in text or "disagreement" in text:
        return FailureCode.DATA_DISAGREEMENT.value
    if "kakao" in text or "notification" in text or "notifications" in module:
        return FailureCode.NOTIFICATION_FAILURE.value
    if "config" in text or "settings" in module or "validationerror" in text:
        return FailureCode.CONFIG_FAILURE.value
    if any(token in text for token in ("market data", "provider", "ohlcv", "download")):
        return FailureCode.DATA_FAILURE.value
    if any(token in text for token in ("backtest", "strategy", "parameter")):
        return FailureCode.BACKTEST_FAILURE.value
    return FailureCode.INTERNAL_FAILURE.value


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
    now = datetime.now(UTC)
    assessment = health_assessment(
        status=status,
        summary=summary or {},
        failure_code=failure_code,
        previous_failure=health.get("last_failure") if isinstance(health, dict) else None,
        now=now,
    )
    health_score = assessment["score"]
    health["last_run"] = {
        "run_id": run_id,
        "status": status,
        "timestamp": now.isoformat(),
        "summary": summary,
        "error": error,
        "failure_code": failure_code,
        "health_score": health_score,
        "health_components": assessment["components"],
    }
    health["health_score"] = health_score
    health["health_components"] = assessment["components"]
    if status == "success":
        health["last_success"] = health["last_run"]
    else:
        health["last_failure"] = health["last_run"]
    atomic_write_json(path, health)
    return health


def compute_health_score(
    *,
    status: str,
    summary: dict[str, Any],
    failure_code: str | None,
    previous_failure: Any,
    now: datetime | None = None,
) -> int:
    return health_assessment(
        status=status,
        summary=summary,
        failure_code=failure_code,
        previous_failure=previous_failure,
        now=now,
    )["score"]


def health_assessment(
    *,
    status: str,
    summary: dict[str, Any],
    failure_code: str | None,
    previous_failure: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    score = 100
    components: list[dict[str, Any]] = []

    def deduct(code: str, points: int, detail: Any = None) -> None:
        nonlocal score
        score -= points
        components.append({"code": code, "deduction": points, "detail": detail})

    if status != "success":
        deduct("RUN_FAILED", 45)
    if failure_code == FailureCode.DATA_CONTRACT_FAILED.value:
        deduct(FailureCode.DATA_CONTRACT_FAILED.value, 35)
    elif failure_code == FailureCode.DATA_DISAGREEMENT.value:
        deduct(FailureCode.DATA_DISAGREEMENT.value, 30)
    elif failure_code in {FailureCode.DATA_FAILURE.value, FailureCode.NOTIFICATION_FAILURE.value}:
        deduct(str(failure_code), 25)
    failed = summary.get("failed_ticker_count")
    if isinstance(failed, (int, float)) and failed:
        deduct("FAILED_TICKERS", min(25, int(failed) * 10), int(failed))
    signals = summary.get("signal_count")
    if isinstance(signals, (int, float)) and signals == 0:
        deduct("NO_SIGNALS", 10)
    if summary.get("risk_status") in {"failed", "blocked"}:
        deduct("RISK_BLOCKED", 20)
    notification = summary.get("notification")
    if isinstance(notification, dict) and (
        notification.get("ok") is False or notification.get("status") in {"failed", "error"}
    ):
        deduct(FailureCode.NOTIFICATION_FAILURE.value, 20)
    if _is_recent_failure(previous_failure, now=now):
        deduct("RECENT_FAILURE", 10, previous_failure.get("failure_code"))
    final_score = max(0, min(100, score))
    return {
        "score": final_score,
        "components": components or [{"code": "HEALTHY", "deduction": 0}],
    }


def _is_recent_failure(previous_failure: Any, *, now: datetime | None) -> bool:
    if not isinstance(previous_failure, dict):
        return False
    timestamp = previous_failure.get("timestamp")
    if not isinstance(timestamp, str):
        return False
    try:
        occurred_at = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    return timedelta(0) <= reference - occurred_at <= timedelta(hours=24)
