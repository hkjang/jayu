from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json

SCHEMA_VERSION = 1
DEFAULT_SOURCE = (
    "data_lineage.json · manifest.json · data_sources.json · "
    "provider_disagreement_report.json · signal/risk/safety artifacts"
)
DATA_FAILURE_CODES = {
    FailureCode.DATA_FAILURE.value,
    FailureCode.DATA_CONTRACT_FAILED.value,
    FailureCode.DATA_DISAGREEMENT.value,
    FailureCode.LIVE_PRICE_SAFETY_FAILED.value,
    FailureCode.UNVERIFIED_PRICE_DATA.value,
    FailureCode.SIGNAL_PUBLICATION_INVALID.value,
}


def build_data_lineage_report(
    run_dir: Path | None,
    *,
    project_root: Path | None = None,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build an artifact-level graph from data collection to operational review."""
    generated_at = (now or datetime.now(UTC)).isoformat()
    if run_dir is None:
        return empty_data_lineage(generated_at=generated_at)

    root = project_root or run_dir.parent.parent
    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    data_sources = _mapping(read_json(run_dir / "data_sources.json", default={}))
    disagreements = _mapping(read_json(run_dir / "provider_disagreement_report.json", default={}))
    signal_replay = _mapping(read_json(run_dir / "signal_replay.json", default={}))
    signal_path = _first_existing_path(run_dir / "signals_risk.json", run_dir / "signals.json")
    signals = _mapping(read_json(signal_path, default={}))
    risk = _mapping(read_json(run_dir / "risk_explanation.json", default={}))
    verdict = _mapping(read_json(run_dir / "safety_verdict.json", default={}))
    publication = _mapping(read_json(run_dir / "signal_publication.json", default={}))
    promotion = _mapping(read_json(run_dir / "promotion.json", default={}))

    order_plan = _state_mapping(state_dir, "order_plan.json")
    allocation = _state_mapping(state_dir, "allocation_preview.json")
    attribution = _state_mapping(state_dir, "account_attribution.json")
    recovery = _state_mapping(state_dir, "recovery_guide.json")
    session = _state_mapping(state_dir, "session_replay.json")
    warnings = _state_mapping(state_dir, "stock_warning_gate.json")

    source_rows = [
        item for item in _sequence(data_sources.get("sources")) if isinstance(item, Mapping)
    ]
    disagreement_rows = [
        item for item in _sequence(disagreements.get("disagreements")) if isinstance(item, Mapping)
    ]

    nodes: list[dict[str, Any]] = []
    nodes.extend(_provider_nodes(source_rows))
    nodes.extend(
        [
            _artifact_node(
                "artifact:manifest",
                "실행 manifest",
                run_dir / "manifest.json",
                root,
                _status_from_run(str(manifest.get("status") or "")),
                _manifest_detail(manifest, run_dir),
            ),
            _artifact_node(
                "artifact:data_sources",
                "Provider 수집 원장",
                run_dir / "data_sources.json",
                root,
                _data_status(manifest, source_rows, disagreement_rows),
                f"source {len(source_rows)}개 · provider {len(_provider_names(source_rows))}개",
            ),
            _artifact_node(
                "artifact:provider_disagreement_report",
                "Provider 불일치 리포트",
                run_dir / "provider_disagreement_report.json",
                root,
                "data_error" if disagreement_rows else "success" if source_rows else "not_evaluated",
                f"불일치 {len(disagreement_rows)}건",
            ),
            _artifact_node(
                "artifact:signal_replay",
                "신호 재현 해시",
                run_dir / "signal_replay.json",
                root,
                "success" if signal_replay.get("signal_hash") else "not_evaluated",
                f"signal_hash={_short(signal_replay.get('signal_hash'))}",
            ),
            _artifact_node(
                "artifact:signals",
                "신호 산출물",
                signal_path,
                root,
                _signal_status(signals),
                _signal_detail(signals),
            ),
            _artifact_node(
                "artifact:risk_explanation",
                "리스크 설명",
                run_dir / "risk_explanation.json",
                root,
                _risk_status(risk),
                _risk_detail(risk),
            ),
            _artifact_node(
                "artifact:safety_verdict",
                "최종 안전 판정",
                run_dir / "safety_verdict.json",
                root,
                _verdict_status(verdict, manifest),
                _verdict_detail(verdict, manifest),
            ),
            _artifact_node(
                "artifact:signal_publication",
                "신호 출판 상태",
                run_dir / "signal_publication.json",
                root,
                _publication_status(publication),
                f"status={publication.get('status', '-')}",
            ),
            _artifact_node(
                "artifact:promotion",
                "Shadow 승격 근거",
                run_dir / "promotion.json",
                root,
                "success" if promotion.get("eligible") is True else "warning" if promotion else "missing",
                f"eligible={promotion.get('eligible', '-')}",
            ),
        ]
    )
    nodes.extend(
        _state_nodes(
            state_dir,
            root,
            order_plan=order_plan,
            allocation=allocation,
            attribution=attribution,
            recovery=recovery,
            session=session,
            warnings=warnings,
        )
    )
    nodes.extend(
        _process_nodes(
            manifest=manifest,
            source_rows=source_rows,
            disagreement_rows=disagreement_rows,
            signals=signals,
            risk=risk,
            verdict=verdict,
            publication=publication,
            order_plan=order_plan,
            allocation=allocation,
        )
    )

    edges = _edges(nodes)
    summary = _summary(nodes, edges, source_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": summary["status"],
        "summary": {
            **summary,
            "run_id": manifest.get("run_id") or run_dir.name,
            "source": DEFAULT_SOURCE,
        },
        "groups": _groups(nodes),
        "nodes": nodes,
        "edges": edges,
        "source": DEFAULT_SOURCE,
    }


def write_data_lineage_report(
    run_dir: Path | None,
    output_path: Path,
    *,
    project_root: Path | None = None,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = build_data_lineage_report(
        run_dir,
        project_root=project_root,
        state_dir=state_dir,
        now=now,
    )
    atomic_write_json(output_path, report)
    return report


def empty_data_lineage(*, generated_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "not_evaluated",
        "summary": {
            "run_id": None,
            "node_count": 0,
            "edge_count": 0,
            "provider_count": 0,
            "artifact_count": 0,
            "missing_artifact_count": 0,
            "failed_provider_count": 0,
            "blocked_gate_count": 0,
            "status": "not_evaluated",
            "source": DEFAULT_SOURCE,
        },
        "groups": [],
        "nodes": [],
        "edges": [],
        "source": DEFAULT_SOURCE,
    }


def _provider_nodes(source_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in source_rows:
        grouped[str(row.get("provider") or "unknown")].append(row)
    nodes = []
    for provider, rows in sorted(grouped.items()):
        failed = [row for row in rows if row.get("status") != "success"]
        tickers = sorted({str(row.get("ticker")) for row in rows if row.get("ticker")})
        nodes.append(
            _node(
                f"provider:{provider}",
                provider,
                "provider",
                "failed" if failed else "success",
                f"{len(rows)}개 source · ticker {len(tickers)}개",
                "data_sources.json",
                provider=provider,
                ticker_count=len(tickers),
                source_count=len(rows),
            )
        )
    return nodes


def _artifact_node(
    node_id: str,
    label: str,
    path: Path,
    root: Path,
    status: str,
    detail: str,
) -> dict[str, Any]:
    exists = path.exists()
    return _node(
        node_id,
        label,
        "artifact",
        status if exists else "missing",
        detail if exists else "파일 없음",
        _artifact_label(root, path),
        path=_artifact_label(root, path),
        exists=exists,
    )


def _state_nodes(
    state_dir: Path | None,
    root: Path,
    *,
    order_plan: Mapping[str, Any],
    allocation: Mapping[str, Any],
    attribution: Mapping[str, Any],
    recovery: Mapping[str, Any],
    session: Mapping[str, Any],
    warnings: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if state_dir is None:
        return []
    return [
        _artifact_node(
            "state:order_plan",
            "주문 의도/전표",
            state_dir / "order_plan.json",
            root,
            "success" if _sequence(order_plan.get("orders")) else "not_evaluated",
            f"orders={len(_sequence(order_plan.get('orders')))}",
        )
        | {"kind": "state"},
        _artifact_node(
            "state:allocation_preview",
            "배분 미리보기",
            state_dir / "allocation_preview.json",
            root,
            str(allocation.get("status") or "not_evaluated"),
            f"status={allocation.get('status', '-')}",
        )
        | {"kind": "state"},
        _artifact_node(
            "state:account_attribution",
            "계좌 성과 기여도",
            state_dir / "account_attribution.json",
            root,
            str(attribution.get("status") or "not_evaluated"),
            f"positions={_mapping(attribution.get('summary')).get('position_count', '-')}",
        )
        | {"kind": "state"},
        _artifact_node(
            "state:recovery_guide",
            "복구 가이드",
            state_dir / "recovery_guide.json",
            root,
            str(recovery.get("status") or "not_evaluated"),
            f"items={len(_sequence(recovery.get('items')))}",
        )
        | {"kind": "state"},
        _artifact_node(
            "state:session_replay",
            "세션 리플레이",
            state_dir / "session_replay.json",
            root,
            str(session.get("status") or "not_evaluated"),
            f"steps={_mapping(session.get('summary')).get('step_count', '-')}",
        )
        | {"kind": "state"},
        _artifact_node(
            "state:stock_warning_gate",
            "매수 유의사항 게이트",
            state_dir / "stock_warning_gate.json",
            root,
            "warning" if warnings else "not_evaluated",
            f"ticker_flags={len(warnings)}",
        )
        | {"kind": "state"},
    ]


def _process_nodes(
    *,
    manifest: Mapping[str, Any],
    source_rows: Sequence[Mapping[str, Any]],
    disagreement_rows: Sequence[Mapping[str, Any]],
    signals: Mapping[str, Any],
    risk: Mapping[str, Any],
    verdict: Mapping[str, Any],
    publication: Mapping[str, Any],
    order_plan: Mapping[str, Any],
    allocation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        _node(
            "process:data_collection",
            "데이터 수집/교차검증",
            "process",
            _data_status(manifest, source_rows, disagreement_rows),
            f"source {len(source_rows)}개 · 불일치 {len(disagreement_rows)}건",
            "data_sources.json · provider_disagreement_report.json",
        ),
        _node(
            "process:signal_generation",
            "신호 생성",
            "process",
            _signal_status(signals),
            _signal_detail(signals),
            "signal_replay.json · signals_risk.json",
        ),
        _node(
            "process:risk_gate",
            "리스크 게이트",
            "gate",
            _risk_status(risk),
            _risk_detail(risk),
            "risk_explanation.json · portfolio_mapping.json",
        ),
        _node(
            "process:safety_verdict",
            "운영 안전 판정",
            "gate",
            _verdict_status(verdict, manifest),
            _verdict_detail(verdict, manifest),
            "safety_verdict.json",
        ),
        _node(
            "process:publication",
            "신호 출판",
            "process",
            _publication_status(publication),
            f"status={publication.get('status', '-')}",
            "signal_publication.json · today_signals sidecar",
        ),
        _node(
            "process:order_review",
            "주문/배분 검토",
            "process",
            _order_status(order_plan, allocation),
            _order_detail(order_plan, allocation),
            "order_plan.json · allocation_preview.json",
        ),
    ]


def _edges(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    node_ids = {str(node.get("id")) for node in nodes}
    provider_edges = [
        _edge(str(node["id"]), "artifact:data_sources", "수집 원장 기록")
        for node in nodes
        if node.get("kind") == "provider"
    ]
    flow = [
        ("artifact:manifest", "process:data_collection", "run 설정/명령"),
        ("artifact:data_sources", "process:data_collection", "provider 결과"),
        ("artifact:provider_disagreement_report", "process:data_collection", "교차검증 결과"),
        ("process:data_collection", "artifact:signal_replay", "검증된 입력 hash"),
        ("artifact:manifest", "process:signal_generation", "전략/모드"),
        ("artifact:signal_replay", "process:signal_generation", "재현성 hash"),
        ("process:signal_generation", "artifact:signals", "신호 기록"),
        ("artifact:signals", "process:risk_gate", "매수 후보"),
        ("process:risk_gate", "artifact:risk_explanation", "리스크 판정"),
        ("artifact:risk_explanation", "process:safety_verdict", "게이트 사유"),
        ("artifact:safety_verdict", "process:publication", "운영 승인/차단"),
        ("process:publication", "artifact:signal_publication", "출판 sidecar"),
        ("artifact:signals", "state:order_plan", "수동 주문 의도"),
        ("artifact:risk_explanation", "state:order_plan", "승인 비중"),
        ("state:order_plan", "process:order_review", "주문 전표"),
        ("state:stock_warning_gate", "process:order_review", "매수 유의사항"),
        ("process:order_review", "state:allocation_preview", "배분 시뮬레이션"),
        ("state:allocation_preview", "state:account_attribution", "계좌 영향"),
        ("artifact:safety_verdict", "state:recovery_guide", "복구 사유"),
        ("artifact:safety_verdict", "state:session_replay", "세션 근거"),
    ]
    edges = provider_edges + [
        _edge(start, end, label) for start, end, label in flow if start in node_ids and end in node_ids
    ]
    return edges


def _node(
    node_id: str,
    label: str,
    kind: str,
    status: str,
    detail: str,
    source: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "kind": kind,
        "status": status or "not_evaluated",
        "detail": detail,
        "source": source,
        **extra,
    }


def _edge(start: str, end: str, label: str) -> dict[str, Any]:
    return {"from": start, "to": end, "label": label, "source": DEFAULT_SOURCE}


def _summary(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    provider_count = len(_provider_names(source_rows))
    failed_provider_count = sum(
        node.get("kind") == "provider" and node.get("status") == "failed" for node in nodes
    )
    missing_artifact_count = sum(node.get("status") == "missing" for node in nodes)
    blocked_gate_count = sum(
        node.get("kind") in {"gate", "process"}
        and node.get("status") in {"blocked", "failed", "data_error"}
        for node in nodes
    )
    status = _overall_status(nodes)
    return {
        "status": status,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "provider_count": provider_count,
        "artifact_count": sum(node.get("kind") in {"artifact", "state"} for node in nodes),
        "missing_artifact_count": missing_artifact_count,
        "failed_provider_count": failed_provider_count,
        "blocked_gate_count": blocked_gate_count,
    }


def _groups(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(node.get("kind") or "unknown") for node in nodes)
    status_counts = Counter(str(node.get("status") or "unknown") for node in nodes)
    return [
        {
            "kind": kind,
            "count": count,
            "status_breakdown": {
                status: sum(
                    node.get("kind") == kind and node.get("status") == status for node in nodes
                )
                for status in sorted(status_counts)
            },
            "source": DEFAULT_SOURCE,
        }
        for kind, count in sorted(counts.items())
    ]


def _data_status(
    manifest: Mapping[str, Any],
    source_rows: Sequence[Mapping[str, Any]],
    disagreement_rows: Sequence[Mapping[str, Any]],
) -> str:
    failure_code = str(manifest.get("failure_code") or "")
    if failure_code in DATA_FAILURE_CODES:
        return "data_error"
    if disagreement_rows:
        return "data_error"
    if any(row.get("status") != "success" for row in source_rows):
        return "warning"
    return "success" if source_rows else "not_evaluated"


def _signal_status(signals: Mapping[str, Any]) -> str:
    rows = [item for item in signals.values() if isinstance(item, Mapping)]
    if not rows:
        return "not_evaluated"
    return "blocked" if any(_is_blocked(item) for item in rows) else "success"


def _risk_status(risk: Mapping[str, Any]) -> str:
    blocked = int(risk.get("blocked_count", 0) or 0)
    approved = int(risk.get("approved_count", 0) or 0)
    hold = int(risk.get("hold_count", 0) or 0)
    if blocked:
        return "blocked"
    return "success" if approved or hold else "not_evaluated"


def _verdict_status(verdict: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    result = _mapping(manifest.get("result"))
    overall = str(verdict.get("overall") or result.get("safety_verdict") or "")
    return {
        "approved": "success",
        "blocked": "blocked",
        "review": "warning",
    }.get(overall, "not_evaluated")


def _publication_status(publication: Mapping[str, Any]) -> str:
    status = str(publication.get("status") or "")
    return {
        "published": "success",
        "blocked": "blocked",
        "missing": "not_evaluated",
    }.get(status, "warning" if status else "not_evaluated")


def _order_status(order_plan: Mapping[str, Any], allocation: Mapping[str, Any]) -> str:
    order_count = len(_sequence(order_plan.get("orders")))
    allocation_status = str(allocation.get("status") or "")
    if allocation_status in {"blocked", "failed", "data_error"}:
        return "blocked"
    if order_count or allocation:
        return "success" if allocation_status not in {"warning"} else "warning"
    return "not_evaluated"


def _overall_status(nodes: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(node.get("status")) for node in nodes}
    if statuses & {"blocked", "failed", "data_error"}:
        return "blocked"
    if statuses & {"warning", "missing"}:
        return "warning"
    if "success" in statuses:
        return "success"
    return "not_evaluated"


def _manifest_detail(manifest: Mapping[str, Any], run_dir: Path) -> str:
    return (
        f"run_id={manifest.get('run_id') or run_dir.name} · "
        f"mode={_run_mode(manifest)} · failure={manifest.get('failure_code', '-')}"
    )


def _signal_detail(signals: Mapping[str, Any]) -> str:
    rows = [item for item in signals.values() if isinstance(item, Mapping)]
    buy = sum(_is_buy(item) for item in rows)
    blocked = sum(_is_blocked(item) for item in rows)
    return f"signals={len(rows)} · buy={buy} · blocked={blocked}"


def _risk_detail(risk: Mapping[str, Any]) -> str:
    return (
        f"approved={int(risk.get('approved_count', 0) or 0)} · "
        f"blocked={int(risk.get('blocked_count', 0) or 0)}"
    )


def _verdict_detail(verdict: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    result = _mapping(manifest.get("result"))
    overall = verdict.get("overall") or result.get("safety_verdict") or "-"
    reason_count = len(_sequence(verdict.get("reasons")))
    return f"overall={overall} · reasons={reason_count}"


def _order_detail(order_plan: Mapping[str, Any], allocation: Mapping[str, Any]) -> str:
    order_count = len(_sequence(order_plan.get("orders")))
    summary = _mapping(allocation.get("summary"))
    skipped = summary.get("skipped_order_count", 0)
    return f"orders={order_count} · allocation={allocation.get('status', '-')} · skipped={skipped}"


def _run_mode(manifest: Mapping[str, Any]) -> str:
    result = _mapping(manifest.get("result"))
    return str(result.get("mode") or manifest.get("execution_mode") or "unknown")


def _status_from_run(status: str) -> str:
    if status == "success":
        return "success"
    if status in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    if status in {"running", "started"}:
        return "warning"
    return "not_evaluated"


def _state_mapping(state_dir: Path | None, filename: str) -> Mapping[str, Any]:
    if state_dir is None:
        return {}
    return _mapping(read_json(state_dir / filename, default={}))


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


def _provider_names(source_rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(row.get("provider")) for row in source_rows if row.get("provider")}


def _short(value: Any) -> str:
    text = str(value or "")
    return text[:12] if text else "-"


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
