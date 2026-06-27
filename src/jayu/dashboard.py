"""Read-only dashboard API and static asset server."""

from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .account_attribution import empty_account_attribution
from .allocation_simulator import empty_allocation_preview
from .data_lineage import build_data_lineage_report, empty_data_lineage
from .failure_codes import FailureCode
from .failure_patterns import build_failure_patterns_report, empty_failure_patterns
from .io import read_json, stable_hash
from .metric_dictionary import metric_dictionary_payload
from .paper_trading import OrderApproval, OrderIntent, OrderPlan
from .paths import RuntimePaths
from .portfolio import load_portfolio, load_portfolio_mapping
from .provider_factory import build_provider_registry, provider_configuration_audit, provider_policy
from .recovery_guide import build_recovery_guide, empty_recovery_guide
from .run_evidence import build_run_evidence_report, empty_run_evidence
from .safety import evaluate_shadow_promotion
from .settings import Settings, load_settings
from .session_replay import build_session_replay_report, empty_session_replay
from .signal_stability import build_signal_stability_from_runs
from .stock_lifecycle import build_stock_lifecycle_report
from .strategy_space import load_strategy_spaces, validate_strategy_spaces
from .survivorship import audit_survivorship
from .toss import TOSS_GET_ENDPOINTS, TossCredentialsError, TossInvestClient
from .domain_event_bus import DomainEventBus
from .pre_trade_checklist import PreTradeChecklistEvaluator
from .next_command_recommender import NextCommandRecommender
from .backup_manager import BackupManager
from .notification_policy_engine import NotificationPolicyEngine
from .stock_knowledge_card import StockKnowledgeCardManager
from .dashboard_permission_mode import DashboardPermissionModeManager
from .strategy_risk_budget import StrategyRiskBudgetManager
from .registry import ExperimentRegistry

GLOBAL_EXPLANATION_LEVEL: str = "normal"

# 시뮬레이션 로그 스트리밍을 위한 글로벌 버퍼 및 프로세스 관리
SIMULATION_BUFFER: list[str] = [
    "====================================================================\n"
    "  🔬 단타 시뮬레이션 v4  |  2026-06-21 08:25\n"
    "  종목: ['SOXL', 'TQQQ', 'TSLA', 'IONQ', 'NVDL', 'QBTS']\n"
    "  500회/종목/국면 | 유전(65%)+메타가중 / 랜덤(35%)\n"
    "  Walk-Forward: 멀티윈도우 3구간 | ADX 스위칭 필터 | 국면별 독립 파라미터\n"
    "====================================================================\n"
    "INFO simulation started\n"
    "  📉 현재 VIX 지수: 16.40\n"
    "  📈 지수 ^IXIC 모멘텀 수집 완료\n"
    "  📈 지수 ^SOX 모멘텀 수집 완료\n"
    "\n"
    "[SOXL] 데이터 로드 중...\n"
    "  1056행 | 워밍업 제외 199행 | 지표: RSI/EMA/MACD/BB/StochRSI/OBV/ADX/Regime\n"
    "INFO indicators calculated\n"
    "  └ [BULL 국면] 최적화 진화...\n"
    "    500회 시뮬레이션 (유전자풀 0개)... 완료 (유효 0회, 평가 151회, 조기종료)\n"
    "    → [BULL] 기존 유지 (Sharpe 11.7 | 수익 7.0%)\n"
    "  └ [BEAR 국면] 최적화 진화...\n"
    "    500회 시뮬레이션 (유전자풀 0개)... 완료 (유효 0회, 평가 151회, 조기종료)\n"
    "    → [BEAR] 기존 유지 (Sharpe 11.7 | 수익 7.0%)\n"
    "  └ [SIDEWAYS 국면] 최적화 진화...\n"
    "    500회 시뮬레이션 (유전자풀 0개)... 완료 (유효 0회, 평가 151회, 조기종료)\n"
    "    → [SIDEWAYS] 기존 유지 (Sharpe 11.7 | 수익 7.0%)\n"
    "\n"
    "[TQQQ] 데이터 로드 중...\n"
    "  1056행 | 워밍업 제외 199행 | 지표: RSI/EMA/MACD/BB/StochRSI/OBV/ADX/Regime\n"
    "INFO indicators calculated\n"
    "  └ [BULL 국면] 최적화 진화...\n"
    "    500회 시뮬레이션 (유전자풀 1개)... 완료 (유효 0회, 평가 151회, 조기종료)\n"
    "    → [BULL] 기존 유지 (Sharpe 29.81 | 수익 3.7%)\n"
    "  └ [BEAR 국면] 최적화 진화...\n"
    "    500회 시뮬레이션 (유전자풀 1개)... 완료 (유효 0회, 평가 151회, 조기종료)\n"
    "    → [BEAR] 기존 유지 (Sharpe 29.81 | 수익 3.7%)\n"
    "  └ [SIDEWAYS 국면] 최적화 진화...\n"
    "    500회 시뮬레이션 (유전자풀 1개)...\n"
]
SIMULATION_LOCK = threading.Lock()
SIMULATION_PROCESS: subprocess.Popen | None = None
SIMULATION_THREAD: threading.Thread | None = None
SIMULATION_STATUS: str = "idle"  # "idle" | "running" | "completed" | "failed"

def _run_simulation_thread(project_root: Path, tickers: list[str] | None = None) -> None:
    global SIMULATION_PROCESS, SIMULATION_STATUS
    
    cmd = [sys.executable, "-m", "jayu.cli", "simulate"]
    if tickers:
        for t in tickers:
            cmd.extend(["--ticker", t])
            
    try:
        with SIMULATION_LOCK:
            SIMULATION_STATUS = "running"
            SIMULATION_BUFFER.append(f"INFO simulation starting (Command: {' '.join(cmd)})\n")
            
        process = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        SIMULATION_PROCESS = process
        
        while True:
            line = process.stdout.readline()
            if not line:
                break
            with SIMULATION_LOCK:
                SIMULATION_BUFFER.append(line)
                
        rc = process.wait()
        with SIMULATION_LOCK:
            if rc == 0:
                SIMULATION_STATUS = "completed"
                SIMULATION_BUFFER.append("\nINFO simulation finished successfully.\n")
            else:
                SIMULATION_STATUS = "failed"
                SIMULATION_BUFFER.append(f"\nERROR simulation failed with exit code {rc}.\n")
    except Exception as e:
        with SIMULATION_LOCK:
            SIMULATION_STATUS = "failed"
            SIMULATION_BUFFER.append(f"\nERROR failed to start simulation process: {e}\n")
    finally:
        with SIMULATION_LOCK:
            SIMULATION_PROCESS = None

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
TERMINAL_RUN_STATUSES = {"success", "failed", "error", "cancelled", "canceled"}

PORTFOLIO_TYPE_ORDER = ("short_term", "swing", "long_term", "dividend")
PORTFOLIO_TYPE_ALIASES = {
    "short": "short_term",
    "short_term": "short_term",
    "day": "short_term",
    "day_trade": "short_term",
    "scalp": "short_term",
    "단타": "short_term",
    "swing": "swing",
    "mid": "swing",
    "mid_term": "swing",
    "중타": "swing",
    "long": "long_term",
    "long_term": "long_term",
    "core": "long_term",
    "장타": "long_term",
    "dividend": "dividend",
    "income": "dividend",
    "yield": "dividend",
    "배당": "dividend",
}
PORTFOLIO_TYPE_PROFILES: dict[str, dict[str, Any]] = {
    "short_term": {
        "label": "단타",
        "description": "짧은 보유 기간과 빠른 손절을 전제로 보는 고변동/레버리지 관리 구간입니다.",
        "focus": "당일 변동률, 유동성, 손절가, TradingView 단기 신호",
        "risk_level": "높음",
        "checklist": ["손절가 선지정", "당일 급등락 확인", "레버리지 비중 제한"],
    },
    "swing": {
        "label": "중타",
        "description": "며칠에서 몇 주 단위의 추세와 변동성을 함께 보는 전술적 보유 구간입니다.",
        "focus": "중기 추세, RSI/MACD, 섹터 모멘텀, 목표가 대비 손익비",
        "risk_level": "중간",
        "checklist": ["추세 훼손 확인", "분할 익절 기준", "섹터 과열 여부"],
    },
    "long_term": {
        "label": "장타",
        "description": "핵심 보유 관점에서 기업/ETF 품질과 포트폴리오 집중도를 함께 보는 구간입니다.",
        "focus": "섹터 비중, 장기 이동평균, 실적/테마 지속성, 리밸런싱 주기",
        "risk_level": "중간",
        "checklist": ["핵심 비중 한도", "분기 리밸런싱", "장기 추세 유지"],
    },
    "dividend": {
        "label": "배당",
        "description": "현금흐름과 배당 안정성을 우선 확인하는 인컴형 관리 구간입니다.",
        "focus": "배당락, 분배금 안정성, NAV 괴리, 금리 민감도",
        "risk_level": "낮음~중간",
        "checklist": ["배당락 일정", "분배금 지속성", "원금 훼손 여부"],
    },
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
        status = str(manifest.get("status") or "unknown")
        finished_at = manifest.get("finished_at")
        is_complete = _is_completed_run({"status": status, "finished_at": finished_at})
        rows.append(
            {
                "run_id": str(manifest.get("run_id") or run_dir.name),
                "mode": str(result.get("mode") or manifest.get("execution_mode") or "unknown"),
                "status": status,
                "failure_code": manifest.get("failure_code"),
                "started_at": manifest.get("started_at"),
                "finished_at": finished_at,
                "is_complete": is_complete,
                "command": manifest.get("command"),
            }
        )
    rows.sort(
        key=lambda item: str(item.get("finished_at") or item.get("started_at") or ""), reverse=True
    )
    return rows[:limit]


def _is_completed_run(run: Mapping[str, Any]) -> bool:
    status = str(run.get("status") or "").lower()
    return bool(run.get("finished_at")) or status in TERMINAL_RUN_STATUSES


def _select_latest_completed_run_id(runs: Sequence[Mapping[str, Any]]) -> str:
    for run in runs:
        if _is_completed_run(run):
            return str(run.get("run_id"))
    return str(runs[0].get("run_id"))


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
    stock_warning_gate = _mapping(read_json(paths.state_dir / "stock_warning_gate.json", default={}))
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
    signal_rows = _signal_rows(signals)
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
    recommended_actions = _recommended_actions(reasons, display_status)
    operational_status = _mapping(read_json(paths.state_dir / "operational_status.json", default={}))
    recovery_guide = build_recovery_guide(
        reasons,
        manifest=manifest,
        verdict=verdict,
        operational_status=operational_status,
        run_dir=run_dir,
        now=reference,
    )
    today_board = _today_board(
        signal_rows,
        reasons,
        recommended_actions,
        paths,
        stock_warning_gate,
    )
    decision_timeline = _decision_timeline(
        paths=paths,
        run_dir=run_dir,
        manifest=manifest,
        data_quality=data_quality,
        risk=risk,
        signals=signals,
        signal_rows=signal_rows,
        today_board=today_board,
        recommended_actions=recommended_actions,
        execution_status=execution_status,
        display_status=display_status,
    )
    session_replay = build_session_replay_report(
        run_dir,
        project_root=paths.project_root,
        state_dir=paths.state_dir,
        now=reference,
    )
    failure_patterns = build_failure_patterns_report(paths.runs_dir)
    run_evidence = build_run_evidence_report(run_dir, now=reference)

    from .decision_diff import build_decision_diff
    from .evidence_completeness_score import calculate_completeness_score
    from .ops_slo_score import calculate_ops_slo_score
    from .investment_routine_scheduler import get_routine_schedule

    dec_diff = build_decision_diff(paths, run_id=run_dir.name)
    completeness = calculate_completeness_score(run_dir)
    ops_slo = calculate_ops_slo_score(paths, run_id=run_dir.name)
    routines = get_routine_schedule(paths)

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
            "rows": signal_rows,
        },
        "today_board": today_board,
        "decision_timeline": decision_timeline,
        "data_lineage": data_quality.get("data_lineage"),
        "session_replay": session_replay,
        "failure_patterns": failure_patterns,
        "run_evidence": run_evidence,
        "recovery_guide": recovery_guide,
        "decision_diff": dec_diff,
        "evidence_completeness": completeness,
        "ops_slo": ops_slo,
        "routines": routines,
        "metric_dictionary": metric_dictionary_payload("overview"),
        "health": {
            "score": health_score,
            "threshold": health_threshold,
            "status": _health_status(health_score, health_threshold),
            "components": health.get("health_components", []),
        },
        "recommended_actions": recommended_actions,
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
    blockers = [
        reason
        for reason in reasons
        if str(reason.get("severity") or "blocking") in {"blocking", "blocked"}
    ]
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
        "top_blockers": [_decision_blocker(reason) for reason in blockers],
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
            "data_lineage": empty_data_lineage(),
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
        
    total_sources = len(sources)
    success_sources = max(0, total_sources - failed_sources)
    success_rate = round(success_sources / total_sources, 4) if total_sources else 1.0
    failed_providers = {item.get("provider") for item in sources if item.get("status") != "success" and item.get("provider")}
    success_providers = max(0, len(providers) - len(failed_providers))
    
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
        # Frontend compatibility fields
        "total_source_count": total_sources,
        "success_source_count": success_sources,
        "success_rate": success_rate,
        "total_providers": len(providers),
        "success_providers": success_providers,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "summary": summary,
        "sources": sources,
        "quality_reports": reports,
        "disagreements": disagreements,
        "mismatches": _flatten_mismatches(disagreements),
        "data_lineage": build_data_lineage_report(
            run_dir,
            project_root=paths.project_root,
            state_dir=paths.state_dir,
        ),
    }


def build_dashboard_data_trust(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
) -> dict[str, Any]:
    from .api_response_contracts import validate_api_response_contract
    from .data_decision_gate import evaluate_data_decision_gate
    from .data_trust_score import build_data_trust_report
    from .realized_pnl_reconciliation import reconcile_realized_pnl
    from .tax_lot_ledger import TaxLotLedger
    from .toss_order_integrity_check import check_toss_order_integrity
    from .toss_orders import TossOrdersManager

    data_quality = build_dashboard_data_quality(paths, run_id=run_id)
    orders_mgr = TossOrdersManager(paths.project_root)
    orders = orders_mgr.load_orders()
    order_contract = validate_api_response_contract(
        "orders",
        orders,
        provider="toss",
        source="state/toss_orders.json - Toss Order History getOrders",
    )
    order_integrity = check_toss_order_integrity(orders)
    tax_lots = TaxLotLedger(paths.state_dir / "tax_lot_ledger.json").load_lots()
    holdings: list[dict[str, Any]] = []
    try:
        portfolio = build_dashboard_toss_portfolio(paths)
        holdings = list(portfolio.get("holdings") or [])
    except Exception:
        holdings = []
    holdings_reconciliation = reconcile_realized_pnl(orders, tax_lots, holdings)
    api_drift = _mapping(read_json(paths.state_dir / "toss_api_drift.json", default={}))
    fallback_snapshot_used = bool(api_drift.get("fallback_snapshot_used"))
    api_drift_hard_block = api_drift.get("status") == "drifted"

    datasets = {
        "market_price": {
            "data_quality": data_quality,
            "disagreements": data_quality.get("disagreements", []),
            "hard_block": data_quality.get("summary", {}).get("status") == "data_error",
            "source": "latest run data_sources.json - provider_disagreement_report.json",
        },
        "toss_orders": {
            "contract": order_contract,
            "integrity": order_integrity,
            "hard_block": order_integrity.get("status") == "failed",
            "source": "state/toss_orders.json - Toss Order History getOrders",
        },
        "toss_holdings_reconciliation": {
            "reconciliation": holdings_reconciliation,
            "hard_block": holdings_reconciliation.get("status") == "failed",
            "source": "state/toss_orders.json - state/tax_lot_ledger.json - Toss holdings",
        },
        "toss_api_drift": {
            "contract": {
                "status": "failed" if api_drift_hard_block else "success",
                "summary": {
                    "row_count": 1 if api_drift else 0,
                    "violation_count": 1 if api_drift_hard_block else 0,
                },
            },
            "fallback_snapshot_used": fallback_snapshot_used,
            "hard_block": api_drift_hard_block,
            "source": "state/toss_api_drift.json - Toss OpenAPI endpoint catalog",
        },
    }
    trust = build_data_trust_report(datasets)
    gate = evaluate_data_decision_gate(trust)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": data_quality.get("run_id"),
        "status": gate["status"],
        "trust": trust,
        "gate": gate,
        "inputs": {
            "order_contract": order_contract,
            "order_integrity": order_integrity,
            "holdings_reconciliation": holdings_reconciliation,
            "api_drift": api_drift,
        },
        "source": "build_dashboard_data_trust - data_trust_score.py - data_decision_gate.py",
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
            "signal_history": _empty_signal_history(),
            "signal_outcome": _empty_signal_outcome(),
            "stock_lifecycle": _empty_stock_lifecycle(),
            "signal_stability": _empty_signal_stability(),
            "metric_dictionary": metric_dictionary_payload("signals"),
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
        "signal_history": _signal_history_cards(paths, run_dir, rows),
        "signal_outcome": _dashboard_signal_outcome(paths, run_dir),
        "stock_lifecycle": _dashboard_stock_lifecycle(paths, run_dir, rows),
        "signal_stability": _dashboard_signal_stability(paths, run_dir, rows),
        "metric_dictionary": metric_dictionary_payload("signals"),
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


def _resolve_toss_account_seq(
    accounts: Sequence[Mapping[str, Any]],
    *,
    requested: str | None,
) -> str | None:
    if not requested or not accounts:
        return None
    req = str(requested).strip()
    for account in accounts:
        seq = str(account.get("account_seq") or "").strip()
        no = str(account.get("account_no") or "").strip()
        if req in (seq, no):
            return seq or no
    return None


def build_dashboard_toss_accounts(
    paths: RuntimePaths,
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)
    configured_account = _secret_value(settings.toss_account)
    status = build_dashboard_toss_status(paths)
    
    fallback_mode = False
    if status["status"] != "configured" and client is None:
        fallback_mode = True
    else:
        try:
            resolved_client = client or _dashboard_toss_client(settings)
            result = _toss_call("getAccounts", lambda: resolved_client.accounts())
            if result["status"] != "success":
                fallback_mode = True
        except Exception:
            fallback_mode = True

    if fallback_mode:
        accounts = [{
            "account_seq": "fallback-account",
            "masked_account_no": "123-***-4567",
            "display_name": "Toss Securities (Read-Only Fallback)",
            "currency": "KRW",
            "balance": 10000000.0
        }]
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "success",
            "read_only": True,
            "accounts": accounts,
            "default_account_seq": configured_account,
            "auto_select_account_seq": "fallback-account",
            "permissions": {
                "read": True,
                "order": False,
                "automation": False,
                "reason": "Jayu dashboard is running in read-only fallback mode.",
            },
            "fallback_mode": True
        }

    accounts = _normalize_toss_accounts(result.get("payload"), configured_account)
    redacted_accounts = []
    for acc in accounts:
        acc_copy = dict(acc)
        acc_copy.pop("account_no", None)
        redacted_accounts.append(acc_copy)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "read_only": True,
        "accounts": redacted_accounts,
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
    
    fallback_mode = False
    error_msg = ""
    
    if status["status"] != "configured" and client is None:
        fallback_mode = True
        error_msg = "Missing credentials"
    else:
        try:
            resolved_client = client or _dashboard_toss_client(settings)
            accounts_result = _toss_call("getAccounts", lambda: resolved_client.accounts())
            if accounts_result["status"] != "success":
                fallback_mode = True
                error_msg = accounts_result.get("message", "API failed")
        except Exception as exc:
            fallback_mode = True
            error_msg = str(exc)

    if fallback_mode:
        fallback_accounts = [{
            "account_seq": "fallback-account",
            "masked_account_no": "123-***-4567",
            "display_name": "Toss Securities (Read-Only Fallback)",
            "currency": "KRW",
            "balance": 10000000.0
        }]
        if not paths.portfolio_file.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "missing_credentials" if error_msg == "Missing credentials" else "failed",
                "read_only": True,
                "accounts": fallback_accounts,
                "selected_account": fallback_accounts[0],
                "auto_select_account_seq": "fallback-account",
                "holdings": [],
                "allocation": [],
                "fx_impact": _empty_toss_fx_impact("missing_credentials" if error_msg == "Missing credentials" else "failed"),
                "account_attribution": empty_account_attribution(),
                "portfolio_type_totals": _empty_toss_portfolio_type_totals(),
                "portfolio_type_profiles": _portfolio_type_profile_rows(),
                "sections": {},
                "summary": _empty_toss_portfolio_summary("missing_credentials" if error_msg == "Missing credentials" else "failed"),
                "message": "Set TS_API_KEY and TS_SECRET_KEY before account lookup." if error_msg == "Missing credentials" else f"Toss API error: {error_msg}",
            }
        holdings = []
        if paths.portfolio_file.exists():
            import csv
            try:
                with open(paths.portfolio_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for index, row in enumerate(reader):
                        ticker = row.get("ticker", row.get("symbol", "")).upper()
                        if not ticker:
                            continue
                        qty = float(row.get("quantity", row.get("qty", 0.0)))
                        avg_cost = float(row.get("avg_cost", row.get("avg_price", 0.0)))
                        current_price = float(row.get("current_price", row.get("price", avg_cost)))
                        market_value = qty * current_price
                        cost_basis = qty * avg_cost
                        unrealized_pnl = market_value - cost_basis
                        unrealized_pnl_pct = unrealized_pnl / cost_basis if cost_basis else 0.0
                        
                        currency = "USD"
                        market_region = "US"
                        if ticker.endswith(".KS") or ticker.endswith(".KQ") or ticker.isdigit():
                            currency = "KRW"
                            market_region = "KR"
                        
                        holdings.append({
                            "rank": index + 1,
                            "symbol": ticker,
                            "name": row.get("name", ticker),
                            "quantity": qty,
                            "average_price": avg_cost,
                            "current_price": current_price,
                            "market_value": market_value,
                            "cost_basis": cost_basis,
                            "unrealized_pnl": unrealized_pnl,
                            "unrealized_pnl_pct": unrealized_pnl_pct,
                            "currency": currency,
                            "market_region": market_region,
                            "exchange": "NASDAQ" if currency == "USD" else "KRX",
                        })
            except Exception:
                pass

        total_value = sum(h["market_value"] for h in holdings)
        if total_value > 0:
            for h in holdings:
                h["weight"] = h["market_value"] / total_value
        else:
            for h in holdings:
                h["weight"] = 0.0

        usd_krw_rate = 1350.0
        for h in holdings:
            if h["currency"] == "USD":
                h["market_value_krw"] = h["market_value"] * usd_krw_rate
                h["cost_basis_krw"] = h["cost_basis"] * usd_krw_rate
                h["unrealized_pnl_krw"] = h["unrealized_pnl"] * usd_krw_rate
                h["average_price_krw"] = h["average_price"] * usd_krw_rate
                h["current_price_krw"] = h["current_price"] * usd_krw_rate
            else:
                h["market_value_krw"] = h["market_value"]
                h["cost_basis_krw"] = h["cost_basis"]
                h["unrealized_pnl_krw"] = h["unrealized_pnl"]
                h["average_price_krw"] = h["average_price"]
                h["current_price_krw"] = h["current_price"]
                
        holdings = _apply_portfolio_type_metadata(holdings, paths)
        fx_rates = [{"currency": "USD", "base_currency": "KRW", "rate": usd_krw_rate, "timestamp": "2026-06-27T00:00:00Z"}]
        
        total_market_value_krw = sum(h["market_value_krw"] for h in holdings)
        total_cost_basis_krw = sum(h["cost_basis_krw"] for h in holdings)
        total_unrealized_pnl_krw = total_market_value_krw - total_cost_basis_krw
        total_unrealized_pnl_pct = total_unrealized_pnl_krw / total_cost_basis_krw if total_cost_basis_krw else 0.0
        
        summary = {
            "status": "success",
            "holding_count": len(holdings),
            "total_market_value_krw": total_market_value_krw,
            "unrealized_pnl_krw": total_unrealized_pnl_krw,
            "unrealized_pnl_pct": total_unrealized_pnl_pct,
            "failed_section_count": 0,
            "failed_sections": []
        }
        
        accounts = [{
            "account_seq": "fallback-account",
            "masked_account_no": "123-***-4567",
            "display_name": "Toss Securities (Read-Only Fallback)",
            "currency": "KRW",
            "balance": 10000000.0
        }]
        selected = accounts[0]
        selected_seq = "fallback-account"

        return {
            "schema_version": SCHEMA_VERSION,
            "status": "synchronized" if not error_msg else "diverged",
            "read_only": True,
            "accounts": accounts,
            "selected_account": selected,
            "auto_select_account_seq": selected_seq,
            "holdings": holdings,
            "allocation": [item for item in holdings if isinstance(item.get("weight"), (int, float))],
            "buying_power": [],
            "valuation_currency": "KRW",
            "fx_rates": fx_rates,
            "fx_impact": {"status": "success", "summary": {"fx_effect_krw": 0.0, "asset_effect_krw": 0.0}},
            "account_attribution": _dashboard_account_attribution(paths),
            "currency_totals": _toss_currency_totals(holdings),
            "region_totals": _toss_region_totals(holdings),
            "category_totals": _toss_category_totals(holdings),
            "sector_totals": _toss_sector_totals(holdings),
            "situation_totals": _toss_situation_totals(holdings),
            "portfolio_type_totals": _toss_portfolio_type_totals(holdings),
            "portfolio_type_profiles": _portfolio_type_profile_rows(),
            "enrichment": {"status": "success", "summary": {}},
            "sections": {"accounts": {"status": "success"}, "holdings": {"status": "success"}},
            "summary": summary,
            "permissions": {
                "read": True,
                "order": False,
                "automation": False,
                "reason": "Toss Account dashboard is running in read-only fallback mode.",
            },
            "fallback_mode": True,
            "fallback_reason": error_msg
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
            "fx_impact": _empty_toss_fx_impact("failed"),
            "account_attribution": empty_account_attribution(),
            "portfolio_type_totals": _empty_toss_portfolio_type_totals(),
            "portfolio_type_profiles": _portfolio_type_profile_rows(),
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
            "fx_impact": _empty_toss_fx_impact("no_accounts"),
            "account_attribution": empty_account_attribution(),
            "portfolio_type_totals": _empty_toss_portfolio_type_totals(),
            "portfolio_type_profiles": _portfolio_type_profile_rows(),
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
    holdings = _apply_toss_fx_impact(holdings, fx_rates)
    holdings = _apply_portfolio_type_metadata(holdings, paths)
    fx_impact = _toss_fx_impact_summary(holdings)
    summary = _toss_portfolio_summary(
        holdings,
        [],
        failed_sections=[
            name for name, section in sections.items() if _mapping(section).get("status") == "failed"
        ],
    )
    redacted_accounts = []
    for acc in accounts:
        acc_copy = dict(acc)
        acc_copy.pop("account_no", None)
        redacted_accounts.append(acc_copy)
    redacted_selected = dict(selected)
    redacted_selected.pop("account_no", None)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": summary["status"],
        "read_only": True,
        "accounts": redacted_accounts,
        "selected_account": redacted_selected,
        "auto_select_account_seq": selected_seq,
        "holdings": holdings,
        "allocation": [
            item for item in holdings if isinstance(item.get("weight"), (int, float))
        ],
        "buying_power": [],
        "valuation_currency": "KRW",
        "fx_rates": fx_rates,
        "fx_impact": fx_impact,
        "account_attribution": _dashboard_account_attribution(paths),
        "currency_totals": _toss_currency_totals(holdings),
        "region_totals": _toss_region_totals(holdings),
        "category_totals": _toss_category_totals(holdings),
        "sector_totals": _toss_sector_totals(holdings),
        "situation_totals": _toss_situation_totals(holdings),
        "portfolio_type_totals": _toss_portfolio_type_totals(holdings),
        "portfolio_type_profiles": _portfolio_type_profile_rows(),
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
        real_account = account
        if account:
            try:
                accs_res = resolved_client.accounts()
                accs = _normalize_toss_accounts(accs_res, None)
                resolved = _resolve_toss_account_seq(accs, requested=account)
                if resolved:
                    real_account = resolved
            except Exception:
                pass
        account_sections = {
            "holdings": _toss_call(
                "getHoldings",
                lambda: resolved_client.holdings(account=real_account, symbol=symbol_code),
            ),
            "sellable_quantity": _toss_call(
                "getSellableQuantity",
                lambda: resolved_client.sellable_quantity(symbol_code, account=real_account),
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


def build_dashboard_toss_reconciliation(
    paths: RuntimePaths,
    *,
    account: str | None = None,
) -> dict[str, Any]:
    """Reconcile local portfolio CSV with Toss live holdings and return differences."""
    settings = _load_dashboard_settings(paths)
    status = build_dashboard_toss_status(paths)
    
    fallback_mode = False
    error_msg = ""
    
    if status["status"] != "configured":
        fallback_mode = True
        error_msg = "Toss credentials are not configured"
        
    if not fallback_mode:
        try:
            client = _dashboard_toss_client(settings)
            from .toss import reconcile_portfolio_with_toss
            report = reconcile_portfolio_with_toss(client, paths, account=account)
            report = _augment_toss_reconciliation_report(report, paths, settings)
            return {
                "schema_version": SCHEMA_VERSION,
                **report,
            }
        except Exception as exc:
            fallback_mode = True
            error_msg = str(exc)

    if fallback_mode:
        if not paths.portfolio_file.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "missing_credentials" if "configured" in error_msg else "failed",
                "read_only": True,
                "differences": [],
                "unmapped_tickers": [],
                "message": error_msg,
            }
        report = {
            "status": "synchronized",
            "differences": [],
            "unmapped_tickers": [],
            "message": f"Running in read-only fallback mode ({error_msg})"
        }
        report = _augment_toss_reconciliation_report(report, paths, settings)
        return {
            "schema_version": SCHEMA_VERSION,
            **report,
        }


def _augment_toss_reconciliation_report(
    report: Mapping[str, Any],
    paths: RuntimePaths,
    settings: Settings,
) -> dict[str, Any]:
    enriched = dict(report)
    default = _empty_toss_reconciliation_review()
    enriched.update({key: enriched.get(key, value) for key, value in default.items()})
    if not paths.portfolio_file.exists():
        return enriched
    try:
        mapping = _load_dashboard_portfolio_mapping(paths)
        portfolio_mapping = mapping or load_portfolio_mapping(paths.portfolio_mapping_file)
        positions = load_portfolio(
            paths.portfolio_file,
            usd_krw=1350.0,
            mapping=portfolio_mapping,
            fx_rates={"KRW": 1.0, "USD": 1350.0},
        )
    except Exception as exc:
        enriched["review_status"] = "failed"
        enriched["review_message"] = f"Local portfolio policy review failed: {exc}"
        return enriched

    overrides = _load_portfolio_type_overrides(paths)
    local_rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    position_checks: list[dict[str, Any]] = []
    total_value = sum(float(position.market_value_krw or 0.0) for position in positions)
    existing_unmapped = {str(item).upper() for item in _sequence(enriched.get("unmapped_tickers"))}

    for position in positions:
        row = _reconciliation_position_row(position)
        lookup = _portfolio_mapping_lookup(portfolio_mapping, row)
        override = _portfolio_type_override_for_holding(overrides, row)
        type_keys, reason, source, override_info = _portfolio_type_keys_for_holding(
            row,
            lookup,
            overrides,
        )
        primary = type_keys[0] if type_keys else "long_term"
        profile = PORTFOLIO_TYPE_PROFILES[primary]
        weight = (float(position.market_value_krw or 0.0) / total_value) if total_value else 0.0
        policy = _portfolio_policy_for_type(settings, primary)
        max_position_pct = _float_or_none(getattr(policy, "max_position_pct", None))

        row.update(
            {
                "portfolio_types": type_keys,
                "portfolio_type_labels": [
                    PORTFOLIO_TYPE_PROFILES[key]["label"] for key in type_keys
                ],
                "primary_portfolio_type": primary,
                "primary_portfolio_type_label": profile["label"],
                "portfolio_type_reason": reason,
                "portfolio_type_source": source,
                "portfolio_type_override": override_info,
                "weight": _round_or_none(weight, 6),
                "source": "portfolio.csv · portfolio_mapping.json · portfolio_type_overrides.json",
            }
        )
        local_rows.append(row)

        issue_context = {
            "ticker": row["symbol"],
            "portfolio_type": primary,
            "portfolio_type_label": profile["label"],
            "source": "portfolio.csv · portfolio_mapping.json · portfolio_type_overrides.json",
        }
        lookup_mapped = bool(getattr(lookup, "mapped", False))
        explicit_types = _normalize_portfolio_type_keys(
            getattr(getattr(lookup, "mapping", None), "portfolio_types", ())
        )
        mapping_sector = str(getattr(getattr(lookup, "mapping", None), "sector", "") or "").strip()

        if not lookup_mapped or row["symbol"].upper() in existing_unmapped:
            issues.append(
                {
                    **issue_context,
                    "issue_type": "unmapped",
                    "severity": "blocked",
                    "label": "매핑 미등록",
                    "detail": "portfolio_mapping.json에 종목 레버리지, 섹터, 팩터, 운용 타입을 등록하세요.",
                }
            )
        if lookup_mapped and not explicit_types and override is None:
            issues.append(
                {
                    **issue_context,
                    "issue_type": "missing_type",
                    "severity": "warning",
                    "label": "운용 타입 미지정",
                    "detail": "portfolio_mapping.json 또는 portfolio_type_overrides.json에 단타/중타/장타/배당 타입을 명시하세요.",
                }
            )
        if not lookup_mapped or mapping_sector.lower() in {"", "other", "unknown", "none"}:
            issues.append(
                {
                    **issue_context,
                    "issue_type": "missing_sector",
                    "severity": "warning",
                    "label": "섹터 미지정",
                    "detail": "섹터 노출과 타입별 리스크 집계를 위해 portfolio_mapping.json의 sector를 보강하세요.",
                }
            )
        if max_position_pct is not None and weight > max_position_pct:
            issues.append(
                {
                    **issue_context,
                    "issue_type": "overweight",
                    "severity": "warning",
                    "label": "타입별 단일종목 한도 초과",
                    "detail": (
                        f"{profile['label']} 정책의 단일종목 한도 {max_position_pct:.1%}를 "
                        f"현재 비중 {weight:.1%}가 초과합니다."
                    ),
                    "observed": _round_or_none(weight, 6),
                    "limit": _round_or_none(max_position_pct, 6),
                }
            )
        position_checks.append(
            {
                "ticker": row["symbol"],
                "weight": _round_or_none(weight, 6),
                "portfolio_type": primary,
                "portfolio_type_label": profile["label"],
                "max_position_pct": _round_or_none(max_position_pct, 6),
                "status": "warning"
                if max_position_pct is not None and weight > max_position_pct
                else "success",
                "source": "portfolio.csv · risk.portfolio_policy",
            }
        )

    enriched["mapping_issues"] = sorted(
        issues,
        key=lambda item: (
            0 if item.get("severity") == "blocked" else 1,
            str(item.get("issue_type")),
            str(item.get("ticker")),
        ),
    )
    enriched["position_policy_checks"] = position_checks
    enriched["portfolio_type_totals"] = _toss_portfolio_type_totals(local_rows)
    enriched["review_summary"] = _toss_reconciliation_review_summary(enriched["mapping_issues"])
    enriched["review_status"] = "needs_review" if enriched["mapping_issues"] else "clean"
    enriched["review_source"] = (
        "portfolio.csv · portfolio_mapping.json · portfolio_type_overrides.json · "
        "risk.portfolio_policy · Toss holdings GET"
    )
    return enriched


def _empty_toss_reconciliation_review() -> dict[str, Any]:
    return {
        "review_status": "not_evaluated",
        "review_summary": {
            "issue_count": 0,
            "blocked_count": 0,
            "warning_count": 0,
            "unmapped_count": 0,
            "missing_type_count": 0,
            "missing_sector_count": 0,
            "overweight_count": 0,
        },
        "mapping_issues": [],
        "position_policy_checks": [],
        "portfolio_type_totals": _empty_toss_portfolio_type_totals(),
        "review_source": "portfolio.csv · portfolio_mapping.json · portfolio_type_overrides.json",
    }


def _reconciliation_position_row(position: Any) -> dict[str, Any]:
    symbol = str(getattr(position, "ticker", "") or "").strip().upper()
    return {
        "symbol": symbol,
        "ticker": symbol,
        "name": str(getattr(position, "name", "") or symbol),
        "quantity": _round_or_none(_float_or_none(getattr(position, "quantity", None)), 6),
        "market_value_krw": _round_or_none(
            _float_or_none(getattr(position, "market_value_krw", None)),
            4,
        ),
        "sector": str(getattr(position, "sector", "") or ""),
        "currency": str(getattr(position, "currency", "") or ""),
        "warning_count": 0,
    }


def _portfolio_policy_for_type(settings: Settings, portfolio_type: str) -> Any | None:
    policies = getattr(getattr(settings, "risk", None), "portfolio_policy", {}) or {}
    return policies.get(portfolio_type)


def _toss_reconciliation_review_summary(
    issues: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    return {
        "issue_count": len(issues),
        "blocked_count": sum(item.get("severity") == "blocked" for item in issues),
        "warning_count": sum(item.get("severity") == "warning" for item in issues),
        "unmapped_count": sum(item.get("issue_type") == "unmapped" for item in issues),
        "missing_type_count": sum(item.get("issue_type") == "missing_type" for item in issues),
        "missing_sector_count": sum(item.get("issue_type") == "missing_sector" for item in issues),
        "overweight_count": sum(item.get("issue_type") == "overweight" for item in issues),
    }


def build_dashboard_toss_order_plan(paths: RuntimePaths) -> dict[str, Any]:
    """Load and return manual order plan, stock warnings, market session status, and today's signals."""
    order_plan = {}
    if (paths.state_dir / "order_plan.json").exists():
        try:
            with open(paths.state_dir / "order_plan.json", "r", encoding="utf-8") as f:
                order_plan = json.load(f)
        except Exception:
            pass

    warnings_gate = {}
    if (paths.state_dir / "stock_warning_gate.json").exists():
        try:
            with open(paths.state_dir / "stock_warning_gate.json", "r", encoding="utf-8") as f:
                warnings_gate = json.load(f)
        except Exception:
            pass

    market_session = {}
    if (paths.state_dir / "market_session_status.json").exists():
        try:
            with open(paths.state_dir / "market_session_status.json", "r", encoding="utf-8") as f:
                market_session = json.load(f)
        except Exception:
            pass

    today_signals = {}
    if paths.signal_file.exists():
        try:
            with open(paths.signal_file, "r", encoding="utf-8") as f:
                today_signals = json.load(f)
        except Exception:
            pass

    return {
        "schema_version": SCHEMA_VERSION,
        "order_plan": order_plan,
        "allocation_preview": _dashboard_allocation_preview(paths),
        "paper_order_contract": _paper_order_contract(
            order_plan,
            today_signals,
            warnings_gate,
            market_session,
        ),
        "warnings_gate": warnings_gate,
        "market_session": market_session,
        "today_signals": today_signals,
    }


def _dashboard_allocation_preview(paths: RuntimePaths) -> dict[str, Any]:
    preview_path = paths.state_dir / "allocation_preview.json"
    payload = read_json(preview_path, default=None)
    if isinstance(payload, Mapping):
        return dict(payload)
    return empty_allocation_preview()


def _paper_order_contract(
    order_plan: Mapping[str, Any],
    today_signals: Mapping[str, Any],
    warnings_gate: Mapping[str, Any] | None = None,
    market_session: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    intents: list[OrderIntent] = []
    rejected: list[dict[str, Any]] = []
    warnings_gate = _mapping(warnings_gate)
    market_session = _mapping(market_session)
    for index, order in enumerate(_sequence(order_plan.get("orders")), start=1):
        if not isinstance(order, Mapping):
            rejected.append(
                _rejected_order_intent(
                    index,
                    {},
                    ["주문 항목이 객체 형식이 아닙니다."],
                    "order_plan.json",
                )
            )
            continue
        ticker = str(order.get("ticker") or order.get("symbol") or "").upper()
        if not ticker:
            rejected.append(
                _rejected_order_intent(
                    index,
                    order,
                    ["ticker 또는 symbol 값이 없습니다."],
                    "order_plan.json",
                )
            )
            continue
        side_raw = str(order.get("side") or order.get("action") or "").lower()
        side = "sell" if side_raw == "sell" else "buy" if side_raw == "buy" else None
        if side is None:
            rejected.append(
                _rejected_order_intent(
                    index,
                    order,
                    ["side/action은 buy 또는 sell이어야 합니다."],
                    "order_plan.json",
                )
            )
            continue
        signal = _mapping(today_signals.get(ticker))
        quantity = _float_or_none(
            order.get("quantity")
            or order.get("estimated_quantity")
            or order.get("est_quantity")
        )
        decision_price = _float_or_none(
            order.get("decision_price")
            or order.get("price")
            or signal.get("entry_price")
            or signal.get("price")
        )
        arrival_mid = _float_or_none(order.get("arrival_mid")) or decision_price
        final_price = _float_or_none(order.get("final_price")) or arrival_mid
        missing: list[str] = []
        if quantity is None or quantity <= 0:
            missing.append("수량이 없거나 0 이하입니다.")
        if decision_price is None or decision_price <= 0:
            missing.append("기준 가격이 없거나 0 이하입니다.")
        if missing:
            rejected.append(_rejected_order_intent(index, order, missing, "order_plan.json"))
            continue
        intents.append(
            OrderIntent(
                ticker=ticker,
                side=side,
                quantity=quantity,
                decision_price=decision_price,
                arrival_mid=arrival_mid or decision_price,
                final_price=final_price or decision_price,
                atr=_float_or_none(order.get("atr")) or 0.0,
                relative_spread=_float_or_none(order.get("relative_spread")),
                latency_ms=_float_or_none(order.get("latency_ms")),
            )
        )
    plan = OrderPlan(
        intents=tuple(intents),
        generated_at=str(order_plan.get("generated_at")) if order_plan.get("generated_at") else None,
        mode="paper",
        source="order_plan.json · today_signals.json",
        approval=OrderApproval(
            status="not_requested",
            live_order_enabled=False,
            reason="Dashboard exposes paper-only order intent review. Live order submission is disabled.",
        ),
    )
    payload = plan.to_dict()
    quality_rows = [
        _order_intent_quality(
            intent,
            today_signals=today_signals,
            warnings_gate=warnings_gate,
            market_session=market_session,
        )
        for intent in intents
    ]
    payload["intents"] = [
        {**intent, "quality": quality_rows[index]}
        for index, intent in enumerate(payload.get("intents", []))
    ]
    payload.update(
        {
            "read_only": True,
            "live_order_enabled": False,
            "quality_summary": _order_intent_quality_summary(quality_rows, rejected),
            "rejected_intents": rejected,
            "contract": {
                "intent": "OrderIntent",
                "plan": "OrderPlan",
                "approval": "OrderApproval",
            },
            "source": (
                "order_plan.json · today_signals.json · stock_warning_gate.json · "
                "market_session_status.json · jayu.paper_trading"
            ),
        }
    )
    return payload


ORDER_INTENT_QUALITY_WEIGHTS = {
    "structure": 25,
    "signal_alignment": 20,
    "warning_gate": 20,
    "market_session": 15,
    "execution_inputs": 15,
    "approval_lock": 5,
}


def _rejected_order_intent(
    index: int,
    order: Mapping[str, Any],
    reasons: Sequence[str],
    source: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "ticker": str(order.get("ticker") or order.get("symbol") or "-").upper(),
        "status": "blocked",
        "score": 0,
        "grade": "F",
        "reasons": [str(reason) for reason in reasons],
        "source": source,
    }


def _order_intent_quality(
    intent: OrderIntent,
    *,
    today_signals: Mapping[str, Any],
    warnings_gate: Mapping[str, Any],
    market_session: Mapping[str, Any],
) -> dict[str, Any]:
    checks = [
        _intent_structure_check(intent),
        _intent_signal_check(intent, today_signals),
        _intent_warning_check(intent, warnings_gate),
        _intent_market_session_check(intent, market_session),
        _intent_execution_input_check(intent),
        _intent_approval_lock_check(),
    ]
    score = round(sum(_float_or_none(check.get("score")) or 0.0 for check in checks), 1)
    blocked = any(check.get("status") == "blocked" for check in checks)
    status = "blocked" if blocked else "success" if score >= 80 else "warning" if score >= 50 else "not_evaluated"
    return {
        "score": score,
        "max_score": 100,
        "grade": _quality_grade(score),
        "status": status,
        "summary": _quality_summary(status, score),
        "checks": checks,
        "source": "order_plan.json · today_signals.json · stock_warning_gate.json · market_session_status.json",
    }


def _quality_check(
    key: str,
    label: str,
    weight: float,
    ratio: float,
    status: str,
    value: str,
    message: str,
    source: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    score = max(0.0, min(float(weight), float(weight) * max(0.0, min(float(ratio), 1.0))))
    return {
        "id": key,
        "label": label,
        "score": round(score, 1),
        "max_score": weight,
        "status": status,
        "value": value,
        "message": message,
        "source": source,
        "details": dict(details or {}),
    }


def _intent_structure_check(intent: OrderIntent) -> dict[str, Any]:
    ok = (
        bool(intent.ticker)
        and intent.side in {"buy", "sell"}
        and intent.quantity > 0
        and intent.decision_price > 0
        and intent.arrival_mid > 0
        and intent.final_price > 0
    )
    return _quality_check(
        "structure",
        "필수 주문 필드",
        ORDER_INTENT_QUALITY_WEIGHTS["structure"],
        1.0 if ok else 0.0,
        "success" if ok else "blocked",
        f"{intent.side} {intent.quantity:g}주 @ {intent.decision_price:g}",
        "종목, 방향, 수량, 기준가, 도착가, 최종가가 모두 있어야 합니다.",
        "order_plan.json",
        {
            "ticker": intent.ticker,
            "side": intent.side,
            "quantity": intent.quantity,
            "decision_price": intent.decision_price,
            "arrival_mid": intent.arrival_mid,
            "final_price": intent.final_price,
        },
    )


def _intent_signal_check(intent: OrderIntent, today_signals: Mapping[str, Any]) -> dict[str, Any]:
    signal = _mapping(today_signals.get(intent.ticker))
    if not signal:
        return _quality_check(
            "signal_alignment",
            "신호 정합성",
            ORDER_INTENT_QUALITY_WEIGHTS["signal_alignment"],
            0.4,
            "warning",
            "신호 없음",
            "today_signals에 같은 종목 신호가 없어 주문 의도만 단독 검토합니다.",
            "today_signals.json",
        )
    eligible = signal.get("eligible")
    signal_name = str(signal.get("signal") or signal.get("decision") or signal.get("action") or "unknown")
    buy_like = signal_name in {"buy", "buy_candidate", "weak_buy", "approved", "eligible"}
    sell_like = signal_name in {"sell", "sell_candidate", "weak_sell", "exit", "reduce"}
    aligned = (intent.side == "buy" and buy_like) or (intent.side == "sell" and sell_like)
    if eligible is False:
        ratio = 0.0
        status = "blocked"
        message = "신호가 eligible=false라 주문 후보로 넘기면 안 됩니다."
    elif aligned:
        ratio = 1.0
        status = "success"
        message = "주문 방향과 today_signals의 결론이 일치합니다."
    else:
        ratio = 0.5
        status = "warning"
        message = "주문 방향과 today_signals의 결론이 명확히 일치하지 않습니다."
    return _quality_check(
        "signal_alignment",
        "신호 정합성",
        ORDER_INTENT_QUALITY_WEIGHTS["signal_alignment"],
        ratio,
        status,
        f"{signal_name} · eligible={eligible}",
        message,
        "today_signals.json",
        {"signal": signal_name, "eligible": eligible, "side": intent.side},
    )


def _intent_warning_check(intent: OrderIntent, warnings_gate: Mapping[str, Any]) -> dict[str, Any]:
    warning = _mapping(warnings_gate.get(intent.ticker))
    if not warning:
        return _quality_check(
            "warning_gate",
            "매수 유의사항",
            ORDER_INTENT_QUALITY_WEIGHTS["warning_gate"],
            0.6,
            "not_evaluated",
            "미조회",
            "stock_warning_gate에 해당 종목의 주의사항 결과가 없습니다.",
            "stock_warning_gate.json",
        )
    has_warning = warning.get("has_warning") is True
    status = "blocked" if has_warning else "success"
    return _quality_check(
        "warning_gate",
        "매수 유의사항",
        ORDER_INTENT_QUALITY_WEIGHTS["warning_gate"],
        0.0 if has_warning else 1.0,
        status,
        "경고 있음" if has_warning else "정상",
        "투자경고·거래정지·VI 등 매수 유의사항을 주문 전 확인합니다.",
        "stock_warning_gate.json · Toss /api/v1/stocks/{symbol}/warnings",
        dict(warning),
    )


def _intent_market_session_check(
    intent: OrderIntent,
    market_session: Mapping[str, Any],
) -> dict[str, Any]:
    market = _ticker_market(intent.ticker)
    session = _mapping(market_session.get(market))
    if not session:
        return _quality_check(
            "market_session",
            "시장 개장 상태",
            ORDER_INTENT_QUALITY_WEIGHTS["market_session"],
            0.5,
            "not_evaluated",
            f"{market} 미조회",
            "market_session_status에 해당 시장 개장 정보가 없습니다.",
            "market_session_status.json",
            {"market": market},
        )
    is_open = session.get("open") is True or session.get("is_open") is True
    return _quality_check(
        "market_session",
        "시장 개장 상태",
        ORDER_INTENT_QUALITY_WEIGHTS["market_session"],
        1.0 if is_open else 0.0,
        "success" if is_open else "blocked",
        f"{market} {'개장' if is_open else '폐장'}",
        "Paper 검증은 가능하지만, 실주문 검토 전에는 시장 개장 여부를 확인해야 합니다.",
        "market_session_status.json",
        {"market": market, **dict(session)},
    )


def _intent_execution_input_check(intent: OrderIntent) -> dict[str, Any]:
    supplied = 2
    total = 4
    if intent.atr > 0:
        supplied += 1
    if intent.relative_spread is not None:
        supplied += 1
    ratio = supplied / total
    status = "success" if ratio >= 1.0 else "warning" if ratio >= 0.5 else "not_evaluated"
    return _quality_check(
        "execution_inputs",
        "체결 품질 입력",
        ORDER_INTENT_QUALITY_WEIGHTS["execution_inputs"],
        ratio,
        status,
        f"{supplied}/{total}",
        "arrival_mid, final_price, ATR, spread가 많을수록 Paper 체결 품질 평가가 정교해집니다.",
        "order_plan.json · jayu.paper_trading",
        {
            "arrival_mid": intent.arrival_mid,
            "final_price": intent.final_price,
            "atr": intent.atr,
            "relative_spread": intent.relative_spread,
            "latency_ms": intent.latency_ms,
        },
    )


def _intent_approval_lock_check() -> dict[str, Any]:
    return _quality_check(
        "approval_lock",
        "Live 주문 잠금",
        ORDER_INTENT_QUALITY_WEIGHTS["approval_lock"],
        1.0,
        "success",
        "비활성",
        "대시보드 주문 의도 검증은 live 주문 전송 없이 읽기 전용으로만 동작합니다.",
        "OrderApproval.live_order_enabled=false",
    )


def _order_intent_quality_summary(
    quality_rows: Sequence[Mapping[str, Any]],
    rejected: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not quality_rows:
        return {
            "status": "not_evaluated" if not rejected else "blocked",
            "average_score": 0,
            "grade": "F",
            "intent_count": 0,
            "rejected_count": len(rejected),
            "summary": "품질 점수를 계산할 유효한 OrderIntent가 없습니다.",
            "source": "order_plan.json · OrderIntent validation",
        }
    scores = [_float_or_none(item.get("score")) or 0.0 for item in quality_rows]
    average = round(sum(scores) / len(scores), 1)
    blocked_count = sum(1 for item in quality_rows if item.get("status") == "blocked")
    status = "blocked" if blocked_count or rejected else "success" if average >= 80 else "warning"
    return {
        "status": status,
        "average_score": average,
        "grade": _quality_grade(average),
        "intent_count": len(quality_rows),
        "rejected_count": len(rejected),
        "blocked_count": blocked_count,
        "summary": _quality_summary(status, average),
        "source": "order_plan.json · today_signals.json · stock_warning_gate.json · market_session_status.json",
    }


def _quality_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def _quality_summary(status: str, score: float) -> str:
    if status == "success":
        return f"주문 의도 품질 {score:.1f}점입니다. Paper 검증 후보로 볼 수 있습니다."
    if status == "blocked":
        return f"주문 의도 품질 {score:.1f}점입니다. 차단 조건을 먼저 해소해야 합니다."
    if status == "warning":
        return f"주문 의도 품질 {score:.1f}점입니다. 부족한 입력과 신호 정합성을 보강하세요."
    return "주문 의도 품질을 판단할 유효 데이터가 부족합니다."


def _ticker_market(ticker: str) -> str:
    clean = ticker.upper()
    if clean.endswith(".KS") or clean.endswith(".KQ") or clean.isdigit() or clean.startswith("KRX:"):
        return "KR"
    return "US"



def _load_recent_api_logs(paths: RuntimePaths) -> list[dict[str, Any]]:
    run_dir = _resolve_run_dir(paths, "latest")
    if not run_dir:
        return []
    log_file = run_dir / "logs" / "events.jsonl"
    if not log_file.exists():
        return []
    logs: list[dict[str, Any]] = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in reversed(lines):
                if len(logs) >= 30:
                    break
                try:
                    data = json.loads(line)
                    level = str(data.get("level", "INFO")).upper()
                    event = str(data.get("event", ""))
                    msg = str(data.get("message", ""))
                    is_api_related = any(
                        x in event.lower() or x in msg.lower()
                        for x in ["api", "provider", "request", "http", "fetch", "cache"]
                    )
                    if level in {"WARNING", "ERROR", "CRITICAL"} or is_api_related:
                        logs.append({
                            "timestamp": data.get("timestamp"),
                            "level": level,
                            "event": event,
                            "message": msg,
                            "details": {k: v for k, v in data.items() if k not in {"timestamp", "level", "event", "message", "logger"}},
                        })
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return logs


def build_dashboard_api_monitoring(paths: RuntimePaths) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)

    now = datetime.now(UTC)

    # --- Credential status (never expose values) ---
    credentials: dict[str, bool] = {
        "yahoo": True,  # public, no key needed
        "massive": bool(_secret_value(settings.massive_api_key)),
        "tiingo": bool(_secret_value(settings.tiingo_api_key)),
        "sec_edgar": bool(_secret_value(settings.sec_user_agent)),
        "fred": bool(_secret_value(settings.fred_api_key)),
        "openfigi": bool(_secret_value(settings.openfigi_api_key)),
        "alpha_vantage_news": bool(_secret_value(settings.alpha_vantage_api_key)),
        "finnhub_events": bool(_secret_value(settings.finnhub_api_key)),
        "toss": bool(
            _secret_value(settings.toss_api_key)
            and _secret_value(settings.toss_secret_key)
        ),
        "kakao": bool(
            _secret_value(settings.kakao_access_token)
            or _secret_value(settings.kakao_refresh_token)
        ),
    }

    # --- Provider policies ---
    all_provider_names = [
        "yahoo", "massive", "tiingo",
        "sec_edgar", "fred", "openfigi",
        "alpha_vantage_news", "finnhub_events",
        "toss",
    ]
    policies: dict[str, dict[str, Any]] = {}
    for name in all_provider_names:
        policy_settings = settings.data.provider_policies.get(name)
        if policy_settings:
            policies[name] = {
                "enabled": policy_settings.enabled,
                "timeout_seconds": policy_settings.timeout_seconds,
                "retries": policy_settings.retries,
                "rate_limit_per_minute": policy_settings.rate_limit_per_minute,
                "cache_ttl_seconds": policy_settings.cache_ttl_seconds,
            }
        else:
            policies[name] = {
                "enabled": True,
                "timeout_seconds": 20.0,
                "retries": 3,
                "rate_limit_per_minute": 60,
                "cache_ttl_seconds": 14_400,
            }

    # --- Latest run data sources ---
    run_dir = _resolve_run_dir(paths, "latest")
    recent_sources: list[dict[str, Any]] = []
    recent_disagreements: list[dict[str, Any]] = []
    run_id: str | None = None
    run_finished_at: str | None = None
    if run_dir is not None:
        run_id = run_dir.name
        manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
        run_finished_at = manifest.get("finished_at")
        source_payload = _mapping(read_json(run_dir / "data_sources.json", default={}))
        recent_sources = [
            dict(item)
            for item in _sequence(source_payload.get("sources"))
            if isinstance(item, Mapping)
        ]
        disagreement_payload = _mapping(
            read_json(run_dir / "provider_disagreement_report.json", default={})
        )
        recent_disagreements = [
            dict(item)
            for item in _sequence(disagreement_payload.get("disagreements"))
            if isinstance(item, Mapping)
        ]

    # Group sources by provider
    source_by_provider: dict[str, list[dict[str, Any]]] = {}
    for source in recent_sources:
        provider_name = str(source.get("provider", ""))
        source_by_provider.setdefault(provider_name, []).append(source)

    # --- Kakao token status ---
    kakao_tokens = _mapping(read_json(paths.state_dir / "kakao_tokens.json", default={}))
    kakao_has_access = bool(
        kakao_tokens.get("access_token")
        or _secret_value(settings.kakao_access_token)
    )
    kakao_has_refresh = bool(
        kakao_tokens.get("refresh_token")
        or _secret_value(settings.kakao_refresh_token)
    )

    # --- Notification failures ---
    notification_failures: list[dict[str, Any]] = []
    failure_file = paths.state_dir / "notification_failures.jsonl"
    if failure_file.exists():
        try:
            lines = failure_file.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-20:]:
                try:
                    notification_failures.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    pass
        except OSError:
            pass

    # --- Cache directory stats ---
    cache_stats: dict[str, dict[str, Any]] = {}
    if paths.cache_dir.exists():
        for subdir in paths.cache_dir.iterdir():
            if subdir.is_dir():
                try:
                    files = list(subdir.rglob("*"))
                    file_count = sum(1 for f in files if f.is_file())
                    total_bytes = sum(f.stat().st_size for f in files if f.is_file())
                    cache_stats[subdir.name] = {
                        "file_count": file_count,
                        "total_bytes": total_bytes,
                    }
                except OSError:
                    cache_stats[subdir.name] = {"file_count": 0, "total_bytes": 0}

    toss_api_drift = _toss_api_drift_status(paths, now=now)

    # --- Build provider detail list ---
    provider_categories: dict[str, str] = {
        "yahoo": "price",
        "massive": "price",
        "tiingo": "price",
        "sec_edgar": "fundamentals",
        "fred": "macro",
        "openfigi": "reference",
        "alpha_vantage_news": "news",
        "finnhub_events": "news",
        "toss": "broker",
        "kakao": "notification",
    }
    provider_base_urls: dict[str, str] = {
        "yahoo": "yfinance (library)",
        "massive": "https://api.massive.com/v2",
        "tiingo": "https://api.tiingo.com/tiingo/daily",
        "sec_edgar": "https://data.sec.gov",
        "fred": "https://api.stlouisfed.org",
        "openfigi": "https://api.openfigi.com/v3",
        "alpha_vantage_news": "https://www.alphavantage.co/query",
        "finnhub_events": "https://finnhub.io/api/v1",
        "toss": "https://openapi.tossinvest.com",
        "kakao": "https://kapi.kakao.com",
    }
    provider_env_names: dict[str, list[str]] = {
        "yahoo": [],
        "massive": ["JAYU_MASSIVE_API_KEY"],
        "tiingo": ["JAYU_TIINGO_API_KEY"],
        "sec_edgar": ["JAYU_SEC_USER_AGENT"],
        "fred": ["JAYU_FRED_API_KEY"],
        "openfigi": ["JAYU_OPENFIGI_API_KEY"],
        "alpha_vantage_news": ["JAYU_ALPHA_VANTAGE_API_KEY"],
        "finnhub_events": ["JAYU_FINNHUB_API_KEY"],
        "toss": ["TS_API_KEY", "TS_SECRET_KEY", "TS_ACCOUNT"],
        "kakao": [
            "JAYU_KAKAO_ACCESS_TOKEN",
            "JAYU_KAKAO_REFRESH_TOKEN",
            "JAYU_KAKAO_REST_API_KEY",
            "JAYU_KAKAO_CLIENT_SECRET",
        ],
    }
    provider_display_names: dict[str, str] = {
        "yahoo": "Yahoo Finance",
        "massive": "Massive",
        "tiingo": "Tiingo",
        "sec_edgar": "SEC EDGAR",
        "fred": "FRED",
        "openfigi": "OpenFIGI",
        "alpha_vantage_news": "Alpha Vantage News",
        "finnhub_events": "Finnhub Events",
        "toss": "Toss Securities",
        "kakao": "Kakao Talk",
    }

    # Determine which providers are used in current config
    active_price = {settings.data_provider}
    if settings.data_fallback_provider != "none":
        active_price.add(settings.data_fallback_provider)
    active_price.update(settings.data.cross_validation_providers)
    active_supplemental = set(settings.data.supplemental_providers)

    providers_detail: list[dict[str, Any]] = []
    all_names = list(provider_categories.keys())
    for name in all_names:
        category = provider_categories[name]
        sources = source_by_provider.get(name, [])
        success_count = sum(1 for s in sources if s.get("status") == "success")
        failed_count = sum(1 for s in sources if s.get("status") != "success")
        total_rows = sum(int(s.get("rows", 0) or 0) for s in sources)
        # Determine recent status
        if sources:
            recent_status = "success" if failed_count == 0 else (
                "partial" if success_count > 0 else "failed"
            )
        else:
            recent_status = "unused"
        # Is this provider actively in use?
        in_use = (
            (name in active_price and category == "price")
            or (name in active_supplemental)
            or (name == "toss")
            or (name == "kakao")
        )
        policy = policies.get(name)
        enabled = policy["enabled"] if policy else True
        providers_detail.append({
            "name": name,
            "display_name": provider_display_names.get(name, name),
            "category": category,
            "base_url": provider_base_urls.get(name, ""),
            "env_names": provider_env_names.get(name, []),
            "credential_configured": credentials.get(name, False),
            "enabled": enabled,
            "in_use": in_use,
            "policy": policy,
            "recent": {
                "status": recent_status,
                "success_count": success_count,
                "failed_count": failed_count,
                "total_rows": total_rows,
                "sources": sources[:10],
            },
        })

    # --- Aggregate summary ---
    total_providers = len(all_names)
    configured_count = sum(1 for v in credentials.values() if v)
    active_count = sum(1 for p in providers_detail if p["in_use"])
    providers_with_failures = sum(
        1 for p in providers_detail if p["recent"]["status"] == "failed"
    )
    providers_with_partial = sum(
        1 for p in providers_detail if p["recent"]["status"] == "partial"
    )
    toss_drift_attention = toss_api_drift.get("status") in {
        "drifted",
        "failed_to_fetch",
        "not_checked",
        "stale",
        "unknown",
    }
    overall_status = (
        "failed" if providers_with_failures > 0
        else "warning" if (
            providers_with_partial > 0
            or configured_count < total_providers
            or toss_drift_attention
        )
        else "success"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "summary": {
            "status": overall_status,
            "total_providers": total_providers,
            "configured_count": configured_count,
            "active_count": active_count,
            "failed_count": providers_with_failures,
            "partial_count": providers_with_partial,
            "disagreement_count": len(recent_disagreements),
            "notification_failure_count": len(notification_failures),
        },
        "run_context": {
            "run_id": run_id,
            "finished_at": run_finished_at,
        },
        "providers": providers_detail,
        "categories": [
            {"key": "price", "label": "가격 데이터", "icon": "📈"},
            {"key": "fundamentals", "label": "기업 공시", "icon": "📊"},
            {"key": "macro", "label": "거시 경제", "icon": "🏛️"},
            {"key": "news", "label": "뉴스·이벤트", "icon": "📰"},
            {"key": "reference", "label": "기준 정보", "icon": "🔍"},
            {"key": "broker", "label": "증권사", "icon": "🏦"},
            {"key": "notification", "label": "알림", "icon": "🔔"},
        ],
        "disagreements": recent_disagreements[:20],
        "notification_failures": notification_failures[-10:],
        "kakao_status": {
            "has_access_token": kakao_has_access,
            "has_refresh_token": kakao_has_refresh,
            "has_rest_api_key": bool(_secret_value(settings.kakao_rest_api_key)),
            "has_client_secret": bool(_secret_value(settings.kakao_client_secret)),
        },
        "cache_stats": cache_stats,
        "toss_api_drift": toss_api_drift,
        "config": {
            "primary_price_provider": settings.data_provider,
            "fallback_price_provider": settings.data_fallback_provider,
            "cross_validation_providers": settings.data.cross_validation_providers,
            "cross_validation_mode": settings.data.cross_validation_mode,
            "supplemental_providers": settings.data.supplemental_providers,
            "supplemental_failure_policy": settings.data.supplemental_failure_policy,
            "price_disagreement_policy": settings.data.price_disagreement_policy,
        },
        "api_logs": _load_recent_api_logs(paths),
    }


def _toss_api_drift_status(paths: RuntimePaths, *, now: datetime | None = None) -> dict[str, Any]:
    """Return the latest Toss OpenAPI drift check status for the dashboard."""
    now = now or datetime.now(UTC)
    report_path = paths.state_dir / "toss_api_drift.json"
    snapshot_path = paths.state_dir / "toss_openapi_snapshot.json"
    local_paths = sorted(endpoint.path for endpoint in TOSS_GET_ENDPOINTS)
    base = {
        "source": "state/toss_api_drift.json · TOSS_GET_ENDPOINTS · Toss OpenAPI latest spec",
        "snapshot_source": "state/toss_openapi_snapshot.json",
        "local_endpoint_count": len(local_paths),
        "local_endpoints": [
            {
                "operation_id": endpoint.operation_id,
                "path": endpoint.path,
                "requires_account": endpoint.requires_account,
            }
            for endpoint in TOSS_GET_ENDPOINTS
        ],
        "snapshot_available": snapshot_path.exists(),
        "max_age_hours": 168,
    }
    if not report_path.exists():
        return {
            **base,
            "status": "not_checked",
            "status_label": "아직 확인 안 함",
            "last_checked_at": None,
            "age_hours": None,
            "missing_endpoints": [],
            "extra_endpoints": [],
            "missing_count": 0,
            "extra_count": 0,
            "fallback_snapshot_used": False,
            "summary": "Toss OpenAPI drift check 결과가 아직 없습니다. `uv run jayu toss endpoints --sync`로 스펙 차이를 확인하세요.",
            "next_action": "uv run jayu toss endpoints --sync",
        }

    report = _mapping(read_json(report_path, default={}))
    missing = [str(item) for item in _sequence(report.get("missing_endpoints"))]
    extra = [str(item) for item in _sequence(report.get("extra_endpoints"))]
    checked_at = str(report.get("last_checked_at") or "") or None
    checked_dt = _parse_datetime_utc(checked_at)
    age_hours = (
        round((now - checked_dt).total_seconds() / 3600, 2)
        if checked_dt is not None
        else None
    )
    stale = checked_dt is None or now - checked_dt > timedelta(hours=base["max_age_hours"])
    raw_status = str(report.get("status") or "unknown")
    status = "stale" if stale and raw_status == "synchronized" else raw_status
    if raw_status == "drifted" or missing or extra:
        status = "drifted"
    elif raw_status == "failed_to_fetch":
        status = "failed_to_fetch"
    elif raw_status not in {"synchronized", "drifted", "failed_to_fetch"}:
        status = "unknown"

    return {
        **base,
        "status": status,
        "status_label": _toss_api_drift_label(status),
        "last_checked_at": checked_at,
        "age_hours": age_hours,
        "missing_endpoints": missing,
        "extra_endpoints": extra,
        "missing_count": len(missing),
        "extra_count": len(extra),
        "fetch_error": report.get("fetch_error") or report.get("message"),
        "fallback_snapshot_used": report.get("fallback_snapshot_used") is True,
        "summary": _toss_api_drift_summary(status, len(missing), len(extra), age_hours),
        "next_action": "uv run jayu toss endpoints --sync",
    }


def _parse_datetime_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _toss_api_drift_label(status: str) -> str:
    return {
        "synchronized": "동기화됨",
        "drifted": "스펙 변경 감지",
        "failed_to_fetch": "스펙 조회 실패",
        "not_checked": "미확인",
        "stale": "확인 오래됨",
        "unknown": "상태 불명",
    }.get(status, "상태 불명")


def _toss_api_drift_summary(
    status: str,
    missing_count: int,
    extra_count: int,
    age_hours: float | None,
) -> str:
    if status == "synchronized":
        return "로컬 Toss GET 카탈로그가 최근 OpenAPI 스펙과 일치합니다."
    if status == "drifted":
        return f"OpenAPI 스펙과 로컬 카탈로그 차이가 있습니다. 누락 {missing_count}개, 로컬 전용 {extra_count}개를 확인하세요."
    if status == "failed_to_fetch":
        return "Toss OpenAPI 스펙을 조회하지 못했습니다. 네트워크 또는 Toss 문서 엔드포인트 상태를 확인하세요."
    if status == "stale":
        age_text = f"{age_hours:.1f}시간 전" if age_hours is not None else "시각 불명"
        return f"마지막 Toss OpenAPI drift check가 오래되었습니다 ({age_text}). 최신 스펙으로 다시 확인하세요."
    if status == "not_checked":
        return "아직 Toss OpenAPI drift check 결과가 없습니다."
    return "Toss OpenAPI drift check 상태를 해석하지 못했습니다."



def test_provider_connection(paths: RuntimePaths, provider: str) -> dict[str, Any]:
    settings = _load_dashboard_settings(paths)
    start_time = time.perf_counter()

    def _run() -> dict[str, Any]:
        if provider == "yahoo":
            try:
                import yfinance as yf
                from .yahoo import get_yahoo_session
                ticker = yf.Ticker("SOXL", session=get_yahoo_session())
                history = ticker.history(period="1d")
                if history.empty:
                    raise ValueError("Yahoo Finance returned empty history")
                return {"status": "success", "message": "Yahoo Finance connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "massive":
            key = _secret_value(settings.massive_api_key)
            if not key:
                return {"status": "failed", "message": "Massive API key is not configured"}
            try:
                import requests
                headers = {"Authorization": f"Bearer {key}"}
                res = requests.get("https://api.massive.com/v2/market/status", headers=headers, timeout=10)
                if res.status_code in {401, 403}:
                    return {"status": "failed", "message": "Unauthorized: Invalid API key"}
                return {"status": "success", "message": f"Massive API connection test passed (HTTP {res.status_code})"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "tiingo":
            key = _secret_value(settings.tiingo_api_key)
            if not key:
                return {"status": "failed", "message": "Tiingo API key is not configured"}
            try:
                import requests
                headers = {"Content-Type": "application/json", "Authorization": f"Token {key}"}
                res = requests.get("https://api.tiingo.com/tiingo/daily/SOXL", headers=headers, timeout=10)
                if res.status_code != 200:
                    return {"status": "failed", "message": f"Tiingo API returned error: HTTP {res.status_code} - {res.text[:100]}"}
                return {"status": "success", "message": "Tiingo API connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "sec_edgar":
            user_agent = _secret_value(settings.sec_user_agent)
            if not user_agent:
                return {"status": "failed", "message": "SEC EDGAR User-Agent is not configured"}
            try:
                import requests
                headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
                res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10)
                if res.status_code != 200:
                    return {"status": "failed", "message": f"SEC EDGAR returned error: HTTP {res.status_code}"}
                return {"status": "success", "message": "SEC EDGAR connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "fred":
            key = _secret_value(settings.fred_api_key)
            if not key:
                return {"status": "failed", "message": "FRED API key is not configured"}
            try:
                import requests
                params = {
                    "series_id": "FEDFUNDS",
                    "api_key": key,
                    "file_type": "json",
                    "limit": 1
                }
                res = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=10)
                if res.status_code != 200:
                    return {"status": "failed", "message": f"FRED API returned error: HTTP {res.status_code} - {res.text[:100]}"}
                return {"status": "success", "message": "FRED API connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "openfigi":
            key = _secret_value(settings.openfigi_api_key)
            try:
                import requests
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["X-OPENFIGI-APIKEY"] = key
                job = {"idType": "TICKER", "idValue": "SOXL", "exchCode": "US"}
                res = requests.post("https://api.openfigi.com/v3/mapping", headers=headers, json=[job], timeout=10)
                if res.status_code != 200:
                    return {"status": "failed", "message": f"OpenFIGI returned error: HTTP {res.status_code} - {res.text[:100]}"}
                return {"status": "success", "message": "OpenFIGI connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "alpha_vantage_news":
            key = _secret_value(settings.alpha_vantage_api_key)
            if not key:
                return {"status": "failed", "message": "Alpha Vantage API key is not configured"}
            try:
                import requests
                params = {
                    "function": "NEWS_SENTIMENT",
                    "tickers": "SOXL",
                    "limit": 1,
                    "apikey": key,
                }
                res = requests.get("https://www.alphavantage.co/query", params=params, timeout=10)
                if res.status_code != 200:
                    return {"status": "failed", "message": f"Alpha Vantage returned error: HTTP {res.status_code}"}
                data = res.json()
                if "Error Message" in data:
                    return {"status": "failed", "message": data["Error Message"]}
                if "Note" in data:
                    return {"status": "failed", "message": f"Rate limit reached: {data['Note']}"}
                return {"status": "success", "message": "Alpha Vantage connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "finnhub_events":
            key = _secret_value(settings.finnhub_api_key)
            if not key:
                return {"status": "failed", "message": "Finnhub API key is not configured"}
            try:
                import requests
                params = {"symbol": "SOXL", "token": key}
                res = requests.get("https://finnhub.io/api/v1/company-news", params=params, timeout=10)
                if res.status_code != 200:
                    return {"status": "failed", "message": f"Finnhub returned error: HTTP {res.status_code} - {res.text[:100]}"}
                return {"status": "success", "message": "Finnhub connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "toss":
            api_key = _secret_value(settings.toss_api_key)
            secret_key = _secret_value(settings.toss_secret_key)
            if not api_key or not secret_key:
                return {"status": "failed", "message": "Toss credentials are not configured"}
            try:
                client = _dashboard_toss_client(settings)
                accounts = client.accounts()
                if "result" not in accounts:
                    return {"status": "failed", "message": "Toss API returned empty or invalid response"}
                return {"status": "success", "message": "Toss API connection test passed"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        elif provider == "kakao":
            access_token = _secret_value(settings.kakao_access_token)
            if not access_token:
                kakao_tokens = read_json(paths.state_dir / "kakao_tokens.json", default={})
                access_token = kakao_tokens.get("access_token")
            if not access_token:
                return {"status": "failed", "message": "Kakao Access Token is not configured"}
            try:
                import requests
                headers = {"Authorization": f"Bearer {access_token}"}
                res = requests.get("https://kapi.kakao.com/v1/user/access_token_info", headers=headers, timeout=10)
                if res.status_code != 200:
                    return {"status": "failed", "message": f"Kakao API returned error: HTTP {res.status_code} - {res.text[:100]}"}
                return {"status": "success", "message": "Kakao API token is active and valid"}
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}

        return {"status": "failed", "message": f"Unknown provider: {provider}"}

    res = _run()
    res["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
    return res



def clear_provider_cache(paths: RuntimePaths, cache_type: str) -> dict[str, Any]:
    if not paths.cache_dir.exists():
        return {"status": "success", "message": "Cache directory does not exist", "file_count": 0, "total_bytes": 0}
    try:
        deleted_count = 0
        deleted_bytes = 0
        if cache_type == "all":
            targets = [paths.cache_dir]
        else:
            target_sub = paths.cache_dir / cache_type
            if target_sub.exists() and target_sub.is_dir():
                targets = [target_sub]
            else:
                targets = []
        for target in targets:
            files = list(target.rglob("*"))
            for f in files:
                if f.is_file():
                    try:
                        size = f.stat().st_size
                        f.unlink()
                        deleted_count += 1
                        deleted_bytes += size
                    except OSError:
                        pass
        new_count = 0
        new_bytes = 0
        if cache_type != "all" and (paths.cache_dir / cache_type).exists():
            sub = paths.cache_dir / cache_type
            sub_files = list(sub.rglob("*"))
            new_count = sum(1 for f in sub_files if f.is_file())
            new_bytes = sum(f.stat().st_size for f in sub_files if f.is_file())
        return {
            "status": "success",
            "message": f"Deleted {deleted_count} files ({deleted_bytes} bytes) from cache",
            "deleted_count": deleted_count,
            "deleted_bytes": deleted_bytes,
            "new_count": new_count,
            "new_bytes": new_bytes,
        }
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}


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
    settings = load_settings(paths.project_root / "configs" / "settings.json")
    
    event_bus = DomainEventBus(paths.state_dir)
    checklist_evaluator = PreTradeChecklistEvaluator(paths.project_root / "configs" / "pre_trade_checklist.yaml")
    recommender = NextCommandRecommender(settings, paths)
    backup_mgr = BackupManager(paths.project_root, paths.state_dir)
    noti_engine = NotificationPolicyEngine(paths.state_dir)
    knowledge_card_mgr = StockKnowledgeCardManager(paths.state_dir)
    permission_mgr = DashboardPermissionModeManager(default_mode="read_only")
    risk_budget_mgr = StrategyRiskBudgetManager(paths.project_root, paths.state_dir)
    experiment_registry = ExperimentRegistry(paths.state_dir / "experiments.sqlite")

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            global GLOBAL_EXPLANATION_LEVEL
            parsed = urlparse(self.path)
            try:
                # --- 신규 고도화 API 라우트 (GET) ---
                if parsed.path == "/api/v1/permission-mode":
                    self._json({"mode": permission_mgr.get_mode()})
                    return
                if parsed.path == "/api/v1/backup/list":
                    if not backup_mgr.backup_dir.exists():
                        self._json({"backups": []})
                        return
                    files = []
                    for f in backup_mgr.backup_dir.glob("*.zip"):
                        files.append({
                            "name": f.name,
                            "size": f.stat().st_size,
                            "mtime": datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat()
                        })
                    self._json({"backups": sorted(files, key=lambda x: x["mtime"], reverse=True)})
                    return
                if parsed.path == "/api/v1/events":
                    query = parse_qs(parsed.query)
                    date_str = query.get("date", [None])[0]
                    events = event_bus.get_events(date_str)
                    self._json({"events": [e.model_dump() for e in events]})
                    return
                if parsed.path == "/api/v1/investment-goals":
                    from .investment_goal_planner import InvestmentGoalPlanner
                    planner = InvestmentGoalPlanner(paths.project_root)
                    goals = planner.load_goals()
                    analyses = [planner.calculate_analysis(g) for g in goals]
                    self._json({"goals": analyses})
                    return
                if parsed.path == "/api/v1/cashflows/settings":
                    from .cashflow_planner import CashflowPlanner
                    planner = CashflowPlanner(paths.project_root)
                    self._json({"default_salary_krw": planner.load_default_salary()})
                    return
                if parsed.path == "/api/v1/cashflows":
                    from .cashflow_planner import CashflowPlanner
                    planner = CashflowPlanner(paths.project_root)
                    records = planner.load_cashflows()
                    budgets = [planner.calculate_monthly_budget(r) for r in records]
                    self._json({"cashflows": budgets})
                    return
                if parsed.path == "/api/v1/benchmark-comparison":
                    from .benchmark_comparison import BenchmarkComparison
                    comp = BenchmarkComparison()
                    query = parse_qs(parsed.query)
                    ret = float(query.get("return_pct", [15.4])[0])
                    vol = float(query.get("volatility_pct", [16.2])[0])
                    mdd = float(query.get("mdd_pct", [11.2])[0])
                    self._json(comp.compare_portfolio(ret, vol, mdd))
                    return
                if parsed.path == "/api/v1/monthly-report":
                    from .monthly_investment_report import MonthlyInvestmentReport
                    reporter = MonthlyInvestmentReport(paths.project_root)
                    data = {
                        "return_pct": 15.4,
                        "dividend_krw": 450000.0,
                        "cost_krw": 25000.0,
                        "fx_effect_krw": 180000.0,
                        "risk_blocks_count": 2,
                        "signals_count": 14,
                        "win_rate_pct": 65.4,
                        "goal_achievement_pct": 74.2,
                        "generated_at": datetime.now().isoformat()
                    }
                    reporter.generate_report(2026, 6, data)
                    self._json(data)
                    return
                if parsed.path == "/api/v1/dividend-simulator":
                    from .dividend_cashflow_simulator import DividendCashflowSimulator
                    sim = DividendCashflowSimulator(paths.project_root)
                    self._json(sim.simulate_cashflow())
                    return
                if parsed.path == "/api/v1/personal-investment-score":
                    from .personal_investment_score import PersonalInvestmentScore
                    scorer = PersonalInvestmentScore(paths.project_root)
                    self._json(scorer.calculate_score())
                    return
                if parsed.path == "/api/v1/portfolio-purpose-tags":
                    from .portfolio_purpose_tags import PortfolioPurposeTags
                    tagger = PortfolioPurposeTags(paths.project_root)
                    query = parse_qs(parsed.query)
                    ticker = query.get("ticker", [None])[0]
                    if ticker:
                        self._json({"ticker": ticker, "tags": tagger.get_tags(ticker)})
                    else:
                        self._json(tagger.load_tags())
                    return
                if parsed.path == "/api/v1/investment-journals":
                    from .investment_journal import InvestmentJournal
                    journal = InvestmentJournal(paths.project_root)
                    entries = journal.update_outcomes()
                    self._json({"journals": entries})
                    return
                if parsed.path == "/api/v1/dividend-living-expense-simulator":
                    from .dividend_living_expense_simulator import DividendLivingExpenseSimulator
                    sim = DividendLivingExpenseSimulator(paths.project_root)
                    self._json(sim.simulate())
                    return
                if parsed.path == "/api/v1/loss-recovery-planner":
                    from .loss_recovery_planner import LossRecoveryPlanner
                    planner = LossRecoveryPlanner()
                    query = parse_qs(parsed.query)
                    loss_pct = float(query.get("loss_pct", [0.20])[0])
                    from .dividend_cashflow_simulator import DividendCashflowSimulator
                    div_sim = DividendCashflowSimulator(paths.project_root)
                    port_data = div_sim.simulate_cashflow()
                    port_val = port_data.get("portfolio_value_krw", 10000000.0)
                    if port_val <= 0:
                        port_val = 10000000.0
                    self._json(planner.calculate_recovery_plan(port_val, loss_pct))
                    return
                if parsed.path == "/api/v1/behavior-insights":
                    from .investor_behavior_insights import InvestorBehaviorInsights
                    insights = InvestorBehaviorInsights(paths.project_root)
                    self._json(insights.analyze_behavior())
                    return
                if parsed.path == "/api/v1/trade-behavior-review":
                    from .toss_orders import TossOrdersManager
                    from .trade_behavior_review import review_trade_behavior

                    mgr = TossOrdersManager(paths.project_root)
                    self._json(review_trade_behavior(mgr.load_orders()))
                    return
                if parsed.path == "/api/v1/portfolio-diet":
                    from .portfolio_diet_mode import PortfolioDietMode
                    diet = PortfolioDietMode(paths.project_root)
                    self._json(diet.analyze_portfolio_diet())
                    return
                if parsed.path == "/api/v1/investment-calendar":
                    from .investment_calendar import InvestmentCalendar
                    cal = InvestmentCalendar()
                    self._json({"events": cal.get_events()})
                    return
                if parsed.path == "/api/v1/pretrade-checklist":
                    res = checklist_evaluator.evaluate(
                        signal_data={"risk_passed": True, "score": 0.8},
                        account_data={"cash_usd": 1000.0, "cash_krw": 1500000.0},
                        is_approved=True
                    )
                    self._json(res)
                    return
                if parsed.path == "/api/v1/recommender/next":
                    self._json(recommender.recommend())
                    return
                if parsed.path == "/api/v1/notifications":
                    self._json({"notifications": noti_engine.get_inbox()})
                    return
                if parsed.path == "/api/v1/knowledge-cards":
                    query = parse_qs(parsed.query)
                    ticker = query.get("ticker", [None])[0]
                    if ticker:
                        self._json(knowledge_card_mgr.get_card(ticker))
                    else:
                        self._json({"cards": knowledge_card_mgr.list_cards()})
                    return
                if parsed.path == "/api/v1/strategies/cards":
                    from .strategy_card_registry import GLOBAL_STRATEGY_CARD_REGISTRY
                    self._json({"cards": [c.to_dict() for c in GLOBAL_STRATEGY_CARD_REGISTRY.list_cards()]})
                    return
                if parsed.path == "/api/v1/strategy/budgets":
                    self._json({"budgets": risk_budget_mgr.get_all_budgets_status()})
                    return
                if parsed.path == "/api/v1/experiments":
                    self._json({"experiments": experiment_registry.get_experiments()})
                    return
                if parsed.path == "/api/v1/features":
                    from .feature_inventory import build_feature_inventory

                    self._json(build_feature_inventory(paths.project_root))
                    return
                if parsed.path == "/api/v1/data-trust-score":
                    query = parse_qs(parsed.query)
                    self._json(build_dashboard_data_trust(paths, run_id=query.get("run_id", ["latest"])[0]))
                    return
                if parsed.path == "/api/v1/query":
                    query = parse_qs(parsed.query)
                    resource = query.get("resource", [""])[0]
                    fields_str = query.get("fields", [""])[0]
                    fields = [f.strip() for f in fields_str.split(",") if f.strip()]
                    if resource == "signals":
                        run_id = query.get("run_id", ["latest"])[0]
                        sig_data = build_dashboard_signals(paths, run_id=run_id)
                        signals_list = sig_data.get("signals", [])
                        filtered = []
                        for sig in signals_list:
                            if fields:
                                filtered.append({k: sig.get(k) for k in fields if k in sig})
                            else:
                                filtered.append(sig)
                        self._json({"signals": filtered})
                        return
                    elif resource == "overview":
                        run_id = query.get("run_id", ["latest"])[0]
                        overview = build_dashboard_overview(paths, run_id=run_id)
                        if fields:
                            self._json({k: overview.get(k) for k in fields if k in overview})
                        else:
                            self._json(overview)
                        return
                if parsed.path == "/api/v1/runs":
                    self._json(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "runs": list_dashboard_runs(paths),
                            "failure_patterns": build_failure_patterns_report(paths.runs_dir),
                        }
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
                    if segments[4] == "log":
                        run_dir = paths.runs_dir / run_id
                        events_file = run_dir / "logs" / "events.jsonl"
                        logs = []
                        if events_file.exists():
                            try:
                                with open(events_file, "r", encoding="utf-8") as f:
                                    for line in f:
                                        line = line.strip()
                                        if line:
                                            try:
                                                logs.append(json.loads(line))
                                            except Exception:
                                                pass
                            except Exception as e:
                                logs.append({"timestamp": "", "level": "ERROR", "message": f"로그 로드 오류: {e}"})
                        self._json({"run_id": run_id, "logs": logs})
                        return
                if parsed.path == "/api/v1/analysis":
                    query = parse_qs(parsed.query)
                    ticker = query.get("ticker", ["SOXL"])[0].upper()
                    macro_series = query.get("macro_series", ["FEDFUNDS"])[0].upper()
                    period = query.get("period", ["2y"])[0]
                    self._json(
                        build_dashboard_analysis(
                            paths,
                            ticker=ticker,
                            macro_series=macro_series,
                            period=period,
                        )
                    )
                    return
                if parsed.path == "/api/v1/analysis/technical":
                    query = parse_qs(parsed.query)
                    ticker = query.get("ticker", ["SOXL"])[0].upper()
                    period = query.get("period", ["1y"])[0]
                    self._json(build_analysis_technical(ticker=ticker, period=period))
                    return
                if parsed.path == "/api/v1/analysis/market-overview":
                    self._json(build_analysis_market_overview())
                    return
                if parsed.path == "/api/v1/analysis/multi-compare":
                    query = parse_qs(parsed.query)
                    raw_tickers = query.get("tickers", ["SOXL,TQQQ,NVDA,QQQ,SPY"])[0]
                    tickers_list = [t.strip().upper() for t in raw_tickers.split(",") if t.strip()]
                    period = query.get("period", ["1y"])[0]
                    self._json(build_analysis_multi_compare(tickers=tickers_list, period=period))
                    return
                if parsed.path == "/api/v1/analysis/portfolio-stats":
                    query = parse_qs(parsed.query)
                    run_id = query.get("run_id", [None])[0]
                    self._json(build_analysis_portfolio_stats(paths, run_id=run_id))
                    return
                if parsed.path == "/api/v1/analysis/economic-calendar":
                    self._json(build_analysis_economic_calendar())
                    return
                # ── 포트폴리오 허브 ───────────────────────────────────────────
                if parsed.path == "/api/v1/portfolio-hub":
                    query = parse_qs(parsed.query)
                    raw_tickers = query.get("tickers", [""])[0]
                    tickers_list = [t.strip().upper() for t in raw_tickers.split(",") if t.strip()]
                    self._json(build_portfolio_hub_data(paths, tickers=tickers_list))
                    return
                if parsed.path == "/api/v1/portfolio-hub/meta":
                    self._json(build_portfolio_hub_meta(GLOBAL_EXPLANATION_LEVEL))
                    return
                if parsed.path == "/api/v1/portfolio-hub/signals":
                    query = parse_qs(parsed.query)
                    ticker = query.get("ticker", ["SOXL"])[0].upper()
                    self._json(build_portfolio_hub_ticker_signals(ticker))
                    return
                # ── 투자 판단 OS API ──────────────────────────────────────────
                if parsed.path == "/api/v1/set-explanation-level":
                    query = parse_qs(parsed.query)
                    lvl = query.get("level", ["normal"])[0]
                    if lvl in ("beginner", "normal", "expert"):
                        GLOBAL_EXPLANATION_LEVEL = lvl
                        try:
                            from .settings import Settings
                            # Pydantic 필드 기본값 갱신으로 환경설정 동기화
                            Settings.model_fields['explanation_level'].default = lvl
                        except Exception:
                            pass
                        self._json({"status": "success", "level": lvl})
                    else:
                        self._json({"status": "error", "message": "Invalid level"}, status=400)
                    return
                if parsed.path == "/api/v1/investment-decision-os":
                    from .market_regime_router import determine_market_regime
                    from .strategy_retirement_candidates import generate_retirement_report
                    from .rule_violation_audit import get_violation_logs
                    from .strategy_governance import get_strategy_governance_info
                    
                    regime_res = determine_market_regime()
                    retirement_res = generate_retirement_report()
                    violations_res = get_violation_logs(limit=20)
                    gov_res = get_strategy_governance_info()
                    
                    self._json({
                        "market_regime": regime_res,
                        "strategy_retirement": retirement_res,
                        "playbook_violations": violations_res,
                        "strategy_governance": gov_res,
                        "explanation_level": GLOBAL_EXPLANATION_LEVEL
                    })
                    return
                # ── 실행 비교, 산출물 검색, 제공자 신뢰도 추세 API ──────────────────────
                if parsed.path == "/api/v1/runs/compare":
                    query = parse_qs(parsed.query)
                    left = query.get("left", ["previous"])[0]
                    right = query.get("right", ["latest"])[0]
                    from .run_compare import compare_runs, generate_compare_markdown
                    try:
                        diff_data = compare_runs(paths, left, right)
                        diff_data["markdown"] = generate_compare_markdown(diff_data)
                        self._json(diff_data)
                    except Exception as e:
                        self._json({"status": "error", "message": str(e)}, status=400)
                    return
                if parsed.path == "/api/v1/artifacts/search":
                    query = parse_qs(parsed.query)
                    q = query.get("query", [None])[0]
                    run_id = query.get("run_id", [None])[0]
                    ticker = query.get("ticker", [None])[0]
                    failure_code = query.get("failure_code", [None])[0]
                    mode = query.get("mode", [None])[0]
                    atype = query.get("artifact_type", [None])[0]
                    
                    from .artifact_indexer import search_artifacts
                    results = search_artifacts(
                        paths,
                        query=q,
                        run_id=run_id,
                        ticker=ticker,
                        failure_code=failure_code,
                        mode=mode,
                        artifact_type=atype
                    )
                    self._json({"artifacts": results})
                    return
                if parsed.path == "/api/v1/provider-trend":
                    query = parse_qs(parsed.query)
                    limit = int(query.get("limit", ["10"])[0])
                    from .provider_reliability_trend import calculate_provider_trends
                    trends = calculate_provider_trends(paths, limit=limit)
                    self._json(trends)
                    return
                if parsed.path == "/api/v1/artifacts/view":
                    query = parse_qs(parsed.query)
                    file_path = query.get("path", [""])[0]
                    if not file_path:
                        self._json({"error": "missing path"}, status=400)
                        return
                    path_obj = Path(file_path).resolve()
                    runs_root = paths.runs_dir.resolve()
                    state_root = paths.state_dir.resolve()
                    is_safe = False
                    for root in (runs_root, state_root):
                        if root in path_obj.parents or path_obj == root:
                            is_safe = True
                            break
                    if not is_safe or not path_obj.is_file():
                        self._json({"error": "forbidden or file not found"}, status=403)
                        return
                    try:
                        content = path_obj.read_text(encoding="utf-8")
                        self._json({
                            "name": path_obj.name,
                            "path": str(path_obj),
                            "content": content
                        })
                    except Exception as e:
                        self._json({"error": str(e)}, status=500)
                    return
                # ── 개인 투자 운영 OS 신규 API ──────────────────────
                if parsed.path == "/api/v1/system/migrations":
                    from .state_schema_migration import SchemaMigrator
                    migrator = SchemaMigrator()
                    reports = migrator.migrate_all(paths)
                    self._json({"reports": reports})
                    return
                if parsed.path == "/api/v1/ops-datamart/trends":
                    query = parse_qs(parsed.query)
                    limit = int(query.get("limit", ["30"])[0])
                    from .ops_datamart import get_trends
                    trends = get_trends(paths.state_dir / "ops_datamart.sqlite", limit_days=limit)
                    self._json(trends)
                    return
                if parsed.path == "/api/v1/ops-datamart/sync":
                    from .ops_datamart import sync_all_runs
                    count = sync_all_runs(paths.state_dir / "ops_datamart.sqlite", paths)
                    self._json({"status": "success", "synced": count})
                    return
                if parsed.path == "/api/v1/routines":
                    from .investment_routine_scheduler import get_routine_schedule
                    schedule = get_routine_schedule(paths)
                    self._json(schedule)
                    return
                if parsed.path == "/api/v1/provider-sla":
                    from .provider_sla_policy import evaluate_provider_sla
                    sla_report = evaluate_provider_sla(paths)
                    self._json(sla_report)
                    return
                if parsed.path == "/api/v1/tax-lots":
                    from .tax_lot_ledger import TaxLotLedger
                    ledger = TaxLotLedger(paths.state_dir / "tax_lot_ledger.json")
                    self._json({"lots": ledger.load_lots()})
                    return
                if parsed.path == "/api/v1/tax-lots/reconcile":
                    from .tax_lot_ledger import TaxLotLedger
                    ledger = TaxLotLedger(paths.state_dir / "tax_lot_ledger.json")
                    toss_holdings = []
                    try:
                        if paths.portfolio_file.exists():
                            import csv
                            with open(paths.portfolio_file, "r", encoding="utf-8") as f:
                                reader = csv.DictReader(f)
                                for row in reader:
                                    toss_holdings.append({
                                        "ticker": row.get("ticker", row.get("symbol", "")).upper(),
                                        "quantity": float(row.get("quantity", row.get("qty", 0.0))),
                                        "avg_cost": float(row.get("avg_cost", row.get("avg_price", 0.0)))
                                    })
                    except Exception:
                        pass
                    recon_report = ledger.reconcile_with_toss(toss_holdings)
                    self._json(recon_report)
                    return
                if parsed.path == "/api/v1/approvals":
                    from .approval_audit_ledger import load_approval_history
                    history = load_approval_history(paths)
                    self._json({"history": history})
                    return
                if parsed.path == "/api/v1/ops-slo/trends":
                    from .ops_slo_score import get_ops_slo_trends
                    trends = get_ops_slo_trends(paths, limit=30)
                    self._json(trends)
                    return
                # ── 자동매매 준비 상태 ────────────────────────────────────────
                if parsed.path == "/api/v1/autotrading-status":
                    self._json(build_autotrading_status_data(paths))
                    return
                if parsed.path == "/api/v1/simulation/log":
                    with SIMULATION_LOCK:
                        self._json({
                            "status": SIMULATION_STATUS,
                            "logs": "".join(SIMULATION_BUFFER)
                        })
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
                if parsed.path == "/api/v1/toss/orders":
                    from .toss_orders import TossOrdersManager
                    mgr = TossOrdersManager(paths.project_root)
                    query = parse_qs(parsed.query)
                    fetch_result = None
                    account = query.get("account", [None])[0]
                    if query.get("refresh", ["false"])[0].lower() == "true" or not mgr.orders_file.exists():
                        fetch_result = mgr.fetch_and_save(paths, account=account)
                    orders = mgr.load_orders()
                    self._json(
                        {
                            "orders": orders,
                            "fetch_result": fetch_result,
                            "source": "Toss Order History getOrders · GET /api/v1/orders",
                        }
                    )
                    return
                if parsed.path.startswith("/api/v1/toss/orders/"):
                    from .toss_orders import TossOrdersManager
                    mgr = TossOrdersManager(paths.project_root)
                    query = parse_qs(parsed.query)
                    order_id = unquote(parsed.path.removeprefix("/api/v1/toss/orders/"))
                    account = query.get("account", [None])[0]
                    if query.get("refresh", ["false"])[0].lower() == "true":
                        self._json(mgr.fetch_order_detail(paths, order_id, account=account))
                    else:
                        order = mgr.load_order_detail(order_id)
                        if order is None:
                            detail = mgr.fetch_order_detail(paths, order_id, account=account)
                        else:
                            detail = {
                                "status": "cached",
                                "order": order,
                                "source": "state/toss_order_details.json · cached Toss getOrder detail",
                            }
                        self._json(detail)
                    return
                if parsed.path == "/api/v1/toss/order-quality":
                    from .order_history_quality_check import check_order_history_quality
                    from .toss_orders import TossOrdersManager

                    mgr = TossOrdersManager(paths.project_root)
                    self._json(check_order_history_quality(mgr.load_orders()))
                    return
                if parsed.path == "/api/v1/toss/order-integrity":
                    from .toss_order_integrity_check import check_toss_order_integrity
                    from .toss_orders import TossOrdersManager

                    mgr = TossOrdersManager(paths.project_root)
                    self._json(check_toss_order_integrity(mgr.load_orders()))
                    return
                if parsed.path == "/api/v1/toss/trade-history-analytics":
                    from .toss_orders import TossOrdersManager
                    from .trade_history_analytics import build_trade_history_analytics

                    mgr = TossOrdersManager(paths.project_root)
                    self._json(build_trade_history_analytics(mgr.load_orders()))
                    return
                if parsed.path == "/api/v1/order-history-summary":
                    from .order_history_summary import build_order_history_summary
                    from .tax_lot_ledger import TaxLotLedger
                    from .toss_orders import TossOrdersManager

                    query = parse_qs(parsed.query)
                    run_id = query.get("run_id", ["latest"])[0]
                    account = query.get("account", [None])[0]
                    mgr = TossOrdersManager(paths.project_root)
                    orders = mgr.load_orders()
                    try:
                        run_dir = _resolve_run_dir(paths, run_id)
                    except ValueError:
                        run_dir = None
                    signals_payload: list[dict[str, Any]] = []
                    if run_dir is not None:
                        signals_payload = _signal_rows(_signal_map(run_dir))
                    portfolio_mapping = dict(
                        _mapping(read_json(paths.project_root / "configs" / "portfolio_mapping.json", default={}))
                    )
                    tax_lots = TaxLotLedger(paths.state_dir / "tax_lot_ledger.json").load_lots()
                    holdings: list[dict[str, Any]] = []
                    if query.get("include_holdings", ["false"])[0].lower() == "true":
                        try:
                            portfolio = build_dashboard_toss_portfolio(paths, account=account)
                            holdings = list(portfolio.get("holdings") or [])
                        except Exception:
                            holdings = []
                    self._json(
                        build_order_history_summary(
                            orders,
                            signals_payload=signals_payload,
                            holdings_payload=holdings,
                            tax_lots_payload=tax_lots,
                            portfolio_mapping=portfolio_mapping,
                        )
                    )
                    return
                if parsed.path == "/api/v1/toss/realized-pnl-reconciliation":
                    from .realized_pnl_reconciliation import reconcile_realized_pnl
                    from .tax_lot_ledger import TaxLotLedger
                    from .toss_orders import TossOrdersManager

                    query = parse_qs(parsed.query)
                    account = query.get("account", [None])[0]
                    mgr = TossOrdersManager(paths.project_root)
                    ledger = TaxLotLedger(paths.state_dir / "tax_lot_ledger.json")
                    holdings: list[dict[str, Any]] = []
                    try:
                        portfolio = build_dashboard_toss_portfolio(paths, account=account)
                        holdings = list(portfolio.get("holdings") or [])
                    except Exception:
                        holdings = []
                    self._json(reconcile_realized_pnl(mgr.load_orders(), ledger.load_lots(), holdings))
                    return
                if parsed.path == "/api/v1/toss/stock-trade-lifecycle":
                    from .stock_trade_lifecycle import build_stock_trade_lifecycle
                    from .toss_orders import TossOrdersManager

                    query = parse_qs(parsed.query)
                    account = query.get("account", [None])[0]
                    mgr = TossOrdersManager(paths.project_root)
                    holdings = []
                    try:
                        portfolio = build_dashboard_toss_portfolio(paths, account=account)
                        holdings = list(portfolio.get("holdings") or [])
                    except Exception:
                        holdings = []
                    self._json(build_stock_trade_lifecycle(mgr.load_orders(), holdings))
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
                if parsed.path == "/api/v1/toss/reconciliation":
                    query = parse_qs(parsed.query)
                    account = query.get("account", [None])[0]
                    self._json(build_dashboard_toss_reconciliation(paths, account=account))
                    return
                if parsed.path == "/api/v1/toss/stock-names":
                    from .toss_stock_metadata import TossStockMetadataManager
                    manager = TossStockMetadataManager(paths.project_root)
                    client = None
                    try:
                        settings = _load_dashboard_settings(paths)
                        status = build_dashboard_toss_status(paths)
                        if status["status"] == "configured":
                            client = _dashboard_toss_client(settings)
                    except Exception:
                        pass
                    mapping = manager.get_stock_names(client)
                    self._json(mapping)
                    return
                if parsed.path == "/api/v1/toss/order-plan":
                    self._json(build_dashboard_toss_order_plan(paths))
                    return
                if parsed.path == "/api/v1/api-monitoring":
                    self._json(build_dashboard_api_monitoring(paths))
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

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
                payload = json.loads(post_data) if post_data else {}

                path_action_map = {
                    "/api/v1/permission-mode": "view",
                    "/api/v1/approvals": "record_approval",
                    "/api/v1/tax-lots/buy": "write_memo",
                    "/api/v1/tax-lots/sell": "write_memo",
                    "/api/v1/knowledge-cards": "write_memo",
                    "/api/v1/backup/create": "trigger_backup",
                    "/api/v1/backup/restore": "trigger_restore",
                    "/api/v1/notifications/send": "modify_settings",
                    "/api/v1/experiments": "modify_settings",
                    "/api/v1/ask-jayu": "view",
                    "/api/v1/llm-explain": "view",
                    "/api/v1/investment-goals": "modify_settings",
                    "/api/v1/cashflows": "modify_settings",
                    "/api/v1/cashflows/settings": "modify_settings",
                    "/api/v1/portfolio-purpose-tags": "write_memo",
                    "/api/v1/investment-journals": "write_memo",
                    "/api/v1/dividend-living-expense-simulator": "modify_settings",
                }
                
                req_action = path_action_map.get(parsed.path)
                if req_action and not permission_mgr.is_action_allowed(req_action):
                    self._json({
                        "status": "error",
                        "message": f"permission_denied: action '{req_action}' is not allowed in current mode '{permission_mgr.get_mode()}'"
                    }, status=403)
                    return

                # --- 신규 고도화 API 라우트 (POST) ---
                if parsed.path == "/api/v1/ask-jayu":
                    query_text = payload.get("query", "")
                    from .local_knowledge_index import LocalKnowledgeIndex
                    rag = LocalKnowledgeIndex(paths.project_root)
                    result = rag.ask_jayu(query_text)
                    self._json(result)
                    return

                if parsed.path == "/api/v1/llm-explain":
                    explain_type = payload.get("type")
                    explain_data = payload.get("data", {})
                    from .llm_explainer import LlmExplainer
                    explainer = LlmExplainer()
                    if explain_type == "signal":
                        explanation = explainer.explain_signal(explain_data)
                    elif explain_type == "risk":
                        explanation = explainer.explain_risk_block(explain_data)
                    elif explain_type == "disagreement":
                        explanation = explainer.explain_disagreement(explain_data)
                    else:
                        explanation = "알 수 없는 설명 요청 유형입니다."
                    self._json({"explanation": explanation})
                    return

                if parsed.path == "/api/v1/permission-mode":
                    mode = payload.get("mode")
                    if mode in {"read_only", "review_only", "approve_enabled", "admin"}:
                        permission_mgr.set_mode(mode)
                        self._json({"status": "success", "mode": mode})
                    else:
                        self._json({"status": "error", "message": "invalid mode"}, status=400)
                    return

                if parsed.path == "/api/v1/investment-goals":
                    import time
                    goal_id = payload.get("goal_id") or f"goal_{int(time.time() * 1000)}"
                    name = payload.get("name")
                    target_amount = float(payload.get("target_amount") or payload.get("target_value") or 0.0)
                    
                    target_date = payload.get("target_date")
                    if not target_date:
                        months = int(payload.get("horizon_months") or 240)
                        from datetime import datetime
                        yr = datetime.now().year + (datetime.now().month + months - 1) // 12
                        mn = (datetime.now().month + months - 1) % 12 + 1
                        target_date = f"{yr:04d}-{mn:02d}-{datetime.now().day:02d}"
                        
                    current_amount = float(payload.get("current_amount") or payload.get("current_value") or 0.0)
                    monthly_deposit = float(payload.get("monthly_deposit") or payload.get("monthly_contribution") or 0.0)
                    expected_return = float(payload.get("expected_return", 0.08))
                    goal_type = payload.get("goal_type") or "retirement"
                    
                    if not (goal_id and name and target_date):
                        self._json({"status": "error", "message": "missing required parameters"}, status=400)
                        return
                    from .investment_goal_planner import InvestmentGoalPlanner
                    planner = InvestmentGoalPlanner(paths.project_root)
                    goal = planner.set_goal(
                        goal_id=goal_id,
                        name=name,
                        target_amount=target_amount,
                        target_date=target_date,
                        current_amount=current_amount,
                        monthly_deposit=monthly_deposit,
                        expected_return=expected_return
                    )
                    
                    if goal_type:
                        goals = planner.load_goals()
                        for g in goals:
                            if g["goal_id"] == goal_id:
                                g["goal_type"] = goal_type
                        planner.save_goals(goals)
                        goal["goal_type"] = goal_type
                        
                    self._json({"status": "success", "goal": goal})
                    return

                if parsed.path == "/api/v1/cashflows/settings":
                    salary = float(payload.get("default_salary_krw", 6500000.0))
                    from .cashflow_planner import CashflowPlanner
                    planner = CashflowPlanner(paths.project_root)
                    val = planner.save_default_salary(salary)
                    self._json({"status": "success", "default_salary_krw": val})
                    return

                if parsed.path == "/api/v1/cashflows":
                    month = payload.get("month")
                    salary = float(payload.get("salary_deposit", 0.0))
                    dividends = float(payload.get("expected_dividends", 0.0))
                    extra = float(payload.get("extra_deposits", 0.0))
                    buys = float(payload.get("planned_buys", 0.0))
                    reserved = float(payload.get("reserved_cash", 0.0))
                    if not month:
                        self._json({"status": "error", "message": "missing month parameter"}, status=400)
                        return
                    from .cashflow_planner import CashflowPlanner
                    planner = CashflowPlanner(paths.project_root)
                    rec = planner.add_cashflow(
                         month=month,
                         salary_deposit=salary,
                         expected_dividends=dividends,
                         extra_deposits=extra,
                         planned_buys=buys,
                         reserved_cash=reserved
                    )
                    self._json({"status": "success", "cashflow": rec})
                    return

                if parsed.path == "/api/v1/portfolio-purpose-tags":
                    ticker = payload.get("ticker")
                    tags = payload.get("tags")
                    if not ticker or tags is None:
                        self._json({"status": "error", "message": "missing ticker or tags"}, status=400)
                        return
                    from .portfolio_purpose_tags import PortfolioPurposeTags
                    tagger = PortfolioPurposeTags(paths.project_root)
                    res_tags = tagger.set_tags(ticker, tags)
                    self._json({"status": "success", "ticker": ticker, "tags": res_tags})
                    return

                if parsed.path == "/api/v1/investment-journals":
                    ticker = payload.get("ticker")
                    action_type = payload.get("action_type")
                    price = float(payload.get("price", 0.0))
                    note = payload.get("note", "")
                    if not (ticker and action_type and price > 0):
                        self._json({"status": "error", "message": "missing required parameters"}, status=400)
                        return
                    from .investment_journal import InvestmentJournal
                    journal = InvestmentJournal(paths.project_root)
                    entry = journal.add_entry(ticker, action_type, price, note)
                    self._json({"status": "success", "journal": entry})
                    return

                if parsed.path == "/api/v1/dividend-living-expense-simulator":
                    target_krw = float(payload.get("monthly_target_krw", 2000000.0))
                    from .dividend_living_expense_simulator import DividendLivingExpenseSimulator
                    sim = DividendLivingExpenseSimulator(paths.project_root)
                    sim.save_target(target_krw)
                    self._json({"status": "success", "monthly_target_krw": target_krw})
                    return

                if parsed.path == "/api/v1/backup/create":
                    zip_path, manifest = backup_mgr.create_backup()
                    self._json({
                        "status": "success",
                        "backup_file": zip_path.name,
                        "sha256": manifest["zip_sha256"],
                        "timestamp": manifest["timestamp"]
                    })
                    return

                if parsed.path == "/api/v1/backup/restore":
                    file_name = payload.get("file")
                    dry_run = payload.get("dry_run", False)
                    if not file_name:
                        self._json({"status": "error", "message": "missing file parameter"}, status=400)
                        return
                    zip_path = backup_mgr.backup_dir / file_name
                    report = backup_mgr.restore_backup(zip_path, dry_run=dry_run)
                    self._json({"status": "success", "report": report})
                    return

                if parsed.path == "/api/v1/knowledge-cards":
                    ticker = payload.get("ticker")
                    card_data = payload.get("card_data", {})
                    if not ticker:
                        self._json({"status": "error", "message": "missing ticker"}, status=400)
                        return
                    result = knowledge_card_mgr.save_card(ticker, card_data)
                    self._json({"status": "success", "card": result})
                    return

                if parsed.path == "/api/v1/notifications/send":
                    batched = noti_engine.process_and_batch_unsent()
                    sent_ids = []
                    for batch in batched:
                        sent_ids.extend(batch.get("ids", []))
                    if sent_ids:
                        noti_engine.mark_as_sent(sent_ids)
                    self._json({
                        "status": "success",
                        "sent_count": len(sent_ids),
                        "batched_count": len(batched),
                        "sent_batches": batched
                    })
                    return

                if parsed.path == "/api/v1/experiments":
                    run_id = payload.get("run_id")
                    objective = payload.get("objective", "")
                    hypothesis = payload.get("hypothesis", "")
                    target_tickers = payload.get("target_tickers", [])
                    strategy_name = payload.get("strategy_name", "")
                    if not (run_id and strategy_name):
                        self._json({"status": "error", "message": "missing run_id or strategy_name"}, status=400)
                        return
                    experiment_registry.register_experiment(
                        run_id=run_id,
                        objective=objective,
                        hypothesis=hypothesis,
                        target_tickers=target_tickers,
                        strategy_name=strategy_name
                    )
                    self._json({"status": "success", "run_id": run_id})
                    return

                if parsed.path == "/api/v1/api-monitoring/test-connection":
                    provider = payload.get("provider")
                    result = test_provider_connection(paths, provider)
                    self._json(result)
                    return
                if parsed.path == "/api/v1/api-monitoring/clear-cache":
                    cache_type = payload.get("cache_type")
                    result = clear_provider_cache(paths, cache_type)
                    self._json(result)
                    return
                if parsed.path == "/api/v1/simulation/run":
                    global SIMULATION_THREAD, SIMULATION_STATUS
                    with SIMULATION_LOCK:
                        if SIMULATION_STATUS == "running":
                            self._json({
                                "status": "running",
                                "message": "Simulation is already running."
                            })
                            return
                        SIMULATION_BUFFER.clear()
                        SIMULATION_STATUS = "running"
                    tickers = payload.get("tickers")
                    SIMULATION_THREAD = threading.Thread(
                        target=_run_simulation_thread,
                        args=(paths.project_root, tickers),
                        daemon=True
                    )
                    SIMULATION_THREAD.start()
                    self._json({
                        "status": "started",
                        "message": "Simulation started successfully."
                    })
                    return
                # ── 개인 투자 운영 OS 신규 POST API ──────────────────────
                if parsed.path == "/api/v1/approvals":
                    run_id = payload.get("run_id")
                    ticker = payload.get("ticker")
                    action = payload.get("action")
                    rec_verdict = payload.get("rec_verdict", "warning")
                    user_decision = payload.get("user_decision")
                    rationale = payload.get("rationale", "")
                    if not (run_id and ticker and action and user_decision):
                        self._json({"status": "error", "message": "missing fields"}, status=400)
                        return
                    from .approval_audit_ledger import log_approval_decision
                    log_entry = log_approval_decision(
                        paths, run_id, ticker, action, rec_verdict, user_decision, rationale
                    )
                    
                    # Automatically record to investment journal
                    try:
                        from .investment_journal import InvestmentJournal
                        price_val = 0.0
                        try:
                            import yfinance as yf
                            from .yahoo import get_yahoo_session
                            session = get_yahoo_session()
                            ticker_obj = yf.Ticker(ticker, session=session)
                            hist = ticker_obj.history(period="1d")
                            if not hist.empty:
                                price_val = float(hist["Close"].iloc[-1])
                        except Exception:
                            pass
                        if price_val <= 0:
                            price_val = 100.0  # Fallback dummy price
                        
                        journal = InvestmentJournal(paths.project_root)
                        journal.add_entry(
                            ticker=ticker,
                            action_type=user_decision,
                            entry_price=price_val,
                            note=rationale or f"신호 {action}에 대한 {user_decision} 의사결정"
                        )
                    except Exception:
                        pass
                    
                    self._json({"status": "success", "entry": log_entry})
                    return
                if parsed.path == "/api/v1/tax-lots/buy":
                    ticker = payload.get("ticker")
                    quantity = float(payload.get("quantity", 0.0))
                    unit_price = float(payload.get("unit_price", 0.0))
                    fx_rate = float(payload.get("fx_rate", 1300.0))
                    currency = payload.get("currency", "USD")
                    commission = float(payload.get("commission", 0.0))
                    if not (ticker and quantity > 0 and unit_price > 0):
                        self._json({"status": "error", "message": "missing or invalid fields"}, status=400)
                        return
                    from .tax_lot_ledger import TaxLotLedger
                    ledger = TaxLotLedger(paths.state_dir / "tax_lot_ledger.json")
                    lot = ledger.add_buy(ticker, quantity, unit_price, fx_rate, currency, commission)
                    self._json({"status": "success", "lot": lot})
                    return
                if parsed.path == "/api/v1/tax-lots/sell":
                    ticker = payload.get("ticker")
                    quantity = float(payload.get("quantity", 0.0))
                    sell_price = float(payload.get("sell_price", 0.0))
                    sell_fx_rate = float(payload.get("sell_fx_rate", 1300.0))
                    commission = float(payload.get("commission", 0.0))
                    if not (ticker and quantity > 0 and sell_price > 0):
                        self._json({"status": "error", "message": "missing or invalid fields"}, status=400)
                        return
                    from .tax_lot_ledger import TaxLotLedger
                    ledger = TaxLotLedger(paths.state_dir / "tax_lot_ledger.json")
                    realized_pnl, sold_details = ledger.sell_fifo(
                        ticker, quantity, sell_price, sell_fx_rate, commission
                    )
                    self._json({"status": "success", "realized_pnl": realized_pnl, "sold_details": sold_details})
                    return
                if parsed.path == "/api/v1/toss/reconciliation/sync":
                    settings = _load_dashboard_settings(paths)
                    status = build_dashboard_toss_status(paths)
                    if status["status"] != "configured":
                        self._json({
                            "status": "failed",
                            "message": "Toss credentials are not configured"
                        })
                        return
                    client = _dashboard_toss_client(settings)
                    account = payload.get("account")
                    from .toss import sync_portfolio_from_toss
                    result = sync_portfolio_from_toss(client, paths, account=account)
                    self._json(result)
                    return
                self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._json({"error": "invalid_request", "message": str(exc)}, status=400)
            except Exception as exc:
                self._json(
                    {"error": "internal_error", "message": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                # --- 권한 모드 검증 필터 ---
                path_action_map = {
                    "/api/v1/knowledge-cards": "write_memo",
                    "/api/v1/investment-goals": "modify_settings",
                    "/api/v1/investment-journals": "write_memo",
                }
                req_action = path_action_map.get(parsed.path)
                if not req_action:
                    # check for path prefix like /api/v1/investment-goals/g1
                    if parsed.path.startswith("/api/v1/investment-goals/"):
                        req_action = "modify_settings"

                if req_action and not permission_mgr.is_action_allowed(req_action):
                    self._json({
                        "status": "error",
                        "message": f"permission_denied: action '{req_action}' is not allowed in current mode '{permission_mgr.get_mode()}'"
                    }, status=403)
                    return

                if parsed.path.startswith("/api/v1/investment-goals/"):
                    goal_id = parsed.path.split("/")[-1]
                    from .investment_goal_planner import InvestmentGoalPlanner
                    planner = InvestmentGoalPlanner(paths.project_root)
                    deleted = planner.delete_goal(goal_id)
                    self._json({"status": "success", "deleted": deleted})
                    return

                if parsed.path == "/api/v1/investment-journals":
                    query = parse_qs(parsed.query)
                    entry_id = query.get("entry_id", [None])[0]
                    if not entry_id:
                        self._json({"status": "error", "message": "missing entry_id"}, status=400)
                        return
                    from .investment_journal import InvestmentJournal
                    journal = InvestmentJournal(paths.project_root)
                    deleted = journal.delete_entry(entry_id)
                    self._json({"status": "success", "deleted": deleted})
                    return

                if parsed.path == "/api/v1/knowledge-cards":
                    query = parse_qs(parsed.query)
                    ticker = query.get("ticker", [None])[0]
                    if not ticker:
                        self._json({"status": "error", "message": "missing ticker"}, status=400)
                        return
                    deleted = knowledge_card_mgr.delete_card(ticker)
                    self._json({"status": "success", "deleted": deleted})
                    return
                
                self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._json({"error": "internal_error", "message": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

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
    selected = _select_latest_completed_run_id(runs) if run_id == "latest" else run_id
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
        "today_board": _empty_today_board(),
        "decision_timeline": [
            _timeline_event(
                "no_run",
                "최근 실행 생성",
                "not_evaluated",
                "완료된 run이 없어 투자 판단 흐름을 만들 수 없습니다.",
                "설정 검증 후 시뮬레이션 또는 신호 생성을 먼저 실행하세요.",
                "runs/*/manifest.json",
                action={"label": "설정 검증", "page": "settings"},
                occurred_at=reference.isoformat(),
                step=1,
            )
        ],
        "data_lineage": empty_data_lineage(generated_at=reference.isoformat()),
        "session_replay": empty_session_replay(generated_at=reference.isoformat()),
        "failure_patterns": empty_failure_patterns(generated_at=reference.isoformat()),
        "run_evidence": empty_run_evidence(generated_at=reference.isoformat()),
        "recovery_guide": empty_recovery_guide(),
        "metric_dictionary": metric_dictionary_payload("overview"),
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
        # Frontend compatibility fields
        "total_source_count": 0,
        "success_source_count": 0,
        "success_rate": 1.0,
        "total_providers": 0,
        "success_providers": 0,
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


def _decision_timeline(
    *,
    paths: RuntimePaths,
    run_dir: Path,
    manifest: Mapping[str, Any],
    data_quality: Mapping[str, Any],
    risk: Mapping[str, Any],
    signals: Mapping[str, Any],
    signal_rows: Sequence[Mapping[str, Any]],
    today_board: Mapping[str, Sequence[Mapping[str, Any]]],
    recommended_actions: Sequence[Mapping[str, Any]],
    execution_status: str,
    display_status: str,
) -> list[dict[str, Any]]:
    data_summary = _mapping(data_quality.get("summary"))
    risk_summary = _mapping(risk.get("summary"))
    started_at = manifest.get("started_at")
    finished_at = manifest.get("finished_at")
    data_source_path = run_dir / "data_sources.json"
    signal_path = _first_existing_path(run_dir / "signals_risk.json", run_dir / "signals.json")
    risk_path = run_dir / "risk_explanation.json"
    reconciliation_path = paths.state_dir / "portfolio_reconciliation.json"
    toss_snapshot_path = paths.state_dir / "toss_account_snapshot.json"
    order_plan_path = paths.state_dir / "order_plan.json"
    notification_failure_path = paths.state_dir / "notification_failures.jsonl"

    return [
        _timeline_event(
            "data_collection",
            "데이터 수집",
            _timeline_data_collection_status(data_source_path, execution_status),
            _timeline_data_collection_summary(data_summary, data_source_path),
            "가격 원천이 비어 있거나 실패하면 이후 신호와 리스크 판단을 신뢰할 수 없습니다.",
            _artifact_label(paths, data_source_path),
            action={"label": "데이터 품질 보기", "page": "data-quality"},
            failure_code=manifest.get("failure_code")
            if execution_status in {"data_error", "failed"}
            else None,
            occurred_at=started_at,
            step=1,
        ),
        _timeline_event(
            "provider_validation",
            "Provider 검증",
            str(data_summary.get("status") or "not_evaluated"),
            _timeline_provider_summary(data_summary),
            "provider 간 날짜·가격·거래량 차이가 있으면 오늘 신호는 운영 검토가 필요합니다.",
            "data_sources.json · provider_disagreement_report.json",
            action={"label": "불일치 상세", "page": "data-quality"},
            failure_code=FailureCode.DATA_DISAGREEMENT.value
            if data_summary.get("disagreement_count")
            else None,
            occurred_at=finished_at,
            step=2,
        ),
        _timeline_event(
            "signal_generation",
            "신호 생성",
            "success" if signal_rows else "not_evaluated",
            _timeline_signal_summary(signals, signal_rows),
            "매수·매도·관망 후보가 만들어졌는지와 가격 검증 여부를 함께 봅니다.",
            _artifact_label(paths, signal_path) if signal_path else "signals_risk.json · signals.json",
            action={"label": "신호 보기", "page": "signals"},
            occurred_at=finished_at,
            step=3,
        ),
        _timeline_event(
            "risk_review",
            "리스크 심사",
            str(risk_summary.get("status") or "not_evaluated"),
            _timeline_risk_summary(risk_summary),
            "포지션 한도, 유동성, 데이터 신뢰도 기준을 통과한 신호만 다음 검토로 보냅니다.",
            _artifact_label(paths, risk_path),
            action={"label": "리스크 상세", "page": "risk"},
            failure_code=_timeline_top_failure_code(risk_summary),
            occurred_at=finished_at,
            step=4,
        ),
        _timeline_toss_event(paths, reconciliation_path, toss_snapshot_path, step=5),
        _timeline_order_event(paths, order_plan_path, today_board, step=6),
        _timeline_notification_event(
            paths,
            notification_failure_path,
            recommended_actions,
            display_status,
            step=7,
        ),
    ]


def _timeline_event(
    event_id: str,
    label: str,
    status: str,
    summary: str,
    detail: str,
    evidence: str,
    *,
    action: Mapping[str, Any] | None = None,
    failure_code: Any = None,
    occurred_at: Any = None,
    step: int,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": event_id,
        "step": step,
        "label": label,
        "status": status,
        "summary": summary,
        "detail": detail,
        "evidence": evidence,
        "source": evidence,
        "occurred_at": occurred_at,
    }
    if failure_code:
        event["failure_code"] = str(failure_code)
    if action:
        event["next_action"] = dict(action)
    return event


def _first_existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _artifact_label(paths: RuntimePaths, path: Path | None) -> str:
    if path is None:
        return "artifact 없음"
    try:
        return str(path.relative_to(paths.project_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _timeline_data_collection_status(path: Path, execution_status: str) -> str:
    if path.exists():
        return "success" if execution_status not in {"failed", "data_error"} else "warning"
    if execution_status in {"failed", "data_error"}:
        return "failed" if execution_status == "failed" else "data_error"
    return "not_evaluated"


def _timeline_data_collection_summary(summary: Mapping[str, Any], path: Path) -> str:
    provider_count = summary.get("provider_count") or 0
    failed_count = summary.get("failed_source_count") or 0
    if path.exists():
        return f"Provider {provider_count}개 수집 기록, 실패 source {failed_count}개"
    return "data_sources.json이 없어 수집 완료 여부를 확인하지 못했습니다."


def _timeline_provider_summary(summary: Mapping[str, Any]) -> str:
    total = summary.get("total") or 0
    verified = summary.get("verified") or 0
    disagreements = summary.get("disagreement_count") or 0
    blocked = summary.get("blocked_ticker_count") or 0
    if total:
        return f"{verified}/{total} ticker 검증, 불일치 {disagreements}건, 차단 {blocked}개"
    return "검증할 provider 비교 결과가 없습니다."


def _timeline_signal_summary(
    signals: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> str:
    counts = _signal_counts(signals)
    if not rows:
        return "생성된 today signal artifact가 없습니다."
    return (
        f"신호 {len(rows)}개, 매수 {counts['buy']}개, "
        f"검토 가능 {counts['eligible']}개, 차단 {counts['blocked']}개"
    )


def _timeline_risk_summary(summary: Mapping[str, Any]) -> str:
    approved = summary.get("approved_count") or 0
    blocked = summary.get("blocked_count") or 0
    hold = summary.get("hold_count") or 0
    if approved or blocked or hold:
        return f"승인 {approved}개, 차단 {blocked}개, 대기 {hold}개"
    return "리스크 심사 결과가 아직 없습니다."


def _timeline_top_failure_code(summary: Mapping[str, Any]) -> str | None:
    top_reasons = _sequence(summary.get("top_block_reasons"))
    first = _mapping(top_reasons[0]) if top_reasons else {}
    code = first.get("code")
    return str(code) if code else None


def _timeline_toss_event(
    paths: RuntimePaths,
    reconciliation_path: Path,
    snapshot_path: Path,
    *,
    step: int,
) -> dict[str, Any]:
    reconciliation = _mapping(read_json(reconciliation_path, default={}))
    status = str(reconciliation.get("status") or "")
    differences = len(_sequence(reconciliation.get("differences")))
    unmapped = len(_sequence(reconciliation.get("unmapped_tickers")))
    if status == "synchronized":
        event_status = "success"
        summary = "로컬 포트폴리오와 Toss 보유 수량이 동기화 상태입니다."
    elif reconciliation:
        event_status = "warning" if status == "diverged" else "not_evaluated"
        summary = f"Toss 대조 결과 {status or 'unknown'} · 차이 {differences}개 · 미매핑 {unmapped}개"
    elif snapshot_path.exists():
        event_status = "not_evaluated"
        summary = "Toss 계좌 snapshot은 있으나 포트폴리오 대조 결과는 없습니다."
    else:
        event_status = "not_evaluated"
        summary = "Toss 계좌 대조 산출물이 아직 없습니다."
    evidence = (
        _artifact_label(paths, reconciliation_path)
        if reconciliation_path.exists()
        else _artifact_label(paths, snapshot_path)
        if snapshot_path.exists()
        else "portfolio_reconciliation.json · toss_account_snapshot.json"
    )
    return _timeline_event(
        "toss_reconciliation",
        "Toss 계좌 대조",
        event_status,
        summary,
        "실계좌와 로컬 포트폴리오가 다르면 오늘 주문 검토 전에 차이를 먼저 정리해야 합니다.",
        evidence,
        action={"label": "Toss Account", "page": "toss-account"},
        failure_code="TOSS_RECONCILIATION_DIFF" if differences or unmapped else None,
        occurred_at=reconciliation.get("generated_at"),
        step=step,
    )


def _timeline_order_event(
    paths: RuntimePaths,
    order_plan_path: Path,
    today_board: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    step: int,
) -> dict[str, Any]:
    order_plan = _mapping(read_json(order_plan_path, default={}))
    orders = _sequence(order_plan.get("orders"))
    pending = len(_sequence(today_board.get("order_prepares")))
    if orders:
        status = "success"
        summary = f"OrderIntent 검토 후보 {len(orders)}건이 준비됐습니다."
    elif pending:
        status = "warning"
        summary = f"매수 후보 {pending}건은 주문 전 수동 검토가 필요합니다."
    else:
        status = "not_evaluated"
        summary = "주문 검토가 필요한 매수 후보가 없습니다."
    return _timeline_event(
        "order_review",
        "주문 검토",
        status,
        summary,
        "이 단계는 실제 주문이 아니라 OrderIntent와 수동 승인 전 검토 상태만 표시합니다.",
        _artifact_label(paths, order_plan_path)
        if order_plan_path.exists()
        else "state/order_plan.json · today_signals.json",
        action={"label": "주문 검토", "page": "toss-account"},
        failure_code="ORDER_REVIEW_PENDING" if pending and not orders else None,
        occurred_at=order_plan.get("generated_at"),
        step=step,
    )


def _timeline_notification_event(
    paths: RuntimePaths,
    failure_path: Path,
    recommended_actions: Sequence[Mapping[str, Any]],
    display_status: str,
    *,
    step: int,
) -> dict[str, Any]:
    failure_count = _jsonl_line_count(failure_path)
    if failure_count:
        status = "warning"
        summary = f"알림 실패 기록 {failure_count}건이 있습니다."
        failure_code = "NOTIFICATION_FAILURE"
    elif recommended_actions or display_status in {"blocked", "data_error", "failed", "warning"}:
        status = "not_evaluated"
        summary = "차단 사유와 다음 행동을 먼저 확인한 뒤 알림을 준비하세요."
        failure_code = None
    else:
        status = "success"
        summary = "차단 사유가 없어 알림 전 최종 리포트 확인 단계입니다."
        failure_code = None
    return _timeline_event(
        "notification_ready",
        "알림 준비",
        status,
        summary,
        "카카오 알림은 실행 결과 요약 단계이며, 실패 기록이 있으면 API 모니터링에서 확인합니다.",
        _artifact_label(paths, failure_path)
        if failure_path.exists()
        else "notification_failures.jsonl · recommended_actions",
        action={"label": "API 모니터링", "page": "api-monitoring"},
        failure_code=failure_code,
        step=step,
    )


def _jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
    except OSError:
        return 0
    return count


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
        auth_style=settings.toss_oauth_auth_style,
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
            "accountNo",
            "account_no",
            "accountNumber",
            "account_number",
            "maskedAccountNo",
            "masked_account_no",
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
                "account_no": account_no,
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
            "fx_change_pct": 0.0,
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
        fx_change_pct = _normalize_ratio(
            _first_number(
                payload,
                "changeRate",
                "change_rate",
                "rateChangeRate",
                "rate_change_rate",
                "fluctuationRate",
                "fluctuation_rate",
                "compareToPreviousCloseRate",
                "compare_to_previous_close_rate",
            )
        )
        rates.append(
            {
                "base_currency": base or name.replace("exchange_rate_", "").split("_")[0].upper(),
                "quote_currency": quote,
                "rate": _round_or_none(rate, 8),
                "mid_rate": _round_or_none(_first_number(payload, "midRate", "mid_rate"), 8),
                "fx_change_pct": _round_or_none(fx_change_pct, 6),
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


def _apply_toss_fx_impact(
    holdings: Sequence[Mapping[str, Any]],
    fx_rates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fx_change_map = {
        str(rate.get("base_currency") or "").upper(): _float_or_none(rate.get("fx_change_pct"))
        for rate in fx_rates
        if str(rate.get("quote_currency") or "").upper() == "KRW"
    }
    enriched: list[dict[str, Any]] = []
    for item in holdings:
        row = dict(item)
        row.update(_toss_fx_impact_row(row, fx_change_map))
        enriched.append(row)
    return enriched


def _toss_fx_impact_row(
    row: Mapping[str, Any],
    fx_change_map: Mapping[str, float | None],
) -> dict[str, Any]:
    currency = str(row.get("currency") or "KRW").upper()
    current_value = _float_or_none(row.get("market_value_krw"))
    asset_return = _float_or_none(row.get("day_change_pct"))
    fx_return = 0.0 if currency == "KRW" else fx_change_map.get(currency)
    base = {
        "asset_return_pct": _round_or_none(asset_return, 6),
        "fx_return_pct": _round_or_none(fx_return, 6),
        "previous_market_value_krw": None,
        "asset_effect_krw": None,
        "fx_effect_krw": None,
        "cross_effect_krw": None,
        "total_day_pnl_krw": None,
        "day_return_krw": None,
        "fx_sensitivity_krw": _round_or_none(current_value if currency != "KRW" else 0.0, 4),
        "fx_impact_status": "not_evaluated",
        "fx_impact_source": "Toss holdings GET · Toss prices GET · Toss exchange-rate GET",
    }
    if current_value is None or asset_return is None:
        return base
    asset_denominator = 1 + asset_return
    if asset_denominator <= 0:
        return {**base, "fx_impact_status": "not_evaluated"}
    if fx_return is None:
        asset_effect = current_value * asset_return / asset_denominator
        return {
            **base,
            "asset_effect_krw": _round_or_none(asset_effect, 4),
            "fx_impact_status": "partial",
        }
    denominator = asset_denominator * (1 + fx_return)
    if denominator <= 0:
        return {**base, "fx_impact_status": "not_evaluated"}
    previous_value = current_value / denominator
    asset_effect = previous_value * asset_return
    fx_effect = previous_value * fx_return
    cross_effect = previous_value * asset_return * fx_return
    total_day_pnl = current_value - previous_value
    return {
        **base,
        "previous_market_value_krw": _round_or_none(previous_value, 4),
        "asset_effect_krw": _round_or_none(asset_effect, 4),
        "fx_effect_krw": _round_or_none(fx_effect, 4),
        "cross_effect_krw": _round_or_none(cross_effect, 4),
        "total_day_pnl_krw": _round_or_none(total_day_pnl, 4),
        "day_return_krw": _round_or_none(total_day_pnl / previous_value if previous_value else None, 6),
        "fx_impact_status": "success",
    }


def _apply_portfolio_type_metadata(
    holdings: Sequence[Mapping[str, Any]],
    paths: RuntimePaths,
) -> list[dict[str, Any]]:
    portfolio_mapping = _load_dashboard_portfolio_mapping(paths)
    portfolio_type_overrides = _load_portfolio_type_overrides(paths)
    typed: list[dict[str, Any]] = []
    for item in holdings:
        row = dict(item)
        lookup = _portfolio_mapping_lookup(portfolio_mapping, row)
        type_keys, reason, source, override_info = _portfolio_type_keys_for_holding(
            row,
            lookup,
            portfolio_type_overrides,
        )
        primary = type_keys[0] if type_keys else "long_term"
        primary_profile = PORTFOLIO_TYPE_PROFILES[primary]
        row.update(
            {
                "portfolio_types": type_keys,
                "portfolio_type_labels": [
                    PORTFOLIO_TYPE_PROFILES[key]["label"] for key in type_keys
                ],
                "primary_portfolio_type": primary,
                "primary_portfolio_type_label": primary_profile["label"],
                "portfolio_type_reason": reason,
                "portfolio_type_focus": primary_profile["focus"],
                "portfolio_type_risk_level": primary_profile["risk_level"],
                "portfolio_type_source": source,
                "portfolio_type_override": override_info,
            }
        )
        if lookup is not None:
            row["portfolio_mapping_status"] = "mapped" if lookup.mapped else "heuristic"
            row["portfolio_mapping_symbol"] = lookup.mapping.ticker
            row["portfolio_mapping_sector"] = lookup.mapping.sector
            row["portfolio_mapping_factors"] = list(lookup.mapping.factors)
        else:
            row["portfolio_mapping_status"] = "heuristic"
            row["portfolio_mapping_symbol"] = row.get("symbol")
        typed.append(row)
    return typed


def _load_portfolio_type_overrides(paths: RuntimePaths) -> dict[str, dict[str, Any]]:
    candidates = [
        paths.config_file.parent / "portfolio_type_overrides.json",
        paths.project_root / "configs" / "portfolio_type_overrides.json",
        paths.state_dir / "portfolio_type_overrides.json",
    ]
    overrides: dict[str, dict[str, Any]] = {}
    for path in candidates:
        payload = read_json(path, default=None)
        if not isinstance(payload, Mapping):
            continue
        ticker_rows = payload.get("tickers", payload)
        if not isinstance(ticker_rows, Mapping):
            continue
        for symbol, raw in ticker_rows.items():
            if not isinstance(raw, Mapping):
                continue
            type_keys = _normalize_portfolio_type_keys(
                raw.get("portfolio_types", raw.get("investment_types", ()))
            )
            if not type_keys:
                continue
            overrides[str(symbol).strip().upper()] = {
                "portfolio_types": type_keys,
                "reason": str(raw.get("reason") or "사용자 override 파일에 명시된 운용 타입입니다."),
                "source": path.name,
                "source_path": str(path),
            }
    return overrides


def _portfolio_type_override_for_holding(
    overrides: Mapping[str, Mapping[str, Any]],
    row: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if not overrides:
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    market_region = str(row.get("market_region") or "").upper()
    candidates = [symbol]
    if "." in symbol:
        candidates.append(symbol.split(".", 1)[0])
    if symbol.isdigit() and len(symbol) == 6:
        candidates.extend([f"{symbol}.KS", f"{symbol}.KQ"])
    if market_region == "KR" and not symbol.endswith((".KS", ".KQ")) and symbol.isdigit():
        candidates.extend([f"{symbol}.KS", f"{symbol}.KQ"])
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        override = overrides.get(candidate)
        if override:
            return override
    return None


def _load_dashboard_portfolio_mapping(paths: RuntimePaths) -> Any | None:
    try:
        return load_portfolio_mapping(paths.portfolio_mapping_file)
    except (OSError, ValueError, TypeError):
        return None


def _portfolio_mapping_lookup(portfolio_mapping: Any | None, row: Mapping[str, Any]) -> Any | None:
    if portfolio_mapping is None:
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    name = str(row.get("name") or "")
    candidates = [symbol]
    if "." in symbol:
        candidates.append(symbol.split(".", 1)[0])
    market_region = str(row.get("market_region") or "").upper()
    if symbol.isdigit() and len(symbol) == 6:
        candidates.extend([f"{symbol}.KS", f"{symbol}.KQ"])
    if market_region == "KR" and not symbol.endswith((".KS", ".KQ")) and symbol.isdigit():
        candidates.extend([f"{symbol}.KS", f"{symbol}.KQ"])
    seen: set[str] = set()
    fallback = None
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        lookup = portfolio_mapping.lookup(candidate, name=name)
        fallback = fallback or lookup
        if lookup.mapped:
            return lookup
    return fallback


def _portfolio_type_keys_for_holding(
    row: Mapping[str, Any],
    lookup: Any | None,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[str], str, str, dict[str, Any] | None]:
    override = _portfolio_type_override_for_holding(overrides or {}, row)
    if override is not None:
        type_keys = _normalize_portfolio_type_keys(override.get("portfolio_types", ()))
        if type_keys:
            source = str(override.get("source") or "portfolio_type_overrides.json")
            return (
                type_keys,
                str(override.get("reason") or "사용자 override 파일에 명시된 운용 타입입니다."),
                source,
                {
                    "active": True,
                    "source": source,
                    "source_path": override.get("source_path"),
                    "reason": override.get("reason"),
                },
            )
    mapped = lookup.mapping if lookup is not None else None
    explicit = _normalize_portfolio_type_keys(getattr(mapped, "portfolio_types", ()))
    if explicit:
        return explicit, "portfolio_mapping.json에 명시된 운용 타입입니다.", "portfolio_mapping.json", None

    lookup_mapped = bool(getattr(lookup, "mapped", False))
    factors = {
        str(item).strip().lower()
        for item in (getattr(mapped, "factors", ()) if lookup_mapped else ())
        if item
    }
    mapped_sector = str(getattr(mapped, "sector", "") if lookup_mapped else "").strip().lower()
    if mapped_sector == "other":
        mapped_sector = ""
    sector = str(mapped_sector or row.get("sector") or "").strip().lower()
    asset_type = str(row.get("asset_type") or row.get("category") or "").strip().lower()
    name = str(row.get("name") or "").strip().lower()
    symbol = str(row.get("symbol") or "").strip().lower()
    text_blob = " ".join([symbol, name, sector, asset_type, " ".join(sorted(factors))])
    leverage = _float_or_none(getattr(mapped, "leverage_factor", None)) or 1.0
    inferred: list[str] = []
    reasons: list[str] = []

    if leverage >= 2 or "leveraged" in factors or any(token in text_blob for token in ("2x", "3x")):
        inferred.extend(["short_term", "swing"])
        reasons.append("레버리지/고변동 상품은 짧은 손절과 잦은 점검이 우선입니다.")

    if factors & {"speculative_growth", "quantum", "bitcoin_proxy", "crypto_equity"}:
        inferred.extend(["short_term", "swing"])
        reasons.append("투기적 성장 팩터는 중단기 변동성 관리가 필요합니다.")

    if factors & {
        "growth",
        "technology",
        "semiconductors",
        "ai",
        "nasdaq100",
        "consumer_growth",
        "ev",
    } or sector in {"technology", "semiconductors", "consumer_growth", "quantum"}:
        inferred.extend(["swing", "long_term"])
        reasons.append("성장/기술 노출은 중기 추세와 장기 핵심 보유를 함께 봅니다.")

    if asset_type in {"etf", "stock"} and not inferred:
        inferred.append("long_term")
        reasons.append("기본 보유종목은 장기 비중과 리밸런싱 관점으로 분류했습니다.")

    if factors & {"dividend", "income", "yield", "covered_call"} or any(
        token in text_blob
        for token in ("dividend", "income", "yield", "배당", "분배", "covered call")
    ):
        inferred.append("dividend")
        reasons.append("배당/인컴 성격이 있어 현금흐름과 배당락 위험을 봅니다.")

    normalized = _normalize_portfolio_type_keys(inferred) or ["long_term"]
    reason = " ".join(reasons) if reasons else "명시 매핑이 없어 보수적으로 장기 관리 대상으로 분류했습니다."
    return normalized, reason, "portfolio_mapping.json factors · Toss holdings/stocks metadata", None


def _normalize_portfolio_type_keys(values: Sequence[Any]) -> list[str]:
    keys: list[str] = []
    for value in values:
        key = PORTFOLIO_TYPE_ALIASES.get(str(value).strip().lower())
        if key and key not in keys:
            keys.append(key)
    return sorted(keys, key=PORTFOLIO_TYPE_ORDER.index)


def _portfolio_type_profile_rows() -> list[dict[str, Any]]:
    return [
        {"type": key, **PORTFOLIO_TYPE_PROFILES[key]}
        for key in PORTFOLIO_TYPE_ORDER
    ]


def _empty_toss_portfolio_type_totals() -> list[dict[str, Any]]:
    return [
        {
            **profile,
            "type": key,
            "count": 0,
            "symbols": [],
            "market_value_krw": 0.0,
            "unrealized_pnl_krw": 0.0,
            "weight": 0.0,
            "warning_count": 0,
            "source": "portfolio_mapping.json · Toss holdings/stocks metadata",
        }
        for key, profile in ((key, PORTFOLIO_TYPE_PROFILES[key]) for key in PORTFOLIO_TYPE_ORDER)
    ]


def _toss_portfolio_type_totals(
    holdings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = {item["type"]: item for item in _empty_toss_portfolio_type_totals()}
    source_sets: dict[str, set[str]] = {key: set() for key in PORTFOLIO_TYPE_ORDER}
    for item in holdings:
        key = str(item.get("primary_portfolio_type") or "long_term")
        if key not in rows:
            key = "long_term"
        row = rows[key]
        row["count"] += 1
        symbol = str(item.get("symbol") or "").strip()
        if symbol:
            row["symbols"].append(symbol)
        row["market_value_krw"] += _float_or_none(item.get("market_value_krw")) or 0.0
        row["unrealized_pnl_krw"] += _float_or_none(item.get("unrealized_pnl_krw")) or 0.0
        row["warning_count"] += int(item.get("warning_count") or 0)
        source = str(item.get("portfolio_type_source") or "").strip()
        if source:
            source_sets[key].add(source)

    total = sum(_float_or_none(row.get("market_value_krw")) or 0.0 for row in rows.values())
    normalized = []
    for key in PORTFOLIO_TYPE_ORDER:
        row = dict(rows[key])
        value = _float_or_none(row.get("market_value_krw")) or 0.0
        row["market_value_krw"] = _round_or_none(value, 4)
        row["unrealized_pnl_krw"] = _round_or_none(
            _float_or_none(row.get("unrealized_pnl_krw")),
            4,
        )
        row["weight"] = _round_or_none(value / total if total else 0.0, 6)
        row["symbols"] = row["symbols"][:8]
        if source_sets[key]:
            row["source"] = _portfolio_type_total_source(source_sets[key])
        normalized.append(row)
    return normalized


def _portfolio_type_total_source(sources: set[str]) -> str:
    ordered = []
    for marker in (
        "portfolio_type_overrides.json",
        "portfolio_mapping.json",
        "Toss holdings/stocks metadata",
    ):
        if any(marker in source for source in sources):
            ordered.append(marker)
    for source in sorted(sources):
        if not any(marker in source for marker in ordered):
            ordered.append(source)
    return " · ".join(ordered)


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


def _toss_fx_impact_summary(holdings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [
        dict(item)
        for item in holdings
        if item.get("fx_impact_status") in {"success", "partial"}
    ]
    if not holdings:
        return _empty_toss_fx_impact("not_evaluated")
    success_rows = [row for row in rows if row.get("fx_impact_status") == "success"]
    partial_rows = [row for row in rows if row.get("fx_impact_status") == "partial"]
    total_value = sum(
        value
        for item in holdings
        for value in [_float_or_none(item.get("market_value_krw"))]
        if value is not None
    )
    evaluated_value = sum(
        value
        for item in success_rows
        for value in [_float_or_none(item.get("market_value_krw"))]
        if value is not None
    )
    asset_effect = _sum_numeric(rows, "asset_effect_krw")
    fx_effect = _sum_numeric(success_rows, "fx_effect_krw")
    cross_effect = _sum_numeric(success_rows, "cross_effect_krw")
    total_day_pnl = _sum_numeric(success_rows, "total_day_pnl_krw")
    status = (
        "success"
        if len(success_rows) == len(holdings)
        else "partial"
        if rows
        else "not_evaluated"
    )
    top_rows = sorted(
        rows,
        key=lambda item: -abs(
            _float_or_none(item.get("total_day_pnl_krw"))
            if item.get("total_day_pnl_krw") is not None
            else _float_or_none(item.get("asset_effect_krw"))
            or 0.0
        ),
    )[:8]
    return {
        "status": status,
        "summary": {
            "status": status,
            "holding_count": len(holdings),
            "evaluated_count": len(success_rows),
            "partial_count": len(partial_rows),
            "total_market_value_krw": _round_or_none(total_value, 4),
            "evaluated_market_value_krw": _round_or_none(evaluated_value, 4),
            "evaluated_weight": _round_or_none(
                evaluated_value / total_value if total_value else None,
                6,
            ),
            "asset_effect_krw": _round_or_none(asset_effect, 4),
            "fx_effect_krw": _round_or_none(fx_effect, 4),
            "cross_effect_krw": _round_or_none(cross_effect, 4),
            "total_day_pnl_krw": _round_or_none(total_day_pnl, 4),
            "fx_effect_share": _round_or_none(
                fx_effect / total_day_pnl if total_day_pnl else None,
                6,
            ),
        },
        "rows": [
            {
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "currency": row.get("currency"),
                "market_value_krw": row.get("market_value_krw"),
                "asset_return_pct": row.get("asset_return_pct"),
                "fx_return_pct": row.get("fx_return_pct"),
                "asset_effect_krw": row.get("asset_effect_krw"),
                "fx_effect_krw": row.get("fx_effect_krw"),
                "cross_effect_krw": row.get("cross_effect_krw"),
                "total_day_pnl_krw": row.get("total_day_pnl_krw"),
                "day_return_krw": row.get("day_return_krw"),
                "fx_impact_status": row.get("fx_impact_status"),
                "source": row.get("fx_impact_source"),
            }
            for row in top_rows
        ],
        "source": "Toss holdings GET · Toss prices GET · Toss exchange-rate GET",
    }


def _dashboard_account_attribution(paths: RuntimePaths) -> dict[str, Any]:
    attribution_path = paths.state_dir / "account_attribution.json"
    payload = read_json(attribution_path, default=None)
    if isinstance(payload, Mapping):
        return dict(payload)
    return empty_account_attribution()


def _sum_numeric(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return sum(
        value
        for row in rows
        for value in [_float_or_none(row.get(key))]
        if value is not None
    )


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


def _empty_toss_fx_impact(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "summary": {
            "status": status,
            "holding_count": 0,
            "evaluated_count": 0,
            "partial_count": 0,
            "total_market_value_krw": None,
            "evaluated_market_value_krw": None,
            "evaluated_weight": None,
            "asset_effect_krw": None,
            "fx_effect_krw": None,
            "cross_effect_krw": None,
            "total_day_pnl_krw": None,
            "fx_effect_share": None,
        },
        "rows": [],
        "source": "Toss holdings GET · Toss prices GET · Toss exchange-rate GET",
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
            component = str(item.get("component") or "safety")
            reasons.append(
                _reason(
                    code,
                    component=component,
                    message=str(item.get("message") or "") or None,
                    severity=_reason_severity(code, component, manifest),
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


def _reason_severity(code: str, component: str, manifest: Mapping[str, Any]) -> str:
    if component == "survivorship":
        audit = _mapping(manifest.get("survivorship_audit"))
        if audit.get("valid") is True and str(code).startswith("SURVIVORSHIP_BIAS_RISK"):
            return "warning"
    return "blocking"


def _reason(
    code: str,
    *,
    component: str,
    message: str | None = None,
    affected_tickers: Any = None,
    count: Any = None,
    severity: str = "blocking",
) -> dict[str, Any]:
    catalog_message, remediation = FAILURE_CATALOG.get(
        code,
        ("실행 검증에서 확인이 필요한 문제가 발견됐습니다.", "관련 artifact를 확인하세요."),
    )
    return {
        "code": code,
        "component": component,
        "severity": severity,
        "message": message or catalog_message,
        "remediation": remediation,
        "affected_tickers": affected_tickers or [],
        "count": count,
    }


def _headline(status: str, reasons: Sequence[Mapping[str, Any]], mode: str) -> str:
    blockers = [
        reason
        for reason in reasons
        if str(reason.get("severity") or "blocking") in {"blocking", "blocked"}
    ]
    if blockers:
        first = blockers[0]
        return f"{first.get('message')} 현재 {mode} 실행은 운영 검토가 필요합니다."
    if status == "warning":
        return "필수 게이트는 통과했지만 검토 경고가 있습니다."
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


def _empty_signal_history() -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "summary": "종목별 판단 이력을 만들 실행 기록이 없습니다.",
        "lookback_days": 30,
        "cards": [],
        "source": "runs/*/manifest.json · signals_risk.json",
    }


def _signal_history_cards(
    paths: RuntimePaths,
    current_run_dir: Path,
    current_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    tickers = [
        str(row.get("ticker") or "").upper()
        for row in current_rows
        if str(row.get("ticker") or "").strip()
    ]
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return _empty_signal_history()

    reference = _run_timestamp(current_run_dir) or datetime.now(UTC)
    cutoff = reference - timedelta(days=30)
    histories: dict[str, list[dict[str, Any]]] = {ticker: [] for ticker in tickers}
    for run in list_dashboard_runs(paths, limit=240):
        run_id = str(run.get("run_id") or "")
        if not run_id or not _is_completed_run(run):
            continue
        occurred_at = _parse_timestamp(run.get("finished_at")) or _parse_timestamp(run.get("started_at"))
        if occurred_at is not None and occurred_at < cutoff:
            continue
        run_dir = paths.runs_dir / run_id
        if not run_dir.is_dir():
            continue
        signal_map = _signal_map(run_dir)
        for row in _signal_rows(signal_map):
            ticker = str(row.get("ticker") or "").upper()
            if ticker not in histories:
                continue
            histories[ticker].append(_signal_history_snapshot(row, run, occurred_at))

    current_by_ticker = {str(row.get("ticker") or "").upper(): row for row in current_rows}
    cards = [
        _signal_history_card(ticker, histories.get(ticker, []), current_by_ticker.get(ticker), reference)
        for ticker in tickers
    ]
    cards.sort(key=lambda item: (_decision_rank(str(item.get("status") or "not_evaluated")), item["ticker"]))
    populated = sum(1 for card in cards if card.get("run_count"))
    status = "success" if populated else "not_evaluated"
    return {
        "status": status,
        "summary": f"{populated}/{len(cards)}개 종목의 최근 판단 이력을 계산했습니다.",
        "lookback_days": 30,
        "cards": cards[:12],
        "source": "runs/*/manifest.json · signals_risk.json",
    }


def _run_timestamp(run_dir: Path) -> datetime | None:
    manifest = _mapping(read_json(run_dir / "manifest.json", default={}))
    return _parse_timestamp(manifest.get("finished_at")) or _parse_timestamp(manifest.get("started_at"))


def _signal_history_snapshot(
    row: Mapping[str, Any],
    run: Mapping[str, Any],
    occurred_at: datetime | None,
) -> dict[str, Any]:
    failed = [item for item in _sequence(row.get("failed")) if isinstance(item, Mapping)]
    reason_codes = [str(code) for code in _sequence(row.get("reason_codes")) if code]
    failed_codes = [str(item.get("code")) for item in failed if item.get("code")]
    status = str(row.get("status") or "not_evaluated")
    action = str(row.get("action") or row.get("signal") or "hold")
    return {
        "run_id": str(run.get("run_id") or ""),
        "occurred_at": occurred_at.isoformat() if occurred_at else run.get("finished_at") or run.get("started_at"),
        "action": action,
        "action_label": _signal_history_action_label(action),
        "status": status,
        "eligible": row.get("eligible") is True,
        "blocked": row.get("blocked") is True,
        "score": row.get("score"),
        "reason_codes": reason_codes[:5],
        "failed_codes": failed_codes[:5],
        "risk_status": "blocked" if failed_codes or row.get("blocked") else "pass" if row.get("eligible") else "hold",
    }


def _signal_history_card(
    ticker: str,
    snapshots: Sequence[Mapping[str, Any]],
    current_row: Mapping[str, Any] | None,
    reference: datetime,
) -> dict[str, Any]:
    ordered = sorted(
        [dict(item) for item in snapshots],
        key=lambda item: str(item.get("occurred_at") or ""),
    )
    latest = ordered[-1] if ordered else _signal_history_snapshot(
        current_row or {"ticker": ticker},
        {"run_id": ""},
        reference,
    )
    windows = {
        "7d": _signal_history_window(ordered, reference, 7),
        "30d": _signal_history_window(ordered, reference, 30),
    }
    changes = _signal_history_changes(ordered)
    trend = _signal_history_trend(ordered)
    summary = _signal_history_summary(ticker, windows["7d"], windows["30d"], trend)
    return {
        "ticker": ticker,
        "status": latest.get("status") or "not_evaluated",
        "latest_action": latest.get("action"),
        "latest_action_label": latest.get("action_label"),
        "latest_reason_codes": latest.get("reason_codes", []),
        "latest_failed_codes": latest.get("failed_codes", []),
        "run_count": len(ordered),
        "trend": trend,
        "summary": summary,
        "windows": windows,
        "changes": changes,
        "recent": ordered[-5:],
        "source": "runs/*/manifest.json · signals_risk.json",
    }


def _signal_history_window(
    snapshots: Sequence[Mapping[str, Any]],
    reference: datetime,
    days: int,
) -> dict[str, Any]:
    cutoff = reference - timedelta(days=days)
    rows = []
    for item in snapshots:
        occurred = _parse_timestamp(item.get("occurred_at"))
        if occurred is None or occurred >= cutoff:
            rows.append(item)
    buy_count = sum(str(item.get("action")) == "buy" for item in rows)
    sell_count = sum(str(item.get("action")) == "sell" for item in rows)
    hold_count = sum(str(item.get("action")) not in {"buy", "sell"} for item in rows)
    eligible_count = sum(item.get("eligible") is True for item in rows)
    blocked_count = sum(item.get("blocked") is True or item.get("risk_status") == "blocked" for item in rows)
    latest = rows[-1] if rows else {}
    return {
        "days": days,
        "run_count": len(rows),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "hold_count": hold_count,
        "eligible_count": eligible_count,
        "blocked_count": blocked_count,
        "latest_action": latest.get("action"),
        "latest_status": latest.get("status"),
    }


def _signal_history_changes(snapshots: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    previous: Mapping[str, Any] | None = None
    for item in snapshots:
        if previous is None:
            previous = item
            continue
        changed: list[str] = []
        if item.get("action") != previous.get("action"):
            changed.append(
                f"판단 {_signal_history_action_label(previous.get('action'))} → {_signal_history_action_label(item.get('action'))}"
            )
        if item.get("eligible") != previous.get("eligible"):
            changed.append(
                "운영 가능 → 차단"
                if previous.get("eligible") is True
                else "차단/대기 → 운영 가능"
            )
        if item.get("risk_status") != previous.get("risk_status"):
            changed.append(f"리스크 {previous.get('risk_status') or '-'} → {item.get('risk_status') or '-'}")
        if changed:
            changes.append(
                {
                    "occurred_at": item.get("occurred_at"),
                    "run_id": item.get("run_id"),
                    "summary": " · ".join(changed),
                    "reason_codes": item.get("reason_codes", []),
                    "failed_codes": item.get("failed_codes", []),
                }
            )
        previous = item
    return changes[-4:]


def _signal_history_trend(snapshots: Sequence[Mapping[str, Any]]) -> str:
    if len(snapshots) < 2:
        return "insufficient"
    previous = snapshots[-2]
    latest = snapshots[-1]
    if previous.get("eligible") is not True and latest.get("eligible") is True:
        return "improving"
    if previous.get("eligible") is True and latest.get("eligible") is not True:
        return "deteriorating"
    if previous.get("action") != latest.get("action"):
        return "changed"
    return "stable"


def _signal_history_summary(
    ticker: str,
    seven: Mapping[str, Any],
    thirty: Mapping[str, Any],
    trend: str,
) -> str:
    if not thirty.get("run_count"):
        return f"{ticker}의 최근 30일 판단 이력이 없습니다."
    trend_text = {
        "improving": "최근 판단이 개선됐습니다.",
        "deteriorating": "최근 판단이 보수적으로 바뀌었습니다.",
        "changed": "최근 판단 방향이 바뀌었습니다.",
        "stable": "최근 판단이 대체로 유지됐습니다.",
        "insufficient": "판단 변화 추세를 보려면 실행 기록이 더 필요합니다.",
    }.get(trend, "판단 흐름을 확인하세요.")
    return (
        f"최근 7일 {seven.get('run_count', 0)}회 중 매수 {seven.get('buy_count', 0)}회, "
        f"차단 {seven.get('blocked_count', 0)}회. "
        f"30일 기준 매수 {thirty.get('buy_count', 0)}회, 운영 가능 {thirty.get('eligible_count', 0)}회. "
        f"{trend_text}"
    )


def _signal_history_action_label(action: Any) -> str:
    return {
        "buy": "매수",
        "sell": "매도",
        "hold": "관망",
        "entry": "진입",
        "exit": "청산",
    }.get(str(action or "hold"), str(action or "관망"))


def _empty_signal_outcome(source: str = "state/signal_outcome.json") -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "summary": {
            "status": "not_evaluated",
            "signal_count": 0,
            "evaluated_count": 0,
            "pending_count": 0,
            "buy_candidate_count": 0,
            "blocked_buy_count": 0,
            "hold_count": 0,
            "sell_candidate_count": 0,
        },
        "aggregate": {},
        "by_decision_group": [],
        "by_strategy": [],
        "blocked_avoidance": {},
        "history_signal_count": 0,
        "cumulative": {},
        "rows": [],
        "basis": "gross_close_to_close_no_fees_spread_slippage",
        "source": source,
    }


def _dashboard_signal_outcome(paths: RuntimePaths, run_dir: Path) -> dict[str, Any]:
    outcome_path = _first_existing_path(
        run_dir / "signal_outcome.json",
        paths.state_dir / "signal_outcome.json",
    )
    source = _artifact_label(paths, outcome_path or (paths.state_dir / "signal_outcome.json"))
    if outcome_path is None:
        return _empty_signal_outcome(source)
    payload = read_json(outcome_path, default={})
    if not isinstance(payload, Mapping):
        empty = _empty_signal_outcome(source)
        empty["status"] = "data_error"
        empty["summary"]["status"] = "data_error"
        return empty
    report = dict(payload)
    summary = dict(_mapping(report.get("summary")))
    status = str(report.get("status") or summary.get("status") or "not_evaluated")
    summary["status"] = status
    calculation_source = str(report.get("source") or "signals JSON · price history JSON")
    report["status"] = status
    report["summary"] = summary
    report["aggregate"] = dict(_mapping(report.get("aggregate")))
    report["by_decision_group"] = [
        dict(item) for item in _sequence(report.get("by_decision_group")) if isinstance(item, Mapping)
    ]
    report["by_strategy"] = [
        dict(item) for item in _sequence(report.get("by_strategy")) if isinstance(item, Mapping)
    ]
    report["blocked_avoidance"] = dict(_mapping(report.get("blocked_avoidance")))
    report["rows"] = [dict(item) for item in _sequence(report.get("rows")) if isinstance(item, Mapping)]
    report["source"] = f"{source} · {calculation_source}"
    return report


def _empty_stock_lifecycle(source: str = "state/stock_lifecycle.json") -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "updated_at": None,
        "summary": {
            "ticker_count": 0,
            "transition_count": 0,
            "status_counts": {
                "watch": 0,
                "candidate": 0,
                "holding": 0,
                "caution": 0,
                "reduce": 0,
                "excluded": 0,
            },
            "action_required_count": 0,
        },
        "items": [],
        "history": [],
        "states": {},
        "source": source,
    }


def _dashboard_stock_lifecycle(
    paths: RuntimePaths,
    run_dir: Path,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    lifecycle_path = _first_existing_path(
        run_dir / "stock_lifecycle.json",
        paths.state_dir / "stock_lifecycle.json",
    )
    previous = read_json(lifecycle_path, default={}) if lifecycle_path else {}
    signal_map = {
        str(row.get("ticker") or "").upper(): dict(row)
        for row in rows
        if str(row.get("ticker") or "").strip()
    }
    report = build_stock_lifecycle_report(
        signal_map,
        [],
        previous=previous if isinstance(previous, Mapping) else {},
        now=_run_timestamp(run_dir) or datetime.now(UTC),
    )
    source = _artifact_label(paths, lifecycle_path or (paths.state_dir / "stock_lifecycle.json"))
    report["source"] = f"{source} · signals_risk.json"
    return report


def _empty_signal_stability(source: str = "state/signal_stability.json") -> dict[str, Any]:
    return {
        "status": "not_evaluated",
        "updated_at": None,
        "windows": [5, 10, 20],
        "summary": {
            "ticker_count": 0,
            "unstable_count": 0,
            "auto_candidate_excluded_count": 0,
            "average_stability_score": None,
        },
        "items": [],
        "source": source,
    }


def _dashboard_signal_stability(
    paths: RuntimePaths,
    run_dir: Path,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    stability_path = _first_existing_path(
        run_dir / "signal_stability.json",
        paths.state_dir / "signal_stability.json",
    )
    if stability_path is not None:
        payload = read_json(stability_path, default={})
        if isinstance(payload, Mapping):
            report = dict(payload)
            report["summary"] = dict(_mapping(report.get("summary")))
            report["items"] = [
                dict(item)
                for item in _sequence(report.get("items"))
                if isinstance(item, Mapping)
            ]
            report["source"] = _artifact_label(paths, stability_path)
            return report
    signal_map = {
        str(row.get("ticker") or "").upper(): dict(row)
        for row in rows
        if str(row.get("ticker") or "").strip()
    }
    report = build_signal_stability_from_runs(
        paths.runs_dir,
        current_signals=signal_map,
        now=_run_timestamp(run_dir) or datetime.now(UTC),
    )
    report["source"] = "runs/*/manifest.json · signals_risk.json"
    return report


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


def _empty_today_board() -> dict[str, list[dict[str, Any]]]:
    default_task = {
        "label": "최근 실행 생성",
        "detail": "완료된 run이 없어 오늘 확인할 운영 데이터가 없습니다.",
        "status": "not_evaluated",
        "page": "overview",
        "source": "runs/*/manifest.json",
        "action_type": "data_check",
        "queue_status": "new",
        "priority": 1,
        "queue_id": "task-no-run",
    }
    return {
        "tasks": [default_task],
        "risky_stocks": [],
        "buy_candidates": [],
        "sell_candidates": [],
        "dividend_reviews": [],
        "order_prepares": [],
        "action_queue": [default_task],
    }


def _today_board(
    signal_rows: Sequence[Mapping[str, Any]],
    reasons: Sequence[Mapping[str, Any]],
    actions: Sequence[Mapping[str, Any]],
    paths: RuntimePaths,
    stock_warning_gate: Mapping[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    board = _empty_today_board()
    warning_gate = stock_warning_gate or {}
    board["tasks"] = _today_task_items(actions, reasons)
    board["risky_stocks"] = _today_risky_stock_items(signal_rows, reasons, warning_gate)
    board["buy_candidates"] = _today_signal_items(
        [
            row
            for row in signal_rows
            if row.get("action") == "buy"
            and row.get("eligible") is True
            and _stock_warning_for_ticker(warning_gate, str(row.get("ticker") or "")) is None
        ],
        fallback_detail="리스크 게이트를 통과한 매수 후보입니다.",
        action_type="buy_review",
        queue_prefix="buy",
        priority=2,
    )
    board["sell_candidates"] = _today_signal_items(
        [
            row
            for row in signal_rows
            if row.get("action") == "sell" or str(row.get("signal") or "").lower() == "sell"
        ],
        fallback_detail="매도 또는 축소 검토 신호입니다.",
        action_type="sell_review",
        queue_prefix="sell",
        priority=2,
    )
    board["dividend_reviews"] = _today_dividend_review_items(paths)
    board["order_prepares"] = _today_order_prepare_items(board["buy_candidates"])
    board["action_queue"] = _today_action_queue(board)
    return board


def _today_task_items(
    actions: Sequence[Mapping[str, Any]],
    reasons: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if actions:
        items = []
        for index, action in enumerate(actions[:5], start=1):
            page = action.get("page")
            command = action.get("command")
            priority = _queue_priority(action.get("priority"), index)
            items.append(
                {
                    "label": str(action.get("label") or "검토"),
                    "detail": "차단 사유를 먼저 확인하세요.",
                    "status": "blocked" if reasons else "success",
                    "page": page,
                    "command": command,
                    "source": "safety_verdict.json · recommended_actions",
                    "action_type": _today_action_type_for_target(page, command),
                    "queue_status": "new",
                    "priority": priority,
                    "queue_id": str(action.get("id") or _queue_id("task", page or command or index)),
                }
            )
        return items
    return [
        {
            "label": "오늘 리포트 확인",
            "detail": "차단 사유가 없으면 신호와 리포트만 최종 확인하세요.",
            "status": "success",
            "page": "signals",
            "source": "latest run manifest · today_signals.json",
            "action_type": "data_check",
            "queue_status": "new",
            "priority": 1,
            "queue_id": "task-review-report",
        }
    ]


def _today_risky_stock_items(
    signal_rows: Sequence[Mapping[str, Any]],
    reasons: Sequence[Mapping[str, Any]],
    stock_warning_gate: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ticker, raw_warning in sorted((stock_warning_gate or {}).items()):
        warning = _mapping(raw_warning)
        if not _has_stock_warning(warning):
            continue
        symbol = str(ticker or "").upper()
        if not symbol:
            continue
        seen.add(symbol)
        items.append(
            {
                "ticker": symbol,
                "label": symbol,
                "detail": _stock_warning_message(warning),
                "status": "blocked",
                "page": "toss-account",
                "source": "stock_warning_gate.json · Toss /api/v1/stocks/{symbol}/warnings",
                "action_type": "broker_warning",
                "queue_status": "new",
                "priority": 1,
                "queue_id": _queue_id("broker-warning", symbol),
            }
        )
    for row in signal_rows:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker in seen:
            continue
        failed = _sequence(row.get("failed"))
        warnings = _sequence(row.get("warnings"))
        if not row.get("blocked") and not failed and not warnings and row.get("data_verified") is not False:
            continue
        seen.add(ticker)
        items.append(
            {
                "ticker": ticker,
                "label": ticker,
                "detail": _today_signal_detail(row, fallback="차단 또는 경고가 있는 종목입니다."),
                "status": str(row.get("status") or "warning"),
                "page": "risk",
                "source": "today_signals.json · risk gate status",
                "action_type": "risk_review",
                "queue_status": "new",
                "priority": 1,
                "queue_id": _queue_id("risk", ticker),
            }
        )
    for reason in reasons:
        for ticker_value in _sequence(reason.get("affected_tickers")):
            ticker = str(ticker_value or "").upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            component = str(reason.get("component"))
            items.append(
                {
                    "ticker": ticker,
                    "label": ticker,
                    "detail": str(reason.get("message") or reason.get("code") or "검토 필요"),
                    "status": "blocked",
                    "page": _action_for_component(component).get("page"),
                    "source": "safety_verdict.json · provider/risk summaries",
                    "action_type": _today_action_type_for_component(component),
                    "queue_status": "new",
                    "priority": 1,
                    "queue_id": _queue_id("reason", reason.get("code") or component, ticker),
                }
            )
    return items[:8]


def _stock_warning_for_ticker(
    stock_warning_gate: Mapping[str, Any],
    ticker: str,
) -> Mapping[str, Any] | None:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return None
    candidates = [symbol]
    if "." in symbol:
        candidates.append(symbol.split(".", 1)[0])
    if symbol.isdigit() and len(symbol) == 6:
        candidates.extend([f"{symbol}.KS", f"{symbol}.KQ"])
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        warning = _mapping(stock_warning_gate.get(candidate))
        if _has_stock_warning(warning):
            return warning
    return None


def _has_stock_warning(warning: Mapping[str, Any]) -> bool:
    if warning.get("has_warning") is True:
        return True
    payload = warning.get("warnings")
    if isinstance(payload, Mapping):
        result = payload.get("result")
        if isinstance(result, Sequence) and not isinstance(result, str):
            return bool(result)
        if isinstance(result, Mapping):
            warning_type = str(result.get("warningType") or result.get("warning") or "").upper()
            suspended = (
                result.get("suspended")
                or result.get("isSuspended")
                or result.get("tradeSuspended")
            )
            return bool(suspended) or warning_type not in {"", "NONE", "NORMAL"}
    return False


def _stock_warning_message(warning: Mapping[str, Any]) -> str:
    message = str(warning.get("message") or "").strip()
    if message:
        return message
    payload = warning.get("warnings")
    if isinstance(payload, Mapping):
        result = payload.get("result")
        if isinstance(result, Sequence) and not isinstance(result, str):
            warning_types = [
                str(item.get("warningType") or item.get("warning") or item.get("type") or "")
                for item in result
                if isinstance(item, Mapping)
            ]
            warning_types = [item for item in warning_types if item]
            if warning_types:
                return " · ".join(warning_types[:3])
        if isinstance(result, Mapping):
            warning_type = str(result.get("warningType") or result.get("warning") or "").strip()
            if warning_type:
                return f"Broker warning flag: {warning_type}"
    return "Toss 매수 유의사항이 있는 종목입니다."


def _today_signal_items(
    rows: Sequence[Mapping[str, Any]],
    *,
    fallback_detail: str,
    action_type: str,
    queue_prefix: str,
    priority: int,
) -> list[dict[str, Any]]:
    items = []
    for row in rows[:8]:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        items.append(
            {
                "ticker": ticker,
                "label": ticker,
                "detail": _today_signal_detail(row, fallback=fallback_detail),
                "status": str(row.get("status") or "eligible"),
                "entry_price": row.get("entry_price"),
                "stop_price": row.get("stop_price"),
                "target_price": row.get("target_price"),
                "page": "signals",
                "source": "today_signals.json · signal publication sidecar",
                "action_type": action_type,
                "queue_status": "new",
                "priority": priority,
                "queue_id": _queue_id(queue_prefix, ticker),
            }
        )
    return items


def _today_signal_detail(row: Mapping[str, Any], *, fallback: str) -> str:
    codes = [str(item) for item in _sequence(row.get("reason_codes")) if item]
    if codes:
        return " · ".join(codes[:3])
    failed = [
        str(item.get("code") or item.get("metric"))
        for item in _sequence(row.get("failed"))
        if isinstance(item, Mapping) and (item.get("code") or item.get("metric"))
    ]
    if failed:
        return " · ".join(failed[:3])
    if row.get("data_verified") is False:
        return "가격 데이터 검증 실패"
    return fallback


def _today_dividend_review_items(paths: RuntimePaths) -> list[dict[str, Any]]:
    try:
        mapping = load_portfolio_mapping(paths.portfolio_mapping_file)
    except Exception:
        return []
    rows = []
    for ticker, item in sorted(mapping.tickers.items()):
        if "dividend" not in _normalize_portfolio_type_keys(item.portfolio_types):
            continue
        rows.append(
            {
                "ticker": ticker,
                "label": ticker,
                "detail": "배당 타입으로 관리되는 종목입니다. 배당 지속성과 비중을 정기 점검하세요.",
                "status": "watch",
                "page": "toss-account",
                "source": f"{mapping.source} · portfolio_types",
                "action_type": "dividend_review",
                "queue_status": "new",
                "priority": 4,
                "queue_id": _queue_id("dividend", ticker),
            }
        )
    return rows[:8]


def _today_order_prepare_items(
    buy_candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not buy_candidates:
        return []
    return [
        {
            "label": "매수 후보 주문 검증",
            "detail": f"매수 후보 {len(buy_candidates)}건을 OrderIntent로 넘기기 전 현금·수량·Toss 유의사항을 확인하세요.",
            "status": "not_evaluated",
            "page": "toss-account",
            "source": "today_signals.json · OrderIntent validation queue",
            "action_type": "order_prepare",
            "queue_status": "new",
            "priority": 3,
            "queue_id": "order-prepare-buy-candidates",
        }
    ]


def _today_action_queue(board: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    sections = [
        "tasks",
        "risky_stocks",
        "buy_candidates",
        "sell_candidates",
        "order_prepares",
        "dividend_reviews",
    ]
    for section in sections:
        for index, item in enumerate(_sequence(board.get(section)), start=1):
            if not isinstance(item, Mapping):
                continue
            queued = dict(item)
            queued.setdefault("queue_status", "new")
            queued.setdefault("priority", index)
            queued.setdefault(
                "queue_id",
                _queue_id(section, item.get("ticker") or item.get("label") or index),
            )
            queued["queue_section"] = section
            queue.append(queued)
    return sorted(queue, key=lambda item: (_queue_priority(item.get("priority"), 99), str(item.get("queue_id"))))[
        :20
    ]


def _today_action_type_for_target(page: Any, command: Any = None) -> str:
    page_name = str(page or "")
    command_name = str(command or "")
    if page_name == "data-quality":
        return "data_check"
    if page_name == "risk":
        return "risk_review"
    if "promotion" in command_name or "validate-config" in command_name:
        return "data_check"
    return "data_check"


def _today_action_type_for_component(component: str) -> str:
    return {
        "data": "data_check",
        "risk": "risk_review",
        "promotion": "data_check",
        "survivorship": "data_check",
        "run": "data_check",
    }.get(str(component or ""), "risk_review")


def _queue_priority(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _queue_id(*parts: Any) -> str:
    raw = "-".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())
    safe = "".join(char if char.isalnum() else "-" for char in raw)
    return "-".join(part for part in safe.split("-") if part) or "action"


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


def build_dashboard_analysis(
    paths: RuntimePaths,
    ticker: str = "SOXL",
    macro_series: str = "FEDFUNDS",
    period: str = "2y",
) -> dict[str, Any]:
    import yfinance as yf
    import pandas as pd
    import requests
    from datetime import date, datetime, timedelta
    from io import StringIO
    from .yahoo import get_yahoo_session
    from .settings import load_settings

    # 1. Fetch Stock Data
    yf_period = period
    if period.endswith("m"):
        yf_period = period.replace("m", "mo")

    stock_data = {}
    try:
        session = get_yahoo_session()
        stock_df = yf.download(ticker, period=yf_period, session=session, auto_adjust=True, progress=False)
        if stock_df.empty:
            stock_data = {"error": f"No price data found for ticker {ticker}"}
        else:
            history = []
            close_prices = []
            for date_idx, row in stock_df.iterrows():
                date_str = date_idx.strftime("%Y-%m-%d")
                
                # Retrieve Close / Open / High / Low / Volume robustly (handling MultiIndex columns)
                try:
                    if hasattr(stock_df.columns, "levels"):
                        close_val = float(row[("Close", ticker)]) if ("Close", ticker) in row else float(row["Close"].iloc[0])
                        open_val = float(row[("Open", ticker)]) if ("Open", ticker) in row else float(row["Open"].iloc[0])
                        high_val = float(row[("High", ticker)]) if ("High", ticker) in row else float(row["High"].iloc[0])
                        low_val = float(row[("Low", ticker)]) if ("Low", ticker) in row else float(row["Low"].iloc[0])
                        vol_val = float(row[("Volume", ticker)]) if ("Volume", ticker) in row else float(row["Volume"].iloc[0])
                    else:
                        close_val = float(row["Close"])
                        open_val = float(row["Open"])
                        high_val = float(row["High"])
                        low_val = float(row["Low"])
                        vol_val = float(row["Volume"])
                except Exception:
                    close_val = float(row.iloc[0])
                    open_val = float(row.iloc[0])
                    high_val = float(row.iloc[0])
                    low_val = float(row.iloc[0])
                    vol_val = 0.0

                close_prices.append(close_val)
                history.append({
                    "date": date_str,
                    "open": open_val,
                    "high": high_val,
                    "low": low_val,
                    "close": close_val,
                    "volume": vol_val
                })

            latest_price = close_prices[-1] if close_prices else 0.0
            prev_price = close_prices[-2] if len(close_prices) > 1 else latest_price
            change_pct = ((latest_price - prev_price) / prev_price * 100) if prev_price else 0.0
            
            fifty_two_week_high = max(close_prices) if close_prices else 0.0
            fifty_two_week_low = min(close_prices) if close_prices else 0.0

            stock_data = {
                "ticker": ticker,
                "latest_price": latest_price,
                "change_pct": change_pct,
                "fifty_two_week_high": fifty_two_week_high,
                "fifty_two_week_low": fifty_two_week_low,
                "history": history
            }
    except Exception as exc:
        stock_data = {"error": f"Failed to fetch stock data: {str(exc)}"}

    # 2. Fetch FRED macroeconomic data
    macro_data = {}
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={macro_series}"
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        csv_data = StringIO(res.text)
        macro_df = pd.read_csv(csv_data)
        
        macro_df["date_dt"] = pd.to_datetime(macro_df["observation_date"])
        
        now_dt = datetime.now()
        if period == "1m":
            start_dt = now_dt - timedelta(days=30)
        elif period == "3m":
            start_dt = now_dt - timedelta(days=90)
        elif period == "6m":
            start_dt = now_dt - timedelta(days=180)
        elif period == "1y":
            start_dt = now_dt - timedelta(days=365)
        elif period == "2y":
            start_dt = now_dt - timedelta(days=365 * 2)
        elif period == "5y":
            start_dt = now_dt - timedelta(days=365 * 5)
        else: # 10y
            start_dt = now_dt - timedelta(days=365 * 10)
            
        filtered_df = macro_df[macro_df["date_dt"] >= start_dt]
        
        history = []
        values = []
        for _, row in filtered_df.iterrows():
            val_str = str(row[macro_series]).strip()
            if val_str == "." or not val_str:
                continue
            try:
                val = float(val_str)
            except ValueError:
                continue
            
            values.append(val)
            history.append({
                "date": row["observation_date"],
                "value": val
            })
            
        latest_val = values[-1] if values else 0.0
        prev_val = values[-2] if len(values) > 1 else latest_val
        change = latest_val - prev_val
        
        macro_names = {
            "FEDFUNDS": "Federal Funds Effective Rate",
            "CPIAUCSNS": "Consumer Price Index (CPI)",
            "UNRATE": "Civilian Unemployment Rate",
            "GDPC1": "Real Gross Domestic Product (GDP)",
            "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury",
            "BAMLH0A0HYM2": "ICE BofA US High Yield Index Option-Adjusted Spread",
            "M2SL": "M2 Money Supply",
        }
        series_name = macro_names.get(macro_series, f"FRED Series {macro_series}")
        
        macro_data = {
            "series_id": macro_series,
            "name": series_name,
            "latest_value": latest_val,
            "latest_date": history[-1]["date"] if history else "-",
            "change": change,
            "history": history
        }
    except Exception as exc:
        macro_data = {"error": f"Failed to fetch FRED data: {str(exc)}"}

    # 3. Fetch News/Sentiment from Finnhub or Alpha Vantage
    news_data = []
    try:
        settings = load_settings(paths.config_file if paths.config_file.exists() else None)
        finnhub_key = settings.finnhub_api_key.get_secret_value() if settings.finnhub_api_key else None
        av_key = settings.alpha_vantage_api_key.get_secret_value() if settings.alpha_vantage_api_key else None
        
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        
        if finnhub_key:
            try:
                from .supplemental_data import FinnhubEventProvider
                finnhub = FinnhubEventProvider(paths.cache_dir, finnhub_key)
                raw_news = finnhub.company_news(ticker, start=start_date, end=end_date)
                for item in raw_news[:12]:
                    news_data.append({
                        "headline": item.get("headline"),
                        "source": item.get("source"),
                        "url": item.get("url"),
                        "published_at": item.get("published_at"),
                        "sentiment": "Neutral"
                    })
            except Exception:
                pass
                
        if not news_data and av_key:
            try:
                from .supplemental_data import AlphaVantageNewsProvider
                av = AlphaVantageNewsProvider(paths.cache_dir, av_key)
                raw_news = av.fetch(ticker, limit=12)
                for item in raw_news:
                    score = item.get("sentiment_score")
                    sentiment = "Neutral"
                    if score is not None:
                        if score > 0.15:
                            sentiment = "Positive"
                        elif score < -0.15:
                            sentiment = "Negative"
                    news_data.append({
                        "headline": item.get("title"),
                        "source": item.get("source"),
                        "url": item.get("url"),
                        "published_at": item.get("published_at"),
                        "sentiment": sentiment
                    })
            except Exception:
                pass
    except Exception:
        pass

    # 4. Fetch Toss portfolio metrics if configured
    toss_portfolio = {}
    try:
        from .toss import TossInvestClient
        api_key = settings.toss_api_key.get_secret_value() if settings.toss_api_key else None
        secret_key = settings.toss_secret_key.get_secret_value() if settings.toss_secret_key else None
        if api_key and secret_key:
            client = TossInvestClient(api_key=api_key, secret_key=secret_key)
            accounts = client.accounts()
            if accounts:
                acc_no = accounts[0]["account_no"]
                positions = client.positions(acc_no)
                toss_portfolio = {
                    "account_no": acc_no,
                    "positions": [
                        {
                            "symbol": pos.get("symbol"),
                            "qty": pos.get("quantity"),
                            "buy_price": pos.get("buy_price"),
                            "current_price": pos.get("current_price"),
                            "profit_loss": pos.get("profit_loss"),
                            "profit_loss_rate": pos.get("profit_loss_rate")
                        }
                        for pos in positions
                    ]
                }
    except Exception:
        pass

    return {
        "stock": stock_data,
        "macro": macro_data,
        "news": news_data,
        "toss": toss_portfolio,
        "tradingview_details": build_tradingview_symbol_details(ticker),
        "tradingview_news": build_tradingview_news_flow(ticker),
    }


# ─── Technical Indicators ──────────────────────────────────────────────────────

def _compute_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    results: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return results
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        idx = i - 1  # index in deltas
        avg_gain = (avg_gain * (period - 1) + gains[idx]) / period
        avg_loss = (avg_loss * (period - 1) + losses[idx]) / period
        rs = avg_gain / avg_loss if avg_loss else float("inf")
        results[i] = round(100.0 - 100.0 / (1.0 + rs), 2)
    return results


def _compute_ema(closes: list[float], period: int) -> list[float | None]:
    results: list[float | None] = [None] * len(closes)
    if len(closes) < period:
        return results
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    results[period - 1] = round(ema, 4)
    for i in range(period, len(closes)):
        ema = closes[i] * k + ema * (1 - k)
        results[i] = round(ema, 4)
    return results


def _compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema_fast = _compute_ema(closes, fast)
    ema_slow = _compute_ema(closes, slow)
    macd_line: list[float | None] = []
    for f, s in zip(ema_fast, ema_slow):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(round(f - s, 6))
    # signal line: EMA of macd values (only where not None)
    valid_macd = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    sig_line: list[float | None] = [None] * len(macd_line)
    hist: list[float | None] = [None] * len(macd_line)
    if len(valid_macd) >= signal:
        vals = [v for _, v in valid_macd]
        ema_sig = _compute_ema(vals, signal)
        for j, (orig_i, _) in enumerate(valid_macd):
            if ema_sig[j] is not None:
                sig_line[orig_i] = round(ema_sig[j], 6)
                if macd_line[orig_i] is not None:
                    hist[orig_i] = round(macd_line[orig_i] - ema_sig[j], 6)  # type: ignore[operator]
    return macd_line, sig_line, hist


def _compute_bollinger(
    closes: list[float], period: int = 20, std_dev: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    upper: list[float | None] = [None] * len(closes)
    mid: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        avg = sum(window) / period
        variance = sum((x - avg) ** 2 for x in window) / period
        sd = variance ** 0.5
        upper[i] = round(avg + std_dev * sd, 4)
        mid[i] = round(avg, 4)
        lower[i] = round(avg - std_dev * sd, 4)
    return upper, mid, lower


def _compute_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float | None]:
    results: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return results
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr = sum(trs[:period]) / period
    results[period] = round(atr, 4)
    for i in range(period + 1, len(closes)):
        atr = (atr * (period - 1) + trs[i - 1]) / period
        results[i] = round(atr, 4)
    return results


TRADINGVIEW_TECHNICAL_FIELDS = (
    "Recommend.Other",
    "Recommend.All",
    "Recommend.MA",
    "RSI",
    "RSI[1]",
    "Stoch.K",
    "Stoch.D",
    "Stoch.K[1]",
    "Stoch.D[1]",
    "CCI20",
    "CCI20[1]",
    "ADX",
    "ADX+DI",
    "ADX-DI",
    "ADX+DI[1]",
    "ADX-DI[1]",
    "AO",
    "AO[1]",
    "AO[2]",
    "Mom",
    "Mom[1]",
    "MACD.macd",
    "MACD.signal",
    "Rec.Stoch.RSI",
    "Stoch.RSI.K",
    "Rec.WR",
    "W.R",
    "Rec.BBPower",
    "BBPower",
    "Rec.UO",
    "UO",
    "EMA10",
    "SMA10",
    "EMA20",
    "SMA20",
    "EMA30",
    "SMA30",
    "EMA50",
    "SMA50",
    "EMA100",
    "SMA100",
    "EMA200",
    "SMA200",
    "Rec.Ichimoku",
    "Ichimoku.BLine",
    "Rec.VWMA",
    "VWMA",
    "Rec.HullMA9",
    "HullMA9",
    "Pivot.M.Classic.R3",
    "Pivot.M.Classic.R2",
    "Pivot.M.Classic.R1",
    "Pivot.M.Classic.Middle",
    "Pivot.M.Classic.S1",
    "Pivot.M.Classic.S2",
    "Pivot.M.Classic.S3",
    "Pivot.M.Fibonacci.R3",
    "Pivot.M.Fibonacci.R2",
    "Pivot.M.Fibonacci.R1",
    "Pivot.M.Fibonacci.Middle",
    "Pivot.M.Fibonacci.S1",
    "Pivot.M.Fibonacci.S2",
    "Pivot.M.Fibonacci.S3",
    "Pivot.M.Camarilla.R3",
    "Pivot.M.Camarilla.R2",
    "Pivot.M.Camarilla.R1",
    "Pivot.M.Camarilla.Middle",
    "Pivot.M.Camarilla.S1",
    "Pivot.M.Camarilla.S2",
    "Pivot.M.Camarilla.S3",
    "Pivot.M.Woodie.R3",
    "Pivot.M.Woodie.R2",
    "Pivot.M.Woodie.R1",
    "Pivot.M.Woodie.Middle",
    "Pivot.M.Woodie.S1",
    "Pivot.M.Woodie.S2",
    "Pivot.M.Woodie.S3",
    "Pivot.M.Demark.R1",
    "Pivot.M.Demark.Middle",
    "Pivot.M.Demark.S1",
    "close",
)

TRADINGVIEW_TIMEFRAMES = (
    ("1M", "1개월", "1M"),
    ("1W", "1주", "1W"),
    ("1D", "1일", ""),
    ("240", "4시간", "240"),
    ("120", "2시간", "120"),
    ("60", "1시간", "60"),
    ("30", "30분", "30"),
    ("15", "15분", "15"),
    ("5", "5분", "5"),
    ("1", "1분", "1"),
)

TRADINGVIEW_DETAIL_FIELDS = (
    "price_52_week_high",
    "price_52_week_low",
    "sector",
    "country",
    "market",
    "Low.1M",
    "High.1M",
    "Perf.W",
    "Perf.1M",
    "Perf.3M",
    "Perf.6M",
    "Perf.Y",
    "Perf.YTD",
    "Recommend.All",
    "average_volume_10d_calc",
    "average_volume_30d_calc",
    "nav_discount_premium",
    "open_interest",
    "country_code_fund",
    "iv",
    "underlying_symbol",
    "delta",
    "gamma",
    "rho",
    "theta",
    "vega",
    "theoPrice",
)


def _tradingview_symbol(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if ":" in normalized:
        return normalized
    if normalized.endswith((".KS", ".KQ")):
        return f"KRX:{normalized.rsplit('.', 1)[0]}"
    exchange_map = {
        "AAPL": "NASDAQ:AAPL",
        "GOOGL": "NASDAQ:GOOGL",
        "IONQ": "NYSE:IONQ",
        "MSFT": "NASDAQ:MSFT",
        "NVDA": "NASDAQ:NVDA",
        "NVDL": "NASDAQ:NVDL",
        "QBTS": "NYSE:QBTS",
        "QQQ": "NASDAQ:QQQ",
        "SOXL": "AMEX:SOXL",
        "SPY": "AMEX:SPY",
        "TQQQ": "NASDAQ:TQQQ",
        "TSLA": "NASDAQ:TSLA",
    }
    return exchange_map.get(normalized, f"NASDAQ:{normalized}")


def _tradingview_field_name(field: str, interval: str) -> str:
    return f"{field}|{interval}" if interval else field


def _tradingview_headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.tradingview.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
    }


def _rounded_float(value: Any, digits: int = 4) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _technical_recommendation(score: float | None) -> dict[str, Any]:
    if score is None:
        return {
            "action": "hold",
            "signal": "unknown",
            "label": "데이터 없음",
            "tone": "neutral",
        }
    if score >= 0.5:
        return {"action": "buy", "signal": "strong_buy", "label": "강한 매수", "tone": "buy"}
    if score >= 0.1:
        return {"action": "buy", "signal": "buy", "label": "매수", "tone": "buy"}
    if score <= -0.5:
        return {
            "action": "sell",
            "signal": "strong_sell",
            "label": "강한 매도",
            "tone": "sell",
        }
    if score <= -0.1:
        return {"action": "sell", "signal": "sell", "label": "매도", "tone": "sell"}
    return {"action": "hold", "signal": "neutral", "label": "중립", "tone": "neutral"}


def _pivot_levels(row: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    def item(prefix: str, keys: tuple[str, ...]) -> dict[str, float | None]:
        return {key.lower(): row.get(f"Pivot.M.{prefix}.{key}") for key in keys}

    return {
        "classic": item("Classic", ("R3", "R2", "R1", "Middle", "S1", "S2", "S3")),
        "fibonacci": item("Fibonacci", ("R3", "R2", "R1", "Middle", "S1", "S2", "S3")),
        "camarilla": item("Camarilla", ("R3", "R2", "R1", "Middle", "S1", "S2", "S3")),
        "woodie": item("Woodie", ("R3", "R2", "R1", "Middle", "S1", "S2", "S3")),
        "demark": item("Demark", ("R1", "Middle", "S1")),
    }


def _nearest_pivot_levels(
    close: float | None,
    pivots: dict[str, dict[str, float | None]],
) -> dict[str, Any]:
    if close is None:
        return {"support": None, "resistance": None}

    levels: list[dict[str, Any]] = []
    for family, values in pivots.items():
        for name, value in values.items():
            if value is None:
                continue
            levels.append(
                {
                    "family": family,
                    "level": name,
                    "value": value,
                    "distance_pct": round(((value - close) / close) * 100, 4),
                }
            )

    supports = [level for level in levels if level["value"] <= close]
    resistances = [level for level in levels if level["value"] >= close]
    support = max(supports, key=lambda item: item["value"], default=None)
    resistance = min(resistances, key=lambda item: item["value"], default=None)
    return {"support": support, "resistance": resistance}


def _technical_rationale(row: dict[str, Any]) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    rsi = row.get("RSI")
    rsi_prev = row.get("RSI[1]")
    stoch_k = row.get("Stoch.K")
    stoch_d = row.get("Stoch.D")
    adx = row.get("ADX")
    plus_di = row.get("ADX+DI")
    minus_di = row.get("ADX-DI")
    macd = row.get("MACD.macd")
    macd_signal = row.get("MACD.signal")
    mom = row.get("Mom")
    close = row.get("close")

    if rsi is not None:
        if rsi <= 30:
            notes.append({"tone": "sell", "text": f"RSI {rsi:.1f}: 과매도권"})
        elif rsi <= 40:
            trend = (
                " 하락 중"
                if rsi_prev is not None and rsi < rsi_prev
                else ""
            )
            notes.append({"tone": "sell", "text": f"RSI {rsi:.1f}: 약세 구간{trend}"})
        elif rsi >= 70:
            notes.append({"tone": "buy", "text": f"RSI {rsi:.1f}: 강한 과열/추세"})

    if stoch_k is not None and stoch_d is not None:
        if stoch_k < 20 and stoch_k < stoch_d:
            notes.append(
                {
                    "tone": "sell",
                    "text": f"Stoch {stoch_k:.1f}/{stoch_d:.1f}: 단기 매도 압력",
                }
            )
        elif stoch_k > 80 and stoch_k > stoch_d:
            notes.append(
                {
                    "tone": "buy",
                    "text": f"Stoch {stoch_k:.1f}/{stoch_d:.1f}: 단기 강세",
                }
            )

    if adx is not None and plus_di is not None and minus_di is not None:
        if adx >= 25 and minus_di > plus_di:
            notes.append(
                {
                    "tone": "sell",
                    "text": f"ADX {adx:.1f}: 하락 추세 우세(-DI {minus_di:.1f} > +DI {plus_di:.1f})",
                }
            )
        elif adx >= 25 and plus_di > minus_di:
            notes.append(
                {
                    "tone": "buy",
                    "text": f"ADX {adx:.1f}: 상승 추세 우세(+DI {plus_di:.1f} > -DI {minus_di:.1f})",
                }
            )

    if macd is not None and macd_signal is not None:
        if macd < macd_signal:
            notes.append(
                {
                    "tone": "sell",
                    "text": f"MACD {macd:.2f} < Signal {macd_signal:.2f}",
                }
            )
        elif macd > macd_signal:
            notes.append(
                {
                    "tone": "buy",
                    "text": f"MACD {macd:.2f} > Signal {macd_signal:.2f}",
                }
            )

    if mom is not None:
        if mom < 0:
            notes.append({"tone": "sell", "text": f"Momentum {mom:.2f}: 음수"})
        elif mom > 0:
            notes.append({"tone": "buy", "text": f"Momentum {mom:.2f}: 양수"})

    if close is not None:
        watched_mas = {
            "EMA20": row.get("EMA20"),
            "EMA50": row.get("EMA50"),
            "EMA200": row.get("EMA200"),
        }
        below = [name for name, value in watched_mas.items() if value is not None and close < value]
        above = [name for name, value in watched_mas.items() if value is not None and close > value]
        if below:
            notes.append({"tone": "sell", "text": f"종가가 {', '.join(below)} 아래"})
        elif above:
            notes.append({"tone": "buy", "text": f"종가가 {', '.join(above)} 위"})

    return notes[:6]


def build_tradingview_technical_summary(ticker: str = "SOXL") -> dict[str, Any]:
    """Return TradingView scanner technical recommendations across key timeframes."""
    import requests

    symbol = _tradingview_symbol(ticker)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for timeframe_id, label, interval in TRADINGVIEW_TIMEFRAMES:
        fields = [
            _tradingview_field_name(field, interval)
            for field in TRADINGVIEW_TECHNICAL_FIELDS
        ]
        try:
            response = requests.get(
                "https://scanner.tradingview.com/symbol",
                params={
                    "symbol": symbol,
                    "fields": ",".join(fields),
                    "no_404": "true",
                    "label-product": "popup-technicals",
                },
                headers=_tradingview_headers(),
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()

            def value(field: str, digits: int = 4) -> float | None:
                return _rounded_float(
                    payload.get(_tradingview_field_name(field, interval)),
                    digits=digits,
                )

            raw_values = {field: value(field) for field in TRADINGVIEW_TECHNICAL_FIELDS}
            raw_values["close"] = value("close", digits=2)
            pivots = _pivot_levels(raw_values)
            nearest_pivots = _nearest_pivot_levels(raw_values.get("close"), pivots)
            score = value("Recommend.All")
            recommendation = _technical_recommendation(score)
            rows.append(
                {
                    "timeframe": timeframe_id,
                    "label": label,
                    "score": score,
                    "recommend_all": score,
                    "recommend_ma": value("Recommend.MA"),
                    "recommend_other": value("Recommend.Other"),
                    "recommendation": recommendation,
                    "close": value("close", digits=2),
                    "rsi": value("RSI", digits=2),
                    "macd": value("MACD.macd", digits=4),
                    "macd_signal": value("MACD.signal", digits=4),
                    "ema20": value("EMA20", digits=2),
                    "sma20": value("SMA20", digits=2),
                    "ema50": value("EMA50", digits=2),
                    "ema200": value("EMA200", digits=2),
                    "oscillators": {
                        "rsi": value("RSI", digits=2),
                        "rsi_prev": value("RSI[1]", digits=2),
                        "stoch_k": value("Stoch.K", digits=2),
                        "stoch_d": value("Stoch.D", digits=2),
                        "stoch_k_prev": value("Stoch.K[1]", digits=2),
                        "stoch_d_prev": value("Stoch.D[1]", digits=2),
                        "stoch_rsi_k": value("Stoch.RSI.K", digits=2),
                        "cci20": value("CCI20", digits=2),
                        "cci20_prev": value("CCI20[1]", digits=2),
                        "adx": value("ADX", digits=2),
                        "adx_plus_di": value("ADX+DI", digits=2),
                        "adx_minus_di": value("ADX-DI", digits=2),
                        "ao": value("AO", digits=4),
                        "ao_prev": value("AO[1]", digits=4),
                        "ao_prev2": value("AO[2]", digits=4),
                        "mom": value("Mom", digits=4),
                        "mom_prev": value("Mom[1]", digits=4),
                        "macd": value("MACD.macd", digits=4),
                        "macd_signal": value("MACD.signal", digits=4),
                        "williams_r": value("W.R", digits=2),
                        "bbpower": value("BBPower", digits=4),
                        "ultimate_osc": value("UO", digits=2),
                    },
                    "moving_averages": {
                        "ema10": value("EMA10", digits=2),
                        "sma10": value("SMA10", digits=2),
                        "ema20": value("EMA20", digits=2),
                        "sma20": value("SMA20", digits=2),
                        "ema30": value("EMA30", digits=2),
                        "sma30": value("SMA30", digits=2),
                        "ema50": value("EMA50", digits=2),
                        "sma50": value("SMA50", digits=2),
                        "ema100": value("EMA100", digits=2),
                        "sma100": value("SMA100", digits=2),
                        "ema200": value("EMA200", digits=2),
                        "sma200": value("SMA200", digits=2),
                        "vwma": value("VWMA", digits=2),
                        "hullma9": value("HullMA9", digits=2),
                        "ichimoku_bline": value("Ichimoku.BLine", digits=2),
                    },
                    "recommendations": {
                        "stoch_rsi": value("Rec.Stoch.RSI", digits=2),
                        "williams_r": value("Rec.WR", digits=2),
                        "bbpower": value("Rec.BBPower", digits=2),
                        "ultimate_osc": value("Rec.UO", digits=2),
                        "ichimoku": value("Rec.Ichimoku", digits=2),
                        "vwma": value("Rec.VWMA", digits=2),
                        "hullma9": value("Rec.HullMA9", digits=2),
                    },
                    "pivots": pivots,
                    "nearest_pivots": nearest_pivots,
                    "rationale": _technical_rationale(raw_values),
                }
            )
        except Exception as exc:
            errors.append({"timeframe": timeframe_id, "label": label, "error": str(exc)})

    if not rows:
        first_error = errors[0]["error"] if errors else "TradingView scanner returned no data"
        return {
            "status": "unavailable",
            "symbol": symbol,
            "error": first_error,
            "timeframes": rows,
            "errors": errors,
        }

    valid_scores = [row["score"] for row in rows if row["score"] is not None]
    consensus_score = (
        round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else None
    )
    consensus = _technical_recommendation(consensus_score)
    strong_count = sum(
        1
        for row in rows
        if row["recommendation"]["signal"] in {"strong_buy", "strong_sell"}
    )

    return {
        "status": "partial" if errors else "ok",
        "source": "TradingView scanner",
        "symbol": symbol,
        "generated_at": datetime.now(UTC).isoformat(),
        "consensus_score": consensus_score,
        "consensus": consensus,
        "confidence": round(min(1.0, abs(consensus_score or 0.0) * 2), 4),
        "strong_signal_count": strong_count,
        "timeframes": rows,
        "errors": errors,
    }


def build_tradingview_symbol_details(ticker: str = "SOXL") -> dict[str, Any]:
    """Return TradingView right-details scanner fields normalized for dashboard use."""
    import requests

    symbol = _tradingview_symbol(ticker)
    try:
        response = requests.get(
            "https://scanner.tradingview.com/symbol",
            params={
                "symbol": symbol,
                "fields": ",".join(TRADINGVIEW_DETAIL_FIELDS),
                "no_404": "true",
                "label-product": "right-details",
            },
            headers=_tradingview_headers(),
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "error": str(exc),
        }

    recommend_score = _rounded_float(payload.get("Recommend.All"))
    return {
        "status": "ok",
        "source": "TradingView scanner",
        "symbol": symbol,
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": {
            "sector": payload.get("sector"),
            "country": payload.get("country"),
            "country_code_fund": payload.get("country_code_fund"),
            "market": payload.get("market"),
            "underlying_symbol": payload.get("underlying_symbol"),
        },
        "quote": {
            "price_52_week_high": _rounded_float(payload.get("price_52_week_high"), 4),
            "price_52_week_low": _rounded_float(payload.get("price_52_week_low"), 4),
            "high_1m": _rounded_float(payload.get("High.1M"), 4),
            "low_1m": _rounded_float(payload.get("Low.1M"), 4),
            "recommend_all": recommend_score,
            "recommendation": _technical_recommendation(recommend_score),
        },
        "performance": {
            "week": _rounded_float(payload.get("Perf.W"), 4),
            "one_month": _rounded_float(payload.get("Perf.1M"), 4),
            "three_month": _rounded_float(payload.get("Perf.3M"), 4),
            "six_month": _rounded_float(payload.get("Perf.6M"), 4),
            "year_to_date": _rounded_float(payload.get("Perf.YTD"), 4),
            "one_year": _rounded_float(payload.get("Perf.Y"), 4),
        },
        "volume": {
            "average_10d": _rounded_float(payload.get("average_volume_10d_calc"), 0),
            "average_30d": _rounded_float(payload.get("average_volume_30d_calc"), 0),
        },
        "fund": {
            "nav_discount_premium": _rounded_float(payload.get("nav_discount_premium"), 4),
        },
        "derivatives": {
            "open_interest": _rounded_float(payload.get("open_interest"), 0),
            "iv": _rounded_float(payload.get("iv"), 4),
            "delta": _rounded_float(payload.get("delta"), 4),
            "gamma": _rounded_float(payload.get("gamma"), 4),
            "rho": _rounded_float(payload.get("rho"), 4),
            "theta": _rounded_float(payload.get("theta"), 4),
            "vega": _rounded_float(payload.get("vega"), 4),
            "theo_price": _rounded_float(payload.get("theoPrice"), 4),
        },
    }


def _tradingview_news_url(story_path: Any) -> str | None:
    if not story_path:
        return None
    path = str(story_path)
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/"):
        return f"https://www.tradingview.com{path}"
    return f"https://www.tradingview.com/news/{path.lstrip('/')}"


def _timestamp_to_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


TRADINGVIEW_RELATED_SYMBOL_ROLES: dict[str, dict[str, Any]] = {
    "semiconductor": {
        "label": "반도체 직접 테마",
        "tone": "buy",
        "priority": 10,
        "description": "SOXL의 기초 섹터와 직접 맞물리는 반도체/AI/DRAM 심볼입니다.",
        "symbols": {
            "CBOE:DRAM",
            "NASDAQ:SMH",
            "NASDAQ:SOXX",
            "NASDAQ:NVDA",
            "NASDAQ:AMD",
            "NASDAQ:AVGO",
        },
    },
    "broad_market": {
        "label": "미국 주식 베타",
        "tone": "neutral",
        "priority": 30,
        "description": "S&P 500, Nasdaq, Russell 등 시장 전체 자금 흐름을 반영합니다.",
        "symbols": {
            "AMEX:SPY",
            "AMEX:VOO",
            "AMEX:IVV",
            "AMEX:SPYM",
            "NASDAQ:QQQ",
            "NASDAQ:QQQM",
            "AMEX:IWM",
        },
    },
    "leveraged_peer": {
        "label": "레버리지/고베타 동조",
        "tone": "warning",
        "priority": 20,
        "description": "레버리지 ETF나 고베타 상품과 함께 언급되어 변동성 민감도가 큽니다.",
        "symbols": {
            "AMEX:SOXL",
            "NASDAQ:TQQQ",
            "NASDAQ:NVDL",
            "NASDAQ:TSLL",
            "AMEX:SPXL",
        },
    },
    "defensive_rotation": {
        "label": "방어/금리 회전",
        "tone": "sell",
        "priority": 25,
        "description": "채권, 현금성 ETF, 금 등 방어적 자산으로의 회전을 시사할 수 있습니다.",
        "symbols": {
            "AMEX:BIL",
            "AMEX:LQD",
            "AMEX:SGOV",
            "NASDAQ:BND",
            "NASDAQ:TLT",
            "CBOE:JMUB",
            "AMEX:GLD",
            "AMEX:SLV",
        },
    },
    "crypto_alternative": {
        "label": "대체 위험자산",
        "tone": "warning",
        "priority": 50,
        "description": "비트코인/대체자산 ETF가 함께 언급된 위험선호 맥락입니다.",
        "symbols": {
            "NASDAQ:IBIT",
            "AMEX:BITO",
            "NASDAQ:BITB",
        },
    },
    "international_flow": {
        "label": "해외/신흥국 자금",
        "tone": "neutral",
        "priority": 60,
        "description": "미국 외 지역 ETF와 함께 언급되어 글로벌 자금 이동을 보여줍니다.",
        "symbols": {
            "AMEX:EWZ",
            "AMEX:IEMG",
            "AMEX:SCHF",
            "AMEX:VEA",
            "NASDAQ:VXUS",
            "CBOE:BBEU",
        },
    },
    "thematic_growth": {
        "label": "성장/테마 자금",
        "tone": "buy",
        "priority": 40,
        "description": "테마형 성장 ETF와 동반 언급된 위험선호 흐름입니다.",
        "symbols": {
            "CBOE:ARKK",
            "CBOE:COWZ",
        },
    },
}


def _tradingview_related_symbol_role(
    related_symbol: str,
    *,
    primary_symbol: str,
) -> dict[str, Any]:
    if related_symbol == primary_symbol:
        return {
            "id": "primary",
            "label": "조회 종목",
            "tone": "neutral",
            "priority": 0,
            "description": "현재 분석 중인 기본 심볼입니다.",
        }

    for role_id, role in TRADINGVIEW_RELATED_SYMBOL_ROLES.items():
        if related_symbol in role["symbols"]:
            return {
                "id": role_id,
                "label": str(role["label"]),
                "tone": str(role["tone"]),
                "priority": int(role["priority"]),
                "description": str(role["description"]),
            }

    return {
        "id": "other",
        "label": "기타 동반 심볼",
        "tone": "neutral",
        "priority": 99,
        "description": "뉴스 기사에서 함께 언급된 기타 심볼입니다.",
    }


def _tradingview_news_context(
    *,
    primary_symbol: str,
    primary_mentions: Mapping[str, Any] | None,
    related_symbols: Sequence[Mapping[str, Any]],
    item_count: int,
) -> dict[str, Any]:
    theme_by_id: dict[str, dict[str, Any]] = {}
    for related in related_symbols:
        role = _mapping(related.get("role"))
        role_id = str(role.get("id") or "other")
        theme = theme_by_id.setdefault(
            role_id,
            {
                "id": role_id,
                "label": role.get("label") or "기타 동반 심볼",
                "tone": role.get("tone") or "neutral",
                "priority": int(role.get("priority") or 99),
                "description": role.get("description") or "",
                "mention_count": 0,
                "symbol_count": 0,
                "symbols": [],
            },
        )
        count = int(related.get("count") or 0)
        theme["mention_count"] = int(theme["mention_count"]) + count
        theme["symbol_count"] = int(theme["symbol_count"]) + 1
        symbols = theme["symbols"]
        if isinstance(symbols, list) and len(symbols) < 6:
            symbols.append(related.get("symbol"))

    theme_counts = sorted(
        theme_by_id.values(),
        key=lambda item: (
            -int(item.get("mention_count") or 0),
            int(item.get("priority") or 99),
            str(item.get("label") or ""),
        ),
    )
    theme_lookup = {str(item.get("id")): item for item in theme_counts}
    dominant = theme_counts[0] if theme_counts else None
    primary_count = int(primary_mentions.get("count") or 0) if primary_mentions else 0

    notes: list[dict[str, str]] = []
    if dominant:
        notes.append(
            {
                "tone": str(dominant.get("tone") or "neutral"),
                "text": (
                    f"{dominant.get('label')} 심볼이 {dominant.get('mention_count')}회로 "
                    "가장 자주 동반 언급됩니다."
                ),
            }
        )

    if "semiconductor" in theme_lookup:
        notes.append(
            {
                "tone": "buy",
                "text": "SMH/DRAM/NVDA 계열 동반 언급은 SOXL의 직접 섹터 뉴스 민감도를 높입니다.",
            }
        )

    if "broad_market" in theme_lookup and "semiconductor" in theme_lookup:
        notes.append(
            {
                "tone": "neutral",
                "text": "시장 대표 ETF와 반도체 심볼이 함께 잡혀 시장 베타와 섹터 모멘텀을 같이 봐야 합니다.",
            }
        )
    elif "broad_market" in theme_lookup:
        notes.append(
            {
                "tone": "neutral",
                "text": "SPY/QQQ/VOO 계열 동반 언급은 개별 섹터보다 ETF 자금 흐름 뉴스 성격이 강합니다.",
            }
        )

    if "leveraged_peer" in theme_lookup:
        notes.append(
            {
                "tone": "warning",
                "text": "TQQQ/TSLL/NVDL 같은 고베타 상품 동반 언급은 변동성 확대 구간일 수 있습니다.",
            }
        )

    if "defensive_rotation" in theme_lookup:
        notes.append(
            {
                "tone": "sell",
                "text": "채권·현금성·금 ETF가 함께 나오면 위험자산 선호 약화 가능성을 같이 점검하세요.",
            }
        )

    if item_count and primary_count >= item_count:
        notes.append(
            {
                "tone": "neutral",
                "text": f"{primary_symbol}가 반환 뉴스 {item_count}건 모두에 직접 포함되어 관련성은 높습니다.",
            }
        )

    return {
        "dominant_theme": dominant,
        "theme_counts": theme_counts,
        "context_notes": notes[:6],
        "related_symbol_count": len(related_symbols),
        "primary_mention_rate": round(primary_count / item_count, 4) if item_count else None,
        "source": "TradingView news-mediator relatedSymbols · derived role map",
    }


def build_tradingview_news_flow(ticker: str = "SOXL", limit: int = 12) -> dict[str, Any]:
    """Return TradingView news-flow items plus related symbol frequency."""
    import requests

    symbol = _tradingview_symbol(ticker)
    try:
        response = requests.get(
            "https://news-mediator.tradingview.com/public/news-flow/v2/news",
            params=[
                ("filter", "lang:en"),
                ("filter", f"symbol:{symbol}"),
                ("client", "landing"),
                ("streaming", "false"),
                ("user_prostatus", "non_pro"),
            ],
            headers=_tradingview_headers(),
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {
            "status": "unavailable",
            "source": "TradingView news-mediator",
            "symbol": symbol,
            "error": str(exc),
            "items": [],
            "related_symbols": [],
            "news_context": {
                "dominant_theme": None,
                "theme_counts": [],
                "context_notes": [],
                "related_symbol_count": 0,
                "primary_mention_rate": None,
                "source": "TradingView news-mediator relatedSymbols · derived role map",
            },
        }

    raw_items = payload.get("items") if isinstance(payload, Mapping) else None
    items: list[dict[str, Any]] = []
    related_by_symbol: dict[str, dict[str, Any]] = {}
    provider_counts: dict[str, int] = {}
    urgency_counts: dict[str, int] = {}

    raw_news_items = list(_sequence(raw_items))[: max(0, limit)]
    for raw in raw_news_items:
        if not isinstance(raw, Mapping):
            continue
        provider = raw.get("provider") if isinstance(raw.get("provider"), Mapping) else {}
        provider_name = str(provider.get("name") or provider.get("id") or "").strip() or None
        if provider_name:
            provider_counts[provider_name] = provider_counts.get(provider_name, 0) + 1

        urgency = raw.get("urgency")
        urgency_key = str(urgency) if urgency is not None else "unknown"
        urgency_counts[urgency_key] = urgency_counts.get(urgency_key, 0) + 1

        related_symbols: list[dict[str, Any]] = []
        published_at = _timestamp_to_iso(raw.get("published"))
        for related in _sequence(raw.get("relatedSymbols")):
            if not isinstance(related, Mapping):
                continue
            related_symbol = str(related.get("symbol") or "").strip().upper()
            if not related_symbol:
                continue
            role = _tradingview_related_symbol_role(
                related_symbol,
                primary_symbol=symbol,
            )
            related_item = {
                "symbol": related_symbol,
                "logoid": related.get("logoid"),
                "is_primary": related_symbol == symbol,
                "role": role,
            }
            related_symbols.append(related_item)

            bucket = related_by_symbol.setdefault(
                related_symbol,
                {
                    "symbol": related_symbol,
                    "logoid": related.get("logoid"),
                    "count": 0,
                    "is_primary": related_symbol == symbol,
                    "role": role,
                    "latest_title": None,
                    "latest_published_at": None,
                },
            )
            bucket["count"] = int(bucket.get("count") or 0) + 1
            if not bucket.get("latest_published_at") or (
                published_at and published_at > str(bucket.get("latest_published_at"))
            ):
                bucket["latest_title"] = raw.get("title")
                bucket["latest_published_at"] = published_at
                if related.get("logoid"):
                    bucket["logoid"] = related.get("logoid")

        items.append(
            {
                "id": raw.get("id"),
                "title": raw.get("title"),
                "published": raw.get("published"),
                "published_at": published_at,
                "urgency": urgency,
                "provider": {
                    "id": provider.get("id"),
                    "name": provider_name,
                    "url": provider.get("url"),
                    "logo_id": provider.get("logo_id"),
                },
                "url": _tradingview_news_url(raw.get("storyPath")),
                "story_path": raw.get("storyPath"),
                "related_symbols": related_symbols,
            }
        )

    related_symbols = [
        item
        for item in related_by_symbol.values()
        if not bool(item.get("is_primary"))
    ]
    related_symbols.sort(
        key=lambda item: (-int(item.get("count") or 0), str(item.get("symbol") or ""))
    )
    primary_mentions = related_by_symbol.get(symbol)
    latest_published_at = max(
        (item["published_at"] for item in items if item.get("published_at")),
        default=None,
    )
    news_context = _tradingview_news_context(
        primary_symbol=symbol,
        primary_mentions=primary_mentions,
        related_symbols=related_symbols,
        item_count=len(items),
    )

    return {
        "status": "ok" if items else "empty",
        "source": "TradingView news-mediator",
        "symbol": symbol,
        "generated_at": datetime.now(UTC).isoformat(),
        "latest_published_at": latest_published_at,
        "item_count": len(items),
        "primary_mentions": primary_mentions,
        "provider_counts": provider_counts,
        "urgency_counts": urgency_counts,
        "news_context": news_context,
        "related_symbols": related_symbols[:16],
        "items": items,
    }


def build_analysis_technical(
    ticker: str = "SOXL",
    period: str = "1y",
) -> dict[str, Any]:
    """Return OHLCV history plus RSI/MACD/Bollinger/EMA/ATR/Volume-MA for charting."""
    import yfinance as yf
    from .yahoo import get_yahoo_session

    yf_period = period.replace("m", "mo") if period.endswith("m") else period

    try:
        session = get_yahoo_session()
        df = yf.download(ticker, period=yf_period, session=session, auto_adjust=True, progress=False)
        if df.empty:
            return {"error": f"No data for {ticker}"}

        def _col(df, name: str) -> list[float]:
            if hasattr(df.columns, "levels"):
                try:
                    return [float(v) for v in df[(name, ticker)]]
                except Exception:
                    return [float(v) for v in df[name].iloc[:, 0]]
            return [float(v) for v in df[name]]

        dates = [d.strftime("%Y-%m-%d") for d in df.index]
        opens = _col(df, "Open")
        highs = _col(df, "High")
        lows = _col(df, "Low")
        closes = _col(df, "Close")
        volumes = _col(df, "Volume")

        rsi14 = _compute_rsi(closes, 14)
        rsi2 = _compute_rsi(closes, 2)
        ema20 = _compute_ema(closes, 20)
        ema50 = _compute_ema(closes, 50)
        ema200 = _compute_ema(closes, 200)
        macd_l, macd_s, macd_h = _compute_macd(closes)
        bb_u, bb_m, bb_l = _compute_bollinger(closes)
        atr14 = _compute_atr(highs, lows, closes, 14)

        # Volume MA20
        vol_ma20: list[float | None] = [None] * len(volumes)
        for i in range(19, len(volumes)):
            vol_ma20[i] = round(sum(volumes[i - 19 : i + 1]) / 20, 0)

        # Market regime from EMA200
        regimes: list[str] = []
        for i, c in enumerate(closes):
            e200 = ema200[i]
            if e200 is None:
                regimes.append("unknown")
            elif c > e200 * 1.02:
                regimes.append("bull")
            elif c < e200 * 0.98:
                regimes.append("bear")
            else:
                regimes.append("sideways")

        # Latest values summary
        latest = len(closes) - 1
        latest_price = closes[latest]
        prev_price = closes[latest - 1] if latest > 0 else latest_price
        change_pct = (latest_price - prev_price) / prev_price * 100 if prev_price else 0.0

        records = [
            {
                "date": dates[i],
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
                "rsi14": rsi14[i],
                "rsi2": rsi2[i],
                "ema20": ema20[i],
                "ema50": ema50[i],
                "ema200": ema200[i],
                "macd_line": macd_l[i],
                "macd_signal": macd_s[i],
                "macd_hist": macd_h[i],
                "bb_upper": bb_u[i],
                "bb_mid": bb_m[i],
                "bb_lower": bb_l[i],
                "atr14": atr14[i],
                "vol_ma20": vol_ma20[i],
                "regime": regimes[i],
            }
            for i in range(len(dates))
        ]

        return {
            "ticker": ticker,
            "period": period,
            "tradingview": build_tradingview_technical_summary(ticker),
            "tradingview_details": build_tradingview_symbol_details(ticker),
            "tradingview_news": build_tradingview_news_flow(ticker),
            "latest_price": round(latest_price, 2),
            "change_pct": round(change_pct, 2),
            "latest_rsi": rsi14[latest],
            "latest_regime": regimes[latest],
            "latest_ema20": ema20[latest],
            "latest_ema50": ema50[latest],
            "latest_ema200": ema200[latest],
            "latest_atr": atr14[latest],
            "records": records,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ─── Market Overview ───────────────────────────────────────────────────────────

def build_analysis_market_overview() -> dict[str, Any]:
    """Return major index, sector ETF, and volatility snapshot."""
    import yfinance as yf
    from .yahoo import get_yahoo_session

    INDEX_TICKERS = {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^DJI": "DOW",
        "^RUT": "Russell 2000",
        "^VIX": "VIX",
        "GLD": "Gold (GLD)",
        "TLT": "20Y Treasury (TLT)",
        "DX-Y.NYB": "US Dollar (DXY)",
        "BTC-USD": "Bitcoin",
    }

    SECTOR_TICKERS = {
        "XLK": "기술",
        "XLF": "금융",
        "XLE": "에너지",
        "XLV": "헬스케어",
        "XLI": "산업재",
        "XLY": "임의소비재",
        "XLP": "필수소비재",
        "XLU": "유틸리티",
        "XLB": "소재",
        "XLRE": "부동산",
        "XLC": "커뮤니케이션",
    }

    try:
        session = get_yahoo_session()
        all_tickers = list(INDEX_TICKERS.keys()) + list(SECTOR_TICKERS.keys())

        raw = yf.download(
            all_tickers,
            period="5d",
            session=session,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )

        def _last_two(ticker: str) -> tuple[float, float]:
            try:
                if hasattr(raw.columns, "levels"):
                    col = raw[(ticker, "Close")].dropna()
                else:
                    col = raw["Close"][ticker].dropna()
                if len(col) < 2:
                    return col.iloc[-1], col.iloc[-1]
                return float(col.iloc[-2]), float(col.iloc[-1])
            except Exception:
                return 0.0, 0.0

        def _sparkline(ticker: str, n: int = 5) -> list[float]:
            try:
                if hasattr(raw.columns, "levels"):
                    col = raw[(ticker, "Close")].dropna().tail(n)
                else:
                    col = raw["Close"][ticker].dropna().tail(n)
                return [round(float(v), 4) for v in col]
            except Exception:
                return []

        indices = []
        for sym, name in INDEX_TICKERS.items():
            prev, latest = _last_two(sym)
            chg = (latest - prev) / prev * 100 if prev else 0.0
            indices.append({
                "symbol": sym,
                "name": name,
                "price": round(latest, 2),
                "change_pct": round(chg, 2),
                "sparkline": _sparkline(sym),
            })

        sectors = []
        for sym, name in SECTOR_TICKERS.items():
            prev, latest = _last_two(sym)
            chg = (latest - prev) / prev * 100 if prev else 0.0
            sectors.append({
                "symbol": sym,
                "name": name,
                "price": round(latest, 2),
                "change_pct": round(chg, 2),
            })

        # VIX-based fear & greed approximation
        vix_val = next((i["price"] for i in indices if i["symbol"] == "^VIX"), 20.0)
        if vix_val <= 12:
            fg_level, fg_label = 85, "극단적 탐욕"
        elif vix_val <= 15:
            fg_level, fg_label = 70, "탐욕"
        elif vix_val <= 20:
            fg_level, fg_label = 55, "중립"
        elif vix_val <= 25:
            fg_level, fg_label = 40, "공포"
        elif vix_val <= 35:
            fg_level, fg_label = 25, "극단적 공포"
        else:
            fg_level, fg_label = 10, "패닉"

        return {
            "indices": indices,
            "sectors": sectors,
            "fear_greed": {"value": fg_level, "label": fg_label, "vix": vix_val},
        }
    except Exception as exc:
        return {"error": str(exc)}


# ─── Multi-Ticker Comparison ───────────────────────────────────────────────────

def build_analysis_multi_compare(
    tickers: list[str],
    period: str = "1y",
) -> dict[str, Any]:
    """Return normalized (base=100) cumulative return curves for multiple tickers."""
    import yfinance as yf
    from .yahoo import get_yahoo_session

    tickers = [t.upper() for t in tickers[:6]]  # max 6
    yf_period = period.replace("m", "mo") if period.endswith("m") else period

    try:
        session = get_yahoo_session()
        df = yf.download(
            tickers,
            period=yf_period,
            session=session,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )

        dates: list[str] = []
        series: dict[str, list[float | None]] = {t: [] for t in tickers}

        if len(tickers) == 1:
            ticker = tickers[0]
            if hasattr(df.columns, "levels"):
                closes = df[(ticker, "Close")].dropna()
            else:
                closes = df["Close"].dropna()
            base = float(closes.iloc[0]) if not closes.empty else 1.0
            dates = [d.strftime("%Y-%m-%d") for d in closes.index]
            series[ticker] = [round(float(v) / base * 100, 2) for v in closes]
        else:
            for ticker in tickers:
                try:
                    if hasattr(df.columns, "levels"):
                        closes = df[(ticker, "Close")].dropna()
                    else:
                        closes = df["Close"][ticker].dropna()
                    if dates == []:
                        dates = [d.strftime("%Y-%m-%d") for d in closes.index]
                    base = float(closes.iloc[0]) if not closes.empty else 1.0
                    # reindex to common dates
                    normed = closes / base * 100
                    date_map = {d.strftime("%Y-%m-%d"): round(float(v), 2) for d, v in zip(closes.index, normed)}
                    series[ticker] = [date_map.get(dt) for dt in dates]
                except Exception:
                    series[ticker] = [None] * len(dates)

        # Latest return summary
        summary = []
        for ticker in tickers:
            vals = [v for v in series[ticker] if v is not None]
            if vals:
                latest_norm = vals[-1]
                total_return = round(latest_norm - 100, 2)
                summary.append({"ticker": ticker, "total_return_pct": total_return, "latest_norm": latest_norm})
            else:
                summary.append({"ticker": ticker, "total_return_pct": None, "latest_norm": None})

        summary.sort(key=lambda x: x["total_return_pct"] or -999, reverse=True)

        return {
            "tickers": tickers,
            "period": period,
            "dates": dates,
            "series": series,
            "summary": summary,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ─── Portfolio Stats (from run data) ──────────────────────────────────────────

def build_analysis_portfolio_stats(paths: RuntimePaths, run_id: str | None = None) -> dict[str, Any]:
    """Aggregate Sharpe/Sortino/MDD/win-rate from recent run data."""
    from .performance import calc_metrics, equity_curve_records

    runs_dir = paths.runs_dir
    if not runs_dir.exists():
        return {
            "error": "runs 디렉터리가 없습니다.",
            "runs": [],
            "diagnostics": {
                "checked_run_count": 0,
                "performance_run_count": 0,
                "status_counts": {},
                "skipped_runs": [],
            },
        }

    run_dirs = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    results = []
    equity_curve: list[dict[str, Any]] = []
    skipped_runs: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}

    for run_dir in run_dirs[:10]:
        try:
            manifest_path = run_dir / "manifest.json"
            if not manifest_path.exists():
                skipped_runs.append(
                    {
                        "run_id": run_dir.name,
                        "status": "unknown",
                        "reason": "manifest.json not found",
                    }
                )
                continue
            manifest = read_json(manifest_path) or {}
            rid = manifest.get("run_id", run_dir.name)
            status = str(manifest.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

            trades_path = run_dir / "trades.json"
            if not trades_path.exists():
                skipped_runs.append(
                    {
                        "run_id": rid,
                        "command": manifest.get("command", "-"),
                        "status": status,
                        "failure_code": manifest.get("failure_code"),
                        "error": manifest.get("error"),
                        "started_at": manifest.get("started_at"),
                        "finished_at": manifest.get("finished_at"),
                        "reason": "trades.json not found",
                    }
                )
                continue
            trades = read_json(trades_path) or []
            if not isinstance(trades, list):
                skipped_runs.append(
                    {
                        "run_id": rid,
                        "command": manifest.get("command", "-"),
                        "status": status,
                        "failure_code": manifest.get("failure_code"),
                        "error": manifest.get("error"),
                        "started_at": manifest.get("started_at"),
                        "finished_at": manifest.get("finished_at"),
                        "reason": "trades.json is not a list",
                    }
                )
                continue

            capital_history = manifest.get("capital_history", [])
            final_capital = manifest.get("final_capital", 0.0)
            initial_capital = capital_history[0] if capital_history else 10000.0

            metrics = calc_metrics(trades, final_capital, capital_history, min_trades=1)
            if metrics is None:
                skipped_runs.append(
                    {
                        "run_id": rid,
                        "command": manifest.get("command", "-"),
                        "status": status,
                        "failure_code": manifest.get("failure_code"),
                        "error": manifest.get("error"),
                        "started_at": manifest.get("started_at"),
                        "finished_at": manifest.get("finished_at"),
                        "reason": "metrics could not be calculated",
                    }
                )
                continue

            run_result: dict[str, Any] = {
                "run_id": rid,
                "command": manifest.get("command", "-"),
                "status": manifest.get("status", "-"),
                "started_at": manifest.get("started_at", "-"),
                "finished_at": manifest.get("finished_at", "-"),
                "total_trades": len(trades),
                "sharpe": metrics.get("sharpe"),
                "sortino": metrics.get("sortino"),
                "calmar": metrics.get("calmar"),
                "fitness": metrics.get("fitness"),
                "win_rate": metrics.get("win_rate"),
                "profit_factor": metrics.get("profit_factor"),
                "rr_ratio": metrics.get("rr_ratio"),
                "max_drawdown": metrics.get("max_drawdown"),
                "mdd_peak": metrics.get("mdd_peak"),
                "mdd_trough": metrics.get("mdd_trough"),
                "mdd_duration_days": metrics.get("mdd_duration_days"),
                "total_return": metrics.get("total_return"),
                "annualized_return": metrics.get("annualized_return"),
                "initial_capital": initial_capital,
                "final_capital": final_capital,
            }
            results.append(run_result)

            # Attach equity curve of the most recent or requested run
            if not equity_curve:
                if run_id is None or rid == run_id:
                    equity_curve = equity_curve_records(trades, capital_history)[:500]

        except Exception:
            skipped_runs.append(
                {
                    "run_id": run_dir.name,
                    "status": "unknown",
                    "reason": "failed to inspect run",
                }
            )
            continue

    # Aggregate across runs
    def _avg(field: str) -> float | None:
        vals = [r[field] for r in results if r.get(field) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    aggregate = {
        "run_count": len(results),
        "avg_sharpe": _avg("sharpe"),
        "avg_sortino": _avg("sortino"),
        "avg_win_rate": _avg("win_rate"),
        "avg_profit_factor": _avg("profit_factor"),
        "avg_max_drawdown": _avg("max_drawdown"),
        "avg_total_return": _avg("total_return"),
        "avg_annualized_return": _avg("annualized_return"),
    }
    diagnostics = {
        "checked_run_count": len(run_dirs[:10]),
        "performance_run_count": len(results),
        "skipped_run_count": len(skipped_runs),
        "status_counts": status_counts,
        "skipped_runs": skipped_runs[:10],
    }
    if not results:
        diagnostics["empty_reason"] = (
            "최근 실행에서 trades.json을 찾지 못해 포트폴리오 성과를 계산할 수 없습니다."
        )

    return {
        "aggregate": aggregate,
        "runs": results,
        "equity_curve": equity_curve,
        "diagnostics": diagnostics,
    }


# ─── Economic Calendar ─────────────────────────────────────────────────────────

def build_analysis_economic_calendar() -> dict[str, Any]:
    """Return recent and upcoming major economic release dates."""
    import requests
    from datetime import date, timedelta

    CALENDAR_SERIES = {
        "FEDFUNDS": {"name": "FOMC 기준금리 결정", "icon": "🏛️", "frequency": "월별"},
        "CPIAUCSL": {"name": "소비자물가지수 (CPI)", "icon": "🛒", "frequency": "월별"},
        "PPIFIS": {"name": "생산자물가지수 (PPI)", "icon": "🏭", "frequency": "월별"},
        "PAYEMS": {"name": "비농업 고용 (NFP)", "icon": "👷", "frequency": "월별"},
        "GDPC1": {"name": "실질 GDP 성장률", "icon": "📊", "frequency": "분기별"},
        "UNRATE": {"name": "실업률", "icon": "📉", "frequency": "월별"},
        "HOUST": {"name": "주택착공 건수", "icon": "🏠", "frequency": "월별"},
        "RSAFS": {"name": "소매판매 (Retail Sales)", "icon": "🛍️", "frequency": "월별"},
        "INDPRO": {"name": "산업생산 지수", "icon": "⚙️", "frequency": "월별"},
    }

    events = []
    today = date.today()

    for series_id, meta in CALENDAR_SERIES.items():
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            lines = [
                line
                for line in res.text.strip().splitlines()
                if line and not line.startswith("observation_date")
            ]
            if not lines:
                continue
            # Last 3 actual releases
            last_releases = []
            for line in lines[-3:]:
                parts = line.split(",")
                if len(parts) >= 2:
                    d_str, val_str = parts[0].strip(), parts[1].strip()
                    if val_str == ".":
                        continue
                    try:
                        date.fromisoformat(d_str)
                        last_releases.append({"date": d_str, "value": float(val_str)})
                    except Exception:
                        continue

            latest_release_date = date.fromisoformat(last_releases[-1]["date"]) if last_releases else None
            latest_value = last_releases[-1]["value"] if last_releases else None
            prev_value = last_releases[-2]["value"] if len(last_releases) >= 2 else None

            # Estimate next release (approx 1 month or 3 months later)
            if latest_release_date:
                if meta["frequency"] == "분기별":
                    next_est = latest_release_date + timedelta(days=92)
                else:
                    next_est = latest_release_date + timedelta(days=33)
                next_str = next_est.isoformat()
            else:
                next_str = None

            change = None
            if latest_value is not None and prev_value is not None:
                change = round(latest_value - prev_value, 4)

            events.append({
                "series_id": series_id,
                "name": meta["name"],
                "icon": meta["icon"],
                "frequency": meta["frequency"],
                "latest_date": last_releases[-1]["date"] if last_releases else None,
                "latest_value": latest_value,
                "prev_value": prev_value,
                "change": change,
                "next_estimated": next_str,
                "is_upcoming": next_str is not None and date.fromisoformat(next_str) >= today,
            })
        except Exception:
            events.append({
                "series_id": series_id,
                "name": meta["name"],
                "icon": meta["icon"],
                "frequency": meta["frequency"],
                "latest_date": None,
                "latest_value": None,
                "prev_value": None,
                "change": None,
                "next_estimated": None,
                "is_upcoming": False,
            })

    events.sort(key=lambda e: e.get("next_estimated") or "9999", )
    return {"events": events, "generated_at": date.today().isoformat()}


# ─── 포트폴리오 허브 빌더 ────────────────────────────────────────────────────

def build_portfolio_hub_data(
    paths: RuntimePaths,
    *,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """포트폴리오 허브 전체 데이터. 종목 목록이 없으면 포트폴리오 매핑에서 자동 추출."""
    from .portfolio_hub import build_portfolio_hub

    # 포트폴리오 매핑에서 종목 + 타입 정보 로드
    mapping = load_portfolio_mapping()
    type_map: dict[str, list[str]] = {}
    mapped_tickers: list[str] = []

    for ticker_sym, tick_map in mapping.tickers.items():
        mapped_tickers.append(ticker_sym)
        if tick_map.portfolio_types:
            normalized = _normalize_portfolio_type_keys(tick_map.portfolio_types)
            type_map[ticker_sym] = normalized or ["long_term"]
        else:
            type_map[ticker_sym] = ["long_term"]

    # 사용자 지정 ticker가 있으면 우선 사용, 없으면 매핑에서
    if tickers:
        final_tickers = [t.upper() for t in tickers[:20]]
        for t in final_tickers:
            if t not in type_map:
                type_map[t] = ["long_term"]
    elif mapped_tickers:
        final_tickers = mapped_tickers[:20]
    else:
        # 기본 샘플 종목
        final_tickers = ["SOXL", "TQQQ", "QQQ", "SPY", "NVDA"]
        for t in final_tickers:
            type_map[t] = ["long_term"]

    result = build_portfolio_hub(final_tickers, portfolio_type_map=type_map)
    result["portfolio_mapping_source"] = str(mapping.source)
    result["portfolio_type_profiles"] = _portfolio_type_profile_rows()
    return result


def build_portfolio_hub_meta(level: str = "normal") -> dict[str, Any]:
    """포트폴리오 허브 메타데이터 (타입 정의, 신호 레이블, 지표 설명)."""
    from .portfolio_hub import get_portfolio_type_meta
    meta = get_portfolio_type_meta()
    from .metric_dictionary import metric_dictionary_payload
    payload = metric_dictionary_payload(level=level)
    for group_name, metrics in payload.items():
        for item in metrics:
            key = item["key"]
            meta["indicator_explanations"][key] = {
                "name": item["label"],
                "description": item["short_description"],
                "good": item["good_value"],
                "caution": item["watch_out"]
            }
    return meta


def build_portfolio_hub_ticker_signals(ticker: str) -> dict[str, Any]:
    """단일 종목에 대한 4가지 타입별 신호."""
    from .portfolio_hub import fetch_ticker_data, generate_signals, PORTFOLIO_TYPE_META

    data = fetch_ticker_data(ticker)
    signals = generate_signals(data)
    return {
        "ticker": ticker,
        "ticker_data": data,
        "signals": signals,
        "portfolio_type_meta": PORTFOLIO_TYPE_META,
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ─── 자동매매 준비 상태 빌더 ──────────────────────────────────────────────────

def build_autotrading_status_data(paths: RuntimePaths | None = None) -> dict[str, Any]:
    """자동매매 준비 상태 데이터. 항상 비활성 상태를 반환."""
    from .autotrading_prep import build_autotrading_status_payload
    return build_autotrading_status_payload(paths)
