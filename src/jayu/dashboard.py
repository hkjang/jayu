"""Read-only dashboard API and static asset server."""

from __future__ import annotations

import json
import mimetypes
import webbrowser
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import ValidationError

from .failure_codes import FailureCode
from .io import read_json, stable_hash
from .paths import RuntimePaths
from .provider_factory import build_provider_registry, provider_configuration_audit
from .safety import evaluate_shadow_promotion
from .settings import Settings, load_settings
from .strategy_space import load_strategy_spaces, validate_strategy_spaces
from .survivorship import audit_survivorship

SCHEMA_VERSION = "1.0"
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
                if parsed.path == "/api/v1/promotion":
                    self._json(build_dashboard_promotion(paths))
                    return
                if parsed.path == "/api/v1/settings/validation":
                    mode = parse_qs(parsed.query).get("mode", [None])[0]
                    self._json(build_dashboard_settings_validation(paths, mode=mode))
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
    if data_summary.get("disagreement_count") and not any(
        item["code"] == FailureCode.DATA_DISAGREEMENT.value for item in reasons
    ):
        reasons.append(
            _reason(
                FailureCode.DATA_DISAGREEMENT.value,
                component="data",
                affected_tickers=data_summary.get("blocked_tickers", []),
            )
        )
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
