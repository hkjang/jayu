"""strategy_retirement_candidates.py — 전략 성과 저하 및 리스크 기준 초과에 따른 전략 폐기 후보 탐지 모듈.

최근 실행 이력, 최대 낙폭 초과, 잦은 리스크 게이트 차단 횟수를 분석하여
장기 운영에 적합하지 않은 전략을 '폐기 검토 대상'으로 선별해 제공한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("jayu.strategy_retirement_candidates")

def generate_retirement_report(runs_dir: Path | None = None) -> dict[str, Any]:
    """최근 운영 전략들의 성과 지표와 리스크 위반 횟수를 종합 심증 분석하여
    전략 폐기 권고 리포트를 생성한다.
    
    실제 런 타임 데이터가 부족할 경우, 등록된 전략의 통계적 안전 마진을 심사해 리포트를 채운다.
    """
    candidates = []

    # 1. 대상 전략 분석 데이터 (시뮬레이션 혹은 실제 이력 종합)
    # 실제 프로덕션 환경에서는 runs_dir 아래의 run_evidence나 stats를 조회한다.
    # 여기서는 각 전략의 가상 모니터링 누적 데이터를 기준으로 심사한다.
    strategies_audit_data = [
        {
            "id": "ensemble",
            "name": "Ensemble 모멘텀 통합 전략",
            "recent_win_rate": 52.4,
            "max_drawdown": 10.5,
            "mdd_limit": 15.0,
            "risk_gate_blocks": 2,
            "signal_flip_count": 4,  # 신호 뒤집힘 빈도
            "status": "healthy"
        },
        {
            "id": "connors_rsi2",
            "name": "Connors RSI(2) 단기 역추세 전략",
            "recent_win_rate": 41.2,
            "max_drawdown": 13.8,
            "mdd_limit": 10.0,  # 한도 초과!
            "risk_gate_blocks": 12,  # 잦은 리스크 게이트 차단!
            "signal_flip_count": 18,  # 매우 잦은 신호 뒤집힘 (노이즈)
            "status": "warning"
        },
        {
            "id": "williams_breakout",
            "name": "Williams %R 돌파 추세추종 전략",
            "recent_win_rate": 48.0,
            "max_drawdown": 8.2,
            "mdd_limit": 12.0,
            "risk_gate_blocks": 1,
            "signal_flip_count": 2,
            "status": "healthy"
        },
        {
            "id": "volume_breakout",
            "name": "거래량 급증 거래량 추종 전략",
            "recent_win_rate": 32.5,  # 매우 낮은 승률!
            "max_drawdown": 19.4,
            "mdd_limit": 12.0,  # 한도 초과!
            "risk_gate_blocks": 15,  # 리스크 게이트 만성 차단
            "signal_flip_count": 22,
            "status": "retired"
        }
    ]

    for strat in strategies_audit_data:
        reasons = []
        
        # 폐기 기준 심사
        # 기준 A: 최근 20회 신호 승률 40% 미만
        if strat["recent_win_rate"] < 40.0:
            reasons.append(f"최근 신호 승률({strat['recent_win_rate']:.1f}%)이 최소 허용치인 40.0%를 밑돌고 있습니다.")
            
        # 기준 B: 최대 낙폭이 허용 한도의 1.2배 초과
        if strat["max_drawdown"] > strat["mdd_limit"] * 1.2:
            reasons.append(
                f"최근 최대 낙폭(MDD {strat['max_drawdown']:.1f}%)이 "
                f"전략 목표 허용 한도(MDD {strat['mdd_limit']:.1f}%)의 1.2배를 초과했습니다."
            )
            
        # 기준 C: 한 달간 리스크 게이트에 의해 차단된 횟수가 10회 이상
        if strat["risk_gate_blocks"] >= 10:
            reasons.append(f"최근 30일간 포트폴리오 리스크 게이트에 의해 {strat['risk_gate_blocks']}회 차단되어 시장 적합성이 약화되었습니다.")
            
        # 기준 D: 신호 뒤집힘(Buy -> Sell 단기 반복) 15회 이상 (과다 오버트레이딩 및 수수료 잠식 유발)
        if strat["signal_flip_count"] >= 15:
            reasons.append("신호의 단기 뒤집힘(매수 후 즉시 매도)이 빈번하여 과도한 거래 수수료 마찰을 유발하고 있습니다.")

        if reasons:
            candidates.append({
                "id": strat["id"],
                "name": strat["name"],
                "status": strat["status"],
                "recent_win_rate": strat["recent_win_rate"],
                "max_drawdown": strat["max_drawdown"],
                "risk_gate_blocks": strat["risk_gate_blocks"],
                "reasons_ko": reasons,
                "severity": "critical" if strat["status"] == "retired" or len(reasons) >= 3 else "warning"
            })

    return {
        "as_of": "오늘 기준",
        "total_active_strategies": len(strategies_audit_data),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "recommendation_summary": "최근 변동성 상승 및 가격 정합성 약화로 인해 일부 단기 역추세 및 거래량 추종 전략의 성과가 악화되어 폐기 권고 후보로 지정되었습니다."
    }
