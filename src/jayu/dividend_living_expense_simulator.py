from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from .dividend_cashflow_simulator import DividendCashflowSimulator

class DividendLivingExpenseSimulator:
    """Simulates monthly dividend target milestones and DRIP pathways to financial freedom."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.target_file = project_root / "state" / "dividend_target.json"
        self.simulator = DividendCashflowSimulator(project_root)

    def load_target(self) -> float:
        """Load target monthly dividend in KRW. Default is 2,000,000 KRW."""
        if not self.target_file.exists():
            return 2000000.0
        try:
            with open(self.target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return float(data.get("monthly_target_krw", 2000000.0))
        except Exception:
            return 2000000.0

    def save_target(self, target_krw: float) -> float:
        """Save target monthly dividend in KRW."""
        self.target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.target_file, "w", encoding="utf-8") as f:
            json.dump({"monthly_target_krw": target_krw}, f, indent=2, ensure_ascii=False)
        return target_krw

    def simulate(self, holdings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Compare current estimated dividend cashflows to target monthly expense."""
        base_sim = self.simulator.simulate_cashflow(holdings)
        monthly_div = base_sim["annual_dividend_krw"] / 12.0
        target = self.load_target()

        shortfall = max(0.0, target - monthly_div)
        yield_rate = base_sim["aggregate_yield_pct"] / 100.0
        portfolio_value = base_sim["portfolio_value_krw"]

        # Capital needed to cover shortfall
        needed_capital = (shortfall * 12.0 / yield_rate) if yield_rate > 0 else 0.0
        achievement_rate = (monthly_div / target * 100.0) if target > 0 else 0.0

        # Years to reach goal under compounding (assuming $0 monthly additional savings, only DRIP reinvestment)
        years_to_goal = None
        if monthly_div < target and yield_rate > 0 and portfolio_value > 0:
            current_val = portfolio_value
            target_val = (target * 12.0 / yield_rate)
            # compound: target_val = current_val * (1 + yield_rate/12) ^ (months)
            import math
            try:
                months = math.log(target_val / current_val) / math.log(1.0 + yield_rate / 12.0)
                years_to_goal = round(months / 12.0, 1)
            except Exception:
                pass

        # DRIP compound snapshots to goal
        snapshots = {}
        for y in [1, 3, 5, 10]:
            monthly_rate = yield_rate / 12.0
            val_comp = portfolio_value * ((1.0 + monthly_rate) ** (y * 12))
            snapshots[f"{y}yr_monthly_dividend"] = round(val_comp * yield_rate / 12.0, 2)

        return {
            "monthly_target_krw": round(target, 2),
            "current_monthly_dividend_krw": round(monthly_div, 2),
            "shortfall_krw": round(shortfall, 2),
            "achievement_rate": round(achievement_rate, 2),
            "needed_additional_capital_krw": round(needed_capital, 2),
            "years_to_goal_via_drip": years_to_goal,
            "drip_future_snapshots": snapshots
        }
