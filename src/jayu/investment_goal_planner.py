from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class InvestmentGoalPlanner:
    """Manages investment goals, computes goal progress, required monthly deposits, and required returns."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.goals_file = project_root / "state" / "investment_goals.json"

    def load_goals(self) -> list[dict[str, Any]]:
        if not self.goals_file.exists():
            return []
        try:
            with open(self.goals_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_goals(self, goals: list[dict[str, Any]]) -> None:
        self.goals_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.goals_file, "w", encoding="utf-8") as f:
            json.dump(goals, f, indent=2, ensure_ascii=False)

    def set_goal(
        self,
        goal_id: str,
        name: str,
        target_amount: float,
        target_date: str,  # YYYY-MM-DD
        current_amount: float,
        monthly_deposit: float,
        expected_return: float,  # Annualized rate, e.g., 0.08 for 8%
    ) -> dict[str, Any]:
        goals = self.load_goals()
        # Find and remove existing goal with same ID
        goals = [g for g in goals if g["goal_id"] != goal_id]
        
        goal = {
            "goal_id": goal_id,
            "name": name,
            "target_amount": target_amount,
            "target_date": target_date,
            "current_amount": current_amount,
            "monthly_deposit": monthly_deposit,
            "expected_return": expected_return,
            "updated_at": datetime.now().isoformat()
        }
        goals.append(goal)
        self.save_goals(goals)
        return goal

    def delete_goal(self, goal_id: str) -> bool:
        goals = self.load_goals()
        filtered = [g for g in goals if g["goal_id"] != goal_id]
        if len(filtered) == len(goals):
            return False
        self.save_goals(filtered)
        return True

    def calculate_analysis(self, goal: dict[str, Any]) -> dict[str, Any]:
        """Perform financial mathematics to check goal feasibility, required deposits and returns."""
        target_amount = float(goal["target_amount"])
        current_amount = float(goal["current_amount"])
        monthly_deposit = float(goal["monthly_deposit"])
        expected_ann_return = float(goal["expected_return"])
        
        # Calculate remaining months
        try:
            target_dt = datetime.strptime(goal["target_date"], "%Y-%m-%d")
        except ValueError:
            target_dt = datetime.now()
            
        now = datetime.now()
        months = (target_dt.year - now.year) * 12 + (target_dt.month - now.month)
        months = max(1, months)

        achievement_rate = (current_amount / target_amount * 100.0) if target_amount > 0 else 0.0
        shortfall = max(0.0, target_amount - current_amount)

        # 1. Estimate future value with expected return
        # Monthly rate conversion: (1 + R)^(1/12) - 1
        r_expected = (1.0 + expected_ann_return) ** (1.0 / 12.0) - 1.0
        
        if r_expected <= 0:
            projected_fv = current_amount + (monthly_deposit * months)
        else:
            fv_from_current = current_amount * ((1.0 + r_expected) ** months)
            fv_from_deposits = monthly_deposit * (((1.0 + r_expected) ** months - 1) / r_expected)
            projected_fv = fv_from_current + fv_from_deposits

        # 2. Required monthly deposit (assuming expected return holds)
        if r_expected <= 0:
            required_monthly_deposit = shortfall / months
        else:
            fv_needed_from_deposits = max(0.0, target_amount - current_amount * ((1.0 + r_expected) ** months))
            required_monthly_deposit = fv_needed_from_deposits / (((1.0 + r_expected) ** months - 1) / r_expected)

        # 3. Required annual expected return (assuming monthly deposit remains constant)
        # We solve: PV * (1+r)^N + PMT * ((1+r)^N - 1)/r - G = 0 for r
        # Using binary search (bisection method)
        low_r = 0.0
        high_r = 10.0  # up to 1000% monthly rate (safe upper bound)
        required_monthly_rate = 0.0

        def fv_func(r_val: float) -> float:
            if r_val <= 0:
                return current_amount + (monthly_deposit * months)
            return current_amount * ((1.0 + r_val) ** months) + monthly_deposit * (((1.0 + r_val) ** months - 1) / r_val)

        if fv_func(0.0) >= target_amount:
            required_monthly_rate = 0.0
        else:
            for _ in range(100):
                mid_r = (low_r + high_r) / 2.0
                val = fv_func(mid_r)
                if abs(val - target_amount) < 1e-2:
                    required_monthly_rate = mid_r
                    break
                if val < target_amount:
                    low_r = mid_r
                else:
                    high_r = mid_r
            required_monthly_rate = (low_r + high_r) / 2.0

        required_ann_return = ((1.0 + required_monthly_rate) ** 12) - 1.0

        # Feasibility check
        is_feasible = projected_fv >= target_amount

        return {
            "goal_id": goal["goal_id"],
            "name": goal["name"],
            "target_amount": round(target_amount, 2),
            "current_amount": round(current_amount, 2),
            "achievement_rate": round(achievement_rate, 2),
            "shortfall": round(shortfall, 2),
            "months_remaining": months,
            "projected_fv": round(projected_fv, 2),
            "is_feasible": is_feasible,
            "required_monthly_deposit": round(required_monthly_deposit, 2),
            "required_annual_return": round(required_ann_return, 4),
            "expected_annual_return": round(expected_ann_return, 4),
        }
