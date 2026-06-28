"""Integration tests for the Investment OS productization pipeline components."""

from __future__ import annotations

import json
import time
from datetime import datetime, UTC
from pathlib import Path
import pytest

from src.jayu.personal_investment_policy import PersonalInvestmentPolicy
from src.jayu.policy_violation_report import PolicyViolationReporter
from src.jayu.state_schema_registry import validate_state_structure
from src.jayu.state_migration_runner import StateMigrationRunner
from src.jayu.state_doctor import StateDoctor
from src.jayu.account_change_diff import AccountChangeDiff
from src.jayu.home_briefing import HomeBriefing
from src.jayu.decision_trace_recorder import DecisionTraceRecorder
from src.jayu.decision_replay import DecisionReplay


@pytest.fixture
def temp_project(tmp_path):
    # Setup standard directory structures
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "runs" / "reports").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_personal_policy_compliance(temp_project):
    # 1. Setup YAML policy
    policy_yaml = """
policy:
  asset_allocation:
    max_leverage_ratio: 0.15
    min_cash_ratio: 0.10
    max_single_position_ratio: 0.25
  trading_restrictions:
    max_daily_trades: 3
    cool_down_days_after_loss: 3
    max_monthly_loss_krw: 1000000
  dividend_quality:
    min_dividend_trust_score: 80.0
    exclude_special_dividend_chasing: true
"""
    (temp_project / "configs" / "investment_policy.yaml").write_text(policy_yaml, encoding="utf-8")
    
    policy = PersonalInvestmentPolicy(temp_project)
    
    # Setup mock holdings and cash
    holdings = [
        {"symbol": "AAPL", "quantity": 10, "price": 150.0, "value_krw": 1500.0 * 1350.0},
        {"symbol": "SOXL", "quantity": 5, "price": 40.0, "value_krw": 200.0 * 1350.0} # Leverage stock
    ]
    cash = 2000.0 * 1350.0 # Total value = 3700.0 * 1350 = 4,995,000 KRW
    
    # AAPL order of 500 USD (post-ratio: (1500+500)/3700 = 54% > 25%) -> Violation!
    res = policy.evaluate_policy_compliance(
        symbol="AAPL",
        order_amount_krw=500.0 * 1350.0,
        holdings=holdings,
        cash_krw=cash,
        is_dividend_focus=True,
        dividend_trust_score=75.0 # Low dividend score -> Violation!
    )
    
    assert res["compliant"] is False
    assert any("비중 한도 초과" in v for v in res["violations"])
    assert any("배당 신뢰도 품질 기준 미달" in v for v in res["violations"])


def test_policy_violation_reporter(temp_project):
    policy_yaml = """
policy:
  asset_allocation:
    max_leverage_ratio: 0.15
    min_cash_ratio: 0.10
    max_single_position_ratio: 0.25
  trading_restrictions:
    max_daily_trades: 5
    cool_down_days_after_loss: 5
    max_monthly_loss_krw: 2000000
  dividend_quality:
    min_dividend_trust_score: 80.0
    exclude_special_dividend_chasing: true
"""
    (temp_project / "configs" / "investment_policy.yaml").write_text(policy_yaml, encoding="utf-8")
    
    reporter = PolicyViolationReporter(temp_project)
    
    holdings = [{"symbol": "TQQQ", "quantity": 50, "price": 100.0, "value_krw": 5000.0 * 1350.0}] # Leverage 100% -> Violation!
    cash = 100.0 * 1350.0
    
    res = reporter.generate_report(
        signals=[],
        holdings=holdings,
        cash_krw=cash
    )
    
    assert res["compliant"] is False
    assert "레버리지 비중" in res["markdown"]
    assert Path(temp_project / res["markdown_path"]).exists()


def test_state_versioning_and_migration(temp_project):
    # Write a legacy v1.0 dividend cache
    legacy_cache = {
        "ticker": "AAPL",
        "fetched_at": time.time(),
        "dividends": [],
        "splits": [],
        "schema_version": "1.0"
    }
    cache_file = temp_project / "state" / "dividend_cache.json"
    cache_file.write_text(json.dumps(legacy_cache), encoding="utf-8")
    
    # Check validation fails or succeeds depending on requirements
    is_valid, err = validate_state_structure("dividend_cache", legacy_cache)
    assert is_valid is True # valid structure, but version is old
    
    # Run migration
    runner = StateMigrationRunner(temp_project)
    res = runner.migrate_file("dividend_cache", cache_file)
    
    assert res["status"] == "success"
    assert res["from_version"] == "1.0"
    assert res["to_version"] == "1.1"
    
    # Check backup is created
    assert len(list((temp_project / "state" / "backups").glob("dividend_cache_*.json"))) == 1
    
    # Verify migrated file contains new fields
    with open(cache_file, "r") as f:
        migrated = json.load(f)
    assert "error_reason" in migrated
    assert migrated["schema_version"] == "1.1"


def test_state_doctor(temp_project):
    doctor = StateDoctor(temp_project)
    
    # Case 1: missing files
    res = doctor.diagnose_all()
    assert res["healthy"] is False
    assert res["reports"]["toss_account_snapshot"]["status"] == "warning"
    
    # Case 2: Corrupted JSON
    (temp_project / "state" / "toss_account_snapshot.json").write_text("{bad json", encoding="utf-8")
    res2 = doctor.diagnose_all()
    assert res2["reports"]["toss_account_snapshot"]["status"] == "corrupted"


def test_account_change_diff(temp_project):
    diff = AccountChangeDiff(temp_project)
    
    # Setup previous snapshot in backup
    prev_data = [
        {"symbol": "AAPL", "holdingQuantity": 10, "currentPrice": 150.0, "currency": "USD"},
        {"symbol": "MSFT", "holdingQuantity": 5, "currentPrice": 300.0, "currency": "USD"}
    ]
    backup_dir = temp_project / "state" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "toss_account_snapshot_20260627_120000.json").write_text(json.dumps(prev_data), encoding="utf-8")
    
    # Setup current snapshot (AAPL price up, MSFT quantity up)
    curr_data = [
        {"symbol": "AAPL", "holdingQuantity": 10, "currentPrice": 160.0, "currency": "USD"}, # Price effect: +10 USD * 10 = +100 USD
        {"symbol": "MSFT", "holdingQuantity": 7, "currentPrice": 300.0, "currency": "USD"}  # Qty effect: +2 MSFT * 300 = +600 USD
    ]
    (temp_project / "state" / "toss_account_snapshot.json").write_text(json.dumps(curr_data), encoding="utf-8")
    
    res = diff.calculate_diff()
    assert res["status"] == "success"
    assert res["summary"]["total_change_usd"] == 700.0
    assert res["summary"]["effects"]["price_change_contribution_usd"] == 100.0
    assert res["summary"]["effects"]["quantity_change_contribution_usd"] == 600.0


def test_decision_replay(temp_project):
    from src.jayu.dividend_source_yahoo import DividendSourceYahoo
    recorder = DecisionTraceRecorder(temp_project)
    
    # Write mock toss_security_master.json to avoid metadata check blocking TSLA
    (temp_project / "state" / "toss_security_master.json").write_text(
        json.dumps({
            "TSLA": {
                "name": "Tesla",
                "market": "US",
                "currency": "USD",
                "warnings": {}
            }
        }),
        encoding="utf-8"
    )
    
    # Write mock yahoo cache for TSLA to pass dividend quality gate (otherwise it gets excluded)
    source = DividendSourceYahoo(temp_project)
    source.save_cache("TSLA", {
        "ticker": "TSLA",
        "fetched_at": time.time(),
        "dividends": [{"date": "2026-06-15", "amount": 1.50}],
        "splits": []
    })
    
    sig_data = {"symbol": "TSLA", "price": 200.0, "quantity": 10, "price_history_30d": [200.0]*30}
    risk_eval = {"verdict": "allow"}
    quality_gate = {"decision": "pass", "trust_score": 90.0}
    chasing = {"verdict": "allow"}
    verdict = {"verdict": "allow"}
    
    trace_id = recorder.record_trace("TSLA", sig_data, risk_eval, quality_gate, chasing, verdict)
    assert trace_id.startswith("trace_TSLA_")
    assert (temp_project / "state" / "decision_traces" / f"{trace_id}.json").exists()
    
    # Replay
    replay = DecisionReplay(temp_project)
    
    # Mock evaluate_order to return allow or simply mock the security master as we did
    res = replay.replay_trace(trace_id)
    
    assert res["symbol"] == "TSLA"
    assert res["comparison"]["autotrade_security_guard"]["matched"] is True, f"Replay mismatch! Reason: {res['comparison']['autotrade_security_guard']['details_replayed'].get('reason')}"
