"""autotrading_prep.py — 자동매매 준비 구조 (현재 항상 비활성).

이 모듈은 향후 자동매매 기능을 안전하게 추가할 수 있도록 구조를 미리 준비합니다.
현재는 모든 자동매매 기능이 비활성 상태입니다.

원칙:
    - 자동매매는 기본값이 항상 비활성 (disabled)
    - 모의투자 → 반자동 → 자동 순서로 단계적 확장
    - 주문 전 검증, 한도, 긴급 중지, 로그가 모두 갖춰진 후에만 활성화 가능
    - 이 모듈을 import해도 실제 주문은 절대 실행되지 않음
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .io import read_json
from .operational_status import latest_run_dir
from .paths import RuntimePaths

UTC = timezone.utc

# ─── 안전장치 요구사항 체크리스트 ────────────────────────────────────────────

SAFETY_REQUIREMENTS = [
    {
        "id": "paper_trading_validated",
        "label": "모의투자 검증 완료",
        "description": "최소 30일 이상 모의투자로 전략을 검증해야 합니다.",
        "required": True,
        "current": False,
    },
    {
        "id": "user_confirmed",
        "label": "사용자 명시적 승인",
        "description": "사용자가 자동매매 위험을 인지하고 명시적으로 승인해야 합니다.",
        "required": True,
        "current": False,
    },
    {
        "id": "daily_loss_limit_set",
        "label": "일별 손실 한도 설정",
        "description": "하루에 허용할 최대 손실 한도를 설정해야 합니다 (예: 계좌의 2%).",
        "required": True,
        "current": False,
    },
    {
        "id": "position_limit_set",
        "label": "종목별 주문 한도 설정",
        "description": "단일 종목에 투자할 수 있는 최대 금액 또는 비중을 설정해야 합니다.",
        "required": True,
        "current": False,
    },
    {
        "id": "emergency_stop_ready",
        "label": "긴급 중지 기능 준비",
        "description": "언제든지 모든 자동매매를 즉시 중지할 수 있는 기능이 있어야 합니다.",
        "required": True,
        "current": False,
    },
    {
        "id": "order_log_enabled",
        "label": "거래 로그 활성화",
        "description": "모든 주문 시도와 결과가 로그에 기록되어야 합니다.",
        "required": True,
        "current": False,
    },
    {
        "id": "pre_order_validation",
        "label": "주문 전 검증 로직",
        "description": "주문 실행 전 리스크, 한도, 데이터 품질을 자동으로 검증해야 합니다.",
        "required": True,
        "current": False,
    },
]


AutoTradingPhase = Literal["disabled", "paper", "semi_auto", "auto"]

READINESS_THRESHOLDS = {
    "semi_auto_review": 80,
    "auto_candidate": 90,
}

READINESS_WEIGHTS = {
    "data_validation": 20,
    "risk_gate": 20,
    "shadow_period": 20,
    "paper_performance": 15,
    "implementation_shortfall": 15,
    "kill_switch": 10,
}

PAPER_PROMOTION_REQUIREMENTS = {
    "min_orders": 20,
    "min_fill_rate": 0.9,
    "max_shortfall_bps": 50,
    "min_realized_pnl": 0,
}


@dataclass
class AutoTradingStatus:
    """자동매매 현재 상태. 기본값은 항상 비활성(disabled)."""

    phase: AutoTradingPhase = "disabled"
    enabled: bool = False  # 항상 False (안전장치 미충족)
    safety_checks_passed: int = 0
    safety_checks_required: int = len(SAFETY_REQUIREMENTS)
    safety_requirements: list[dict[str, Any]] = field(default_factory=lambda: list(SAFETY_REQUIREMENTS))
    message: str = "자동매매는 현재 비활성 상태입니다. 모든 안전장치를 갖춘 후 단계적으로 활성화할 수 있습니다."
    warning: str = (
        "⚠️ 자동매매는 투자 원금 손실 위험이 있습니다. "
        "반드시 모의투자로 충분히 검증한 후, 손실 한도와 긴급 중지 기능을 갖춘 뒤 사용하세요."
    )
    disclaimer: str = (
        "이 시스템의 신호와 분석은 투자 추천이 아닙니다. "
        "투자 결정과 결과에 대한 책임은 전적으로 사용자에게 있습니다."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderCandidate:
    """신호 → 주문 후보 변환 결과. 실제 주문은 아님."""

    ticker: str
    portfolio_type: str
    signal: str
    signal_label: str
    direction: Literal["buy", "sell", "hold"] = "hold"
    suggested_pct: float = 0.0  # 포트폴리오 대비 비중 제안 (%)
    max_amount_krw: float = 0.0  # 최대 투자 금액 (KRW)
    stop_loss_pct: float = 0.0   # 손절 비율 (%)
    take_profit_pct: float = 0.0  # 목표 수익 비율 (%)
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    risk_checks_passed: bool = False
    data_quality: str = "unknown"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    is_executable: bool = False  # 항상 False (자동매매 비활성)
    not_executable_reason: str = "자동매매가 비활성 상태입니다"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_autotrading_status() -> AutoTradingStatus:
    """현재 자동매매 상태 반환. 항상 비활성."""
    passed = sum(1 for r in SAFETY_REQUIREMENTS if r.get("current", False))
    return AutoTradingStatus(
        phase="disabled",
        enabled=False,
        safety_checks_passed=passed,
        safety_checks_required=len(SAFETY_REQUIREMENTS),
    )


def signal_to_order_candidate(
    ticker: str,
    portfolio_type: str,
    signal_data: dict[str, Any],
    *,
    account_value_krw: float = 0.0,
    max_single_pct: float = 0.05,
) -> OrderCandidate:
    """신호 데이터를 주문 후보로 변환. 실제 주문은 실행하지 않음."""
    signal_key = signal_data.get("signal", "hold")
    reasons = signal_data.get("reasons", [])
    cautions = signal_data.get("cautions", [])

    direction: Literal["buy", "sell", "hold"]
    if signal_key in ("buy_candidate", "weak_buy"):
        direction = "buy"
        suggested_pct = max_single_pct if signal_key == "buy_candidate" else max_single_pct * 0.5
    elif signal_key in ("sell_candidate", "weak_sell"):
        direction = "sell"
        suggested_pct = max_single_pct
    else:
        direction = "hold"
        suggested_pct = 0.0

    max_amount = account_value_krw * suggested_pct

    # 포트폴리오 타입별 손절/목표 기본값
    _stops = {"short_term": 3.0, "swing": 7.0, "long_term": 15.0, "dividend": 10.0}
    _targets = {"short_term": 5.0, "swing": 12.0, "long_term": 25.0, "dividend": 15.0}

    return OrderCandidate(
        ticker=ticker,
        portfolio_type=portfolio_type,
        signal=signal_key,
        signal_label=signal_data.get("signal_label", signal_key),
        direction=direction,
        suggested_pct=round(suggested_pct * 100, 2),
        max_amount_krw=round(max_amount, 0),
        stop_loss_pct=_stops.get(portfolio_type, 10.0),
        take_profit_pct=_targets.get(portfolio_type, 15.0),
        reasons=reasons,
        cautions=cautions,
        risk_checks_passed=False,
        data_quality=signal_data.get("data_quality", "unknown"),
        is_executable=False,
        not_executable_reason="자동매매가 비활성 상태입니다. 모든 안전장치를 갖춘 후 사용하세요.",
    )


def build_autotrading_readiness_score(paths: RuntimePaths | None = None) -> dict[str, Any]:
    """자동매매 전환 가능성을 0~100점으로 계산합니다. 실제 주문 가능 여부와는 분리됩니다."""
    if paths is None:
        components = [
            _readiness_component(
                key,
                _readiness_label(key),
                weight,
                0.0,
                "not_evaluated",
                "미검증",
                "runtime paths unavailable",
                "대시보드 runtime 경로가 없어 자동매매 준비 점수를 계산하지 못했습니다.",
            )
            for key, weight in READINESS_WEIGHTS.items()
        ]
        return _readiness_payload(components, latest_run=None)

    latest_dir = latest_run_dir(paths.runs_dir, execution_modes=None)
    manifest = _mapping(read_json(latest_dir / "manifest.json", default={})) if latest_dir else {}
    risk = _mapping(read_json(latest_dir / "risk_explanation.json", default={})) if latest_dir else {}
    operational = _mapping(read_json(paths.state_dir / "operational_status.json", default={}))
    paper_path, paper_report = _latest_paper_report(paths, latest_dir)

    components = [
        _data_validation_component(manifest),
        _risk_gate_component(risk),
        _shadow_period_component(operational),
        _paper_performance_component(paper_report, paper_path),
        _implementation_shortfall_component(paper_report, paper_path),
        _kill_switch_component(paper_report, paper_path),
    ]
    latest_run = str(manifest.get("run_id") or latest_dir.name) if latest_dir else None
    return _readiness_payload(components, latest_run=latest_run)


def build_paper_promotion_report(
    paths: RuntimePaths | None = None,
    readiness_score: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Paper Trading 결과로 반자동/자동 후보 승격 가능성을 설명합니다."""
    if readiness_score is None:
        readiness_score = build_autotrading_readiness_score(paths)

    if paths is None:
        source = "runtime paths unavailable"
        criteria = [
            _promotion_criterion(
                "paper_report",
                "Paper 결과 파일",
                "not_evaluated",
                False,
                "미검증",
                "paper_trading.json 필요",
                source,
                "대시보드 runtime 경로가 없어 Paper Trading 결과를 확인하지 못했습니다.",
            )
        ]
        return _paper_promotion_payload(criteria, readiness_score, None, source)

    latest_dir = latest_run_dir(paths.runs_dir, execution_modes=None)
    paper_path, paper_report = _latest_paper_report(paths, latest_dir)
    source = _paper_source(paper_path)
    criteria = _paper_promotion_criteria(paper_report, paper_path, readiness_score)
    return _paper_promotion_payload(criteria, readiness_score, paper_report, source)


def _paper_promotion_criteria(
    paper_report: Mapping[str, Any],
    paper_path: Path | None,
    readiness_score: Mapping[str, Any],
) -> list[dict[str, Any]]:
    source = _paper_source(paper_path)
    if not paper_report:
        return [
            _promotion_criterion(
                "paper_report",
                "Paper 결과 파일",
                "not_evaluated",
                False,
                "미검증",
                "paper_trading.json 필요",
                source,
                "Paper Trading 결과 파일을 찾지 못해 승격 판단을 보류합니다.",
            )
        ]

    submitted = _number(paper_report.get("orders_submitted"), 0)
    filled = _number(paper_report.get("orders_filled"), 0)
    blocked = _number(paper_report.get("orders_blocked"), 0)
    min_orders = _number(PAPER_PROMOTION_REQUIREMENTS["min_orders"], 20)
    order_passed = submitted >= min_orders and blocked <= 0
    order_status = "success" if order_passed else "blocked" if blocked > 0 else "warning"

    fill_rate = filled / submitted if submitted > 0 else None
    min_fill_rate = _number(PAPER_PROMOTION_REQUIREMENTS["min_fill_rate"], 0.9)
    fill_passed = fill_rate is not None and fill_rate >= min_fill_rate
    fill_status = (
        "success"
        if fill_passed
        else "not_evaluated"
        if fill_rate is None
        else "warning"
        if fill_rate >= 0.75
        else "blocked"
    )

    start = _number(paper_report.get("starting_equity"), 0)
    end = _number(paper_report.get("ending_equity"), start)
    realized = _number(paper_report.get("realized_pnl"), 0)
    return_pct = (end - start) / start if start > 0 else None
    pnl_passed = return_pct is not None and realized >= 0 and return_pct >= 0
    pnl_status = "success" if pnl_passed else "not_evaluated" if return_pct is None else "blocked"

    quality = _mapping(paper_report.get("execution_quality"))
    shortfall = quality.get("avg_implementation_shortfall_bps")
    shortfall_bps = _number(shortfall, 0) if shortfall is not None else None
    max_shortfall = _number(PAPER_PROMOTION_REQUIREMENTS["max_shortfall_bps"], 50)
    shortfall_passed = shortfall_bps is not None and shortfall_bps <= max_shortfall
    shortfall_status = (
        "success"
        if shortfall_passed
        else "not_evaluated"
        if shortfall_bps is None
        else "warning"
        if shortfall_bps <= 150
        else "blocked"
    )

    kill_switch = _mapping(paper_report.get("kill_switch"))
    kill_tripped = kill_switch.get("tripped") is True
    kill_passed = bool(kill_switch) and not kill_tripped
    kill_status = "success" if kill_passed else "blocked" if kill_tripped else "not_evaluated"

    score = _number(readiness_score.get("score"), 0)
    stage = str(readiness_score.get("stage") or "analysis_only")
    score_passed = score >= READINESS_THRESHOLDS["semi_auto_review"] and stage != "blocked"
    score_status = (
        "success"
        if score >= READINESS_THRESHOLDS["auto_candidate"] and stage != "blocked"
        else "warning"
        if score_passed
        else "blocked"
        if stage == "blocked"
        else "warning"
    )

    return [
        _promotion_criterion(
            "paper_orders",
            "Paper 주문 표본",
            order_status,
            order_passed,
            f"{submitted:.0f}건 · 차단 {blocked:.0f}건",
            f"{min_orders:.0f}건 이상 · 차단 0건",
            source,
            "승격 전에는 충분한 Paper 주문 표본과 차단 없는 실행 로그가 필요합니다.",
            {"orders_submitted": submitted, "orders_filled": filled, "orders_blocked": blocked},
        ),
        _promotion_criterion(
            "paper_fill_rate",
            "Paper 체결률",
            fill_status,
            fill_passed,
            _format_ratio(fill_rate),
            _format_ratio(min_fill_rate),
            source,
            "주문 의도가 시장 조건에서 안정적으로 체결되는지 확인합니다.",
            {"fill_rate": fill_rate, "orders_filled": filled, "orders_submitted": submitted},
        ),
        _promotion_criterion(
            "paper_pnl",
            "Paper 손익",
            pnl_status,
            pnl_passed,
            f"PnL {realized:.2f} · 수익률 {_format_ratio(return_pct)}",
            f"PnL {PAPER_PROMOTION_REQUIREMENTS['min_realized_pnl']:.0f} 이상",
            source,
            "승격 후보는 최소한 최근 Paper 세션에서 손실 전환이 없어야 합니다.",
            {"realized_pnl": realized, "return_pct": return_pct, "starting_equity": start, "ending_equity": end},
        ),
        _promotion_criterion(
            "paper_shortfall",
            "체결 비용",
            shortfall_status,
            shortfall_passed,
            "미검증" if shortfall_bps is None else f"{shortfall_bps:.1f} bps",
            f"{max_shortfall:.0f} bps 이하",
            source,
            "의사결정 가격과 실제 체결 가격의 괴리가 작아야 합니다.",
            {"avg_implementation_shortfall_bps": shortfall_bps},
        ),
        _promotion_criterion(
            "paper_kill_switch",
            "Kill switch",
            kill_status,
            kill_passed,
            "발동" if kill_tripped else "정상" if kill_switch else "미검증",
            "미발동",
            source,
            "최근 Paper Trading에서 긴급 중지 조건이 발동하면 승격을 차단합니다.",
            {"tripped": kill_tripped, "reasons": [str(item) for item in _sequence(kill_switch.get("reasons"))]},
        ),
        _promotion_criterion(
            "readiness_score",
            "자동매매 준비 점수",
            score_status,
            score_passed,
            f"{score:.1f}점 · {readiness_score.get('stage_label', stage)}",
            "반자동 80점 이상 · 자동 후보 90점 이상",
            "autotrading readiness score",
            "Paper 결과만으로 승격하지 않고 데이터·리스크·운영 증거를 함께 확인합니다.",
            {
                "score": score,
                "stage": stage,
                "auto_candidate_passed": score >= READINESS_THRESHOLDS["auto_candidate"] and stage == "auto_candidate",
            },
        ),
    ]


def _promotion_criterion(
    key: str,
    label: str,
    status: str,
    passed: bool,
    observed: str,
    required: str,
    source: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": key,
        "label": label,
        "status": status,
        "passed": bool(passed),
        "observed": observed,
        "required": required,
        "source": source,
        "message": message,
        "details": dict(details or {}),
    }


def _paper_promotion_payload(
    criteria: Sequence[Mapping[str, Any]],
    readiness_score: Mapping[str, Any],
    paper_report: Mapping[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    score = _number(readiness_score.get("score"), 0)
    stage = str(readiness_score.get("stage") or "analysis_only")
    has_report = bool(paper_report)
    all_passed = has_report and all(item.get("passed") is True for item in criteria)
    hard_blocked = any(item.get("status") == "blocked" for item in criteria)
    eligible_for_semi_auto = all_passed and score >= READINESS_THRESHOLDS["semi_auto_review"] and stage != "blocked"
    eligible_for_auto_candidate = all_passed and score >= READINESS_THRESHOLDS["auto_candidate"] and stage == "auto_candidate"
    status = (
        "not_evaluated"
        if not has_report
        else "success"
        if eligible_for_auto_candidate
        else "warning"
        if eligible_for_semi_auto
        else "blocked"
        if hard_blocked
        else "warning"
    )
    return {
        "status": status,
        "status_label": _paper_promotion_status_label(status, eligible_for_semi_auto, eligible_for_auto_candidate),
        "eligible_for_semi_auto": eligible_for_semi_auto,
        "eligible_for_auto_candidate": eligible_for_auto_candidate,
        "summary": _paper_promotion_summary(status, eligible_for_semi_auto, eligible_for_auto_candidate, has_report),
        "latest_run": readiness_score.get("latest_run"),
        "source": source,
        "requirements": dict(PAPER_PROMOTION_REQUIREMENTS),
        "criteria": [dict(item) for item in criteria],
        "next_actions": _paper_promotion_next_actions(criteria),
    }


def _paper_promotion_status_label(
    status: str,
    eligible_for_semi_auto: bool,
    eligible_for_auto_candidate: bool,
) -> str:
    if eligible_for_auto_candidate:
        return "자동 후보 검토 가능"
    if eligible_for_semi_auto:
        return "반자동 검토 가능"
    return {
        "not_evaluated": "Paper 미검증",
        "blocked": "승격 차단",
        "warning": "추가 검증 필요",
        "success": "승격 검토 가능",
    }.get(status, "추가 검증 필요")


def _paper_promotion_summary(
    status: str,
    eligible_for_semi_auto: bool,
    eligible_for_auto_candidate: bool,
    has_report: bool,
) -> str:
    if not has_report:
        return "Paper Trading 결과 파일이 없어 반자동·자동 후보 승격을 판단할 수 없습니다."
    if eligible_for_auto_candidate:
        return "Paper Trading 증거는 자동 후보 검토권에 도달했습니다. 실제 주문 전송은 여전히 비활성이고 별도 승인·한도 설정이 필요합니다."
    if eligible_for_semi_auto:
        return "Paper Trading 증거는 반자동 검토권에 도달했습니다. 사용자가 승인한 주문만 허용하는 단계가 적절합니다."
    if status == "blocked":
        return "Paper Trading 결과에 손실, 체결 품질, 차단 주문, kill switch 중 승격을 막는 조건이 있습니다."
    return "Paper Trading 표본이나 실행 품질이 아직 부족합니다. 승격 전 더 많은 세션을 누적하세요."


def _paper_promotion_next_actions(criteria: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    action_map = {
        "paper_report": "OrderIntent 기반 Paper Trading 세션을 실행해 paper_trading.json을 생성하세요.",
        "paper_orders": "최소 20건 이상의 Paper 주문 표본을 만들고 차단 주문 원인을 해소하세요.",
        "paper_fill_rate": "미체결 주문의 가격·수량·유동성 조건을 조정해 체결률을 높이세요.",
        "paper_pnl": "손실 전환 원인을 전략·포지션 크기·손절 조건별로 분해해 다시 검증하세요.",
        "paper_shortfall": "스프레드와 지연 비용을 줄이도록 주문 가격 산정과 체결 조건을 조정하세요.",
        "paper_kill_switch": "kill switch 발동 사유를 해소하고 새 Paper Trading 세션으로 재검증하세요.",
        "readiness_score": "데이터 검증, 리스크 게이트, shadow 기간을 보강해 준비 점수를 80점 이상으로 올리세요.",
    }
    weak = [item for item in criteria if item.get("passed") is not True]
    return [
        {
            "criterion": item.get("id"),
            "label": item.get("label"),
            "status": item.get("status"),
            "action": action_map.get(str(item.get("id")), "관련 Paper artifact를 확인하세요."),
            "source": item.get("source"),
        }
        for item in weak[:4]
    ]


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "미검증"
    return f"{value * 100:.1f}%"


def _data_validation_component(manifest: Mapping[str, Any]) -> dict[str, Any]:
    weight = READINESS_WEIGHTS["data_validation"]
    reports = [
        item
        for item in _mapping(manifest.get("data_reports")).values()
        if isinstance(item, Mapping) and "valid" in item
    ]
    if not reports:
        return _readiness_component(
            "data_validation",
            "데이터 검증률",
            weight,
            0.0,
            "not_evaluated",
            "미검증",
            "latest run manifest · data_reports",
            "최근 실행에서 data_reports를 찾지 못했습니다.",
        )
    passed = sum(item.get("valid") is True for item in reports)
    rate = passed / len(reports)
    status = "success" if rate >= 0.95 else "warning" if rate >= 0.8 else "blocked"
    return _readiness_component(
        "data_validation",
        "데이터 검증률",
        weight,
        weight * rate,
        status,
        f"{passed}/{len(reports)}",
        "latest run manifest · data_reports",
        "가격·입력 데이터 검증 성공률입니다.",
        {"rate": round(rate, 4), "passed": passed, "total": len(reports)},
    )


def _risk_gate_component(risk: Mapping[str, Any]) -> dict[str, Any]:
    weight = READINESS_WEIGHTS["risk_gate"]
    approved = int(_number(risk.get("approved_count"), 0))
    blocked = int(_number(risk.get("blocked_count"), 0))
    reviewed = approved + blocked
    if reviewed <= 0:
        hold_count = int(_number(risk.get("hold_count"), 0))
        return _readiness_component(
            "risk_gate",
            "리스크 통과율",
            weight,
            0.0,
            "not_evaluated",
            f"검토 0건 · 대기 {hold_count}건",
            "risk_explanation.json",
            "자동매매 전환을 판단할 매수 후보 리스크 심사 기록이 없습니다.",
            {"approved": approved, "blocked": blocked, "hold": hold_count},
        )
    rate = approved / reviewed
    status = "success" if rate >= 0.8 and blocked == 0 else "warning" if rate >= 0.5 else "blocked"
    return _readiness_component(
        "risk_gate",
        "리스크 통과율",
        weight,
        weight * rate,
        status,
        f"{approved}/{reviewed}",
        "risk_explanation.json",
        "매수 후보가 리스크 게이트를 통과한 비율입니다.",
        {"rate": round(rate, 4), "approved": approved, "blocked": blocked},
    )


def _shadow_period_component(operational: Mapping[str, Any]) -> dict[str, Any]:
    weight = READINESS_WEIGHTS["shadow_period"]
    promotion = _mapping(operational.get("promotion"))
    criteria = _sequence(promotion.get("criteria"))
    shadow_rule = next(
        (
            item
            for item in criteria
            if isinstance(item, Mapping) and item.get("name") == "shadow_days"
        ),
        {},
    )
    observed = _number(shadow_rule.get("observed"), len(_sequence(promotion.get("shadow_days"))))
    required = max(1.0, _number(shadow_rule.get("required"), 30))
    ratio = min(max(observed / required, 0.0), 1.0)
    status = "success" if ratio >= 1.0 else "warning" if observed > 0 else "blocked"
    return _readiness_component(
        "shadow_period",
        "Shadow 기간",
        weight,
        weight * ratio,
        status,
        f"{int(observed)}/{int(required)}일",
        "operational_status.json · promotion.shadow_days",
        "반자동·자동 전환 전에 shadow 운용 기록을 충분히 쌓았는지 봅니다.",
        {"observed_days": observed, "required_days": required, "ratio": round(ratio, 4)},
    )


def _paper_performance_component(
    paper_report: Mapping[str, Any],
    paper_path: Path | None,
) -> dict[str, Any]:
    weight = READINESS_WEIGHTS["paper_performance"]
    if not paper_report:
        return _readiness_component(
            "paper_performance",
            "Paper 성과",
            weight,
            0.0,
            "not_evaluated",
            "미검증",
            "paper trading report",
            "Paper Trading 결과 파일을 찾지 못했습니다.",
        )
    submitted = _number(paper_report.get("orders_submitted"), 0)
    filled = _number(paper_report.get("orders_filled"), 0)
    if submitted <= 0:
        return _readiness_component(
            "paper_performance",
            "Paper 성과",
            weight,
            0.0,
            "not_evaluated",
            "주문 0건",
            _paper_source(paper_path),
            "Paper Trading 주문 기록이 아직 없습니다.",
        )
    fill_rate = min(max(filled / submitted, 0.0), 1.0)
    realized = _number(paper_report.get("realized_pnl"), 0)
    start = _number(paper_report.get("starting_equity"), 0)
    end = _number(paper_report.get("ending_equity"), start)
    return_pct = (end - start) / start if start > 0 else 0.0
    pnl_factor = 1.0 if realized >= 0 and return_pct >= 0 else max(0.0, 1.0 + return_pct / 0.05)
    readiness = 0.6 * fill_rate + 0.4 * pnl_factor
    status = (
        "success"
        if fill_rate >= 0.9 and realized >= 0 and return_pct >= 0
        else "warning"
        if realized >= 0
        else "blocked"
    )
    return _readiness_component(
        "paper_performance",
        "Paper 성과",
        weight,
        weight * readiness,
        status,
        f"체결 {filled:.0f}/{submitted:.0f} · PnL {realized:.2f}",
        _paper_source(paper_path),
        "Paper 주문 체결률과 손익이 자동매매 전환에 충분한지 봅니다.",
        {
            "orders_submitted": submitted,
            "orders_filled": filled,
            "fill_rate": round(fill_rate, 4),
            "realized_pnl": realized,
            "return_pct": round(return_pct, 6),
        },
    )


def _implementation_shortfall_component(
    paper_report: Mapping[str, Any],
    paper_path: Path | None,
) -> dict[str, Any]:
    weight = READINESS_WEIGHTS["implementation_shortfall"]
    quality = _mapping(paper_report.get("execution_quality"))
    shortfall = quality.get("avg_implementation_shortfall_bps")
    if shortfall is None:
        return _readiness_component(
            "implementation_shortfall",
            "Shortfall 비용",
            weight,
            0.0,
            "not_evaluated",
            "미검증",
            _paper_source(paper_path),
            "Paper Trading 실행 품질에 implementation shortfall 값이 없습니다.",
        )
    bps = _number(shortfall, 0)
    ratio = 1.0 if bps <= 25 else max(0.0, 1.0 - (bps - 25) / 125)
    status = "success" if bps <= 50 else "warning" if bps <= 150 else "blocked"
    return _readiness_component(
        "implementation_shortfall",
        "Shortfall 비용",
        weight,
        weight * ratio,
        status,
        f"{bps:.1f} bps",
        _paper_source(paper_path),
        "결정가 대비 실제 체결 비용이 자동매매에 감당 가능한 수준인지 봅니다.",
        {"avg_implementation_shortfall_bps": bps},
    )


def _kill_switch_component(
    paper_report: Mapping[str, Any],
    paper_path: Path | None,
) -> dict[str, Any]:
    weight = READINESS_WEIGHTS["kill_switch"]
    kill_switch = _mapping(paper_report.get("kill_switch"))
    if not kill_switch:
        return _readiness_component(
            "kill_switch",
            "Kill switch",
            weight,
            0.0,
            "not_evaluated",
            "미검증",
            _paper_source(paper_path),
            "Paper Trading 결과에 kill switch 상태가 없습니다.",
        )
    tripped = kill_switch.get("tripped") is True
    reasons = [str(item) for item in _sequence(kill_switch.get("reasons"))]
    return _readiness_component(
        "kill_switch",
        "Kill switch",
        weight,
        0.0 if tripped else weight,
        "blocked" if tripped else "success",
        "발동" if tripped else "정상",
        _paper_source(paper_path),
        "긴급 중지 조건이 최근 Paper Trading에서 발동했는지 봅니다.",
        {"tripped": tripped, "reasons": reasons},
    )


def _readiness_payload(
    components: Sequence[Mapping[str, Any]],
    *,
    latest_run: str | None,
) -> dict[str, Any]:
    score = round(sum(_number(item.get("score"), 0) for item in components), 1)
    max_score = round(sum(_number(item.get("max_score"), 0) for item in components), 1)
    stage = _readiness_stage(score, components)
    return {
        "score": score,
        "max_score": max_score,
        "grade": _readiness_grade(score),
        "stage": stage,
        "stage_label": _readiness_stage_label(stage),
        "summary": _readiness_summary_text(stage),
        "thresholds": READINESS_THRESHOLDS,
        "latest_run": latest_run,
        "components": [dict(item) for item in components],
        "next_actions": _readiness_next_actions(components),
        "sources": sorted(
            {
                str(item.get("source"))
                for item in components
                if item.get("source") and item.get("source") != "runtime paths unavailable"
            }
        ),
    }


def _readiness_component(
    key: str,
    label: str,
    max_score: float,
    score: float,
    status: str,
    value: str,
    source: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    capped = min(max(float(score), 0.0), float(max_score))
    return {
        "id": key,
        "label": label,
        "score": round(capped, 1),
        "max_score": max_score,
        "status": status,
        "value": value,
        "source": source,
        "message": message,
        "details": dict(details or {}),
        "gap": round(max(0.0, float(max_score) - capped), 1),
    }


def _readiness_stage(score: float, components: Sequence[Mapping[str, Any]]) -> str:
    if any(
        item.get("id") == "kill_switch" and item.get("status") == "blocked"
        for item in components
    ):
        return "blocked"
    paper_ready = any(
        item.get("id") == "paper_performance" and item.get("status") == "success"
        for item in components
    )
    if score >= READINESS_THRESHOLDS["auto_candidate"] and paper_ready:
        return "auto_candidate"
    if score >= READINESS_THRESHOLDS["semi_auto_review"]:
        return "semi_auto_review"
    if score >= 50:
        return "paper_required"
    return "analysis_only"


def _readiness_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def _readiness_stage_label(stage: str) -> str:
    return {
        "auto_candidate": "자동매매 후보",
        "semi_auto_review": "반자동 검토 가능",
        "paper_required": "Paper 검증 필요",
        "analysis_only": "분석 모드 유지",
        "blocked": "자동매매 차단",
    }.get(stage, "분석 모드 유지")


def _readiness_summary_text(stage: str) -> str:
    return {
        "auto_candidate": "점수는 높지만 실제 주문 전송은 여전히 별도 승인과 제한 설정이 필요합니다.",
        "semi_auto_review": "반자동 검토 후보입니다. 사용자가 승인한 주문만 허용하는 단계가 적절합니다.",
        "paper_required": "Paper Trading 기록을 더 쌓은 뒤 반자동 전환을 검토하세요.",
        "analysis_only": "지금은 자동매매보다 데이터·리스크·Paper 검증을 보강해야 합니다.",
        "blocked": "Kill switch 또는 핵심 안전 조건 때문에 자동매매 전환을 막아야 합니다.",
    }.get(stage, "자동매매 준비 상태를 계속 점검하세요.")


def _readiness_next_actions(components: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    weak = sorted(
        [item for item in components if _number(item.get("gap"), 0) > 0],
        key=lambda item: _number(item.get("gap"), 0),
        reverse=True,
    )
    return [
        {
            "component": item.get("id"),
            "label": item.get("label"),
            "gap": item.get("gap"),
            "status": item.get("status"),
            "action": _component_next_action(str(item.get("id"))),
            "source": item.get("source"),
        }
        for item in weak[:4]
    ]


def _component_next_action(component_id: str) -> str:
    return {
        "data_validation": "최신 signal/shadow 실행을 다시 만들고 data_reports 검증 실패를 먼저 정리하세요.",
        "risk_gate": "매수 후보가 생긴 날의 risk_explanation.json에서 차단 사유를 줄이세요.",
        "shadow_period": "shadow 모드 실행 일수를 누적하고 promotion 기준을 통과시키세요.",
        "paper_performance": "OrderIntent를 Paper Trading으로 돌려 체결률과 손익 기록을 쌓으세요.",
        "implementation_shortfall": "스프레드, 지연, 체결 가격 비용을 낮추는 주문 조건을 조정하세요.",
        "kill_switch": "kill switch 발동 원인을 해소한 뒤 Paper Trading을 다시 검증하세요.",
    }.get(component_id, "관련 artifact를 확인하세요.")


def _latest_paper_report(
    paths: RuntimePaths,
    latest_dir: Path | None,
) -> tuple[Path | None, Mapping[str, Any]]:
    names = ("paper_trading.json", "paper_session.json", "paper_report.json")
    candidates: list[Path] = []
    if latest_dir is not None:
        candidates.extend(latest_dir / name for name in names)
    candidates.extend(paths.state_dir / name for name in names)
    if paths.runs_dir.exists():
        for name in names:
            candidates.extend(paths.runs_dir.glob(f"*/{name}"))
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return None, {}
    selected = max(existing, key=lambda path: path.stat().st_mtime)
    return selected, _mapping(read_json(selected, default={}))


def _paper_source(path: Path | None) -> str:
    return str(path) if path is not None else "paper trading report"


def _readiness_label(key: str) -> str:
    return {
        "data_validation": "데이터 검증률",
        "risk_gate": "리스크 통과율",
        "shadow_period": "Shadow 기간",
        "paper_performance": "Paper 성과",
        "implementation_shortfall": "Shortfall 비용",
        "kill_switch": "Kill switch",
    }.get(key, key)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def build_autotrading_status_payload(paths: RuntimePaths | None = None) -> dict[str, Any]:
    """대시보드용 자동매매 상태 페이로드."""
    status = get_autotrading_status()
    readiness_score = build_autotrading_readiness_score(paths)
    paper_promotion_report = build_paper_promotion_report(paths, readiness_score)
    return {
        "status": status.to_dict(),
        "readiness_score": readiness_score,
        "paper_promotion_report": paper_promotion_report,
        "phases": [
            {
                "phase": "disabled",
                "label": "비활성",
                "description": "자동매매 기능이 완전히 꺼져 있습니다. (현재 상태)",
                "is_current": True,
                "color": "#94a3b8",
            },
            {
                "phase": "paper",
                "label": "모의투자",
                "description": "실제 주문 없이 전략을 검증합니다. 최소 30일 권장.",
                "is_current": False,
                "color": "#6366f1",
                "requirements": ["사용자 승인 필요"],
            },
            {
                "phase": "semi_auto",
                "label": "반자동 매매",
                "description": "신호 생성 후 사용자가 직접 승인한 주문만 실행합니다.",
                "is_current": False,
                "color": "#f59e0b",
                "requirements": ["모의투자 검증", "일별 손실 한도 설정", "긴급 중지 기능"],
            },
            {
                "phase": "auto",
                "label": "자동 매매",
                "description": "신호에 따라 자동으로 주문을 실행합니다. 모든 안전장치 필수.",
                "is_current": False,
                "color": "#ef4444",
                "requirements": ["모든 안전장치 충족", "30일 이상 반자동 운영"],
            },
        ],
        "safety_requirements": SAFETY_REQUIREMENTS,
        "disclaimer": status.disclaimer,
        "warning": status.warning,
    }
