"""Read-only dashboard API and static asset server."""

from __future__ import annotations

import json
import mimetypes
import time
import webbrowser
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .failure_codes import FailureCode
from .io import read_json, stable_hash
from .paths import RuntimePaths
from .provider_factory import build_provider_registry, provider_configuration_audit, provider_policy
from .safety import evaluate_shadow_promotion
from .settings import Settings, load_settings
from .strategy_space import load_strategy_spaces, validate_strategy_spaces
from .survivorship import audit_survivorship
from .toss import TOSS_GET_ENDPOINTS, TossCredentialsError, TossInvestClient

SCHEMA_VERSION = "1.0"
TOSS_SYMBOL_CHUNK_SIZE = 180
TOSS_WARNING_CHECK_LIMIT = 12
DATA_FAILURE_CODES = {
    FailureCode.DATA_FAILURE.value,
    FailureCode.DATA_CONTRACT_FAILED.value,
    FailureCode.DATA_DISAGREEMENT.value,
    FailureCode.LIVE_PRICE_SAFETY_FAILED.value,
    FailureCode.UNVERIFIED_PRICE_DATA.value,
    FailureCode.SIGNAL_PUBLICATION_INVALID.value,
}

FAILURE_CATALOG: dict[str, tuple[str, str]] = {
    FailureCode.DATA_FAILURE.value: (
        "가격 데이터를 사용할 수 없습니다.",
        "Provider 상태와 API 설정을 확인한 뒤 데이터를 다시 검증하세요.",
    ),
    FailureCode.DATA_CONTRACT_FAILED.value: (
        "데이터가 필수 스키마를 충족하지 못했습니다.",
        "데이터 품질 artifact에서 누락 열과 잘못된 값을 확인하세요.",
    ),
    FailureCode.DATA_DISAGREEMENT.value: (
        "Provider 간 가격 또는 거래량 차이가 허용 범위를 넘었습니다.",
        "불일치 날짜와 provider 원본값을 확인한 뒤 신호를 재검증하세요.",
    ),
    FailureCode.UNVERIFIED_PRICE_DATA.value: (
        "가격 데이터가 교차 검증되지 않았습니다.",
        "최소 두 개의 가격 provider가 성공하도록 설정하세요.",
    ),
    FailureCode.SURVIVORSHIP_GATE_FAILED.value: (
        "생존편향 안전 정책을 통과하지 못했습니다.",
        "시점별 universe 또는 명시적 예외 사유와 strict policy를 준비하세요.",
    ),
    FailureCode.SHADOW_PROMOTION_FAILED.value: (
        "Shadow 승격 조건이 충족되지 않았습니다.",
        "부족한 실행 일수와 품질 조건을 보완하세요.",
    ),
    FailureCode.SAFETY_VERDICT_BLOCKED.value: (
        "최종 안전성 판정이 운영 사용을 차단했습니다.",
        "차단된 데이터, 리스크, 승격 조건을 검토하세요.",
    ),
    FailureCode.SECTOR_EXPOSURE_EXCEEDED.value: (
        "섹터 집중도가 허용 한도를 초과했습니다.",
        "해당 섹터의 승인 포지션 비중을 검토하세요.",
    ),
    FailureCode.SINGLE_POSITION_EXCEEDED.value: (
        "단일 종목 비중이 허용 한도를 초과했습니다.",
        "요청 비중과 승인 비중을 비교하세요.",
    ),
    FailureCode.MIN_CASH_BREACHED.value: (
        "최소 현금 비중을 확보하지 못했습니다.",
        "신규 포지션 크기와 현금 한도를 검토하세요.",
    ),
    FailureCode.LIQUIDITY_INSUFFICIENT.value: (
        "예상 포지션에 비해 유동성이 부족합니다.",
        "거래대금과 참여율 한도를 확인하세요.",
    ),
    FailureCode.UNMAPPED_TICKER.value: (
        "포트폴리오 기준정보에 매핑되지 않은 ticker가 있습니다.",
        "portfolio_mapping.json의 ticker 매핑을 확인하세요.",
    ),
    FailureCode.HEALTH_SCORE_LOW.value: (
        "최근 운영 상태 점수가 기준보다 낮습니다.",
        "최근 실패 run과 health 구성 요소를 확인하세요.",
    ),
    FailureCode.RUN_FAILED.value: (
        "마지막 실행이 완료되지 않았습니다.",
        "실행 로그와 failure code를 확인한 뒤 다시 검증하세요.",
    ),
}


def dashboard_static_dir() -> Path:
    return Path(__file__).with_name("dashboard_static")


def list_dashboard_runs(paths: RuntimePaths, *, limit: int = 100) -> list[dict[str, Any]]:
    if not paths.runs_dir.exists():
        return []
    rows = []
    for run_dir in paths.runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
        if not manifest:
            continue
        result = _mapping(manifest.get("result"))
        rows.append(
            {
                "run_id": str(manifest.get("run_id") or run_dir.name),
                "mode": str(result.get("mode") or manifest.get("execution_mode") or "unknown"),
                "status": str(manifest.get("status") or "unknown"),
                "failure_code": manifest.get("failure_code"),
                "started_at": manifest.get("started_at"),
                "finished_at": manifest.get("finished_at"),
                "command": manifest.get("command"),
            }
        )
    rows.sort(
        key=lambda item: str(item.get("finished_at") or item.get("started_at") or ""), reverse=True
    )
    return rows[:limit]


def build_dashboard_overview(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = now or datetime.now(UTC)
    run_dir = _resolve_run_dir(paths, run_id)
    if run_dir is None:
        return _empty_overview(reference)

    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    result = _mapping(manifest.get("result"))
    verdict = _mapping(read_json(run_dir / "safety_verdict.json", default={}))
    health = _mapping(read_json(paths.state_dir / "health.json", default={}))
    data_quality = build_dashboard_data_quality(paths, run_id=run_dir.name)
    risk = build_dashboard_risk(paths, run_id=run_dir.name)
    promotion = _mapping(read_json(run_dir / "promotion.json", default={}))
    if not promotion:
        promotion = _mapping(read_json(paths.state_dir / "promotion.json", default={}))
    signals = _signal_map(run_dir)
    execution_status = _execution_status(manifest)
    safety_decision = str(
        verdict.get("overall")
        or result.get("safety_verdict")
        or ("blocked" if manifest.get("status") == "failed" else "not_evaluated")
    )
    reasons = _overview_reasons(manifest, verdict, data_quality, risk, promotion)
    display_status = _display_status(execution_status, safety_decision, reasons)
    counts = _signal_counts(signals)
    finished_at = _parse_timestamp(manifest.get("finished_at"))
    age_minutes = (
        round(max(0.0, (reference - finished_at).total_seconds() / 60), 1)
        if finished_at is not None
        else None
    )
    mode = str(result.get("mode") or manifest.get("execution_mode") or "unknown")
    headline = _headline(display_status, reasons, mode)
    health_score = health.get("health_score")
    health_threshold = _promotion_threshold(run_dir, paths)
    survivorship = _survivorship_gate(manifest)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": reference.isoformat(),
        "run": {
            "run_id": str(manifest.get("run_id") or run_dir.name),
            "mode": mode,
            "command": manifest.get("command"),
            "execution_status": execution_status,
            "display_status": display_status,
            "safety_decision": safety_decision,
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "freshness": {
                "status": "unknown"
                if age_minutes is None
                else "stale"
                if age_minutes > 1440
                else "fresh",
                "age_minutes": age_minutes,
            },
            "config_hash": manifest.get("config_hash"),
            "data_hash": result.get("data_hash") or stable_hash(manifest.get("data_hashes", {})),
            "signal_hash": result.get("signal_hash"),
            "failure_code": manifest.get("failure_code"),
        },
        "decision": {
            "overall": display_status,
            "headline": headline,
            "top_reasons": reasons[:3],
        },
        "gates": {
            "data": data_quality["summary"],
            "survivorship": survivorship,
            "risk": risk["summary"],
            "promotion": _promotion_gate(promotion, mode),
        },
        "signals": {
            **counts,
            "rows": _signal_rows(signals),
        },
        "health": {
            "score": health_score,
            "threshold": health_threshold,
            "status": _health_status(health_score, health_threshold),
            "components": health.get("health_components", []),
        },
        "recommended_actions": _recommended_actions(reasons, display_status),
        "artifacts": {
            "run_dir": str(run_dir),
            "report_html": str(run_dir / "report.html")
            if (run_dir / "report.html").exists()
            else None,
            "report_markdown": str(run_dir / "report.md")
            if (run_dir / "report.md").exists()
            else None,
        },
    }


def build_dashboard_decision(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
    now: datetime | None = None,
) -> dict[str, Any]:
    overview = build_dashboard_overview(paths, run_id=run_id, now=now)
    run = _mapping(overview.get("run"))
    decision = _mapping(overview.get("decision"))
    reasons = [
        dict(item) for item in _sequence(decision.get("top_reasons")) if isinstance(item, Mapping)
    ]
    actions = [
        dict(item)
        for item in _sequence(overview.get("recommended_actions"))
        if isinstance(item, Mapping)
    ]
    primary_action = actions[0] if actions else _default_action(str(decision.get("overall")))
    affected_tickers = sorted(
        {
            str(ticker)
            for reason in reasons
            for ticker in _sequence(reason.get("affected_tickers"))
            if ticker
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": overview.get("generated_at"),
        "run_id": run.get("run_id"),
        "mode": run.get("mode"),
        "overall": decision.get("overall", "not_evaluated"),
        "headline": decision.get("headline"),
        "status_rank": _decision_rank(str(decision.get("overall"))),
        "top_blockers": [_decision_blocker(reason) for reason in reasons],
        "recommended_next_action": primary_action,
        "recommended_actions": actions,
        "affected_tickers": affected_tickers,
        "context": {
            "execution_status": run.get("execution_status"),
            "safety_decision": run.get("safety_decision"),
            "finished_at": run.get("finished_at"),
            "freshness": run.get("freshness"),
            "config_hash": run.get("config_hash"),
            "data_hash": run.get("data_hash"),
            "signal_hash": run.get("signal_hash"),
        },
    }


def build_dashboard_data_quality(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(paths, run_id)
    if run_dir is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": None,
            "summary": _empty_data_summary(),
            "sources": [],
            "quality_reports": [],
            "disagreements": [],
            "mismatches": [],
        }
    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    source_payload = _mapping(read_json(run_dir / "data_sources.json", default={}))
    disagreement_payload = _mapping(
        read_json(run_dir / "provider_disagreement_report.json", default={})
    )
    sources = [
        dict(item) for item in _sequence(source_payload.get("sources")) if isinstance(item, Mapping)
    ]
    disagreements = [
        dict(item)
        for item in _sequence(disagreement_payload.get("disagreements"))
        if isinstance(item, Mapping)
    ]
    reports = []
    for key, value in _mapping(manifest.get("data_reports")).items():
        if isinstance(value, Mapping):
            reports.append({"key": str(key), **dict(value)})
    price_reports = [item for item in reports if item.get("ticker")]
    valid_count = sum(
        item.get("valid") is True and item.get("price_usable", True) is True
        for item in price_reports
    )
    failed_sources = sum(item.get("status") != "success" for item in sources)
    blocked_tickers = sorted(
        {
            str(item.get("ticker"))
            for item in price_reports
            if item.get("valid") is not True or item.get("price_usable", True) is not True
        }
        | {str(item.get("ticker")) for item in disagreements if item.get("ticker")}
    )
    providers = sorted({str(item.get("provider")) for item in sources if item.get("provider")})
    status = "not_evaluated"
    if price_reports or sources:
        status = "data_error" if disagreements or blocked_tickers or failed_sources else "pass"
    if manifest.get("failure_code") in DATA_FAILURE_CODES:
        status = "data_error"
    summary = {
        "status": status,
        "verified": valid_count,
        "total": len(price_reports),
        "validation_rate": round(valid_count / len(price_reports), 4) if price_reports else None,
        "provider_count": len(providers),
        "providers": providers,
        "failed_source_count": failed_sources,
        "disagreement_count": len(disagreements),
        "blocked_ticker_count": len(blocked_tickers),
        "blocked_tickers": blocked_tickers,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "summary": summary,
        "sources": sources,
        "quality_reports": reports,
        "disagreements": disagreements,
        "mismatches": _flatten_mismatches(disagreements),
    }


def build_dashboard_risk(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(paths, run_id)
    if run_dir is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": None,
            "summary": _empty_risk_summary(),
            "signals": [],
            "checks": [],
        }
    explanation = _mapping(read_json(run_dir / "risk_explanation.json", default={}))
    signal_map = _mapping(read_json(run_dir / "signals_risk.json", default={}))
    rows = [
        dict(item) for item in _sequence(explanation.get("signals")) if isinstance(item, Mapping)
    ]
    if not rows and signal_map:
        rows = _risk_rows_from_signals(signal_map)
    checks = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        for state, key in (("pass", "passed"), ("blocked", "failed")):
            for detail in _sequence(row.get(key)):
                if not isinstance(detail, Mapping):
                    continue
                checks.append(
                    {
                        "ticker": ticker,
                        "status": state,
                        "code": detail.get("code"),
                        "message": detail.get("message"),
                        "metric": detail.get("metric"),
                        "observed": detail.get("observed"),
                        "limit": detail.get("limit"),
                        "excess": detail.get("excess"),
                    }
                )
    reviewed = [row for row in rows if row.get("reviewed", True)]
    blocked = [row for row in reviewed if row.get("eligible") is not True]
    approved_count = int(explanation.get("approved_count", len(reviewed) - len(blocked)) or 0)
    blocked_count = int(explanation.get("blocked_count", len(blocked)) or 0)
    hold_count = int(explanation.get("hold_count", max(0, len(rows) - len(reviewed))) or 0)
    summary = {
        "status": "not_evaluated" if not rows else "blocked" if blocked_count else "pass",
        "approved_count": approved_count,
        "blocked_count": blocked_count,
        "hold_count": hold_count,
        "top_block_reasons": explanation.get("top_block_reasons", _top_reason_counts(checks)),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "summary": summary,
        "signals": rows,
        "checks": checks,
    }


def build_dashboard_signals(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(paths, run_id)
    if run_dir is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": None,
            "summary": _empty_signal_summary(),
            "publication": {"status": "missing"},
            "rows": [],
        }
    signals = _signal_map(run_dir)
    rows = _signal_rows(signals)
    counts = _signal_counts(signals)
    publication = _signal_publication(run_dir, paths)
    data_verified = sum(item.get("data_verified") is True for item in rows)
    total = len(rows)
    status = (
        "not_evaluated"
        if not rows
        else "blocked"
        if counts["blocked"]
        else "pass"
        if counts["eligible"]
        else "warning"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "summary": {
            "status": status,
            "buy_count": counts["buy"],
            "eligible_count": counts["eligible"],
            "blocked_count": counts["blocked"],
            "hold_count": counts["hold"],
            "data_verified_count": data_verified,
            "total_count": total,
            "data_verified_rate": round(data_verified / total, 4) if total else None,
        },
        "publication": publication,
        "rows": rows,
    }


def build_dashboard_trader_lens(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(paths, run_id)
    if run_dir is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": None,
            "summary": {
                "status": "not_evaluated",
                "average_reward_to_risk": None,
                "signals_reviewed": 0,
                "provider_issue_count": 0,
                "risk_issue_count": 0,
            },
            "signal_ladder": [],
            "provider_trust": [],
            "risk_concentration": [],
            "decision_notes": [],
        }
    signals = build_dashboard_signals(paths, run_id=run_dir.name)
    data_quality = build_dashboard_data_quality(paths, run_id=run_dir.name)
    risk = build_dashboard_risk(paths, run_id=run_dir.name)
    decision = build_dashboard_decision(paths, run_id=run_dir.name)
    signal_ladder = _trader_signal_ladder(_sequence(signals.get("rows")))
    provider_trust = _provider_trust_rows(data_quality)
    risk_concentration = _risk_concentration_rows(risk)
    rr_values = [
        item["reward_to_risk"]
        for item in signal_ladder
        if isinstance(item.get("reward_to_risk"), (int, float))
    ]
    data_summary = _mapping(data_quality.get("summary"))
    risk_summary = _mapping(risk.get("summary"))
    signal_summary = _mapping(signals.get("summary"))
    status = (
        "data_error"
        if data_summary.get("status") == "data_error"
        else "blocked"
        if risk_summary.get("status") == "blocked" or signal_summary.get("blocked_count")
        else "success"
        if signal_ladder
        else "not_evaluated"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "summary": {
            "status": status,
            "average_reward_to_risk": round(sum(rr_values) / len(rr_values), 3)
            if rr_values
            else None,
            "signals_reviewed": len(signal_ladder),
            "eligible_count": signal_summary.get("eligible_count", 0),
            "blocked_count": signal_summary.get("blocked_count", 0),
            "provider_issue_count": int(data_summary.get("disagreement_count", 0) or 0)
            + int(data_summary.get("failed_source_count", 0) or 0),
            "risk_issue_count": int(risk_summary.get("blocked_count", 0) or 0),
        },
        "signal_ladder": signal_ladder,
        "provider_trust": provider_trust,
        "risk_concentration": risk_concentration,
        "decision_notes": decision.get("top_blockers", []),
        "read_only": True,
    }


def build_dashboard_promotion(paths: RuntimePaths) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)
    stored = _mapping(read_json(paths.state_dir / "promotion.json", default={}))
    if stored:
        report = dict(stored)
    else:
        report = evaluate_shadow_promotion(
            paths.signals_dir / "shadow",
            paths.state_dir / "health.json",
            settings.promotion,
        )
    criteria = [
        dict(item) for item in _sequence(report.get("criteria")) if isinstance(item, Mapping)
    ]
    failed = [item for item in criteria if item.get("passed") is not True]
    history = _shadow_daily_history(paths.signals_dir / "shadow")
    metrics = _mapping(report.get("metrics"))
    eligible = report.get("eligible") is True
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "status": "pass" if eligible else "blocked",
            "eligible": eligible,
            "shadow_day_count": len(_sequence(report.get("shadow_days"))),
            "buy_signal_count": int(report.get("buy_signal_count", 0) or 0),
            "completed_signal_count": int(report.get("completed_signal_count", 0) or 0),
            "failed_criteria_count": len(failed),
            "failure_code": report.get("failure_code"),
        },
        "metrics": dict(metrics),
        "criteria": criteria,
        "critical_failures": report.get("critical_failures", []),
        "history": history,
        "report": report,
    }


def build_dashboard_settings_validation(
    paths: RuntimePaths,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    load_error: str | None = None
    mode_error: str | None = None
    try:
        base_settings = _load_dashboard_settings(paths)
    except Exception as exc:
        load_error = str(exc)
        base_settings = Settings()
    requested_mode = mode or base_settings.mode
    try:
        settings = Settings.model_validate({**base_settings.model_dump(), "mode": requested_mode})
    except (ValidationError, ValueError) as exc:
        mode_error = str(exc)
        settings = base_settings.model_copy(update={"mode": requested_mode})

    provider_audit: dict[str, Any]
    try:
        provider_audit = provider_configuration_audit(
            settings,
            build_provider_registry(settings, paths.cache_dir),
        )
    except Exception as exc:
        provider_audit = {"valid": False, "errors": [str(exc)], "warnings": []}

    survivorship_audit: dict[str, Any]
    try:
        survivorship_audit = audit_survivorship(settings).to_dict()
    except ValueError as exc:
        survivorship_audit = {
            "valid": False,
            "policy": settings.universe.policy,
            "error": str(exc),
        }

    strategy_space_audit: dict[str, Any]
    try:
        strategy_space_audit = validate_strategy_spaces(load_strategy_spaces())
    except Exception as exc:
        strategy_space_audit = {"valid": False, "errors": [str(exc)]}

    promotion_audit = evaluate_shadow_promotion(
        paths.signals_dir / "shadow",
        paths.state_dir / "health.json",
        settings.promotion,
    )
    rules = _settings_rules(
        settings,
        requested_mode=str(requested_mode),
        provider_audit=provider_audit,
        survivorship_audit=survivorship_audit,
        promotion_audit=promotion_audit,
        load_error=load_error,
        mode_error=mode_error,
    )
    errors = [item for item in rules if item["status"] == "blocked"]
    warnings = [item for item in rules if item["status"] == "warning"]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": str(requested_mode),
        "summary": {
            "status": "blocked" if errors else "warning" if warnings else "pass",
            "blocked_count": len(errors),
            "warning_count": len(warnings),
            "safe": not errors,
        },
        "rules": rules,
        "provider_audit": provider_audit,
        "survivorship_audit": survivorship_audit,
        "promotion_audit": promotion_audit,
        "strategy_space_audit": strategy_space_audit,
        "settings": settings.public_dict(),
    }


def build_dashboard_toss_status(paths: RuntimePaths) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)
    api_key = _secret_value(settings.toss_api_key)
    secret_key = _secret_value(settings.toss_secret_key)
    account = _secret_value(settings.toss_account)
    configured = bool(api_key and secret_key)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "configured" if configured else "missing_credentials",
        "read_only": True,
        "credentials": {
            "api_key": bool(api_key),
            "secret_key": bool(secret_key),
            "account": bool(account),
        },
        "account_required_for": [
            endpoint.operation_id for endpoint in TOSS_GET_ENDPOINTS if endpoint.requires_account
        ],
        "endpoints": [
            {
                "operation_id": endpoint.operation_id,
                "method": "GET",
                "path": endpoint.path,
                "requires_account": endpoint.requires_account,
            }
            for endpoint in TOSS_GET_ENDPOINTS
        ],
        "warnings": []
        if configured
        else ["Set TS_API_KEY and TS_SECRET_KEY in .env or environment."],
    }


def build_dashboard_toss_accounts(
    paths: RuntimePaths,
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)
    configured_account = _secret_value(settings.toss_account)
    status = build_dashboard_toss_status(paths)
    if status["status"] != "configured" and client is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "missing_credentials",
            "read_only": True,
            "accounts": [],
            "default_account_seq": configured_account,
            "message": "Set TS_API_KEY and TS_SECRET_KEY before account lookup.",
        }
    resolved_client = client or _dashboard_toss_client(settings)
    result = _toss_call("getAccounts", lambda: resolved_client.accounts())
    if result["status"] != "success":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "read_only": True,
            "accounts": [],
            "default_account_seq": configured_account,
            "error": result.get("message"),
        }
    accounts = _normalize_toss_accounts(result.get("payload"), configured_account)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "read_only": True,
        "accounts": accounts,
        "default_account_seq": configured_account,
        "auto_select_account_seq": accounts[0]["account_seq"] if len(accounts) == 1 else None,
        "permissions": {
            "read": True,
            "order": False,
            "automation": False,
            "reason": "Jayu dashboard currently exposes Toss GET endpoints only.",
        },
    }


def build_dashboard_toss_portfolio(
    paths: RuntimePaths,
    *,
    account: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)
    configured_account = _secret_value(settings.toss_account)
    status = build_dashboard_toss_status(paths)
    if status["status"] != "configured" and client is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "missing_credentials",
            "read_only": True,
            "accounts": [],
            "selected_account": None,
            "holdings": [],
            "allocation": [],
            "sections": {},
            "summary": _empty_toss_portfolio_summary("missing_credentials"),
            "message": "Set TS_API_KEY and TS_SECRET_KEY before account lookup.",
        }
    resolved_client = client or _dashboard_toss_client(settings)
    accounts_result = _toss_call("getAccounts", lambda: resolved_client.accounts())
    if accounts_result["status"] != "success":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "read_only": True,
            "accounts": [],
            "selected_account": None,
            "holdings": [],
            "allocation": [],
            "sections": {"accounts": accounts_result},
            "summary": _empty_toss_portfolio_summary("failed"),
            "error": accounts_result.get("message"),
        }
    accounts = _normalize_toss_accounts(accounts_result.get("payload"), configured_account)
    selected = _select_toss_account(accounts, requested=account, configured=configured_account)
    if selected is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "no_accounts",
            "read_only": True,
            "accounts": accounts,
            "selected_account": None,
            "holdings": [],
            "allocation": [],
            "sections": {"accounts": accounts_result},
            "summary": _empty_toss_portfolio_summary("no_accounts"),
            "message": "Toss accounts response did not include an account row.",
        }
    selected_seq = str(selected["account_seq"])
    sections = {
        "accounts": accounts_result,
        "holdings": _toss_call(
            "getHoldings",
            lambda: resolved_client.holdings(account=selected_seq),
        ),
    }
    holdings = _normalize_toss_holdings(_mapping(sections["holdings"]).get("payload"))
    fx_sections = _toss_fx_sections(resolved_client, holdings)
    sections.update(fx_sections)
    fx_rates = _normalize_toss_fx_rates(sections)
    holdings = _apply_toss_fx_conversion(holdings, fx_rates)
    enrichment_sections = _toss_enrichment_sections(resolved_client, holdings)
    sections.update(enrichment_sections)
    holdings = _apply_toss_enrichment(holdings, enrichment_sections)
    summary = _toss_portfolio_summary(
        holdings,
        [],
        failed_sections=[
            name for name, section in sections.items() if _mapping(section).get("status") == "failed"
        ],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": summary["status"],
        "read_only": True,
        "accounts": accounts,
        "selected_account": selected,
        "auto_select_account_seq": selected_seq,
        "holdings": holdings,
        "allocation": [
            item for item in holdings if isinstance(item.get("weight"), (int, float))
        ],
        "buying_power": [],
        "valuation_currency": "KRW",
        "fx_rates": fx_rates,
        "currency_totals": _toss_currency_totals(holdings),
        "region_totals": _toss_region_totals(holdings),
        "category_totals": _toss_category_totals(holdings),
        "sector_totals": _toss_sector_totals(holdings),
        "situation_totals": _toss_situation_totals(holdings),
        "enrichment": _toss_enrichment_summary(holdings, sections),
        "sections": {name: _toss_section_status(section) for name, section in sections.items()},
        "summary": summary,
        "permissions": {
            "read": True,
            "order": False,
            "automation": False,
            "reason": "Toss Account dashboard uses GET account endpoints only.",
        },
    }


def build_dashboard_toss_market_snapshot(
    paths: RuntimePaths,
    *,
    symbol: str,
    account: str | None = None,
    include_account: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)
    symbol_code = symbol.strip().upper()
    if not symbol_code:
        raise ValueError("symbol is required")
    resolved_client = client or _dashboard_toss_client(settings)
    sections = {
        "price": _toss_call("getPrices", lambda: resolved_client.prices(symbol_code)),
        "stock": _toss_call("getStocks", lambda: resolved_client.stocks(symbol_code)),
        "warnings": _toss_call(
            "getStockWarnings", lambda: resolved_client.stock_warnings(symbol_code)
        ),
        "price_limit": _toss_call(
            "getPriceLimit", lambda: resolved_client.price_limits(symbol_code)
        ),
        "orderbook": _toss_call("getOrderbook", lambda: resolved_client.orderbook(symbol_code)),
        "trades": _toss_call(
            "getTrades", lambda: resolved_client.trades(symbol_code, count=50)
        ),
        "candles_1d": _toss_call(
            "getCandles:1d",
            lambda: resolved_client.candles(symbol_code, interval="1d", count=100),
        ),
        "candles_1m": _toss_call(
            "getCandles:1m",
            lambda: resolved_client.candles(symbol_code, interval="1m", count=100),
        ),
    }
    account_sections: dict[str, Any] = {}
    if include_account:
        account_sections = {
            "holdings": _toss_call(
                "getHoldings",
                lambda: resolved_client.holdings(account=account, symbol=symbol_code),
            ),
            "sellable_quantity": _toss_call(
                "getSellableQuantity",
                lambda: resolved_client.sellable_quantity(symbol_code, account=account),
            ),
        }
    successful = sum(item.get("status") == "success" for item in sections.values())
    failed = sum(item.get("status") == "failed" for item in sections.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol_code,
        "read_only": True,
        "summary": {
            "status": "failed" if failed and not successful else "warning" if failed else "success",
            "successful_sections": successful,
            "failed_sections": failed,
            "account_sections_included": include_account,
        },
        "sections": sections,
        "account_sections": account_sections,
        "available_actions": [
            "review_quote",
            "review_orderbook",
            "review_candles",
            "review_warnings",
        ],
    }


def serve_dashboard(
    paths: RuntimePaths,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    server = create_dashboard_server(paths, host=host, port=port)
    url = f"http://{host}:{port}"
    print(f"Jayu dashboard: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def create_dashboard_server(
    paths: RuntimePaths,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    static_dir = dashboard_static_dir()
    if not (static_dir / "index.html").exists():
        raise RuntimeError(f"dashboard assets are missing: {static_dir}")
    return ThreadingHTTPServer((host, port), _dashboard_handler(paths, static_dir))


def _dashboard_handler(
    paths: RuntimePaths,
    static_dir: Path,
) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/v1/runs":
                    self._json(
                        {"schema_version": SCHEMA_VERSION, "runs": list_dashboard_runs(paths)}
                    )
                    return
                if parsed.path == "/api/v1/overview":
                    run_id = parse_qs(parsed.query).get("run_id", ["latest"])[0]
                    self._json(build_dashboard_overview(paths, run_id=run_id))
                    return
                if parsed.path == "/api/v1/decision":
                    run_id = parse_qs(parsed.query).get("run_id", ["latest"])[0]
                    self._json(build_dashboard_decision(paths, run_id=run_id))
                    return
                segments = [item for item in parsed.path.split("/") if item]
                if len(segments) == 5 and segments[:3] == ["api", "v1", "runs"]:
                    run_id = unquote(segments[3])
                    if segments[4] == "data-quality":
                        self._json(build_dashboard_data_quality(paths, run_id=run_id))
                        return
                    if segments[4] == "risk":
                        self._json(build_dashboard_risk(paths, run_id=run_id))
                        return
                    if segments[4] == "signals":
                        self._json(build_dashboard_signals(paths, run_id=run_id))
                        return
                    if segments[4] == "trader-lens":
                        self._json(build_dashboard_trader_lens(paths, run_id=run_id))
                        return
                if parsed.path == "/api/v1/promotion":
                    self._json(build_dashboard_promotion(paths))
                    return
                if parsed.path == "/api/v1/settings/validation":
                    mode = parse_qs(parsed.query).get("mode", [None])[0]
                    self._json(build_dashboard_settings_validation(paths, mode=mode))
                    return
                if parsed.path == "/api/v1/toss/status":
                    self._json(build_dashboard_toss_status(paths))
                    return
                if parsed.path == "/api/v1/toss/accounts":
                    self._json(build_dashboard_toss_accounts(paths))
                    return
                if parsed.path == "/api/v1/toss/portfolio":
                    query = parse_qs(parsed.query)
                    self._json(
                        build_dashboard_toss_portfolio(
                            paths,
                            account=query.get("account", [None])[0],
                        )
                    )
                    return
                if parsed.path == "/api/v1/toss/market":
                    query = parse_qs(parsed.query)
                    self._json(
                        build_dashboard_toss_market_snapshot(
                            paths,
                            symbol=query.get("symbol", [""])[0],
                            account=query.get("account", [None])[0],
                            include_account=query.get("include_account", ["false"])[0].lower()
                            == "true",
                        )
                    )
                    return
                if parsed.path.startswith("/api/"):
                    self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._static(parsed.path)
            except ValueError as exc:
                self._json({"error": "invalid_request", "message": str(exc)}, status=400)
            except Exception as exc:
                self._json(
                    {"error": "internal_error", "message": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _json(self, payload: Any, *, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, request_path: str) -> None:
            relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
            candidate = (static_dir / relative).resolve()
            root = static_dir.resolve()
            if root not in candidate.parents and candidate != root:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not candidate.is_file():
                candidate = static_dir / "index.html"
            body = candidate.read_bytes()
            content_type, _ = mimetypes.guess_type(candidate.name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def _resolve_run_dir(paths: RuntimePaths, run_id: str) -> Path | None:
    runs = list_dashboard_runs(paths)
    if not runs:
        return None
    selected = runs[0]["run_id"] if run_id == "latest" else run_id
    candidate = (paths.runs_dir / selected).resolve()
    root = paths.runs_dir.resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise ValueError("unknown run_id")
    return candidate


def _empty_overview(reference: datetime) -> dict[str, Any]:
    reason = _reason(FailureCode.NO_RUN_HISTORY.value, component="run")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": reference.isoformat(),
        "run": {
            "run_id": None,
            "mode": "unknown",
            "execution_status": "not_evaluated",
            "display_status": "not_evaluated",
            "safety_decision": "not_evaluated",
        },
        "decision": {
            "overall": "not_evaluated",
            "headline": "아직 완료된 Jayu 실행이 없습니다.",
            "top_reasons": [reason],
        },
        "gates": {
            "data": _empty_data_summary(),
            "survivorship": {"status": "not_evaluated"},
            "risk": _empty_risk_summary(),
            "promotion": {"status": "not_evaluated", "eligible": False},
        },
        "signals": {"buy": 0, "eligible": 0, "blocked": 0, "hold": 0, "rows": []},
        "health": {"score": None, "threshold": None, "status": "not_evaluated"},
        "recommended_actions": [
            {
                "id": "validate-config",
                "label": "설정 검증",
                "page": "settings",
                "priority": 1,
            }
        ],
        "artifacts": {},
    }


def _empty_data_summary() -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "verified": 0,
        "total": 0,
        "validation_rate": None,
        "provider_count": 0,
        "providers": [],
        "failed_source_count": 0,
        "disagreement_count": 0,
        "blocked_ticker_count": 0,
        "blocked_tickers": [],
    }


def _empty_risk_summary() -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "approved_count": 0,
        "blocked_count": 0,
        "hold_count": 0,
        "top_block_reasons": [],
    }


def _empty_signal_summary() -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "buy_count": 0,
        "eligible_count": 0,
        "blocked_count": 0,
        "hold_count": 0,
        "data_verified_count": 0,
        "total_count": 0,
        "data_verified_rate": None,
    }


def _load_dashboard_settings(paths: RuntimePaths) -> Settings:
    config = paths.config_file if paths.config_file.exists() else None
    return load_settings(config)


def _secret_value(value: Any) -> str | None:
    return value.get_secret_value() if value else None


def _dashboard_toss_client(settings: Settings) -> TossInvestClient:
    api_key = _secret_value(settings.toss_api_key)
    secret_key = _secret_value(settings.toss_secret_key)
    if not api_key or not secret_key:
        raise TossCredentialsError("Toss Open API requires TS_API_KEY and TS_SECRET_KEY")
    return TossInvestClient(
        api_key,
        secret_key,
        account=_secret_value(settings.toss_account),
        policy=provider_policy(settings, "toss"),
    )


def _toss_call(operation_id: str, loader: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload = loader()
        return {
            "operation_id": operation_id,
            "status": "success",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "payload": payload,
        }
    except Exception as exc:
        return {
            "operation_id": operation_id,
            "status": "failed",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "message": str(exc),
        }


def _toss_section_status(section: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": section.get("operation_id"),
        "status": section.get("status"),
        "latency_ms": section.get("latency_ms"),
        "message": section.get("message"),
    }


def _normalize_toss_accounts(payload: Any, default_account_seq: str | None) -> list[dict[str, Any]]:
    rows = _extract_toss_account_rows(payload)
    default_seq = str(default_account_seq).strip() if default_account_seq else None
    accounts: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        account_seq = _first_text(
            row,
            "accountSeq",
            "account_seq",
            "accountId",
            "account_id",
            "seq",
            "id",
        )
        account_no = _first_text(
            row,
            "maskedAccountNo",
            "masked_account_no",
            "accountNo",
            "account_no",
            "accountNumber",
            "account_number",
        )
        display_name = _first_text(
            row,
            "accountName",
            "account_name",
            "name",
            "alias",
            "nickname",
        )
        if not account_seq:
            account_seq = f"account-{index + 1}"
        accounts.append(
            {
                "account_seq": account_seq,
                "display_name": display_name or f"Toss account {index + 1}",
                "masked_account_no": _mask_account_text(account_no or account_seq),
                "account_type": _first_text(row, "accountType", "account_type", "type"),
                "currency": _first_text(row, "currency", "baseCurrency", "base_currency"),
                "is_default": bool(default_seq and account_seq == default_seq),
                "permissions": {
                    "read": True,
                    "order": False,
                    "automation": False,
                },
            }
        )
    return accounts


def _extract_toss_account_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("accounts", "accountList", "account_list", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    for key in ("data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            return _extract_toss_account_rows(value)
    if any(str(key).lower().startswith("account") for key in payload):
        return [payload]
    return []


def _select_toss_account(
    accounts: Sequence[Mapping[str, Any]],
    *,
    requested: str | None,
    configured: str | None,
) -> Mapping[str, Any] | None:
    if not accounts:
        return None
    preferred = [value.strip() for value in (requested, configured) if value and value.strip()]
    for account in accounts:
        account_seq = str(account.get("account_seq") or "")
        if account_seq and account_seq in preferred:
            return account
    return accounts[0]


def _normalize_toss_holdings(payload: Any) -> list[dict[str, Any]]:
    rows = _extract_toss_rows(
        payload,
        keys=(
            "holdings",
            "positions",
            "stockBalances",
            "stock_balances",
            "stocks",
            "assets",
            "items",
            "balances",
            "result",
        ),
    )
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        symbol = _first_text(
            row,
            "symbol",
            "stockCode",
            "stock_code",
            "symbolCode",
            "symbol_code",
            "ticker",
            "securityCode",
            "security_code",
            "code",
        ) or _deep_text(
            row,
            "symbol",
            "stockCode",
            "stock_code",
            "symbolCode",
            "symbol_code",
            "ticker",
            "securityCode",
            "security_code",
            "code",
        )
        quantity = _first_number(
            row,
            "quantity",
            "qty",
            "holdingQuantity",
            "holding_quantity",
            "balanceQuantity",
            "balance_quantity",
        ) or _deep_number(
            row,
            "quantity",
            "qty",
            "holdingQuantity",
            "holding_quantity",
            "balanceQuantity",
            "balance_quantity",
        )
        average_price = _first_number(
            row,
            "averagePrice",
            "average_price",
            "avgPrice",
            "avg_price",
            "purchasePrice",
            "purchase_price",
            "unitCost",
            "unit_cost",
        ) or _deep_number(
            row,
            "averagePrice",
            "average_price",
            "avgPrice",
            "avg_price",
            "purchasePrice",
            "purchase_price",
            "unitCost",
            "unit_cost",
        )
        current_price = _first_number(
            row,
            "currentPrice",
            "current_price",
            "marketPrice",
            "market_price",
            "lastPrice",
            "last_price",
            "close",
            "price",
        ) or _deep_number(
            row,
            "currentPrice",
            "current_price",
            "marketPrice",
            "market_price",
            "lastPrice",
            "last_price",
            "close",
            "price",
        )
        market_value = _first_number(
            row,
            "marketValue",
            "market_value",
            "valuationAmount",
            "valuation_amount",
            "evaluatedAmount",
            "evaluated_amount",
            "evaluationAmount",
            "evaluation_amount",
        ) or _deep_number(
            row,
            "marketValue",
            "market_value",
            "valuationAmount",
            "valuation_amount",
            "evaluatedAmount",
            "evaluated_amount",
            "evaluationAmount",
            "evaluation_amount",
        )
        cost_basis = _first_number(
            row,
            "costBasis",
            "cost_basis",
            "purchaseAmount",
            "purchase_amount",
            "investmentAmount",
            "investment_amount",
            "principal",
        ) or _deep_number(
            row,
            "costBasis",
            "cost_basis",
            "purchaseAmount",
            "purchase_amount",
            "investmentAmount",
            "investment_amount",
            "principal",
        )
        if market_value is None and quantity is not None and current_price is not None:
            market_value = quantity * current_price
        if cost_basis is None and quantity is not None and average_price is not None:
            cost_basis = quantity * average_price
        unrealized_pnl = _first_number(
            row,
            "unrealizedPnl",
            "unrealized_pnl",
            "profitLoss",
            "profit_loss",
            "evaluationProfitLoss",
            "evaluation_profit_loss",
            "pnl",
        )
        if unrealized_pnl is None and market_value is not None and cost_basis is not None:
            unrealized_pnl = market_value - cost_basis
        unrealized_pnl_pct = _normalize_ratio(
            _first_number(
                row,
                "unrealizedPnlRate",
                "unrealized_pnl_rate",
                "profitLossRate",
                "profit_loss_rate",
                "pnlRate",
                "pnl_rate",
                "returnRate",
                "return_rate",
            )
        )
        if unrealized_pnl_pct is None and unrealized_pnl is not None and cost_basis:
            unrealized_pnl_pct = unrealized_pnl / cost_basis
        normalized.append(
            {
                "rank": index + 1,
                "symbol": symbol or f"HOLDING-{index + 1}",
                "name": _first_text(
                    row,
                "name",
                "stockName",
                "stock_name",
                "securityName",
                "security_name",
                "displayName",
                "display_name",
                )
                or _deep_text(
                    row,
                    "name",
                    "stockName",
                    "stock_name",
                    "securityName",
                    "security_name",
                    "displayName",
                    "display_name",
                ),
                "quantity": _round_or_none(quantity, 8),
                "average_price": _round_or_none(average_price, 4),
                "current_price": _round_or_none(current_price, 4),
                "market_value": _round_or_none(market_value, 4),
                "cost_basis": _round_or_none(cost_basis, 4),
                "unrealized_pnl": _round_or_none(unrealized_pnl, 4),
                "unrealized_pnl_pct": _round_or_none(unrealized_pnl_pct, 6),
                "currency": _first_text(row, "currency", "currencyCode", "currency_code") or "-",
                "exchange": _first_text(row, "exchange", "market", "marketCode", "market_code"),
            }
        )
        normalized[-1]["currency"] = _infer_toss_currency(
            str(normalized[-1].get("symbol") or ""),
            str(normalized[-1].get("currency") or ""),
            str(normalized[-1].get("exchange") or ""),
        )
        normalized[-1]["market_region"] = _infer_toss_market_region(
            str(normalized[-1].get("symbol") or ""),
            str(normalized[-1].get("currency") or ""),
            str(normalized[-1].get("exchange") or ""),
        )
    total_value = sum(
        value
        for item in normalized
        for value in [_float_or_none(item.get("market_value"))]
        if value is not None
    )
    if total_value > 0:
        for item in normalized:
            market_value = _float_or_none(item.get("market_value"))
            item["weight"] = _round_or_none(
                market_value / total_value if market_value is not None else None,
                6,
            )
    return sorted(
        normalized,
        key=lambda item: -(_float_or_none(item.get("market_value")) or 0.0),
    )


def _normalize_toss_buying_power(currency: str, payload: Any) -> dict[str, Any]:
    row = _first_mapping(payload)
    buying_power = _first_number(
        row,
        "buyingPower",
        "buying_power",
        "orderableAmount",
        "orderable_amount",
        "availableAmount",
        "available_amount",
        "cash",
    )
    withdrawable = _first_number(
        row,
        "withdrawableAmount",
        "withdrawable_amount",
        "withdrawable",
        "availableWithdrawalAmount",
        "available_withdrawal_amount",
    )
    return {
        "currency": currency,
        "buying_power": _round_or_none(buying_power, 4),
        "withdrawable": _round_or_none(withdrawable, 4),
    }


def _toss_fx_sections(
    client: Any,
    holdings: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    currencies = {
        str(item.get("currency") or "").upper()
        for item in holdings
        if str(item.get("currency") or "").upper() not in {"", "-", "KRW"}
    }
    sections: dict[str, dict[str, Any]] = {}
    date_time = datetime.now(ZoneInfo("Asia/Seoul")).replace(microsecond=0).isoformat()
    for currency in sorted(currencies):
        sections[f"exchange_rate_{currency.lower()}_krw"] = _toss_call(
            f"getExchangeRate:{currency}/KRW",
            lambda currency=currency: client.exchange_rate(
                base_currency=currency,
                quote_currency="KRW",
                date_time=date_time,
            ),
        )
    return sections


def _normalize_toss_fx_rates(sections: Mapping[str, Any]) -> list[dict[str, Any]]:
    rates = [
        {
            "base_currency": "KRW",
            "quote_currency": "KRW",
            "rate": 1.0,
            "mid_rate": 1.0,
            "status": "success",
            "valid_from": None,
            "valid_until": None,
            "rate_change_type": "FLAT",
        }
    ]
    for name, section in sections.items():
        if not str(name).startswith("exchange_rate_"):
            continue
        mapped = _mapping(section)
        payload = _first_mapping(mapped.get("payload"))
        base = (_first_text(payload, "baseCurrency", "base_currency") or "").upper()
        quote = (_first_text(payload, "quoteCurrency", "quote_currency") or "KRW").upper()
        rate = _first_number(payload, "rate", "midRate", "mid_rate")
        rates.append(
            {
                "base_currency": base or name.replace("exchange_rate_", "").split("_")[0].upper(),
                "quote_currency": quote,
                "rate": _round_or_none(rate, 8),
                "mid_rate": _round_or_none(_first_number(payload, "midRate", "mid_rate"), 8),
                "basis_point": _round_or_none(_first_number(payload, "basisPoint", "basis_point"), 4),
                "rate_change_type": _first_text(payload, "rateChangeType", "rate_change_type"),
                "valid_from": _first_text(payload, "validFrom", "valid_from"),
                "valid_until": _first_text(payload, "validUntil", "valid_until"),
                "status": mapped.get("status"),
                "message": mapped.get("message"),
            }
        )
    return rates


def _apply_toss_fx_conversion(
    holdings: Sequence[Mapping[str, Any]],
    fx_rates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rate_map = {
        str(rate.get("base_currency") or "").upper(): _float_or_none(rate.get("rate"))
        for rate in fx_rates
        if str(rate.get("quote_currency") or "").upper() == "KRW"
        and rate.get("status") == "success"
    }
    converted: list[dict[str, Any]] = []
    for item in holdings:
        row = dict(item)
        currency = str(row.get("currency") or "KRW").upper()
        rate = rate_map.get(currency)
        row["fx_rate_to_krw"] = _round_or_none(rate, 8)
        row["fx_status"] = "success" if rate is not None else "missing"
        for source_key, target_key in (
            ("market_value", "market_value_krw"),
            ("cost_basis", "cost_basis_krw"),
            ("unrealized_pnl", "unrealized_pnl_krw"),
        ):
            value = _float_or_none(row.get(source_key))
            row[target_key] = _round_or_none(value * rate, 4) if value is not None and rate else None
        converted.append(row)
    total_value = sum(
        value
        for item in converted
        for value in [_float_or_none(item.get("market_value_krw"))]
        if value is not None
    )
    if total_value > 0:
        for item in converted:
            market_value = _float_or_none(item.get("market_value_krw"))
            item["weight"] = _round_or_none(
                market_value / total_value if market_value is not None else None,
                6,
            )
    return sorted(
        converted,
        key=lambda item: -(_float_or_none(item.get("market_value_krw")) or 0.0),
    )


def _toss_enrichment_sections(
    client: Any,
    holdings: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    symbols = _holding_symbols(holdings)
    sections: dict[str, dict[str, Any]] = {}
    for index, chunk in enumerate(_chunks(symbols, TOSS_SYMBOL_CHUNK_SIZE), start=1):
        sections[f"stocks_{index}"] = _toss_call(
            f"getStocks:{index}",
            lambda chunk=chunk: client.stocks(chunk),
        )
        sections[f"prices_{index}"] = _toss_call(
            f"getPrices:{index}",
            lambda chunk=chunk: client.prices(chunk),
        )
    warning_targets = sorted(
        holdings,
        key=lambda item: -(_float_or_none(item.get("market_value_krw")) or 0.0),
    )[:TOSS_WARNING_CHECK_LIMIT]
    for item in warning_targets:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        sections[f"warnings_{_section_symbol(symbol)}"] = _toss_call(
            f"getStockWarnings:{symbol}",
            lambda symbol=symbol: client.stock_warnings(symbol),
        )
    return sections


def _apply_toss_enrichment(
    holdings: Sequence[Mapping[str, Any]],
    sections: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    stock_map = _toss_symbol_payload_map(sections, prefix="stocks_", keys=("stocks", "result", "data", "items"))
    price_map = _toss_symbol_payload_map(sections, prefix="prices_", keys=("prices", "result", "data", "items"))
    warning_map = _toss_warning_map(sections)
    enriched: list[dict[str, Any]] = []
    for item in holdings:
        row = dict(item)
        symbol = str(row.get("symbol") or "")
        stock = stock_map.get(symbol, {})
        price = price_map.get(symbol, {})
        warning_rows = warning_map.get(symbol, [])
        name = row.get("name") or _deep_text(
            stock,
            "name",
            "stockName",
            "stock_name",
            "securityName",
            "security_name",
            "displayName",
            "display_name",
        )
        asset_type = _classify_toss_asset_type(symbol, str(name or ""), stock)
        sector = _deep_text(stock, "sector", "sectorName", "sector_name", "industryGroup")
        industry = _deep_text(stock, "industry", "industryName", "industry_name", "subIndustry")
        day_change_pct = _normalize_ratio(
            _deep_number(
                price,
                "changeRate",
                "change_rate",
                "dayChangeRate",
                "day_change_rate",
                "compareToPreviousCloseRate",
                "compare_to_previous_close_rate",
                "fluctuationRate",
                "fluctuation_rate",
                "fluctuationsRatio",
                "priceChangeRate",
                "price_change_rate",
                "signedChangeRate",
                "signed_change_rate",
                "rate",
            )
        )
        day_change = _deep_number(
            price,
            "change",
            "changePrice",
            "change_price",
            "dayChange",
            "day_change",
            "compareToPreviousClosePrice",
            "compare_to_previous_close_price",
            "signedChangePrice",
            "signed_change_price",
            "fluctuation",
        )
        current_price = _deep_number(
            price,
            "price",
            "close",
            "closePrice",
            "close_price",
            "tradePrice",
            "trade_price",
            "currentPrice",
            "current_price",
            "lastPrice",
            "last_price",
        )
        if current_price is not None:
            row["current_price"] = _round_or_none(current_price, 4)
        row.update(
            {
                "name": name,
                "asset_type": asset_type,
                "category": asset_type,
                "sector": sector or _sector_fallback(asset_type),
                "industry": industry,
                "day_change": _round_or_none(day_change, 4),
                "day_change_pct": _round_or_none(day_change_pct, 6),
                "quote_available": bool(price),
                "warning_codes": [warning["code"] for warning in warning_rows if warning.get("code")],
                "warning_messages": [
                    warning["message"] for warning in warning_rows if warning.get("message")
                ],
                "warning_count": len(warning_rows),
            }
        )
        row["situation_tags"] = _toss_situation_tags(row)
        enriched.append(row)
    return enriched


def _toss_portfolio_summary(
    holdings: Sequence[Mapping[str, Any]],
    buying_power: Sequence[Mapping[str, Any]],
    *,
    failed_sections: Sequence[str],
) -> dict[str, Any]:
    total_market_value = sum(
        value
        for item in holdings
        for value in [_float_or_none(item.get("market_value_krw"))]
        if value is not None
    )
    total_cost_basis = sum(
        value
        for item in holdings
        for value in [_float_or_none(item.get("cost_basis_krw"))]
        if value is not None
    )
    unrealized_pnl = sum(
        value
        for item in holdings
        for value in [_float_or_none(item.get("unrealized_pnl_krw"))]
        if value is not None
    )
    cash_available = sum(
        value
        for item in buying_power
        for value in [_float_or_none(item.get("buying_power"))]
        if value is not None
    )
    pnl_pct = unrealized_pnl / total_cost_basis if total_cost_basis else None
    return {
        "status": "warning" if failed_sections else "success",
        "holding_count": len(holdings),
        "total_market_value": _round_or_none(total_market_value, 4),
        "total_cost_basis": _round_or_none(total_cost_basis, 4),
        "unrealized_pnl": _round_or_none(unrealized_pnl, 4),
        "unrealized_pnl_pct": _round_or_none(pnl_pct, 6),
        "cash_available": _round_or_none(cash_available, 4),
        "failed_sections": list(failed_sections),
        "failed_section_count": len(failed_sections),
        "valuation_currency": "KRW",
        "fx_missing_count": sum(item.get("fx_status") != "success" for item in holdings),
    }


def _toss_currency_totals(holdings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in holdings:
        currency = str(item.get("currency") or "UNKNOWN").upper()
        row = groups.setdefault(
            currency,
            {
                "currency": currency,
                "count": 0,
                "market_value": 0.0,
                "market_value_krw": 0.0,
                "unrealized_pnl_krw": 0.0,
            },
        )
        row["count"] += 1
        row["market_value"] += _float_or_none(item.get("market_value")) or 0.0
        row["market_value_krw"] += _float_or_none(item.get("market_value_krw")) or 0.0
        row["unrealized_pnl_krw"] += _float_or_none(item.get("unrealized_pnl_krw")) or 0.0
    return _totals_with_weight(groups.values(), group_key="currency")


def _toss_region_totals(holdings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in holdings:
        region = str(item.get("market_region") or "UNKNOWN").upper()
        row = groups.setdefault(
            region,
            {
                "region": region,
                "count": 0,
                "market_value_krw": 0.0,
                "unrealized_pnl_krw": 0.0,
            },
        )
        row["count"] += 1
        row["market_value_krw"] += _float_or_none(item.get("market_value_krw")) or 0.0
        row["unrealized_pnl_krw"] += _float_or_none(item.get("unrealized_pnl_krw")) or 0.0
    return _totals_with_weight(groups.values(), group_key="region")


def _toss_category_totals(holdings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _toss_group_totals(holdings, key="category", default="UNKNOWN")


def _toss_sector_totals(holdings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _toss_group_totals(holdings, key="sector", default="UNKNOWN")[:12]


def _toss_situation_totals(holdings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in holdings:
        for tag in _sequence(item.get("situation_tags")):
            key = str(tag)
            row = groups.setdefault(
                key,
                {
                    "tag": key,
                    "count": 0,
                    "market_value_krw": 0.0,
                    "unrealized_pnl_krw": 0.0,
                },
            )
            row["count"] += 1
            row["market_value_krw"] += _float_or_none(item.get("market_value_krw")) or 0.0
            row["unrealized_pnl_krw"] += _float_or_none(item.get("unrealized_pnl_krw")) or 0.0
    return _totals_with_weight(groups.values(), group_key="tag")[:16]


def _toss_group_totals(
    holdings: Sequence[Mapping[str, Any]],
    *,
    key: str,
    default: str,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in holdings:
        group = str(item.get(key) or default).upper()
        row = groups.setdefault(
            group,
            {
                key: group,
                "count": 0,
                "market_value_krw": 0.0,
                "unrealized_pnl_krw": 0.0,
            },
        )
        row["count"] += 1
        row["market_value_krw"] += _float_or_none(item.get("market_value_krw")) or 0.0
        row["unrealized_pnl_krw"] += _float_or_none(item.get("unrealized_pnl_krw")) or 0.0
    return _totals_with_weight(groups.values(), group_key=key)


def _toss_enrichment_summary(
    holdings: Sequence[Mapping[str, Any]],
    sections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    enrichment_sections = [
        name
        for name in sections
        if name.startswith("stocks_") or name.startswith("prices_") or name.startswith("warnings_")
    ]
    failed = [
        name
        for name in enrichment_sections
        if _mapping(sections.get(name)).get("status") == "failed"
    ]
    return {
        "status": "warning" if failed else "success" if enrichment_sections else "not_evaluated",
        "section_count": len(enrichment_sections),
        "failed_section_count": len(failed),
        "failed_sections": failed,
        "stocks_covered": sum(bool(item.get("asset_type")) for item in holdings),
        "prices_covered": sum(item.get("quote_available") is True for item in holdings),
        "day_change_covered": sum(item.get("day_change_pct") is not None for item in holdings),
        "warnings_checked": sum(str(name).startswith("warnings_") for name in enrichment_sections),
        "warning_limit": TOSS_WARNING_CHECK_LIMIT,
        "warning_hit_count": sum(int(item.get("warning_count", 0) or 0) > 0 for item in holdings),
    }


def _totals_with_weight(
    rows: Iterable[Mapping[str, Any]],
    *,
    group_key: str,
) -> list[dict[str, Any]]:
    normalized = [dict(row) for row in rows]
    total = sum(_float_or_none(row.get("market_value_krw")) or 0.0 for row in normalized)
    for row in normalized:
        value = _float_or_none(row.get("market_value_krw"))
        row["weight"] = _round_or_none(value / total if total and value is not None else None, 6)
        row["market_value"] = _round_or_none(_float_or_none(row.get("market_value")), 4)
        row["market_value_krw"] = _round_or_none(value, 4)
        row["unrealized_pnl_krw"] = _round_or_none(
            _float_or_none(row.get("unrealized_pnl_krw")),
            4,
        )
    return sorted(
        normalized,
        key=lambda item: (-(_float_or_none(item.get("market_value_krw")) or 0.0), str(item.get(group_key))),
    )


def _holding_symbols(holdings: Sequence[Mapping[str, Any]]) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for item in holdings:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen or symbol.startswith("HOLDING-"):
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def _section_symbol(symbol: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in symbol.upper())


def _toss_symbol_payload_map(
    sections: Mapping[str, Mapping[str, Any]],
    *,
    prefix: str,
    keys: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    mapped: dict[str, Mapping[str, Any]] = {}
    for name, section in sections.items():
        if not str(name).startswith(prefix) or _mapping(section).get("status") != "success":
            continue
        for row in _extract_toss_rows(_mapping(section).get("payload"), keys=keys):
            symbol = _symbol_from_toss_row(row)
            if symbol:
                mapped[symbol] = row
    return mapped


def _toss_warning_map(
    sections: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    mapped: dict[str, list[dict[str, Any]]] = {}
    for section in sections.values():
        item = _mapping(section)
        operation = str(item.get("operation_id") or "")
        if not operation.startswith("getStockWarnings:") or item.get("status") != "success":
            continue
        symbol = operation.split(":", 1)[1].strip().upper()
        mapped[symbol] = _normalize_toss_warnings(item.get("payload"))
    return mapped


def _normalize_toss_warnings(payload: Any) -> list[dict[str, Any]]:
    rows = _extract_toss_rows(
        payload,
        keys=("warnings", "stockWarnings", "stock_warnings", "items", "result", "data"),
    )
    warnings: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        code = _first_text(row, "code", "warningCode", "warning_code", "type", "category")
        message = _first_text(row, "message", "warning", "name", "title", "description")
        if code or message:
            warnings.append(
                {
                    "code": code or f"WARNING_{index + 1}",
                    "message": message or code,
                }
            )
    if not warnings and isinstance(payload, Mapping):
        code = _first_text(payload, "code", "warningCode", "warning_code", "type", "category")
        message = _first_text(payload, "message", "warning", "name", "title", "description")
        if code or message:
            warnings.append({"code": code or "WARNING", "message": message or code})
    return warnings


def _symbol_from_toss_row(row: Mapping[str, Any]) -> str | None:
    symbol = _deep_text(
        row,
        "symbol",
        "stockCode",
        "stock_code",
        "symbolCode",
        "symbol_code",
        "ticker",
        "securityCode",
        "security_code",
        "code",
    )
    return symbol.strip().upper() if symbol else None


def _classify_toss_asset_type(symbol: str, name: str, stock: Mapping[str, Any]) -> str:
    raw = (
        _deep_text(
            stock,
            "assetType",
            "asset_type",
            "securityType",
            "security_type",
            "type",
            "stockType",
            "stock_type",
        )
        or ""
    ).upper()
    text = f"{raw} {name}".upper()
    if "ETF" in text or any(token in text for token in ("KODEX", "TIGER", "ACE ", "RISE ", "SOL ")):
        if any(token in text for token in ("2X", "LEVERAGE", "레버리지")):
            return "LEVERAGED_ETF"
        if any(token in text for token in ("INVERSE", "인버스")):
            return "INVERSE_ETF"
        return "ETF"
    if "ADR" in text:
        return "ADR"
    if "PREFERRED" in text or "우선주" in text:
        return "PREFERRED"
    if symbol.endswith(".P") or symbol.endswith("P"):
        return "PREFERRED"
    return "STOCK"


def _sector_fallback(asset_type: str) -> str:
    if "ETF" in asset_type:
        return "ETF"
    return "UNKNOWN"


def _toss_situation_tags(row: Mapping[str, Any]) -> list[str]:
    tags: list[str] = []
    region = str(row.get("market_region") or "UNKNOWN")
    asset_type = str(row.get("asset_type") or "UNKNOWN")
    if region in {"KR", "US"}:
        tags.append(region)
    if asset_type != "STOCK":
        tags.append(asset_type)
    weight = _float_or_none(row.get("weight")) or 0.0
    if weight >= 0.2:
        tags.append("HIGH_CONCENTRATION")
    elif weight >= 0.05:
        tags.append("CORE_POSITION")
    pnl_pct = _float_or_none(row.get("unrealized_pnl_pct"))
    if pnl_pct is not None:
        if pnl_pct <= -0.1:
            tags.append("LOSS_10PCT")
        elif pnl_pct >= 0.1:
            tags.append("GAIN_10PCT")
    day_change_pct = _float_or_none(row.get("day_change_pct"))
    if day_change_pct is not None:
        if day_change_pct <= -0.03:
            tags.append("DOWN_3PCT_TODAY")
        elif day_change_pct >= 0.03:
            tags.append("UP_3PCT_TODAY")
    if row.get("quote_available") is True:
        tags.append("QUOTE_OK")
    if int(row.get("warning_count", 0) or 0) > 0:
        tags.append("TOSS_WARNING")
    if str(row.get("currency") or "").upper() == "USD":
        tags.append("FX_USD")
    return list(dict.fromkeys(tags))


def _empty_toss_portfolio_summary(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "holding_count": 0,
        "total_market_value": None,
        "total_cost_basis": None,
        "unrealized_pnl": None,
        "unrealized_pnl_pct": None,
        "cash_available": None,
        "failed_sections": [],
        "failed_section_count": 0,
    }


def _extract_toss_rows(payload: Any, *, keys: Sequence[str]) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            nested = _extract_toss_rows(value, keys=keys)
            if nested:
                return nested
    for key in ("result", "data", "payload"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            nested = _extract_toss_rows(value, keys=keys)
            if nested:
                return nested
    if any(key in payload for key in ("symbol", "stockCode", "quantity", "marketValue")):
        return [payload]
    return []


def _first_mapping(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        for key in ("result", "data", "payload"):
            value = payload.get(key)
            if isinstance(value, Mapping):
                return value
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, Mapping):
                        return item
        return payload
    return {}


def _deep_text(value: Any, *keys: str, depth: int = 0) -> str | None:
    if depth > 3:
        return None
    if isinstance(value, Mapping):
        direct = _first_text(value, *keys)
        if direct:
            return direct
        for child in value.values():
            found = _deep_text(child, *keys, depth=depth + 1)
            if found:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found = _deep_text(child, *keys, depth=depth + 1)
            if found:
                return found
    return None


def _deep_number(value: Any, *keys: str, depth: int = 0) -> float | None:
    if depth > 3:
        return None
    if isinstance(value, Mapping):
        direct = _first_number(value, *keys)
        if direct is not None:
            return direct
        for child in value.values():
            found = _deep_number(child, *keys, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found = _deep_number(child, *keys, depth=depth + 1)
            if found is not None:
                return found
    return None


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = _float_or_none(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _normalize_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1:
        return value / 100
    return value


def _infer_toss_currency(symbol: str, currency: str, exchange: str) -> str:
    explicit = currency.strip().upper()
    if explicit and explicit != "-":
        return explicit
    market = exchange.strip().upper()
    if any(token in market for token in ("NASDAQ", "NYSE", "AMEX", "US", "USA")):
        return "USD"
    if any(token in market for token in ("KRX", "KOSPI", "KOSDAQ", "KR", "KOREA")):
        return "KRW"
    code = symbol.strip().upper()
    if code.isdigit() and len(code) == 6:
        return "KRW"
    if code.isalpha() and 1 <= len(code) <= 5:
        return "USD"
    return "KRW"


def _infer_toss_market_region(symbol: str, currency: str, exchange: str) -> str:
    market = exchange.strip().upper()
    code = symbol.strip().upper()
    resolved_currency = _infer_toss_currency(code, currency, market)
    if any(token in market for token in ("NASDAQ", "NYSE", "AMEX", "US", "USA")):
        return "US"
    if any(token in market for token in ("KRX", "KOSPI", "KOSDAQ", "KR", "KOREA")):
        return "KR"
    if resolved_currency == "USD":
        return "US"
    if resolved_currency == "KRW" or (code.isdigit() and len(code) == 6):
        return "KR"
    return "UNKNOWN"


def _mask_account_text(value: str) -> str:
    digits = [char for char in value if char.isdigit()]
    if len(digits) < 5:
        return value
    visible = "".join(digits[-4:])
    return f"***-{visible}"


def _trader_signal_ladder(rows: Sequence[Any]) -> list[dict[str, Any]]:
    ladder: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        entry = _float_or_none(row.get("entry_price"))
        stop = _float_or_none(row.get("stop_price"))
        target = _float_or_none(row.get("target_price"))
        risk_unit = abs(entry - stop) if entry is not None and stop is not None else None
        reward_unit = target - entry if entry is not None and target is not None else None
        risk_pct = risk_unit / entry if entry and risk_unit is not None else None
        reward_pct = reward_unit / entry if entry and reward_unit is not None else None
        reward_to_risk = (
            reward_unit / risk_unit
            if reward_unit is not None and risk_unit is not None and risk_unit > 0
            else None
        )
        data_verified = row.get("data_verified")
        status = str(row.get("status") or "not_evaluated")
        review_priority = (
            "data_error"
            if data_verified is False
            else "blocked"
            if status == "blocked" or row.get("blocked") is True
            else "warning"
            if reward_to_risk is not None and reward_to_risk < 1.5
            else "success"
            if status in {"eligible", "success", "pass"}
            else status
        )
        ladder.append(
            {
                "ticker": row.get("ticker"),
                "action": row.get("action"),
                "strategy": row.get("strategy"),
                "status": status,
                "review_priority": review_priority,
                "score": row.get("score"),
                "entry_price": entry,
                "stop_price": stop,
                "target_price": target,
                "approved_position_pct": row.get("approved_position_pct"),
                "data_verified": data_verified,
                "liquidity_status": row.get("liquidity_status"),
                "reason_codes": row.get("reason_codes") or [],
                "risk_pct": _round_or_none(risk_pct, 6),
                "reward_pct": _round_or_none(reward_pct, 6),
                "reward_to_risk": _round_or_none(reward_to_risk, 3),
            }
        )
    return sorted(
        ladder,
        key=lambda item: (
            _decision_rank(str(item.get("review_priority") or "not_evaluated")),
            str(item.get("ticker") or ""),
        ),
    )


def _provider_trust_rows(data_quality: Mapping[str, Any]) -> list[dict[str, Any]]:
    summary = _mapping(data_quality.get("summary"))
    blocked_tickers = {str(item) for item in _sequence(summary.get("blocked_tickers"))}
    mismatch_counts: dict[str, int] = {}
    for item in _sequence(data_quality.get("mismatches")):
        if not isinstance(item, Mapping):
            continue
        ticker = item.get("ticker")
        if ticker is None:
            continue
        key = str(ticker)
        mismatch_counts[key] = mismatch_counts.get(key, 0) + 1
    rows: list[dict[str, Any]] = []
    for source in _sequence(data_quality.get("sources")):
        if not isinstance(source, Mapping):
            continue
        ticker = str(source.get("ticker") or source.get("symbol") or "")
        source_status = str(source.get("status") or "unknown")
        mismatch_count = mismatch_counts.get(ticker, 0)
        status = (
            "failed"
            if source_status != "success"
            else "data_error"
            if ticker in blocked_tickers or mismatch_count
            else "success"
        )
        rows.append(
            {
                "provider": source.get("provider"),
                "ticker": ticker or None,
                "status": status,
                "source_status": source_status,
                "rows": source.get("rows"),
                "first_date": source.get("first_date"),
                "last_date": source.get("last_date"),
                "hash": source.get("hash"),
                "hash_short": str(source.get("hash") or "")[:8] or None,
                "mismatch_count": mismatch_count,
                "blocked": ticker in blocked_tickers,
                "error": source.get("error"),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            _decision_rank(str(item.get("status") or "not_evaluated")),
            str(item.get("ticker") or ""),
            str(item.get("provider") or ""),
        ),
    )


def _risk_concentration_rows(risk: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for check in _sequence(risk.get("checks")):
        if not isinstance(check, Mapping) or check.get("status") != "blocked":
            continue
        code = str(check.get("code") or "RISK_BLOCKED")
        row = grouped.setdefault(
            code,
            {
                "code": code,
                "count": 0,
                "max_excess": None,
                "tickers": set(),
                "metrics": set(),
            },
        )
        row["count"] += 1
        ticker = check.get("ticker")
        if ticker:
            row["tickers"].add(str(ticker))
        metric = check.get("metric")
        if metric:
            row["metrics"].add(str(metric))
        excess = _float_or_none(check.get("excess"))
        current_max = row.get("max_excess")
        if excess is not None and (current_max is None or excess > current_max):
            row["max_excess"] = excess
    summary = _mapping(risk.get("summary"))
    for item in _sequence(summary.get("top_block_reasons")):
        if not isinstance(item, Mapping) or not item.get("code"):
            continue
        code = str(item["code"])
        row = grouped.setdefault(
            code,
            {
                "code": code,
                "count": 0,
                "max_excess": None,
                "tickers": set(),
                "metrics": set(),
            },
        )
        row["count"] = max(int(row.get("count", 0) or 0), int(item.get("count", 0) or 0))
    normalized = [
        {
            "code": code,
            "count": int(row.get("count", 0) or 0),
            "max_excess": _round_or_none(_float_or_none(row.get("max_excess")), 6),
            "tickers": sorted(row.get("tickers", set())),
            "metrics": sorted(row.get("metrics", set())),
        }
        for code, row in grouped.items()
    ]
    return sorted(normalized, key=lambda item: (-item["count"], item["code"]))


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _round_or_none(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _signal_publication(run_dir: Path, paths: RuntimePaths) -> dict[str, Any]:
    run_status = _mapping(read_json(run_dir / "signal_publication.json", default={}))
    if run_status:
        return {
            "status": run_status.get("status", "unknown"),
            "run_id": run_status.get("run_id"),
            "signal_date": run_status.get("signal_date"),
            "signal_hash": run_status.get("signal_hash"),
            "content_hash": run_status.get("content_hash"),
            "failure_code": run_status.get("failure_code"),
        }
    sidecar = _mapping(read_json(paths.signal_status_file, default={}))
    if sidecar.get("run_id") == run_dir.name:
        return {
            "status": sidecar.get("status", "unknown"),
            "run_id": sidecar.get("run_id"),
            "signal_date": sidecar.get("signal_date"),
            "signal_hash": sidecar.get("signal_hash"),
            "content_hash": sidecar.get("content_hash"),
            "failure_code": sidecar.get("failure_code"),
        }
    return {"status": "missing", "run_id": run_dir.name}


def _shadow_daily_history(shadow_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    invalid_files = 0
    for path in sorted(shadow_dir.glob("*.json")):
        try:
            shadow_date = date.fromisoformat(path.stem)
        except ValueError:
            invalid_files += 1
            continue
        payload = read_json(path, default={})
        signals = _mapping(payload)
        signal_rows = [item for item in signals.values() if isinstance(item, Mapping)]
        buy_rows = [item for item in signal_rows if item.get("action") == "buy"]
        completed = [item for item in buy_rows if item.get("shadow_status") == "completed"]
        verified = [
            item
            for item in signal_rows
            if _mapping(_mapping(_mapping(item.get("risk")).get("data_trust")).get("price")).get(
                "verified"
            )
            is True
        ]
        disagreements = [
            item
            for item in signal_rows
            if _mapping(_mapping(_mapping(item.get("risk")).get("data_trust")).get("price")).get(
                "provider_disagreements"
            )
        ]
        risk_passes = [item for item in buy_rows if item.get("eligible") is True]
        rows.append(
            {
                "date": shadow_date.isoformat(),
                "signal_count": len(signal_rows),
                "buy_count": len(buy_rows),
                "completed_count": len(completed),
                "data_verified_count": len(verified),
                "provider_disagreement_count": len(disagreements),
                "risk_pass_count": len(risk_passes),
            }
        )
    if invalid_files:
        rows.append(
            {
                "date": "invalid_files",
                "signal_count": invalid_files,
                "buy_count": 0,
                "completed_count": 0,
                "data_verified_count": 0,
                "provider_disagreement_count": 0,
                "risk_pass_count": 0,  # nosec B105
            }
        )
    return rows


def _settings_rules(
    settings: Settings,
    *,
    requested_mode: str,
    provider_audit: Mapping[str, Any],
    survivorship_audit: Mapping[str, Any],
    promotion_audit: Mapping[str, Any],
    load_error: str | None,
    mode_error: str | None,
) -> list[dict[str, Any]]:
    operational = requested_mode in {"signal", "shadow", "paper", "live"}
    research_mode = requested_mode in {"research", "backtest"}
    live_like = requested_mode in {"paper", "live"}
    price_sources = {settings.data_provider, *settings.data.cross_validation_providers}
    rules = [
        _settings_rule(
            "config.parse",
            "Config parse",
            load_error is None,
            "valid file",
            "parseable config",
            load_error or "config file parsed",
            severity="blocked",
        ),
        _settings_rule(
            "settings.mode_validation",
            "Mode validation",
            mode_error is None,
            requested_mode,
            f"{requested_mode} accepted",
            mode_error or "mode-specific model validation passed",
            severity="blocked",
        ),
        _settings_rule(
            "data.price_source_count",
            "At least two price providers",
            not operational or len(price_sources) >= 2,
            len(price_sources),
            ">= 2",
            "live/signal-like modes require two independent price sources",
            severity="blocked" if operational else "warning",
        ),
        _settings_rule(
            "data.cross_validation_mode",
            "Strict price cross-validation",
            not operational or settings.data.cross_validation_mode == "strict",
            settings.data.cross_validation_mode,
            "strict",
            "operational signals must fail closed when cross validation is absent",
            severity="blocked" if operational else "warning",
        ),
        _settings_rule(
            "data.price_disagreement_policy",
            "Provider disagreement policy",
            not operational or settings.data.price_disagreement_policy == "block",
            settings.data.price_disagreement_policy,
            "block",
            "severe provider disagreement must block eligible=true",
            severity="blocked" if operational else "warning",
        ),
        _settings_rule(
            "data.require_verified_price",
            "Verified price required",
            not operational or settings.data.require_verified_price_for_eligibility,
            settings.data.require_verified_price_for_eligibility,
            True,
            "eligible signals must use verified price data",
            severity="blocked" if operational else "warning",
        ),
        _settings_rule(
            "provider.audit",
            "Provider credentials and inventory",
            provider_audit.get("valid") is True,
            "valid" if provider_audit.get("valid") else provider_audit.get("errors", []),
            "valid",
            "required provider credentials must be configured via environment",
            severity="blocked" if operational else "warning",
        ),
        _settings_rule(
            "universe.survivorship",
            "Survivorship policy",
            not research_mode or survivorship_audit.get("valid") is True,
            {
                "policy": settings.universe.policy,
                "includes_delisted": settings.universe.includes_delisted,
                "as_of": settings.universe.as_of,
            },
            "strict point-in-time universe or explicit exception",
            "research/backtest results must avoid survivorship bias",
            severity="blocked"
            if research_mode and settings.universe.policy == "strict"
            else "warning",
        ),
        _settings_rule(
            "promotion.eligible",
            "Shadow promotion",
            not live_like or promotion_audit.get("eligible") is True,
            promotion_audit.get("eligible"),
            True,
            "paper/live requires a passing shadow promotion gate",
            severity="blocked" if live_like else "warning",
        ),
        _settings_rule(
            "risk.enforcement",
            "Risk enforcement",
            not live_like or settings.risk.enforcement == "block",
            settings.risk.enforcement,
            "block",
            "paper/live must not silently resize or warn through hard limits",
            severity="blocked" if live_like else "warning",
        ),
        _settings_rule(
            "risk.block_unmapped_tickers",
            "Block unmapped tickers",
            not live_like or settings.risk.block_unmapped_tickers,
            settings.risk.block_unmapped_tickers,
            True,
            "paper/live must block unmapped portfolio reference data",
            severity="blocked" if live_like else "warning",
        ),
    ]
    return rules


def _settings_rule(
    key: str,
    label: str,
    passed: bool,
    current: Any,
    required: Any,
    message: str,
    *,
    severity: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "pass" if passed else severity,
        "current": current,
        "required": required,
        "message": message,
        "severity": severity,
    }


def _execution_status(manifest: Mapping[str, Any]) -> str:
    status = str(manifest.get("status") or "unknown")
    if status == "running":
        return "validating"
    if status == "failed" and manifest.get("failure_code") in DATA_FAILURE_CODES:
        return "data_error"
    if status == "failed":
        return "failed"
    if status == "success":
        return "success"
    return "not_evaluated"


def _display_status(execution: str, safety: str, reasons: Sequence[Mapping[str, Any]]) -> str:
    if execution == "data_error" or any(item.get("component") == "data" for item in reasons):
        return "data_error"
    if safety == "blocked":
        return "blocked"
    if execution == "failed":
        return "failed"
    if execution == "validating":
        return "validating"
    if safety in {"review", "not_evaluated"}:
        return "warning" if execution == "success" else "not_evaluated"
    return "success"


def _overview_reasons(
    manifest: Mapping[str, Any],
    verdict: Mapping[str, Any],
    data_quality: Mapping[str, Any],
    risk: Mapping[str, Any],
    promotion: Mapping[str, Any],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    for item in _sequence(verdict.get("reasons")):
        if isinstance(item, Mapping):
            code = str(item.get("code") or "UNKNOWN")
            reasons.append(
                _reason(
                    code,
                    component=str(item.get("component") or "safety"),
                    message=str(item.get("message") or "") or None,
                )
            )
    failure_code = manifest.get("failure_code")
    if failure_code and not any(item["code"] == failure_code for item in reasons):
        component = (
            "data"
            if failure_code in DATA_FAILURE_CODES
            else "survivorship"
            if failure_code == FailureCode.SURVIVORSHIP_GATE_FAILED.value
            else "run"
        )
        reasons.append(_reason(str(failure_code), component=component))
    data_summary = _mapping(data_quality.get("summary"))
    if data_summary.get("disagreement_count"):
        data_reason = next(
            (item for item in reasons if item["code"] == FailureCode.DATA_DISAGREEMENT.value),
            None,
        )
        if data_reason is None:
            reasons.append(
                _reason(
                    FailureCode.DATA_DISAGREEMENT.value,
                    component="data",
                    affected_tickers=data_summary.get("blocked_tickers", []),
                )
            )
        elif not data_reason.get("affected_tickers"):
            data_reason["affected_tickers"] = data_summary.get("blocked_tickers", [])
    risk_summary = _mapping(risk.get("summary"))
    for item in _sequence(risk_summary.get("top_block_reasons")):
        if isinstance(item, Mapping) and item.get("code"):
            reasons.append(
                _reason(
                    str(item["code"]),
                    component="risk",
                    count=item.get("count"),
                )
            )
    if promotion and promotion.get("eligible") is False:
        reasons.append(_reason(FailureCode.SHADOW_PROMOTION_FAILED.value, component="promotion"))
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in reasons:
        unique[(item["component"], item["code"])] = item
    priority = {"data": 0, "run": 1, "risk": 2, "promotion": 3, "survivorship": 4}
    return sorted(unique.values(), key=lambda item: priority.get(item["component"], 9))


def _reason(
    code: str,
    *,
    component: str,
    message: str | None = None,
    affected_tickers: Any = None,
    count: Any = None,
) -> dict[str, Any]:
    catalog_message, remediation = FAILURE_CATALOG.get(
        code,
        ("실행 검증에서 확인이 필요한 문제가 발견됐습니다.", "관련 artifact를 확인하세요."),
    )
    return {
        "code": code,
        "component": component,
        "severity": "blocking",
        "message": message or catalog_message,
        "remediation": remediation,
        "affected_tickers": affected_tickers or [],
        "count": count,
    }


def _headline(status: str, reasons: Sequence[Mapping[str, Any]], mode: str) -> str:
    if reasons:
        first = reasons[0]
        return f"{first.get('message')} 현재 {mode} 실행은 운영 검토가 필요합니다."
    if status == "success":
        return "필수 검증을 통과했습니다. 알림 전 최종 리포트를 확인하세요."
    if status == "validating":
        return "실행 결과를 검증하고 있습니다."
    if status == "not_evaluated":
        return "운영 상태를 판단할 검증 결과가 충분하지 않습니다."
    return "실행 결과를 확인하세요."


def _survivorship_gate(manifest: Mapping[str, Any]) -> dict[str, Any]:
    audit = _mapping(manifest.get("survivorship_audit"))
    if not audit:
        return {"status": "not_evaluated"}
    valid = audit.get("valid") is True
    policy = audit.get("policy")
    return {
        "status": "pass" if valid else "blocked" if policy == "strict" else "warning",
        "policy": policy,
        "valid": valid,
        "universe_source": audit.get("universe_source"),
        "universe_as_of": audit.get("universe_as_of"),
        "includes_delisted": audit.get("includes_delisted"),
        "exception_reason": audit.get("exception_reason"),
        "warnings": audit.get("warnings", []),
    }


def _promotion_gate(promotion: Mapping[str, Any], mode: str) -> dict[str, Any]:
    if not promotion:
        return {
            "status": "not_evaluated",
            "eligible": False,
            "required": mode in {"paper", "live"},
        }
    eligible = promotion.get("eligible") is True
    return {
        "status": "pass" if eligible else "blocked" if mode in {"paper", "live"} else "warning",
        "eligible": eligible,
        "required": mode in {"paper", "live"},
        "shadow_day_count": len(_sequence(promotion.get("shadow_days"))),
        "criteria": promotion.get("criteria", []),
        "metrics": promotion.get("metrics", {}),
        "failure_code": promotion.get("failure_code"),
    }


def _signal_map(run_dir: Path) -> Mapping[str, Any]:
    for path in (
        run_dir / "signals_risk.json",
        run_dir / "signals.json",
    ):
        payload = read_json(path, default={})
        if isinstance(payload, Mapping) and payload:
            return payload
    return {}


def _signal_counts(signals: Mapping[str, Any]) -> dict[str, int]:
    rows = [item for item in signals.values() if isinstance(item, Mapping)]
    buy = [item for item in rows if item.get("action") == "buy"]
    return {
        "buy": len(buy),
        "eligible": sum(item.get("eligible") is True for item in buy),
        "blocked": sum(item.get("eligible") is not True for item in buy),
        "hold": sum(item.get("action") != "buy" for item in rows),
    }


def _signal_rows(signals: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for ticker, value in signals.items():
        if not isinstance(value, Mapping):
            continue
        risk = _mapping(value.get("risk"))
        price_trust = _mapping(_mapping(risk.get("data_trust")).get("price"))
        failed = [
            dict(item)
            for item in _sequence(risk.get("violation_details"))
            if isinstance(item, Mapping)
        ]
        passed = [
            dict(item) for item in _sequence(risk.get("pass_details")) if isinstance(item, Mapping)
        ]
        rows.append(
            {
                "ticker": str(ticker),
                "signal": value.get("signal"),
                "action": value.get("action"),
                "status": value.get("status")
                or (
                    "blocked"
                    if value.get("blocked")
                    else "eligible"
                    if value.get("eligible")
                    else "hold"
                ),
                "eligible": value.get("eligible") is True,
                "blocked": value.get("blocked") is True
                or (value.get("action") == "buy" and value.get("eligible") is not True),
                "score": value.get("confidence_score") or value.get("score"),
                "entry_price": value.get("entry_price") or value.get("price"),
                "stop_price": value.get("stop_price"),
                "target_price": value.get("target_price"),
                "suggested_position_pct": value.get("suggested_position_pct"),
                "approved_position_pct": value.get("approved_position_pct"),
                "strategy": value.get("strategy_mode") or value.get("regime"),
                "liquidity_status": value.get("liquidity_status")
                or _liquidity_status(failed, passed),
                "data_verified": price_trust.get("verified"),
                "provider_sources": price_trust.get("source"),
                "reason_codes": value.get("reason_codes") or risk.get("reason_codes", []),
                "failed": failed,
                "passed": passed,
                "warnings": risk.get("warnings", []),
                "risk_notes": value.get("risk_notes", []),
                "shadow_status": value.get("shadow_status"),
                "shadow_reason": value.get("shadow_reason"),
                "future_return_1d": value.get("future_return_1d"),
                "future_return_5d": value.get("future_return_5d"),
                "future_return_20d": value.get("future_return_20d"),
            }
        )
    return rows


def _liquidity_status(
    failed: Sequence[Mapping[str, Any]],
    passed: Sequence[Mapping[str, Any]],
) -> str:
    if any(item.get("code") == FailureCode.LIQUIDITY_INSUFFICIENT.value for item in failed):
        return "blocked"
    if any(item.get("metric") == "liquidity" for item in passed):
        return "pass"
    return "not_evaluated"


def _flatten_mismatches(disagreements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for report in disagreements:
        ticker = report.get("ticker")
        comparisons = _sequence(report.get("disagreements")) or [report]
        for comparison in comparisons:
            if not isinstance(comparison, Mapping):
                continue
            baseline = comparison.get("baseline")
            candidate = comparison.get("candidate")
            for item in _sequence(comparison.get("value_mismatches")):
                if isinstance(item, Mapping):
                    rows.append(
                        {
                            "ticker": ticker,
                            "kind": "value",
                            "date": item.get("date"),
                            "field": item.get("field"),
                            "baseline": baseline,
                            "candidate": candidate,
                            "values": item.get("values", {}),
                            "relative_delta": item.get("relative_delta"),
                            "threshold": item.get("threshold"),
                        }
                    )
            for item in _sequence(comparison.get("date_mismatches")):
                if isinstance(item, Mapping):
                    rows.append(
                        {
                            "ticker": ticker,
                            "kind": "date",
                            "date": item.get("date"),
                            "field": "Date",
                            "baseline": baseline,
                            "candidate": candidate,
                            "present_in": item.get("present_in", []),
                            "missing_in": item.get("missing_in", []),
                        }
                    )
    return rows


def _risk_rows_from_signals(signals: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for ticker, signal in signals.items():
        if not isinstance(signal, Mapping):
            continue
        risk = _mapping(signal.get("risk"))
        rows.append(
            {
                "ticker": str(ticker),
                "action": signal.get("action"),
                "reviewed": signal.get("action") == "buy",
                "eligible": signal.get("eligible") is True,
                "approved_position_pct": signal.get("approved_position_pct"),
                "passed": risk.get("pass_details", []),
                "failed": risk.get("violation_details", []),
                "warnings": risk.get("warnings", []),
            }
        )
    return rows


def _top_reason_counts(checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in checks:
        if item.get("status") != "blocked" or not item.get("code"):
            continue
        code = str(item["code"])
        counts[code] = counts.get(code, 0) + 1
    return [
        {"code": code, "count": count}
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _recommended_actions(
    reasons: Sequence[Mapping[str, Any]],
    status: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reason in reasons:
        component = str(reason.get("component"))
        page = {
            "data": "data-quality",
            "risk": "risk",
            "promotion": None,
            "survivorship": None,
            "run": "overview",
        }.get(component, "overview")
        label = {
            "data": "데이터 검증 확인",
            "risk": "리스크 상세 확인",
            "promotion": "Promotion 검증 명령",
            "survivorship": "설정 검증 명령",
            "run": "실행 로그 확인",
        }.get(component, "리포트 확인")
        command = {
            "promotion": "uv run jayu promotion check",
            "survivorship": "uv run jayu validate-config --mode research",
        }.get(component)
        action_key = page or command
        if not action_key or action_key in seen:
            continue
        seen.add(action_key)
        actions.append(
            {
                "id": f"review-{component}",
                "label": label,
                "page": page,
                "command": command,
                "priority": len(actions) + 1,
            }
        )
    if not actions and status == "success":
        actions.append(
            {
                "id": "review-report",
                "label": "전체 리포트 확인",
                "page": "overview",
                "priority": 1,
            }
        )
    return actions[:3]


def _decision_blocker(reason: Mapping[str, Any]) -> dict[str, Any]:
    action = _action_for_component(str(reason.get("component")))
    return {
        "code": reason.get("code"),
        "component": reason.get("component"),
        "message": reason.get("message"),
        "remediation": reason.get("remediation"),
        "affected_tickers": reason.get("affected_tickers", []),
        "count": reason.get("count"),
        "action": action,
    }


def _action_for_component(component: str) -> dict[str, Any]:
    page = {
        "data": "data-quality",
        "risk": "risk",
        "promotion": None,
        "survivorship": None,
        "run": "overview",
    }.get(component, "overview")
    label = {
        "data": "데이터 품질 화면으로 이동",
        "risk": "리스크 상세로 이동",
        "promotion": "승격 조건 점검 명령 복사",
        "survivorship": "설정 검증 명령 복사",
        "run": "실행 로그 확인",
    }.get(component, "리포트 확인")
    command = {
        "promotion": "uv run jayu promotion check",
        "survivorship": "uv run jayu validate-config --mode research",
    }.get(component)
    return {
        "label": label,
        "page": page,
        "command": command,
    }


def _default_action(status: str) -> dict[str, Any]:
    if status == "success":
        return {
            "id": "review-report",
            "label": "전체 리포트 확인",
            "page": "overview",
            "priority": 1,
        }
    if status == "not_evaluated":
        return {
            "id": "validate-config",
            "label": "설정 검증 명령",
            "page": "settings",
            "priority": 1,
        }
    return {
        "id": "review-overview",
        "label": "차단 원인 확인",
        "page": "overview",
        "priority": 1,
    }


def _decision_rank(status: str) -> int:
    return {
        "data_error": 0,
        "failed": 1,
        "blocked": 2,
        "warning": 3,
        "validating": 4,
        "not_evaluated": 5,
        "success": 6,
    }.get(status, 5)


def _health_status(score: Any, threshold: Any) -> str:
    if not isinstance(score, (int, float)):
        return "not_evaluated"
    if isinstance(threshold, (int, float)) and score < threshold:
        return "warning"
    return "healthy"


def _promotion_threshold(run_dir: Path, paths: RuntimePaths) -> Any:
    config = _mapping(read_json(run_dir / "config.json", default={}))
    promotion = _mapping(config.get("promotion"))
    if promotion.get("min_health_score") is not None:
        return promotion["min_health_score"]
    state_promotion = _mapping(read_json(paths.state_dir / "promotion.json", default={}))
    for item in _sequence(state_promotion.get("criteria")):
        if isinstance(item, Mapping) and item.get("name") == "health_score":
            return item.get("required")
    return 80


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


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return []
