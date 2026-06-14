"""Operator-facing readiness snapshot for Jayu runs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json
from .paths import RuntimePaths
from .safety import evaluate_shadow_promotion
from .settings import Settings


def latest_run_dir(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    candidates = [path for path in runs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_operational_status(
    paths: RuntimePaths,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = now or datetime.now(UTC)
    health = _mapping(read_json(paths.state_dir / "health.json", default={}))
    latest_dir = latest_run_dir(paths.runs_dir)
    latest_run = _latest_run_summary(latest_dir, now=reference) if latest_dir else None
    promotion = (
        evaluate_shadow_promotion(
            paths.signals_dir / "shadow",
            paths.state_dir / "health.json",
            settings.promotion,
            now=reference,
        )
        if settings.promotion.enabled
        else {"eligible": True, "disabled": True, "criteria": [], "metrics": {}}
    )
    health_score = health.get("health_score")
    health_ok = (
        isinstance(health_score, (int, float))
        and health_score >= settings.promotion.min_health_score
    )
    reasons = _readiness_reasons(
        latest_run=latest_run,
        promotion=promotion,
        health_score=health_score,
        min_health_score=settings.promotion.min_health_score,
        max_ready_run_age_hours=settings.promotion.max_ready_run_age_hours,
    )
    run_fresh = (
        isinstance(latest_run, Mapping)
        and isinstance(latest_run.get("run_age_hours"), (int, float))
        and latest_run["run_age_hours"] <= settings.promotion.max_ready_run_age_hours
    )
    ready = not reasons
    report = {
        "generated_at": reference.isoformat(),
        "mode": settings.mode,
        "health_score": health_score,
        "health_status": _health_status(health_score, settings.promotion.min_health_score),
        "max_ready_run_age_hours": settings.promotion.max_ready_run_age_hours,
        "latest_run": latest_run,
        "promotion": promotion,
        "paper_ready": ready,
        "live_ready": ready,
        "readiness_reasons": reasons,
        "checks": {
            "latest_safety_verdict": latest_run.get("safety_verdict")
            if isinstance(latest_run, Mapping)
            else None,
            "latest_run_fresh": run_fresh,
            "promotion_eligible": promotion.get("eligible") is True,
            "health_score_ok": health_ok,
        },
    }
    return report


def write_operational_status(
    paths: RuntimePaths,
    settings: Settings,
    *,
    now: datetime | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    report = build_operational_status(paths, settings, now=now)
    atomic_write_json(output or (paths.state_dir / "operational_status.json"), report)
    return report


def _latest_run_summary(run_dir: Path | None, *, now: datetime) -> dict[str, Any] | None:
    if run_dir is None:
        return None
    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    result = _mapping(manifest.get("result"))
    verdict = _mapping(read_json(run_dir / "safety_verdict.json", default={}))
    safety_verdict = verdict.get("overall") or result.get("safety_verdict")
    finished_at = manifest.get("finished_at")
    finished_at_dt = _parse_timestamp(finished_at)
    run_age_hours = (
        round(max(0.0, (now - finished_at_dt).total_seconds() / 3600), 4)
        if finished_at_dt is not None
        else None
    )
    return {
        "run_id": manifest.get("run_id") or run_dir.name,
        "artifact_dir": str(run_dir),
        "status": manifest.get("status"),
        "failure_code": manifest.get("failure_code"),
        "mode": result.get("mode") or manifest.get("execution_mode"),
        "safety_verdict": safety_verdict,
        "config_hash": manifest.get("config_hash"),
        "data_hash": result.get("data_hash") or verdict.get("data_hash"),
        "signal_hash": result.get("signal_hash"),
        "risk_status": result.get("risk_status"),
        "cost_survival": result.get("cost_survival"),
        "finished_at": finished_at,
        "run_age_hours": run_age_hours,
    }


def _readiness_reasons(
    *,
    latest_run: Mapping[str, Any] | None,
    promotion: Mapping[str, Any],
    health_score: Any,
    min_health_score: int,
    max_ready_run_age_hours: int,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if latest_run is None:
        reasons.append(
            {
                "code": FailureCode.NO_RUN_HISTORY.value,
                "message": "no completed Jayu run is available for operational review",
            }
        )
    else:
        if latest_run.get("status") != "success":
            reasons.append(
                {
                    "code": latest_run.get("failure_code") or FailureCode.RUN_FAILED.value,
                    "message": "latest run did not finish successfully",
                    "run_id": latest_run.get("run_id"),
                }
            )
        if latest_run.get("safety_verdict") != "approved":
            reasons.append(
                {
                    "code": FailureCode.SAFETY_VERDICT_BLOCKED.value,
                    "message": "latest run safety verdict is not approved",
                    "run_id": latest_run.get("run_id"),
                    "observed": latest_run.get("safety_verdict"),
                    "required": "approved",
                }
            )
        age = latest_run.get("run_age_hours")
        if not isinstance(age, (int, float)) or age > max_ready_run_age_hours:
            reasons.append(
                {
                    "code": FailureCode.OPERATIONAL_RUN_STALE.value,
                    "message": "latest run is too old for operational readiness",
                    "run_id": latest_run.get("run_id"),
                    "observed_hours": age,
                    "required_max_hours": max_ready_run_age_hours,
                }
            )
    if promotion.get("eligible") is not True:
        criteria = promotion.get("criteria", [])
        failed = (
            [
                str(item.get("name"))
                for item in criteria
                if isinstance(item, Mapping) and item.get("passed") is not True
            ]
            if isinstance(criteria, list)
            else []
        )
        reasons.append(
            {
                "code": FailureCode.SHADOW_PROMOTION_FAILED.value,
                "message": "shadow promotion criteria are not satisfied",
                "failed_criteria": failed,
            }
        )
    if not isinstance(health_score, (int, float)) or health_score < min_health_score:
        reasons.append(
            {
                "code": FailureCode.HEALTH_SCORE_LOW.value,
                "message": "health score is below the promotion threshold",
                "observed": health_score,
                "required": min_health_score,
            }
        )
    return reasons


def _health_status(value: Any, min_health_score: int) -> str:
    if not isinstance(value, (int, float)):
        return "unknown"
    if value >= min_health_score:
        return "healthy"
    if value >= 70:
        return "degraded"
    return "critical"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
