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

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

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


def build_autotrading_status_payload() -> dict[str, Any]:
    """대시보드용 자동매매 상태 페이로드."""
    status = get_autotrading_status()
    return {
        "status": status.to_dict(),
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
