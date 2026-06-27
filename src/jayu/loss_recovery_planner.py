from __future__ import annotations

import math
from typing import Any

class LossRecoveryPlanner:
    """Computes break-even return, time to recover, and deposit impacts for underwater portfolios."""

    def calculate_recovery_plan(
        self,
        current_portfolio_value: float,
        loss_pct: float,  # e.g., 0.20 for -20% loss (positive float representing loss)
    ) -> dict[str, Any]:
        loss_pct = abs(loss_pct)
        if loss_pct >= 1.0:
            loss_pct = 0.99  # Cap at 99% to avoid zero division

        # 1. Break-even return needed
        # Formula: 1 / (1 - L) - 1
        break_even_pct = 1.0 / (1.0 - loss_pct) - 1.0

        # 2. Time to recover (months) under different annualized growth rate assumptions
        rates = [0.08, 0.15, 0.25]  # 8%, 15%, 25%
        recovery_months = {}
        for r in rates:
            # Formula: (1 + r/12)^n = 1 / (1 - L)
            # n * log(1 + r/12) = -log(1 - L)
            # n = -log(1 - L) / log(1 + r/12)
            monthly_rate = r / 12.0
            try:
                months = -math.log(1.0 - loss_pct) / math.log(1.0 + monthly_rate)
                recovery_months[f"{int(r*100)}pct_return"] = round(months, 1)
            except Exception:
                recovery_months[f"{int(r*100)}pct_return"] = None

        # 3. Monthly deposit impact (PMT effect)
        # Target amount to reach = current_value / (1 - L)
        # Shortfall amount = target - current_value
        target_amount = current_portfolio_value / (1.0 - loss_pct)
        shortfall = target_amount - current_portfolio_value

        # Calculate time with monthly deposits (assuming 15% p.a. growth)
        r_15 = 0.15
        monthly_rate_15 = r_15 / 12.0
        deposit_scenarios = {}
        for pmt in [500000, 1000000, 2000000]:  # 500k, 1M, 2M KRW
            # Solve: PV * (1+r)^N + PMT * ((1+r)^N - 1)/r = FV for N
            # PV * (1+r)^N + PMT/r * (1+r)^N - PMT/r = FV
            # (1+r)^N * (PV + PMT/r) = FV + PMT/r
            # (1+r)^N = (FV + PMT/r) / (PV + PMT/r)
            # N = log( (FV + PMT/r) / (PV + PMT/r) ) / log(1 + r)
            try:
                pv = current_portfolio_value
                fv = target_amount
                numerator = fv + (pmt / monthly_rate_15)
                denominator = pv + (pmt / monthly_rate_15)
                months = math.log(numerator / denominator) / math.log(1.0 + monthly_rate_15)
                deposit_scenarios[f"deposit_{pmt // 10000}ten_thousand_krw"] = round(months, 1)
            except Exception:
                deposit_scenarios[f"deposit_{pmt // 10000}ten_thousand_krw"] = None

        # 4. Korean Risk Reduction Advices
        advices = []
        if loss_pct >= 0.30:
            advices.append("🚨 현재 포트폴리오의 평가 손실이 30%를 초과한 심각한 상태입니다. 3배 레버리지(SOXL, TQQQ)의 추가 신규 매수를 전면 중단하고, 1배수 지수 ETF 또는 현금 비중을 확보하십시오.")
            advices.append("💡 원금 복구에 42.8% 이상의 고수익 상승이 필요합니다. 물타기 빈도를 낮추고, 추세선(EMA 200) 위로 지수가 회복된 후 진입하는 전략으로 안전성을 극대화해야 합니다.")
        elif loss_pct >= 0.15:
            advices.append("⚠️ 손실율이 15%를 넘어 주의 단계에 진입했습니다. 특정 고변동 종목(엔비디아 레버리지 등)의 개별 노출도를 15% 이하로 제약할 것을 권장합니다.")
            advices.append("💡 매월 정기적인 예산 배분(현금흐름 계획판 연동)을 통해 평단가 매수 효과를 극대화하되, 감정적 무단 추격 매수는 억제하십시오.")
        else:
            advices.append("✅ 정상적인 시장 변동성 손실 범주 내에 있습니다. 기존 시스템 신호 및 리스크 통제선을 신뢰하여 차분하게 원칙 매매를 지속하십시오.")

        return {
            "loss_pct": round(loss_pct * 100.0, 2),
            "break_even_return_pct": round(break_even_pct * 100.0, 2),
            "shortfall_amount_krw": round(shortfall, 2),
            "recovery_months_by_return": recovery_months,
            "deposit_scenarios_recovery_months_at_15pct": deposit_scenarios,
            "risk_reduction_advices": advices
        }
