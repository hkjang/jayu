"""Integration and unit tests for the Investment Decision Hub component suite."""

from __future__ import annotations

import json
import time
from pathlib import Path
import pytest

from src.jayu.order_history_intelligence import OrderHistoryIntelligence
from src.jayu.dividend_reconciliation import DividendReconciler
from src.jayu.portfolio_decision_hub import PortfolioDecisionHub
from src.jayu.signal_outcome_tracker import SignalOutcomeTracker
from src.jayu.agent_guardrail import AgentGuardrail


@pytest.fixture
def temp_project(tmp_path):
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "signals").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_order_history_intelligence(temp_project):
    # 1. Setup mock toss_orders.json (FIFO: BUY 10 AAPL @ 150, BUY 10 AAPL @ 160, SELL 15 AAPL @ 180)
    # Total buy cost for 15 AAPL: 10 * 150 + 5 * 160 = 1500 + 800 = 2300 USD
    # Total sell revenue: 15 * 180 = 2700 USD
    # P&L = +400 USD
    orders = [
        {"symbol": "AAPL", "orderType": "BUY", "quantity": 10, "price": 150.0, "fee": 1.5, "date": "2026-06-01T10:00:00Z"},
        {"symbol": "AAPL", "orderType": "BUY", "quantity": 10, "price": 160.0, "fee": 1.6, "date": "2026-06-02T10:00:00Z"},
        {"symbol": "AAPL", "orderType": "SELL", "quantity": 15, "price": 180.0, "fee": 2.5, "date": "2026-06-03T10:00:00Z"}
    ]
    (temp_project / "state" / "toss_orders.json").write_text(json.dumps(orders), encoding="utf-8")

    intel = OrderHistoryIntelligence(temp_project)
    res = intel.analyze_trades()

    assert res["status"] == "success"
    assert res["summary"]["total_orders_processed"] == 3
    # FIFO Realized P&L = 400.0 (excluding fees in net calculation as per basic arithmetic logic)
    assert res["summary"]["total_realized_pnl_krw"] == 400.0
    assert res["summary"]["total_commissions_krw"] == 6.0
    assert len(res["open_positions"]) == 1
    assert res["open_positions"][0]["symbol"] == "AAPL"
    assert res["open_positions"][0]["quantity"] == 5.0 # 20 - 15 = 5 remaining


def test_dividend_reconciliation_matching(temp_project):
    # Setup mock actual receipts with correct CSV headers: date, symbol, amount, currency, source
    receipts_csv = (
        "date,symbol,amount,currency,source\n"
        "2026-06-15,AAPL,15.0,USD,manual\n"
        "2026-06-18,MSFT,20.0,USD,manual\n"
    )
    (temp_project / "state" / "dividend_actual_receipts.csv").write_text(receipts_csv, encoding="utf-8")

    reconciler = DividendReconciler(temp_project)
    receipts = reconciler.load_actual_receipts()

    assert len(receipts) == 2
    assert receipts[0]["symbol"] == "AAPL"
    assert float(receipts[1]["amount"]) == 20.0


def test_portfolio_decision_hub(temp_project):
    # Setup configs
    policy_yaml = """
policy:
  asset_allocation:
    max_single_position_ratio: 0.20
  dividend_quality:
    min_dividend_trust_score: 80.0
"""
    (temp_project / "configs" / "investment_policy.yaml").write_text(policy_yaml, encoding="utf-8")

    # Setup mock holdings in portfolio_hub / toss snapshot
    holdings_data = [
        {"symbol": "AAPL", "holdingQuantity": 10, "currentPrice": 150.0, "currency": "USD"}, # 1500 USD (30%) -> Overweight!
        {"symbol": "T", "holdingQuantity": 100, "currentPrice": 18.0, "currency": "USD"}   # 1800 USD (36%) -> Overweight!
    ]
    (temp_project / "state" / "toss_account_snapshot.json").write_text(json.dumps(holdings_data), encoding="utf-8")

    # Setup mock cash
    (temp_project / "state" / "toss_accounts_cache.json").write_text(json.dumps({
        "timestamp": time.time(),
        "accounts": [{"cash_krw": 1700.0 * 1350.0}] # 1700 USD cash -> Total value = 5000 USD
    }), encoding="utf-8")

    hub = PortfolioDecisionHub(temp_project)
    res = hub.evaluate_portfolio()

    assert res["summary"]["rebalance_required_count"] >= 1
    # Check that AAPL or T is flagged for rebalance since they exceed 20% of 5000 USD
    decisions = {d["symbol"]: d for d in res["decisions"]}
    assert decisions["AAPL"]["verdict"] == "rebalance"


def test_signal_outcome_tracker(temp_project):
    # 1. Setup today_signals.json
    signals = [
        {"symbol": "MSFT", "strategy": "DividendGrowth", "price": 400.0, "date": "2026-06-25"}
    ]
    (temp_project / "signals" / "today_signals.json").write_text(json.dumps(signals), encoding="utf-8")

    tracker = SignalOutcomeTracker(temp_project)
    res = tracker.track_new_signals()

    assert res["status"] == "success"
    assert res["summary"]["total_signals_tracked"] == 1
    assert res["outcomes"][0]["symbol"] == "MSFT"
    assert res["outcomes"][0]["entry_price"] == 400.0


def test_agent_guardrail():
    # Test safe commands
    assert AgentGuardrail.is_safe_command("ls -la")[0] is True
    assert AgentGuardrail.is_safe_command("cat state/toss_orders.json")[0] is True

    # Test dangerous commands
    assert AgentGuardrail.is_safe_command("rm -rf /")[0] is False
    assert AgentGuardrail.is_safe_command("bash hack.sh")[0] is False

    # Test tool validation
    assert AgentGuardrail.validate_tool_invocation("get_status", {})[0] is True
    assert AgentGuardrail.validate_tool_invocation("write_to_file", {"TargetFile": "hack.py"})[0] is False
    assert AgentGuardrail.validate_tool_invocation("run_command", {"CommandLine": "rm -rf"})[0] is False

    # Test citation check
    assert AgentGuardrail.verify_citation_presence("이 종목의 배당에 대한 상세 근거는 [report.md](file:///c:/path/to/report.md)를 참고하세요.") is True
    assert AgentGuardrail.verify_citation_presence("이 종목의 배당은 매우 우수합니다.") is False
