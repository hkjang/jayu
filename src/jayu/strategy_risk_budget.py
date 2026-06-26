from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class StrategyRiskBudgetManager:
    def __init__(self, project_root: Path, state_dir: Path):
        self.project_root = Path(project_root)
        self.state_dir = Path(state_dir)
        self.budget_config_path = self.project_root / "configs" / "strategy_risk_budgets.json"
        self.trade_history_path = self.state_dir / "strategy_trade_history.jsonl"
        self.budgets = self._load_budgets()

    def _load_budgets(self) -> dict[str, Any]:
        default_budgets = {
            "Default": {
                "monthly_loss_limit": 800.0,
                "max_trade_count": 25,
                "max_capital_allocation": 0.25
            }
        }
        if not self.budget_config_path.exists():
            return default_budgets
        
        try:
            with open(self.budget_config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("budgets", default_budgets)
        except Exception:
            return default_budgets

    def record_trade(self, strategy_name: str, pnl: float, timestamp: datetime | None = None) -> None:
        """Records a trade result (profit/loss in USD) to the history log."""
        ts = timestamp or datetime.now(UTC)
        row = {
            "strategy": strategy_name,
            "pnl": pnl,
            "timestamp": ts.isoformat(),
        }
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.trade_history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _get_monthly_stats(self, strategy_name: str) -> tuple[float, int]:
        """Calculates total loss (only negative PnL accumulated) and trade count for the current month."""
        if not self.trade_history_path.exists():
            return 0.0, 0
        
        now = datetime.now(UTC)
        current_year = now.year
        current_month = now.month

        total_loss = 0.0
        trade_count = 0

        with open(self.trade_history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    if trade.get("strategy") != strategy_name:
                        continue
                    
                    trade_time = datetime.fromisoformat(trade["timestamp"])
                    if trade_time.year == current_year and trade_time.month == current_month:
                        trade_count += 1
                        pnl = float(trade["pnl"])
                        if pnl < 0:
                            total_loss += abs(pnl)  # Accumulate losses as a positive sum
                except Exception:
                    continue

        return total_loss, trade_count

    def evaluate_strategy(self, strategy_name: str, current_allocation_ratio: float = 0.0) -> dict[str, Any]:
        """Evaluates whether a strategy has exceeded its monthly risk budget.
        Returns a dict:
          - suspended: bool
          - reason: Optional[str]
          - budget_limit: dict
          - current_usage: dict
        """
        # Fallback to Default budget if specific strategy budget is not defined
        budget = self.budgets.get(strategy_name, self.budgets.get("Default", {}))
        
        loss_limit = budget.get("monthly_loss_limit", 800.0)
        max_trades = budget.get("max_trade_count", 25)
        max_alloc = budget.get("max_capital_allocation", 0.25)

        current_loss, current_trades = self._get_monthly_stats(strategy_name)

        suspended = False
        reasons = []

        if current_loss >= loss_limit:
            suspended = True
            reasons.append(f"월간 누적 손실 한도 초과 (손실: ${current_loss:.2f} >= 한도: ${loss_limit:.2f})")

        if current_trades >= max_trades:
            suspended = True
            reasons.append(f"월간 최대 거래 횟수 초과 (횟수: {current_trades}회 >= 한도: {max_trades}회)")

        if current_allocation_ratio > max_alloc:
            suspended = True
            reasons.append(f"전략 최대 자금 할당 비율 초과 (요청: {current_allocation_ratio*100:.1f}% >= 한도: {max_alloc*100:.1f}%)")

        return {
            "strategy": strategy_name,
            "suspended": suspended,
            "reason": " | ".join(reasons) if suspended else None,
            "budget_limit": {
                "monthly_loss_limit": loss_limit,
                "max_trade_count": max_trades,
                "max_capital_allocation": max_alloc,
            },
            "current_usage": {
                "monthly_loss": current_loss,
                "trade_count": current_trades,
                "capital_allocation": current_allocation_ratio,
                "remaining_loss_budget": max(0.0, loss_limit - current_loss),
                "remaining_trade_budget": max(0, max_trades - current_trades),
            }
        }
    
    def get_all_budgets_status(self) -> list[dict[str, Any]]:
        """Returns the evaluation status of all configured strategies."""
        statuses = []
        for strategy in self.budgets.keys():
            if strategy == "Default":
                continue
            statuses.append(self.evaluate_strategy(strategy))
        return statuses
