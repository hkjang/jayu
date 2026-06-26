from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json

SCHEMA_VERSION = 1
DEFAULT_SOURCE = "runs/*/manifest.json · safety_verdict.json · risk_explanation.json"
TERMINAL_RUN_STATUSES = {"success", "failed", "error", "cancelled", "canceled"}

ACTION_HINTS = {
    "DATA_DISAGREEMENT": {
        "page": "data-quality",
        "label": "Provider 불일치 확인",
        "detail": "data_sources.json과 provider_disagreement_report.json의 원본값을 먼저 비교하세요.",
    },
    "SURVIVORSHIP_GATE_FAILED": {
        "page": "settings",
        "label": "생존편향 정책 확인",
        "detail": "point-in-time universe 또는 명시적 예외 사유를 설정 검증에서 확인하세요.",
    },
    "SECTOR_EXPOSURE_EXCEEDED": {
        "page": "risk",
        "label": "섹터 한도 조정",
        "detail": "portfolio_mapping.json의 섹터와 리스크 한도를 함께 확인하세요.",
    },
    "SAFETY_VERDICT_BLOCKED": {
        "page": "overview",
        "label": "안전 판정 사유 확인",
        "detail": "safety_verdict.json의 첫 번째 차단 사유를 기준으로 복구 순서를 잡으세요.",
    },
    "SHADOW_PROMOTION_FAILED": {
        "page": "promotion",
        "label": "Shadow 승격 조건 확인",
        "detail": "승격 기준, shadow 실행 수, 최근 실패율을 함께 확인하세요.",
    },
}


def build_failure_patterns_report(
    runs_dir: Path,
    *,
    limit: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated_at = (now or datetime.now(UTC)).isoformat()
    rows = _run_rows(runs_dir, limit=limit)
    if not rows:
        return empty_failure_patterns(generated_at=generated_at)

    patterns = _patterns(rows)
    latest_failure = next((row for row in rows if row.get("primary_code")), None)
    streak_code, streak_count = _active_streak(rows)
    repeated = [item for item in patterns if int(item.get("count", 0) or 0) >= 2]
    status = (
        "blocked"
        if streak_count >= 2
        else "warning"
        if repeated or latest_failure
        else "success"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "summary": {
            "run_count": len(rows),
            "failed_run_count": sum(_is_failed(row.get("status")) for row in rows),
            "code_count": sum(len(_sequence(row.get("codes"))) for row in rows),
            "repeated_code_count": len(repeated),
            "top_code": patterns[0]["code"] if patterns else None,
            "top_code_count": patterns[0]["count"] if patterns else 0,
            "latest_failure_code": latest_failure.get("primary_code") if latest_failure else None,
            "active_streak_code": streak_code,
            "active_streak_count": streak_count,
            "source": DEFAULT_SOURCE,
        },
        "patterns": patterns,
        "timeline": rows[: min(limit, 30)],
        "source": DEFAULT_SOURCE,
    }


def write_failure_patterns_report(
    runs_dir: Path,
    output_path: Path,
    *,
    limit: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = build_failure_patterns_report(runs_dir, limit=limit, now=now)
    atomic_write_json(output_path, report)
    return report


def empty_failure_patterns(*, generated_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "not_evaluated",
        "summary": {
            "run_count": 0,
            "failed_run_count": 0,
            "code_count": 0,
            "repeated_code_count": 0,
            "top_code": None,
            "top_code_count": 0,
            "latest_failure_code": None,
            "active_streak_code": None,
            "active_streak_count": 0,
            "source": DEFAULT_SOURCE,
        },
        "patterns": [],
        "timeline": [],
        "source": DEFAULT_SOURCE,
    }


def _run_rows(runs_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    if not runs_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
        if not manifest:
            continue
        status = str(manifest.get("status") or "unknown")
        finished_at = manifest.get("finished_at")
        started_at = manifest.get("started_at")
        if not _is_complete(status, finished_at):
            continue
        verdict = _mapping(read_json(run_dir / "safety_verdict.json", default={}))
        risk = _mapping(read_json(run_dir / "risk_explanation.json", default={}))
        codes = _failure_codes(manifest, verdict, risk)
        rows.append(
            {
                "run_id": str(manifest.get("run_id") or run_dir.name),
                "mode": _run_mode(manifest),
                "status": status,
                "primary_code": codes[0] if codes else None,
                "codes": codes,
                "started_at": started_at,
                "finished_at": finished_at,
                "occurred_at": finished_at or started_at,
                "command": manifest.get("command"),
                "source": _source_for(run_dir),
            }
        )
    rows.sort(key=lambda item: str(item.get("occurred_at") or ""), reverse=True)
    return rows[:limit]


def _failure_codes(
    manifest: Mapping[str, Any],
    verdict: Mapping[str, Any],
    risk: Mapping[str, Any],
) -> list[str]:
    codes: list[str] = []
    if manifest.get("failure_code"):
        codes.append(str(manifest["failure_code"]))
    for reason in _sequence(verdict.get("reasons")):
        if isinstance(reason, Mapping) and reason.get("code"):
            codes.append(str(reason["code"]))
    for item in _sequence(risk.get("top_block_reasons")):
        if isinstance(item, Mapping) and item.get("code"):
            codes.append(str(item["code"]))
    return list(dict.fromkeys(codes))


def _patterns(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    occurrences: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    components: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for code in _sequence(row.get("codes")):
            code_text = str(code)
            occurrences[code_text].append(row)
            components[code_text][str(row.get("mode") or "unknown")] += 1

    result = []
    for code, code_rows in occurrences.items():
        ordered = sorted(code_rows, key=lambda item: str(item.get("occurred_at") or ""))
        action = ACTION_HINTS.get(
            code,
            {
                "page": "overview",
                "label": "차단 사유 확인",
                "detail": "manifest와 safety_verdict의 failure_code를 기준으로 복구 가이드를 확인하세요.",
            },
        )
        result.append(
            {
                "code": code,
                "count": len(code_rows),
                "failed_run_count": sum(_is_failed(item.get("status")) for item in code_rows),
                "first_seen_at": ordered[0].get("occurred_at") if ordered else None,
                "last_seen_at": ordered[-1].get("occurred_at") if ordered else None,
                "run_ids": [str(item.get("run_id")) for item in code_rows[:8]],
                "modes": dict(components[code]),
                "severity": "blocked" if len(code_rows) >= 2 else "warning",
                "action": action,
                "source": DEFAULT_SOURCE,
            }
        )
    result.sort(key=lambda item: (int(item["count"]), str(item.get("last_seen_at") or "")), reverse=True)
    return result


def _active_streak(rows: Sequence[Mapping[str, Any]]) -> tuple[str | None, int]:
    first_code = None
    count = 0
    for row in rows:
        code = row.get("primary_code")
        if not code:
            break
        if first_code is None:
            first_code = str(code)
        if str(code) != first_code:
            break
        count += 1
    return first_code, count


def _run_mode(manifest: Mapping[str, Any]) -> str:
    result = _mapping(manifest.get("result"))
    return str(result.get("mode") or manifest.get("execution_mode") or "unknown")


def _is_complete(status: str, finished_at: Any) -> bool:
    return bool(finished_at) or str(status).lower() in TERMINAL_RUN_STATUSES


def _is_failed(status: Any) -> bool:
    return str(status or "").lower() in {"failed", "error"}


def _source_for(run_dir: Path) -> str:
    return f"{run_dir.name}/manifest.json · safety_verdict.json · risk_explanation.json"


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
