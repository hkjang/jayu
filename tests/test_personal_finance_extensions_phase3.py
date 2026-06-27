"""Tests for Phase 3 Personal Investment extensions.

Covers:
- personal_investment_score
- portfolio_purpose_tags
- investment_journal
- dividend_living_expense_simulator
- loss_recovery_planner
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from jayu.personal_investment_score import PersonalInvestmentScore
from jayu.portfolio_purpose_tags import PortfolioPurposeTags
from jayu.investment_journal import InvestmentJournal
from jayu.dividend_living_expense_simulator import DividendLivingExpenseSimulator
from jayu.loss_recovery_planner import LossRecoveryPlanner


# ──────────────────────────────────────────────────────────────────────────────
# Personal Investment Score Tests
# ──────────────────────────────────────────────────────────────────────────────
class TestPersonalInvestmentScore:
    def test_score_calculation(self, tmp_path: Path) -> None:
        # Create dummy user_approval_audit.jsonl
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        audit_file = state_dir / "user_approval_audit.jsonl"
        
        with open(audit_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ticker": "AAPL",
                "action": "buy",
                "recommendation_verdict": "pass",
                "user_decision": "approve",
                "rationale": "Strong thesis"
            }) + "\n")

        # Create dummy budget file
        budget_file = state_dir / "monthly_budget.json"
        with open(budget_file, "w", encoding="utf-8") as f:
            json.dump({
                "monthly_income": 5000000,
                "living_expense": 2000000,
                "fixed_savings": 2000000,
                "investment_budget": 1000000,
                "emergency_reserve": 500000
            }, f)

        score_calc = PersonalInvestmentScore(tmp_path)
        res = score_calc.calculate_score()
        
        assert "total_score" in res
        assert "grade" in res
        assert "breakdown" in res
        assert res["total_score"] >= 0 and res["total_score"] <= 100


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio Purpose Tags Tests
# ──────────────────────────────────────────────────────────────────────────────
class TestPortfolioPurposeTags:
    def test_tags_crud(self, tmp_path: Path) -> None:
        tags_mgr = PortfolioPurposeTags(tmp_path)
        assert tags_mgr.get_tags("AAPL") == []

        # Set tags
        tags_mgr.set_tags("AAPL", ["노후", "배당"])
        assert tags_mgr.get_tags("AAPL") == ["노후", "배당"]

        # All tags
        all_tags = tags_mgr.load_tags()
        assert all_tags["AAPL"] == ["노후", "배당"]

        # Clear tags
        tags_mgr.set_tags("AAPL", [])
        assert tags_mgr.get_tags("AAPL") == []


# ──────────────────────────────────────────────────────────────────────────────
# Investment Journal Tests
# ──────────────────────────────────────────────────────────────────────────────
class TestInvestmentJournal:
    def test_journal_crud_and_outcomes(self, tmp_path: Path) -> None:
        journal = InvestmentJournal(tmp_path)
        assert journal.load_journal() == []

        # Add entry
        entry = journal.add_entry("TSLA", "approve", 200.0, "Long term TSLA thesis")
        assert entry["ticker"] == "TSLA"
        assert entry["action_type"] == "approve"
        assert entry["entry_price"] == 200.0
        assert entry["note"] == "Long term TSLA thesis"
        assert entry["return_5d_pct"] is None

        entries = journal.load_journal()
        assert len(entries) == 1
        entry_id = entries[0]["entry_id"]

        # Update outcomes mock
        with patch("yfinance.Ticker") as mock_ticker:
            # Mock historical data for ticker
            mock_hist = MagicMock()
            mock_hist.empty = False
            import pandas as pd
            import numpy as np
            dates = pd.date_range(start="2026-06-01", periods=30)
            mock_hist = pd.DataFrame({"Close": np.linspace(200.0, 250.0, 30)}, index=dates)
            
            mock_ticker_inst = MagicMock()
            mock_ticker_inst.history.return_value = mock_hist
            mock_ticker.return_value = mock_ticker_inst

            journal.update_outcomes()

        # Reload entries and check updated fields
        entries = journal.load_journal()
        assert len(entries) == 1
        # The return_5d_pct is None in the test because target_date (start + 5 days) is in the future.
        # But wait! To make start_dt be in the past so it calculates the outcome:
        # Let's mock datetime in the journal entry to be in the past!
        # Let's set created_at to 10 days ago.
        from datetime import datetime, timedelta
        past_date = (datetime.now() - timedelta(days=10)).isoformat()
        entries[0]["created_at"] = past_date
        journal.save_journal(entries)

        with patch("yfinance.download") as mock_download:
            # Mock historical data for yfinance.download
            import pandas as pd
            import numpy as np
            dates = pd.date_range(start="2026-06-01", periods=5)
            mock_hist = pd.DataFrame({"Close": np.linspace(220.0, 240.0, 5)}, index=dates)
            mock_download.return_value = mock_hist

            journal.update_outcomes()

        # Reload entries and check updated fields
        entries = journal.load_journal()
        assert len(entries) == 1
        assert entries[0]["return_5d_pct"] is not None
        assert entries[0]["return_5d_pct"] == 10.0

        # Delete entry
        assert journal.delete_entry(entry_id) is True
        assert journal.load_journal() == []


# ──────────────────────────────────────────────────────────────────────────────
# Dividend Living Expense Simulator Tests
# ──────────────────────────────────────────────────────────────────────────────
class TestDividendLivingExpenseSimulator:
    def test_simulation(self, tmp_path: Path) -> None:
        sim = DividendLivingExpenseSimulator(tmp_path)
        
        # Test default target or custom target
        sim.save_target(1500000)
        
        # Pass holdings directly to simulate()
        holdings = [
            {"ticker": "SCHD", "quantity": 1000.0, "price": 75.0}
        ]
        res = sim.simulate(holdings=holdings)
        
        assert res["monthly_target_krw"] == 1500000
        assert res["current_monthly_dividend_krw"] > 0
        assert res["shortfall_krw"] > 0
        assert res["achievement_rate"] > 0
        assert res["needed_additional_capital_krw"] > 0
        assert "drip_future_snapshots" in res


# ──────────────────────────────────────────────────────────────────────────────
# Loss Recovery Planner Tests
# ──────────────────────────────────────────────────────────────────────────────
class TestLossRecoveryPlanner:
    def test_recovery_plan(self) -> None:
        planner = LossRecoveryPlanner()
        plan = planner.calculate_recovery_plan(current_portfolio_value=10000000, loss_pct=0.25)
        
        assert plan["loss_pct"] == 25.0
        assert plan["break_even_return_pct"] == pytest.approx(33.3, rel=0.01)
        assert plan["shortfall_amount_krw"] == pytest.approx(3333333.33, rel=0.01)
        assert "recovery_months_by_return" in plan
        assert "deposit_scenarios_recovery_months_at_15pct" in plan
        assert len(plan["risk_reduction_advices"]) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Toss Orders Manager Tests
# ──────────────────────────────────────────────────────────────────────────────
class TestTossOrdersManager:
    def test_toss_orders_cache(self, tmp_path: Path) -> None:
        from jayu.toss_orders import TossOrdersManager

        mgr = TossOrdersManager(tmp_path)
        if mgr.orders_file.exists():
            mgr.orders_file.unlink()

        # Empty cache should stay empty; live data comes only from Toss Order History.
        assert mgr.load_orders() == []

        # Test save and load back
        custom_orders = [{"orderId": "custom_1", "symbol": "AAPL", "side": "BUY"}]
        mgr._save_orders(custom_orders)

        assert mgr.load_orders() == custom_orders

    def test_toss_orders_fetches_official_history_and_detail(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import date

        from jayu.paths import RuntimePaths
        from jayu.toss_orders import TossOrdersManager

        class FakeSecret:
            def __init__(self, value: str) -> None:
                self.value = value

            def get_secret_value(self) -> str:
                return self.value

        class FakeSettings:
            toss_api_key = FakeSecret("client-id")
            toss_secret_key = FakeSecret("client-secret")
            toss_account = FakeSecret("account-seq")
            toss_oauth_auth_style = "body"

        clients = []

        class FakeTossClient:
            def __init__(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs
                self.calls = []
                clients.append(self)

            def orders(self, **kwargs):
                self.calls.append(("orders", kwargs))
                if kwargs["status"] == "CLOSED" and kwargs.get("cursor") is None:
                    return {
                        "result": {
                            "orders": [
                                {
                                    "orderId": "closed-1",
                                    "symbol": "005930",
                                    "side": "BUY",
                                    "status": "FILLED",
                                    "orderedAt": "2026-03-28T09:30:00+09:00",
                                    "currency": "KRW",
                                }
                            ],
                            "hasNext": True,
                            "nextCursor": "cursor-2",
                        }
                    }
                if kwargs["status"] == "CLOSED":
                    return {
                        "result": {
                            "orders": [
                                {
                                    "orderId": "closed-2",
                                    "symbol": "AAPL",
                                    "side": "SELL",
                                    "status": "FILLED",
                                    "orderedAt": "2026-03-27T09:30:00+09:00",
                                    "currency": "USD",
                                }
                            ],
                            "hasNext": False,
                        }
                    }
                return {
                    "result": {
                        "orders": [
                            {
                                "orderId": "open-1",
                                "symbol": "SOXL",
                                "side": "BUY",
                                "status": "OPEN",
                                "orderedAt": "2026-03-29T09:30:00+09:00",
                                "currency": "USD",
                            }
                        ]
                    }
                }

            def order(self, order_id: str, **kwargs):
                self.calls.append(("order", order_id, kwargs))
                return {
                    "result": {
                        "orderId": order_id,
                        "symbol": "005930",
                        "side": "BUY",
                        "orderType": "LIMIT",
                        "timeInForce": "DAY",
                        "status": "FILLED",
                        "price": "70000",
                        "quantity": "10",
                        "orderAmount": None,
                        "currency": "KRW",
                        "orderedAt": "2026-03-28T09:30:00+09:00",
                        "canceledAt": None,
                        "execution": {
                            "filledQuantity": "10",
                            "averageFilledPrice": "70000",
                            "filledAmount": "700000",
                            "commission": "1400",
                            "tax": "0",
                            "filledAt": "2026-03-28T09:31:15+09:00",
                            "settlementDate": "2026-03-30",
                        },
                    }
                }

        monkeypatch.setattr("jayu.toss_orders.load_settings", lambda config: FakeSettings())
        monkeypatch.setattr("jayu.toss_orders.TossInvestClient", FakeTossClient)

        paths = RuntimePaths.from_root(tmp_path)
        mgr = TossOrdersManager(tmp_path)

        result = mgr.fetch_and_save(paths, account="override-account", today=date(2026, 6, 27))

        assert result["status"] == "success"
        assert result["from"] == "2025-06-27"
        assert result["to"] == "2026-06-27"
        assert result["closed_pages"] == 2
        assert result["closed_count"] == 2
        assert result["open_count"] == 1
        assert result["count"] == 3
        assert "GET /api/v1/orders" in result["source"]
        assert [order["orderId"] for order in mgr.load_orders()] == ["open-1", "closed-1", "closed-2"]

        orders_calls = clients[0].calls
        assert orders_calls[0][1] == {
            "status": "CLOSED",
            "account": "override-account",
            "from_date": "2025-06-27",
            "to_date": "2026-06-27",
            "cursor": None,
            "limit": 100,
        }
        assert orders_calls[1][1]["cursor"] == "cursor-2"
        assert orders_calls[2][1]["status"] == "OPEN"

        detail = mgr.fetch_order_detail(paths, "closed-1", account="override-account")

        assert detail["status"] == "success"
        assert detail["order"]["execution"]["filledQuantity"] == "10"
        assert "GET /api/v1/orders/{orderId}" in detail["source"]
        assert mgr.load_order_detail("closed-1")["execution"]["settlementDate"] == "2026-03-30"
        assert clients[1].calls == [("order", "closed-1", {"account": "override-account"})]
