"""Replays and audits historical trading decisions to compare logic changes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .personal_investment_policy import PersonalInvestmentPolicy
from .dividend_chasing_guard import DividendChasingGuard
from .autotrade_security_guard import AutotradeSecurityGuard


class DecisionReplay:
    """Loads a decision trace and re-evaluates it using the current policy and guard logic."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.trace_dir = self.project_root / "state" / "decision_traces"

    def replay_trace(self, trace_id: str) -> dict[str, Any]:
        """Loads a trace file, runs current logic, and returns a diff comparison."""
        trace_file = self.trace_dir / f"{trace_id}.json"
        if not trace_file.exists():
            # Try searching by matching prefix
            matches = list(self.trace_dir.glob(f"*{trace_id}*.json"))
            if matches:
                trace_file = matches[0]
            else:
                raise FileNotFoundError(f"Decision trace not found for ID: {trace_id}")

        with open(trace_file, "r", encoding="utf-8") as f:
            trace = json.load(f)

        symbol = trace["symbol"]
        stages = trace["stages"]

        # Extract parameters from the recorded trace to feed into current logic
        sig_data = stages.get("1_signal_generation", {})
        price = float(sig_data.get("price", 0.0))
        qty = float(sig_data.get("quantity", 0.0))
        order_amount = price * qty

        # 1. Re-run Dividend Chasing Guard
        chasing_guard = DividendChasingGuard(self.project_root)
        # Mock price history from trace if available, otherwise fallback
        price_history = sig_data.get("price_history_30d", [price] * 30)
        re_chasing = chasing_guard.evaluate_symbol_simple(symbol, price=price, price_history_30d=price_history)

        # 2. Re-run Autotrade Security Guard
        sec_guard = AutotradeSecurityGuard(self.project_root)
        re_sec = sec_guard.evaluate_order(symbol, order_amount)

        # Compare old vs new
        old_verdict = stages.get("5_autotrading_guard", {}).get("verdict", "unknown")
        new_verdict = re_sec.get("verdict", "unknown")

        old_chasing = stages.get("4_dividend_chasing_guard", {}).get("verdict", "unknown")
        new_chasing = re_chasing.get("verdict", "unknown")

        return {
            "trace_id": trace["trace_id"],
            "symbol": symbol,
            "recorded_at": trace["timestamp"],
            "inputs": {
                "price": price,
                "quantity": qty,
                "order_amount_krw": order_amount
            },
            "comparison": {
                "dividend_chasing_guard": {
                    "recorded": old_chasing,
                    "replayed": new_chasing,
                    "matched": old_chasing == new_chasing,
                    "details_replayed": re_chasing
                },
                "autotrade_security_guard": {
                    "recorded": old_verdict,
                    "replayed": new_verdict,
                    "matched": old_verdict == new_verdict,
                    "details_replayed": re_sec
                }
            },
            "logic_drift_detected": (old_verdict != new_verdict) or (old_chasing != new_chasing)
        }
