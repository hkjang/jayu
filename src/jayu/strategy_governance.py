"""strategy_governance.py — 전략 사용 승인 검토 및 신호 필터링 모듈.

전략이 속한 포트폴리오 타입, 허용되는 시장 국면, 과거 검증 조건(OOS 성과 등)을 심사하여
현재 조건에서 작동할 자격이 있는지 판정한다.
"""

from __future__ import annotations

from typing import Any

# 전략별 운영 지배 구조 정책 정의
STRATEGY_POLICIES: dict[str, dict[str, Any]] = {
    "ensemble": {
        "name": "Ensemble 모멘텀 통합 전략",
        "allowed_portfolio_types": ["short_term", "swing", "long_term"],
        "allowed_market_regimes": ["bull", "sideways", "volatile"],
        "min_oos_sharpe": 1.1,
        "active": True,
        "inactivation_reason": None
    },
    "connors_rsi2": {
        "name": "Connors RSI(2) 단기 역추세 전략",
        "allowed_portfolio_types": ["short_term"],
        "allowed_market_regimes": ["bull", "sideways"],  # bear나 volatile에서는 역추세 단타 극단적으로 위험
        "min_oos_sharpe": 1.0,
        "active": True,
        "inactivation_reason": None
    },
    "williams_breakout": {
        "name": "Williams %R 돌파 추세추종 전략",
        "allowed_portfolio_types": ["swing", "long_term"],
        "allowed_market_regimes": ["bull", "sideways", "volatile"],
        "min_oos_sharpe": 1.2,
        "active": True,
        "inactivation_reason": None
    },
    "volume_breakout": {
        "name": "거래량 급증 거래량 추종 전략",
        "allowed_portfolio_types": ["short_term", "swing"],
        "allowed_market_regimes": ["bull"],
        "min_oos_sharpe": 0.9,
        "active": False,  # 최근 성과 저하로 영구 정지/비활성화
        "inactivation_reason": "최근 2개월 간의 백테스트 결과 및 실전 모의(OOS) Sharpe 지수가 0.5 미만으로 떨어져 승인이 취소되었습니다."
    }
}

def get_strategy_governance_info() -> dict[str, Any]:
    """등록된 모든 전략의 승인 정책 및 활성화 상태 정보를 제공한다."""
    return STRATEGY_POLICIES

def check_strategy_approval(
    strategy_name: str,
    portfolio_type: str,
    regime: str
) -> dict[str, Any]:
    """개별 전략이 특정 포트폴리오 타입 및 현재 시장 국면에서 작동 가능한지 심사한다.
    
    Returns:
        {
            "approved": bool,
            "reason_ko": str | None,
            "strategy_info": dict
        }
    """
    # 등록되지 않은 전략 처리 (기본 승인 차단 및 수동 검토 유도)
    if strategy_name not in STRATEGY_POLICIES:
        return {
            "approved": False,
            "reason_ko": f"미승인 전략: '{strategy_name}'은(는) 시스템에 거버넌스 정책이 등록되지 않아 작동이 제한됩니다.",
            "strategy_info": {}
        }

    policy = STRATEGY_POLICIES[strategy_name]

    # 1. 활성화 여부 검사
    if not policy["active"]:
        return {
            "approved": False,
            "reason_ko": f"전략 비활성화 상태: {policy['inactivation_reason']}",
            "strategy_info": policy
        }

    # 2. 허용 포트폴리오 타입 검사
    if portfolio_type not in policy["allowed_portfolio_types"]:
        allowed_types_ko = ", ".join(policy["allowed_portfolio_types"])
        return {
            "approved": False,
            "reason_ko": f"포트폴리오 타입 미지원: 해당 전략은 '{portfolio_type}' 타입을 지원하지 않습니다. (지원 타입: {allowed_types_ko})",
            "strategy_info": policy
        }

    # 3. 시장 국면 검사
    if regime not in policy["allowed_market_regimes"]:
        allowed_regimes_ko = ", ".join(policy["allowed_market_regimes"])
        return {
            "approved": False,
            "reason_ko": f"시장 국면 조건 미충족: 현재 시장 국면 '{regime}'은(는) 이 전략의 작동 허용 범위가 아닙니다. (허용 국면: {allowed_regimes_ko})",
            "strategy_info": policy
        }

    return {
        "approved": True,
        "reason_ko": None,
        "strategy_info": policy
    }
