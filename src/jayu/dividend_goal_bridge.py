from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DividendGoalBridge:
    """Connect dividend simulation output to the monthly dividend goal."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.target_path = self.project_root / "state" / "dividend_target.json"

    def load_monthly_target(self) -> float:
        if not self.target_path.exists():
            return 3000000.0
        try:
            data = json.loads(self.target_path.read_text(encoding="utf-8"))
            return max(0.0, float(data.get("monthly_target_krw", data.get("target_krw", 3000000.0))))
        except Exception:
            return 3000000.0

    def build(self, sim_data: dict[str, Any]) -> dict[str, Any]:
        target = self.load_monthly_target()
        annual_net = _to_float(sim_data.get("annual_net_dividend_krw"))
        portfolio_value = _to_float(sim_data.get("portfolio_value_krw"))
        yield_pct = _to_float(sim_data.get("aggregate_yield_pct"))
        annual_yield = max(0.0, yield_pct / 100.0)
        current_monthly_net = annual_net / 12.0
        monthly_shortfall = max(0.0, target - current_monthly_net)
        needed_capital = (monthly_shortfall * 12.0 / annual_yield) if annual_yield > 0 else 0.0
        target_capital = (target * 12.0 / annual_yield) if annual_yield > 0 else 0.0
        achievement_rate = (current_monthly_net / target * 100.0) if target > 0 else 0.0

        return {
            "monthly_target_krw": round(target, 2),
            "current_monthly_net_krw": round(current_monthly_net, 2),
            "monthly_shortfall_krw": round(monthly_shortfall, 2),
            "achievement_rate_pct": round(achievement_rate, 2),
            "needed_additional_capital_krw": round(needed_capital, 2),
            "target_capital_krw": round(target_capital, 2),
            "current_portfolio_value_krw": round(portfolio_value, 2),
            "required_monthly_investment": {
                "1_year": round(needed_capital / 12.0, 2) if needed_capital > 0 else 0.0,
                "3_year": round(needed_capital / 36.0, 2) if needed_capital > 0 else 0.0,
                "5_year": round(needed_capital / 60.0, 2) if needed_capital > 0 else 0.0,
            },
            "assumptions": {
                "annual_net_yield_pct": round(yield_pct, 4),
                "uses_current_portfolio_yield": True,
                "source": "dividend simulation net cashflow · state/dividend_target.json",
            },
        }


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "").replace("₩", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0
