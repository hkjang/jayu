"""Operator-facing readiness snapshot for Jayu runs."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json
from .paths import RuntimePaths
from .safety import evaluate_shadow_promotion
from .settings import Settings

OPERATIONAL_EXECUTION_MODES = frozenset({"signal", "shadow", "paper", "live"})


def latest_run_dir(
    runs_dir: Path,
    *,
    execution_modes: frozenset[str] | None = None,
) -> Path | None:
    if not runs_dir.exists():
        return None
    candidates = [
        path
        for path in runs_dir.iterdir()
        if path.is_dir() and _is_completed_run(path, execution_modes=execution_modes)
    ]
    if not candidates:
        return None
    return max(candidates, key=_run_sort_key)


def build_operational_status(
    paths: RuntimePaths,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = now or datetime.now(UTC)
    health = _mapping(read_json(paths.state_dir / "health.json", default={}))
    latest_dir = latest_run_dir(
        paths.runs_dir,
        execution_modes=OPERATIONAL_EXECUTION_MODES,
    )
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
    summary = _readiness_summary(reasons)
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
        "readiness_summary": summary,
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


def write_operational_status_markdown(
    paths: RuntimePaths,
    settings: Settings,
    *,
    now: datetime | None = None,
    output: Path | None = None,
    report: Mapping[str, Any] | None = None,
) -> Path:
    snapshot = dict(report or build_operational_status(paths, settings, now=now))
    path = output or (paths.state_dir / "operational_status.md")
    _atomic_write_text(path, operational_status_markdown(snapshot))
    return path


def write_operational_status_bundle(
    paths: RuntimePaths,
    settings: Settings,
    *,
    now: datetime | None = None,
    output: Path | None = None,
    markdown_output: Path | None = None,
) -> dict[str, Any]:
    report = write_operational_status(paths, settings, now=now, output=output)
    write_operational_status_markdown(
        paths,
        settings,
        now=now,
        output=markdown_output,
        report=report,
    )
    return report


def operational_status_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("readiness_summary"))
    latest = _mapping(report.get("latest_run"))
    promotion = _mapping(report.get("promotion"))
    reasons = report.get("readiness_reasons")
    reason_rows = reasons if isinstance(reasons, list) else []
    actions = summary.get("next_actions")
    action_rows = actions if isinstance(actions, list) else []
    lines = [
        "# Jayu Operational Status",
        "",
        f"- Generated: `{report.get('generated_at', 'unknown')}`",
        f"- Mode: `{report.get('mode', 'unknown')}`",
        f"- Status: `{summary.get('overall', 'unknown')}`",
        f"- Message: {summary.get('message', 'not evaluated')}",
        f"- Health: `{report.get('health_score')}` (`{report.get('health_status')}`)",
        f"- Paper ready: `{report.get('paper_ready')}`",
        f"- Live ready: `{report.get('live_ready')}`",
        "",
        "## Latest Run",
        "",
        f"- Run: `{latest.get('run_id', 'none')}`",
        f"- Finished: `{latest.get('finished_at')}`",
        f"- Age hours: `{latest.get('run_age_hours')}`",
        f"- Safety verdict: `{latest.get('safety_verdict')}`",
        f"- Risk status: `{latest.get('risk_status')}`",
        f"- Cost survival: `{latest.get('cost_survival')}`",
        "",
        "## Promotion",
        "",
        f"- Eligible: `{promotion.get('eligible')}`",
        f"- Failure code: `{promotion.get('failure_code')}`",
        "",
        "## Readiness Reasons",
        "",
    ]
    if reason_rows:
        for reason in reason_rows:
            if isinstance(reason, Mapping):
                lines.append(f"- `{reason.get('code')}`: {reason.get('message')}")
    else:
        lines.append("- None")
    lines.extend(["", "## Next Actions", ""])
    if action_rows:
        for index, action in enumerate(action_rows, start=1):
            lines.append(f"{index}. {action}")
    else:
        lines.append("1. Continue normal shadow/paper/live operating sequence.")
    return "\n".join(lines) + "\n"


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


def _readiness_summary(reasons: list[dict[str, Any]]) -> dict[str, Any]:
    codes = [str(reason.get("code")) for reason in reasons if reason.get("code")]
    unique_codes = list(dict.fromkeys(codes))
    ready = not unique_codes
    return {
        "overall": "ready" if ready else "blocked",
        "message": "paper/live readiness checks passed"
        if ready
        else "blocked by " + ", ".join(unique_codes),
        "reason_codes": unique_codes,
        "next_actions": [_next_action(code) for code in unique_codes],
    }


def _next_action(code: str) -> str:
    actions = {
        FailureCode.NO_RUN_HISTORY.value: "Run a fresh shadow signal and review its report.",
        FailureCode.RUN_FAILED.value: "Inspect the latest run manifest and logs before retrying.",
        FailureCode.SAFETY_VERDICT_BLOCKED.value: (
            "Open the latest run safety_verdict.json and report.md to clear blocking gates."
        ),
        FailureCode.OPERATIONAL_RUN_STALE.value: (
            "Generate a fresh operational run before paper or live execution."
        ),
        FailureCode.SHADOW_PROMOTION_FAILED.value: (
            "Continue shadow runs until promotion criteria are satisfied."
        ),
        FailureCode.HEALTH_SCORE_LOW.value: (
            "Inspect state/health.json and resolve recent failures before promotion."
        ),
    }
    if code in actions:
        return actions[code]
    if code.endswith("_FAILURE") or code.endswith("_FAILED"):
        return "Inspect the latest manifest, logs, and failure code details."
    return "Review the corresponding readiness reason details."


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


def _is_completed_run(
    run_dir: Path,
    *,
    execution_modes: frozenset[str] | None,
) -> bool:
    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    if manifest.get("status") not in {"success", "failed"}:
        return False
    if execution_modes is None:
        return True
    result = _mapping(manifest.get("result"))
    mode = result.get("mode") or manifest.get("execution_mode")
    return mode in execution_modes


def _run_sort_key(run_dir: Path) -> float:
    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    finished_at = _parse_timestamp(manifest.get("finished_at"))
    return finished_at.timestamp() if finished_at is not None else run_dir.stat().st_mtime


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
