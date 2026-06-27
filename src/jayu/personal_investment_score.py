from __future__ import annotations

from pathlib import Path
from typing import Any
from .investor_behavior_insights import InvestorBehaviorInsights
from .cashflow_planner import CashflowPlanner

class PersonalInvestmentScore:
    """Computes a multi-dimensional investment score (0-100) based on behavior, risk, cash, and trade choices."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.behavior_insights = InvestorBehaviorInsights(project_root)
        self.cashflow_planner = CashflowPlanner(project_root)

    def calculate_score(self) -> dict[str, Any]:
        """Scans audits, behavior metrics, and cash budgets to yield a robust coaching score."""
        # 1. Fetch behavioral insights
        insights = self.behavior_insights.analyze_behavior()
        biases = insights.get("biases_detected", {})
        
        fomo_count = biases.get("fomo_override_count", 0)
        overtrading_count = biases.get("overtrading_approvals", 0)
        loss_aversion_count = biases.get("loss_aversion_holds", 0)
        early_take_profit_count = biases.get("early_profit_takes", 0)

        # 2. Risk Compliance Score (25 pts)
        # Lose 5 pts per FOMO override, down to 0
        risk_score = max(0.0, 25.0 - (fomo_count * 5.0))

        # 3. Loss Avoidance Score (25 pts)
        # Lose 10 pts per ignored exit recommendation, down to 0
        loss_score = max(0.0, 25.0 - (loss_aversion_count * 10.0))

        # 4. Trading Frequency / Overtrading Score (20 pts)
        # Optimal is low trades. Over 15 approvals in history starts reducing score
        frequency_score = 20.0
        if overtrading_count > 15:
            frequency_score = max(0.0, 20.0 - ((overtrading_count - 15) * 1.5))

        # 5. Cash/Budget Management Score (15 pts)
        # Check cashflow records. If net investable budget > 0, we give high marks
        cashflows = self.cashflow_planner.load_cashflows()
        cash_score = 15.0
        if cashflows:
            latest_cf = cashflows[-1]
            reserved = float(latest_cf.get("reserved_cash", 0))
            salary = float(latest_cf.get("salary_deposit", 0))
            # Cash reserve ratio. Optimal is 10% - 20% of salary
            if salary > 0:
                ratio = reserved / salary
                if ratio < 0.05:
                    cash_score = 7.5  # Too low reserves
                elif ratio > 0.40:
                    cash_score = 10.0 # Too high lazy cash
            else:
                cash_score = 12.0
        else:
            cash_score = 12.0  # Default fallback if no records

        # 6. Yield/Consistency Score (15 pts)
        # Lose 3 pts per early profit take, down to 0
        yield_score = max(0.0, 15.0 - (early_take_profit_count * 3.0))

        # Combine
        total_score = round(risk_score + loss_score + frequency_score + cash_score + yield_score, 1)

        # Define grade
        if total_score >= 90:
            grade = "A (최우수)"
            description = "시스템의 안전 장치와 리스크 권고를 완벽히 준수하고 있으며 자금 관리 습관이 탁월합니다."
        elif total_score >= 80:
            grade = "B (우수)"
            description = "일부 미세한 규칙 이탈이 있으나 전반적으로 합리적이고 안전한 매매 습관을 준수하고 있습니다."
        elif total_score >= 70:
            grade = "C (보통)"
            description = "과도한 매매 회수나 손절 무시 성향이 발견되었습니다. 가설 기반의 기계적 대응 비중을 늘리세요."
        else:
            grade = "D (위험)"
            description = "원칙을 우회한 뇌동 매매 및 리스크 경고 무시가 누적되었습니다. 즉각적인 매매 정지 및 복기가 요구됩니다."

        return {
            "total_score": total_score,
            "grade": grade,
            "description": description,
            "breakdown": {
                "risk_compliance_score": round(risk_score, 1),
                "loss_avoidance_score": round(loss_score, 1),
                "trading_frequency_score": round(frequency_score, 1),
                "cash_management_score": round(cash_score, 1),
                "consistency_score": round(yield_score, 1),
            },
            "metrics": {
                "fomo_override_count": fomo_count,
                "overtrading_approvals": overtrading_count,
                "loss_aversion_holds": loss_aversion_count,
                "early_profit_takes": early_take_profit_count
            }
        }
