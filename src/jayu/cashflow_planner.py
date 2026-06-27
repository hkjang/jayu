from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class CashflowPlanner:
    """Manages monthly cashflow planning, income, expenses, and portfolio allocations."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.cashflow_file = project_root / "state" / "cashflows.json"

    def load_cashflows(self) -> list[dict[str, Any]]:
        if not self.cashflow_file.exists():
            return []
        try:
            with open(self.cashflow_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_cashflows(self, cashflows: list[dict[str, Any]]) -> None:
        self.cashflow_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cashflow_file, "w", encoding="utf-8") as f:
            json.dump(cashflows, f, indent=2, ensure_ascii=False)

    def add_cashflow(
        self,
        month: str,  # YYYY-MM
        salary_deposit: float,
        expected_dividends: float,
        extra_deposits: float,
        planned_buys: float,
        reserved_cash: float,
    ) -> dict[str, Any]:
        cashflows = self.load_cashflows()
        # Filter out existing month
        cashflows = [c for c in cashflows if c["month"] != month]

        record = {
            "month": month,
            "salary_deposit": salary_deposit,
            "expected_dividends": expected_dividends,
            "extra_deposits": extra_deposits,
            "planned_buys": planned_buys,
            "reserved_cash": reserved_cash,
            "created_at": datetime.now().isoformat()
        }
        cashflows.append(record)
        self.save_cashflows(sorted(cashflows, key=lambda x: x["month"]))
        return record

    def delete_cashflow(self, month: str) -> bool:
        cashflows = self.load_cashflows()
        filtered = [c for c in cashflows if c["month"] != month]
        if len(filtered) == len(cashflows):
            return False
        self.save_cashflows(filtered)
        return True

    def calculate_monthly_budget(
        self,
        record: dict[str, Any],
        allocation_weights: dict[str, float] | None = None
    ) -> dict[str, Any]:
        """Calculate total available cashflow budget and distribute it into 4 strategy pools."""
        if allocation_weights is None:
            # Default weights matching common balanced long-term portfolios
            allocation_weights = {
                "short_term": 0.10,
                "swing": 0.20,
                "long_term": 0.40,
                "dividend": 0.30
            }

        salary = float(record["salary_deposit"])
        dividends = float(record["expected_dividends"])
        extra = float(record["extra_deposits"])
        buys = float(record["planned_buys"])
        reserved = float(record["reserved_cash"])

        # Net cashflow available for new investments
        total_income = salary + dividends + extra
        net_investable = max(0.0, total_income - reserved - buys)

        # Distribute net investable budget based on weights
        allocations = {}
        for strategy, weight in allocation_weights.items():
            allocations[strategy] = round(net_investable * weight, 2)

        return {
            "month": record["month"],
            "total_income": round(total_income, 2),
            "net_investable_budget": round(net_investable, 2),
            "planned_buys": round(buys, 2),
            "reserved_cash": round(reserved, 2),
            "allocation_weights": allocation_weights,
            "allocations": allocations
        }
