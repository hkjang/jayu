from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json

SCHEMA_VERSION = 1
DEFAULT_SOURCE = "run_evidence.json · run artifact existence checks"

BASE_CHECKS = [
    {
        "id": "manifest",
        "label": "실행 manifest",
        "category": "run",
        "paths": ["manifest.json"],
        "severity": "required",
    },
    {
        "id": "data_sources",
        "label": "Provider 수집 원장",
        "category": "data",
        "paths": ["data_sources.json"],
        "severity": "required",
    },
    {
        "id": "provider_disagreement",
        "label": "Provider 불일치 리포트",
        "category": "data",
        "paths": ["provider_disagreement_report.json"],
        "severity": "required",
    },
    {
        "id": "signals",
        "label": "신호 산출물",
        "category": "signal",
        "paths": ["signals_risk.json", "signals.json"],
        "severity": "signal_required",
    },
    {
        "id": "risk_explanation",
        "label": "리스크 설명",
        "category": "risk",
        "paths": ["risk_explanation.json"],
        "severity": "signal_required",
    },
    {
        "id": "safety_verdict",
        "label": "최종 안전 판정",
        "category": "safety",
        "paths": ["safety_verdict.json"],
        "severity": "required",
    },
    {
        "id": "signal_replay",
        "label": "신호 재현 해시",
        "category": "reproducibility",
        "paths": ["signal_replay.json"],
        "severity": "warning",
    },
    {
        "id": "signal_publication",
        "label": "신호 출판 상태",
        "category": "publication",
        "paths": ["signal_publication.json"],
        "severity": "warning",
    },
    {
        "id": "promotion",
        "label": "Shadow 승격 근거",
        "category": "promotion",
        "paths": ["promotion.json"],
        "severity": "warning",
    },
    {
        "id": "event_log",
        "label": "이벤트 로그",
        "category": "log",
        "paths": ["logs/events.jsonl"],
        "severity": "warning",
    },
    {
        "id": "html_report",
        "label": "HTML 리포트",
        "category": "report",
        "paths": ["report.html"],
        "severity": "optional",
    },
    {
        "id": "markdown_report",
        "label": "Markdown 리포트",
        "category": "report",
        "paths": ["report.md"],
        "severity": "optional",
    },
]


def build_run_evidence_report(
    run_dir: Path | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated_at = (now or datetime.now(UTC)).isoformat()
    if run_dir is None:
        return empty_run_evidence(generated_at=generated_at)

    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    signal_like = _is_signal_like(manifest)
    items = [_check_item(run_dir, check, signal_like=signal_like) for check in BASE_CHECKS]
    required_items = [item for item in items if item["severity"] == "required"]
    warning_items = [item for item in items if item["severity"] == "warning"]
    optional_items = [item for item in items if item["severity"] == "optional"]
    missing_required = [item for item in required_items if item["exists"] is not True]
    missing_warning = [item for item in warning_items if item["exists"] is not True]
    present_required = len(required_items) - len(missing_required)
    completeness = round(present_required / len(required_items), 4) if required_items else None
    status = (
        "blocked"
        if missing_required
        else "warning"
        if missing_warning
        else "success"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "summary": {
            "run_id": manifest.get("run_id") or run_dir.name,
            "mode": _run_mode(manifest),
            "command": manifest.get("command"),
            "required_count": len(required_items),
            "present_required_count": present_required,
            "missing_required_count": len(missing_required),
            "warning_count": len(warning_items),
            "missing_warning_count": len(missing_warning),
            "optional_count": len(optional_items),
            "completeness_rate": completeness,
            "source": DEFAULT_SOURCE,
        },
        "groups": _groups(items),
        "items": items,
        "source": DEFAULT_SOURCE,
    }


def write_run_evidence_report(
    run_dir: Path | None,
    output_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = build_run_evidence_report(run_dir, now=now)
    atomic_write_json(output_path, report)
    return report


def empty_run_evidence(*, generated_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "not_evaluated",
        "summary": {
            "run_id": None,
            "mode": "unknown",
            "command": None,
            "required_count": 0,
            "present_required_count": 0,
            "missing_required_count": 0,
            "warning_count": 0,
            "missing_warning_count": 0,
            "optional_count": 0,
            "completeness_rate": None,
            "source": DEFAULT_SOURCE,
        },
        "groups": [],
        "items": [],
        "source": DEFAULT_SOURCE,
    }


def _check_item(
    run_dir: Path,
    check: Mapping[str, Any],
    *,
    signal_like: bool,
) -> dict[str, Any]:
    paths = [str(path) for path in _sequence(check.get("paths"))]
    severity = _severity(check, signal_like=signal_like)
    candidates = [run_dir / path for path in paths]
    existing = next((path for path in candidates if path.exists()), None)
    status = "success" if existing else "missing" if severity == "required" else "warning"
    return {
        "id": str(check.get("id")),
        "label": str(check.get("label")),
        "category": str(check.get("category") or "artifact"),
        "severity": severity,
        "status": status,
        "exists": existing is not None,
        "path": _artifact_label(run_dir, existing) if existing else paths[0] if paths else "",
        "alternatives": paths,
        "detail": "존재 확인" if existing else "파일 없음",
        "source": DEFAULT_SOURCE,
    }


def _severity(check: Mapping[str, Any], *, signal_like: bool) -> str:
    value = str(check.get("severity") or "warning")
    if value == "signal_required":
        return "required" if signal_like else "warning"
    return value


def _groups(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    categories = Counter(str(item.get("category") or "artifact") for item in items)
    return [
        {
            "category": category,
            "count": count,
            "present_count": sum(
                item.get("category") == category and item.get("exists") is True for item in items
            ),
            "missing_count": sum(
                item.get("category") == category and item.get("exists") is not True
                for item in items
            ),
            "source": DEFAULT_SOURCE,
        }
        for category, count in sorted(categories.items())
    ]


def _is_signal_like(manifest: Mapping[str, Any]) -> bool:
    command = str(manifest.get("command") or "").lower()
    mode = _run_mode(manifest).lower()
    return "signal" in command or mode in {"shadow", "paper", "live"}


def _run_mode(manifest: Mapping[str, Any]) -> str:
    result = _mapping(manifest.get("result"))
    return str(result.get("mode") or manifest.get("execution_mode") or "unknown")


def _artifact_label(run_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(run_dir)).replace("\\", "/")
    except ValueError:
        return str(path)


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
