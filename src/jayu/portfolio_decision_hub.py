"""Combines holdings, cash, risk gates, and signals to make unified portfolio decisions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .dividend_cashflow_simulator import DividendCashflowSimulator
from .personal_investment_policy import PersonalInvestmentPolicy


class PortfolioDecisionHub:
    """Analyzes overall portfolio state and assigns action status to each holding/signal."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.policy_manager = PersonalInvestmentPolicy(self.project_root)

    def evaluate_portfolio(self) -> dict[str, Any]:
        """Runs a complete check on all assets and generates decisions."""
        simulator = DividendCashflowSimulator(self.project_root)
        sim_res = simulator.simulate_cashflow()
        
        holdings = sim_res.get("holdings", [])
        cash_krw = sim_res.get("cash_krw", 0.0)
        
        total_value = sum(float(h.get("value_krw") or h.get("price", 0) * h.get("quantity", 0)) for h in holdings) + cash_krw
        max_single_ratio = self.policy_manager.get_rule("asset_allocation", "max_single_position_ratio", 0.25)
        min_dividend_score = self.policy_manager.get_rule("dividend_quality", "min_dividend_trust_score", 80.0)
        
        decisions = []
        rebalance_count = 0
        warn_count = 0
        allow_count = 0

        for h in holdings:
            symbol = h["symbol"]
            qty = float(h.get("quantity", 0))
            price = float(h.get("price", 0))
            val_krw = float(h.get("value_krw") or qty * price)
            ratio = val_krw / total_value if total_value > 0 else 0.0
            
            trust_score = float(h.get("trust_score", 100.0))
            decision = h.get("decision", "pass")

            verdict = "allow"
            reasons = []
            next_action = "유지"

            # Check 1: Single position limit
            if ratio > max_single_ratio:
                verdict = "rebalance"
                reasons.append(f"단일 종목 비중 초과: {ratio*100:.1f}% (한도 {max_single_ratio*100:.1f}%)")
                next_action = "부분 매도 (비중 조절)"
                rebalance_count += 1
                
            # Check 2: Low quality dividend stock
            elif decision in {"block", "exclude"} or trust_score < min_dividend_score:
                verdict = "warn"
                reasons.append(f"배당 데이터 신뢰도 미달: {trust_score:.1f}점 (기준 {min_dividend_score:.1f}점)")
                next_action = "수동 상태 점검"
                warn_count += 1
            else:
                allow_count += 1

            decisions.append({
                "symbol": symbol,
                "name": h.get("name", symbol),
                "quantity": qty,
                "value_krw": round(val_krw, 0),
                "ratio": round(ratio, 4),
                "trust_score": trust_score,
                "verdict": verdict,
                "reasons": reasons,
                "next_action": next_action
            })

        # Sort: rebalance first, then warn, then allow
        verdict_order = {"rebalance": 0, "warn": 1, "allow": 2}
        decisions.sort(key=lambda x: verdict_order.get(x["verdict"], 3))

        return {
            "timestamp": time.time(),
            "summary": {
                "total_portfolio_value_krw": round(total_value, 0),
                "cash_krw": round(cash_krw, 0),
                "cash_ratio": round(cash_krw / total_value, 4) if total_value > 0 else 0.0,
                "rebalance_required_count": rebalance_count,
                "warning_count": warn_count,
                "allow_count": allow_count
            },
            "decisions": decisions
        }
