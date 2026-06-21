from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json

SCHEMA_VERSION = 1
DEFAULT_SOURCE = (
    "manifest.json · signal_replay.json · data_sources.json · signals_risk.json · "
    "risk_explanation.json · safety_verdict.json · session_replay.py"
)
DATA_FAILURE_CODES = {
    FailureCode.DATA_FAILURE.value,
    FailureCode.DATA_CONTRACT_FAILED.value,
    FailureCode.DATA_DISAGREEMENT.value,
    FailureCode.LIVE_PRICE_SAFETY_FAILED.value,
    FailureCode.UNVERIFIED_PRICE_DATA.value,
    FailureCode.SIGNAL_PUBLICATION_INVALID.value,
}


def build_session_replay_report(
    run_dir: Path | None,
    *,
    project_root: Path | None = None,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a compact, artifact-backed replay of one Jayu investment session."""
    generated_at = (now or datetime.now(UTC)).isoformat()
    if run_dir is None:
        return empty_session_replay(generated_at=generated_at)

    root = project_root or run_dir.parent.parent
    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    data_sources = _mapping(read_json(run_dir / "data_sources.json", default={}))
    disagreements = _mapping(read_json(run_dir / "provider_disagreement_report.json", default={}))
    signal_replay = _mapping(read_json(run_dir / "signal_replay.json", default={}))
    signals = _mapping(
        read_json(_first_existing_path(run_dir / "signals_risk.json", run_dir / "signals.json"), default={})
    )
    risk = _mapping(read_json(run_dir / "risk_explanation.json", default={}))
    verdict = _mapping(read_json(run_dir / "safety_verdict.json", default={}))
    publication = _mapping(read_json(run_dir / "signal_publication.json", default={}))
    notification = _mapping(read_json(run_dir / "notification.json", default={}))
    order_plan = _mapping(read_json(state_dir / "order_plan.json", default={})) if state_dir else {}
    allocation = (
        _mapping(read_json(state_dir / "allocation_preview.json", default={})) if state_dir else {}
    )
    events_log = _recent_log_events(run_dir / "logs" / "events.jsonl")

    events = [
        _manifest_event(manifest, run_dir, root),
        _data_event(manifest, data_sources, disagreements, run_dir, root),
        _signal_replay_event(signal_replay, run_dir, root),
        _signal_event(signals, run_dir, root),
        _risk_event(risk, run_dir, root),
        _safety_event(verdict, manifest, run_dir, root),
        _publication_event(publication, run_dir, root),
        _order_event(order_plan, allocation, state_dir, root),
        _notification_event(notification, events_log, run_dir, root),
    ]
    events = [event for event in events if event is not None]
    status = _overall_status(events)
    artifacts = _artifact_index(events)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "summary": {
            "run_id": manifest.get("run_id") or run_dir.name,
            "mode": _run_mode(manifest),
            "command": manifest.get("command"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "duration_seconds": _duration_seconds(manifest.get("started_at"), manifest.get("finished_at")),
            "step_count": len(events),
            "success_count": sum(event["status"] == "success" for event in events),
            "warning_count": sum(event["status"] == "warning" for event in events),
            "blocked_count": sum(event["status"] in {"blocked", "failed", "data_error"} for event in events),
            "artifact_count": len(artifacts),
            "source": DEFAULT_SOURCE,
        },
        "events": events,
        "artifacts": artifacts,
        "source": DEFAULT_SOURCE,
    }


def write_session_replay_report(
    run_dir: Path | None,
    output_path: Path,
    *,
    project_root: Path | None = None,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = build_session_replay_report(
        run_dir,
        project_root=project_root,
        state_dir=state_dir,
        now=now,
    )
    atomic_write_json(output_path, report)
    return report


def empty_session_replay(*, generated_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "not_evaluated",
        "summary": {
            "run_id": None,
            "mode": "unknown",
            "command": None,
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "step_count": 0,
            "success_count": 0,
            "warning_count": 0,
            "blocked_count": 0,
            "artifact_count": 0,
            "source": DEFAULT_SOURCE,
        },
        "events": [],
        "artifacts": [],
        "source": DEFAULT_SOURCE,
    }


def _manifest_event(manifest: Mapping[str, Any], run_dir: Path, root: Path) -> dict[str, Any]:
    status = str(manifest.get("status") or "not_evaluated")
    run_id = str(manifest.get("run_id") or run_dir.name)
    details = [
        f"mode={_run_mode(manifest)}",
        f"config_hash={_short(manifest.get('config_hash'))}",
        f"data_hash={_short(_data_hash(manifest))}",
    ]
    if manifest.get("failure_code"):
        details.append(f"failure_code={manifest.get('failure_code')}")
    return _event(
        "run_manifest",
        1,
        "실행 선언",
        _status_from_run(status),
        manifest.get("started_at"),
        f"{run_id} 실행이 {_run_mode(manifest)} 모드로 시작됐습니다.",
        details,
        [run_dir / "manifest.json"],
        root,
    )


def _data_event(
    manifest: Mapping[str, Any],
    data_sources: Mapping[str, Any],
    disagreements: Mapping[str, Any],
    run_dir: Path,
    root: Path,
) -> dict[str, Any]:
    sources = [item for item in _sequence(data_sources.get("sources")) if isinstance(item, Mapping)]
    failed = [item for item in sources if item.get("status") != "success"]
    disagreement_rows = _sequence(disagreements.get("disagreements"))
    failure_code = str(manifest.get("failure_code") or "")
    status = (
        "data_error"
        if failure_code in DATA_FAILURE_CODES
        else "warning"
        if failed or disagreement_rows
        else "success"
        if sources
        else "not_evaluated"
    )
    providers = sorted({str(item.get("provider") or "unknown") for item in sources})
    details = [
        f"providers={', '.join(providers) if providers else 'none'}",
        f"source_count={len(sources)}",
        f"failed_source_count={len(failed)}",
        f"disagreement_count={len(disagreement_rows)}",
    ]
    return _event(
        "data_collection",
        2,
        "데이터 수집/검증",
        status,
        manifest.get("finished_at"),
        f"가격 데이터 source {len(sources)}개와 provider 불일치 {len(disagreement_rows)}건을 확인했습니다.",
        details,
        [run_dir / "data_sources.json", run_dir / "provider_disagreement_report.json"],
        root,
        failure_code=failure_code if failure_code in DATA_FAILURE_CODES else None,
    )


def _signal_replay_event(
    replay: Mapping[str, Any],
    run_dir: Path,
    root: Path,
) -> dict[str, Any]:
    signal_hash = replay.get("signal_hash")
    return _event(
        "signal_replay_hash",
        3,
        "신호 재현 해시",
        "success" if signal_hash else "not_evaluated",
        None,
        "동일 설정, 데이터 hash, seed로 같은 신호를 재현할 수 있는지 확인합니다.",
        [
            f"signal_hash={_short(signal_hash)}",
            f"seed={replay.get('seed', '-')}",
            f"signal_date={replay.get('signal_date', '-')}",
            f"replay={replay.get('replay', False)}",
        ],
        [run_dir / "signal_replay.json"],
        root,
    )


def _signal_event(signals: Mapping[str, Any], run_dir: Path, root: Path) -> dict[str, Any]:
    rows = [item for item in signals.values() if isinstance(item, Mapping)]
    buy_count = sum(_is_buy(item) for item in rows)
    eligible_count = sum(item.get("eligible") is True for item in rows)
    blocked_count = sum(_is_blocked(item) for item in rows)
    status = "warning" if blocked_count else "success" if rows else "not_evaluated"
    return _event(
        "signal_generation",
        4,
        "신호 생성",
        status,
        None,
        f"신호 {len(rows)}개 중 매수 {buy_count}개, 운영 가능 {eligible_count}개, 차단 {blocked_count}개입니다.",
        [
            f"ticker_count={len(rows)}",
            f"buy_count={buy_count}",
            f"eligible_count={eligible_count}",
            f"blocked_count={blocked_count}",
        ],
        [run_dir / "signals_risk.json", run_dir / "signals.json"],
        root,
    )


def _risk_event(risk: Mapping[str, Any], run_dir: Path, root: Path) -> dict[str, Any]:
    approved = int(risk.get("approved_count", 0) or 0)
    blocked = int(risk.get("blocked_count", 0) or 0)
    hold = int(risk.get("hold_count", 0) or 0)
    top_reasons = [
        str(item.get("code"))
        for item in _sequence(risk.get("top_block_reasons"))
        if isinstance(item, Mapping) and item.get("code")
    ]
    return _event(
        "risk_review",
        5,
        "리스크 심사",
        "blocked" if blocked else "success" if approved or hold else "not_evaluated",
        None,
        f"승인 {approved}개, 차단 {blocked}개, 대기 {hold}개로 리스크 심사를 마쳤습니다.",
        [
            f"approved={approved}",
            f"blocked={blocked}",
            f"hold={hold}",
            f"top_reasons={', '.join(top_reasons) if top_reasons else '-'}",
        ],
        [run_dir / "risk_explanation.json"],
        root,
        failure_code=top_reasons[0] if top_reasons else None,
    )


def _safety_event(
    verdict: Mapping[str, Any],
    manifest: Mapping[str, Any],
    run_dir: Path,
    root: Path,
) -> dict[str, Any]:
    result = _mapping(manifest.get("result"))
    overall = str(verdict.get("overall") or result.get("safety_verdict") or "")
    reasons = [item for item in _sequence(verdict.get("reasons")) if isinstance(item, Mapping)]
    status = {
        "approved": "success",
        "review": "warning",
        "blocked": "blocked",
    }.get(overall, "not_evaluated")
    return _event(
        "safety_verdict",
        6,
        "안전 판정",
        status,
        None,
        f"최종 안전 판정은 {overall or '미평가'}이며, reason {len(reasons)}건이 기록됐습니다.",
        [
            f"overall={overall or '-'}",
            f"reason_count={len(reasons)}",
            f"codes={', '.join(str(item.get('code')) for item in reasons[:4]) if reasons else '-'}",
        ],
        [run_dir / "safety_verdict.json"],
        root,
        failure_code=str(reasons[0].get("code")) if reasons else None,
    )


def _publication_event(
    publication: Mapping[str, Any],
    run_dir: Path,
    root: Path,
) -> dict[str, Any]:
    status_raw = str(publication.get("status") or "")
    status = {
        "published": "success",
        "blocked": "blocked",
        "missing": "not_evaluated",
    }.get(status_raw, "not_evaluated" if not status_raw else "warning")
    return _event(
        "signal_publication",
        7,
        "신호 출판",
        status,
        publication.get("published_at") or publication.get("generated_at"),
        f"primary signal publication 상태는 {status_raw or '미기록'}입니다.",
        [
            f"status={status_raw or '-'}",
            f"signal_hash={_short(publication.get('signal_hash'))}",
            f"failure_code={publication.get('failure_code', '-')}",
        ],
        [run_dir / "signal_publication.json"],
        root,
        failure_code=publication.get("failure_code"),
    )


def _order_event(
    order_plan: Mapping[str, Any],
    allocation: Mapping[str, Any],
    state_dir: Path | None,
    root: Path,
) -> dict[str, Any] | None:
    if state_dir is None:
        return None
    orders = _sequence(order_plan.get("orders"))
    allocation_summary = _mapping(allocation.get("summary"))
    skipped = int(allocation_summary.get("skipped_order_count", 0) or 0)
    status = "blocked" if skipped else "success" if orders else "not_evaluated"
    return _event(
        "order_review",
        8,
        "주문/배분 검토",
        status,
        order_plan.get("generated_at") or allocation.get("generated_at"),
        f"수동 주문 전표 {len(orders)}건과 배분 미리보기 상태 {allocation.get('status', '미평가')}를 확인했습니다.",
        [
            f"order_count={len(orders)}",
            f"allocation_status={allocation.get('status', '-')}",
            f"skipped_order_count={skipped}",
        ],
        [state_dir / "order_plan.json", state_dir / "allocation_preview.json"],
        root,
    )


def _notification_event(
    notification: Mapping[str, Any],
    events_log: Sequence[Mapping[str, Any]],
    run_dir: Path,
    root: Path,
) -> dict[str, Any]:
    failures = [
        item for item in events_log if "notification" in str(item.get("event") or item).lower()
    ]
    notification_ok = notification.get("ok") is True or notification.get("status") == "sent"
    status = "success" if notification_ok else "warning" if failures else "not_evaluated"
    return _event(
        "notification",
        9,
        "알림/운영 로그",
        status,
        notification.get("sent_at"),
        f"알림 산출물 상태 {notification.get('status', '미기록')} · 관련 로그 {len(failures)}건입니다.",
        [
            f"notification_status={notification.get('status', '-')}",
            f"notification_ok={notification.get('ok', '-')}",
            f"related_log_count={len(failures)}",
        ],
        [run_dir / "notification.json", run_dir / "logs" / "events.jsonl"],
        root,
    )


def _event(
    event_id: str,
    step: int,
    title: str,
    status: str,
    occurred_at: Any,
    summary: str,
    details: Sequence[str],
    artifacts: Sequence[Path],
    root: Path,
    *,
    failure_code: Any = None,
) -> dict[str, Any]:
    existing_artifacts = [
        {
            "path": _artifact_label(root, artifact),
            "exists": artifact.exists(),
            "source": _artifact_label(root, artifact),
        }
        for artifact in artifacts
    ]
    payload: dict[str, Any] = {
        "id": event_id,
        "step": step,
        "title": title,
        "status": status,
        "occurred_at": occurred_at,
        "summary": summary,
        "details": [str(item) for item in details if str(item)],
        "artifacts": existing_artifacts,
        "source": " · ".join(item["source"] for item in existing_artifacts),
    }
    if failure_code:
        payload["failure_code"] = str(failure_code)
    return payload


def _artifact_index(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for event in events:
        for artifact in _sequence(event.get("artifacts")):
            if isinstance(artifact, Mapping) and artifact.get("path"):
                by_path[str(artifact["path"])] = dict(artifact)
    return sorted(by_path.values(), key=lambda item: str(item.get("path") or ""))


def _recent_log_events(path: Path, *, limit: int = 30) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            rows.append(dict(value))
    return rows


def _overall_status(events: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(event.get("status")) for event in events}
    if statuses & {"blocked", "failed", "data_error"}:
        return "blocked"
    if statuses & {"warning", "partial"}:
        return "warning"
    if "success" in statuses:
        return "success"
    return "not_evaluated"


def _status_from_run(status: str) -> str:
    if status == "success":
        return "success"
    if status in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    if status in {"running", "started"}:
        return "warning"
    return "not_evaluated"


def _duration_seconds(started_at: Any, finished_at: Any) -> float | None:
    start = _parse_time(started_at)
    finish = _parse_time(finished_at)
    if start is None or finish is None:
        return None
    return round(max(0.0, (finish - start).total_seconds()), 3)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _run_mode(manifest: Mapping[str, Any]) -> str:
    result = _mapping(manifest.get("result"))
    return str(result.get("mode") or manifest.get("execution_mode") or "unknown")


def _data_hash(manifest: Mapping[str, Any]) -> Any:
    result = _mapping(manifest.get("result"))
    return result.get("data_hash") or manifest.get("data_hash") or manifest.get("data_hashes")


def _first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def _artifact_label(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _short(value: Any) -> str:
    text = str(value or "")
    if not text:
        return "-"
    return text[:12]


def _is_buy(item: Mapping[str, Any]) -> bool:
    text = str(item.get("action") or item.get("signal") or "").lower()
    return "buy" in text or "매수" in text


def _is_blocked(item: Mapping[str, Any]) -> bool:
    return (
        item.get("blocked") is True
        or item.get("eligible") is False
        or str(item.get("status") or "").lower() == "blocked"
    )


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
