from __future__ import annotations

from pathlib import Path
from typing import Any

from .approval_audit_ledger import load_approval_history
from .paths import RuntimePaths


class InvestorBehaviorInsights:
    """Analyzes the user's trading patterns, override habits, and behavioral biases (FOMO, Loss Aversion)."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.paths = RuntimePaths.from_root(project_root)

    def analyze_behavior(self, limit: int = 100) -> dict[str, Any]:
        """Scan the user decision audit ledger and flag common biases with professional Korean insights."""
        history = load_approval_history(self.paths, limit=limit)
        
        total_decisions = len(history)
        fomo_count = 0
        overtrading_count = 0
        loss_aversion_count = 0
        early_take_profit_count = 0
        
        # Check for overrides & decision counts
        for entry in history:
            rec = entry.get("recommendation_verdict", "").lower()
            user = entry.get("user_decision", "").lower()
            action = entry.get("action", "").lower()

            # 1. FOMO (Chasing): Overriding system warnings/blocks to buy
            if user == "approve" and rec in ["blocked", "rejected", "ignore"]:
                fomo_count += 1
            
            # 2. Overtrading: Approving everything regardless of status
            if user == "approve":
                overtrading_count += 1
                
            # 3. Loss Aversion: Ignoring sell exit recommendations
            if action == "sell" and rec == "sell" and user == "ignore":
                loss_aversion_count += 1

            # 4. Early profit taking: Selling when the recommendation says hold
            if action == "sell" and rec == "hold" and user == "approve":
                early_take_profit_count += 1

        # Evaluate risk indicators and warnings
        warnings = []
        insights = []

        # Overtrading check
        if overtrading_count > 15:
            warnings.append({
                "bias": "Overtrading (과잉 매매)",
                "level": "warning",
                "tag": "⚠️ 잦은 매매",
                "message": f"최근 의사결정 중 {overtrading_count}회 승인이 발견되었습니다. 과도한 거래는 수수료와 슬리피지 비용을 누적시켜 장기Edge를 훼손합니다."
            })
        else:
            insights.append("매매 횟수가 통제 하에 잘 유지되고 있으며 거래 빈도가 적정합니다.")

        # FOMO check
        if fomo_count > 0:
            warnings.append({
                "bias": "FOMO Chasing (추격 매수 성향)",
                "level": "danger",
                "tag": "🚨 뇌동 매매 경보",
                "message": f"시스템이 리스크나 비용 문제로 차단한 신호에 대해 사용자가 {fomo_count}회 강제 승인하여 진입했습니다. 감정에 의한 추격 매수는 장기 손실의 가장 큰 원인입니다."
            })
        else:
            insights.append("시스템 리스크 권고 사항을 철저히 준수하여 불필요한 추격 매수를 완벽히 방어했습니다.")

        # Loss Aversion check
        if loss_aversion_count > 0:
            warnings.append({
                "bias": "Loss Aversion (손실 회피 및 처분 효과)",
                "level": "danger",
                "tag": "🚨 손절 미준수",
                "message": f"시스템이 제시한 매도/손절 청산 신호를 {loss_aversion_count}회 무시하고 보유를 고수했습니다. 손익비 붕괴를 막기 위해 기계적 손절을 즉각 준수해야 합니다."
            })
        else:
            insights.append("리스크 청산 및 손절 기준 도달 시 규칙에 따라 단호하게 청산 결정을 내렸습니다.")

        # Early Profit Taking check
        if early_take_profit_count > 0:
            warnings.append({
                "bias": "Disposition Effect (이익 조기 실현 성향)",
                "level": "warning",
                "tag": "⚠️ 조기 청산",
                "message": f"시스템이 포지션 유지를 권고한(hold) 상태에서 {early_take_profit_count}회 조기 익절을 단행했습니다. 추세가 자랄 시간을 주지 못하면 손익비가 극도로 악화될 수 있습니다."
            })

        return {
            "total_decisions_analyzed": total_decisions,
            "biases_detected": {
                "fomo_override_count": fomo_count,
                "overtrading_approvals": overtrading_count,
                "loss_aversion_holds": loss_aversion_count,
                "early_profit_takes": early_take_profit_count
            },
            "warnings": warnings,
            "healthy_habits": insights
        }
