from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from jayu.artifacts import RunContext
from jayu.backup_manager import BackupManager
from jayu.dashboard_permission_mode import DashboardPermissionModeManager
from jayu.domain_event_bus import DomainEvent, DomainEventBus
from jayu.next_command_recommender import NextCommandRecommender
from jayu.notification_policy_engine import NotificationPolicyEngine
from jayu.paths import RuntimePaths
from jayu.pre_trade_checklist import PreTradeChecklistEvaluator
from jayu.registry import ExperimentRegistry
from jayu.settings import Settings
from jayu.stock_knowledge_card import StockKnowledgeCardManager
from jayu.strategy_risk_budget import StrategyRiskBudgetManager


@pytest.fixture
def temp_dirs():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        project_root = tmp_path / "project"
        state_dir = project_root / "state"
        runs_dir = project_root / "runs"
        signals_dir = project_root / "signals"
        reports_dir = project_root / "reports"
        configs_dir = project_root / "configs"

        for d in [project_root, state_dir, runs_dir, signals_dir, reports_dir, configs_dir]:
            d.mkdir(parents=True, exist_ok=True)

        yield {
            "project_root": project_root,
            "state_dir": state_dir,
            "runs_dir": runs_dir,
            "signals_dir": signals_dir,
            "reports_dir": reports_dir,
            "configs_dir": configs_dir,
        }


# 1. Domain Event Bus Tests
def test_domain_event_bus(temp_dirs):
    bus = DomainEventBus(temp_dirs["state_dir"])
    evt = bus.publish(
        run_id="test_run_123",
        event_type="signal_created",
        source_module="signal_generation",
        ticker="SOXL",
        severity="info",
        payload={"message": "Signal generated successfully"},
    )
    
    assert evt.run_id == "test_run_123"
    assert evt.event_type == "signal_created"
    assert evt.ticker == "SOXL"
    assert evt.payload["message"] == "Signal generated successfully"
    assert len(evt.payload_hash) == 64  # SHA256 length

    # Retrieve events
    events = bus.get_events()
    assert len(events) >= 1
    assert events[0].event_id == evt.event_id


# 2. Experiment Registry Expansion Tests
def test_experiment_registry_expansion(temp_dirs):
    db_path = temp_dirs["state_dir"] / "experiments.sqlite"
    registry = ExperimentRegistry(db_path)
    
    # Create mock RunContext with research mode via factory to bypass validation
    settings = Settings(mode="research")
    paths = RuntimePaths.from_root(temp_dirs["project_root"])
    context = RunContext.create(paths, settings, "test")
    
    registry.start(context)
    
    # Register experiment
    registry.register_experiment(
        run_id=context.run_id,
        objective="Verify momentum alpha",
        hypothesis="Momentum strategy outperforms in bull regimes",
        target_tickers=["SOXL", "TQQQ"],
        strategy_name="Momentum_V4",
    )
    
    # Record result
    registry.record_experiment_result(
        run_id=context.run_id,
        result_metrics={"sharpe": 2.1, "return": 0.15},
        promoted=True,
    )
    
    # Fetch experiments
    experiments = registry.get_experiments()
    assert len(experiments) == 1
    assert experiments[0]["run_id"] == context.run_id
    assert experiments[0]["strategy_name"] == "Momentum_V4"
    assert experiments[0]["promoted"] == 1


# 3. Backup Manager Tests
def test_backup_manager(temp_dirs):
    manager = BackupManager(temp_dirs["project_root"], temp_dirs["state_dir"])
    
    # Write dummy file to backup
    dummy_file = temp_dirs["configs_dir"] / "settings.json"
    dummy_file.write_text('{"mode": "research"}', encoding="utf-8")

    # Create backup
    zip_path, manifest = manager.create_backup()
    assert zip_path.exists()
    assert "zip_sha256" in manifest
    assert len(manifest["files"]) > 0

    # Dry-run restore
    report = manager.restore_backup(zip_path, dry_run=True)
    assert report["valid"] is True
    assert report["dry_run"] is True
    assert len(report["actions"]) > 0


# 4. Next Command Recommender Tests
def test_next_command_recommender(temp_dirs):
    # settings.json config file setup to pass Settings validation
    configs_dir = temp_dirs["configs_dir"]
    config_file = configs_dir / "settings.json"
    config_file.write_text('{"mode": "research"}', encoding="utf-8")

    settings = Settings(mode="research")
    paths = RuntimePaths.from_root(temp_dirs["project_root"])
    recommender = NextCommandRecommender(settings, paths)
    
    # 1. No signal file exists -> should recommend 'signal'
    rec1 = recommender.recommend()
    assert "signal" in rec1["command"]
    assert "신호가 아직 생성되지 않았습니다" in rec1["reason"]

    # Write dummy signal file
    paths.signal_file.parent.mkdir(parents=True, exist_ok=True)
    paths.signal_file.write_text("{}", encoding="utf-8")

    # 2. Today's report missing -> should recommend 'report build'
    rec2 = recommender.recommend()
    assert "report build" in rec2["command"]
    assert "보고서가 빌드되지 않았습니다" in rec2["reason"]


# 5. Pre-trade Checklist Evaluator Tests
def test_pre_trade_checklist_evaluator(temp_dirs):
    config_path = temp_dirs["configs_dir"] / "pre_trade_checklist.yaml"
    # Create checklist yaml
    config_path.write_text("""
data_freshness:
  max_delay_minutes: 15
  fail_severity: "blocked"
risk_gate:
  require_all_passed: true
  fail_severity: "blocked"
account_cash:
  min_cash_usd: 500.0
  min_cash_krw: 500000.0
  fail_severity: "warning"
user_approval:
  require_explicit_approval: true
  fail_severity: "blocked"
""", encoding="utf-8")

    evaluator = PreTradeChecklistEvaluator(config_path)
    
    # Friday 15:00 UTC = New York Friday 11:00 AM (Within regular market hours)
    market_time = datetime(2026, 6, 26, 15, 0, 0, tzinfo=UTC)
    
    # Test Blocked scenario (no user approval)
    res1 = evaluator.evaluate(
        signal_data={"risk_passed": True, "score": 0.8},
        account_data={"cash_usd": 1000.0, "cash_krw": 1500000.0},
        is_approved=False,
        last_data_update=datetime.now(UTC),
        market_time=market_time,
    )
    assert res1["status"] == "blocked"
    # User approval failure should be in reasons
    approval_reasons = [r for r in res1["reasons"] if "의사결정 승인" in r]
    assert len(approval_reasons) > 0

    # Test Passed scenario
    res2 = evaluator.evaluate(
        signal_data={"risk_passed": True, "score": 0.8},
        account_data={"cash_usd": 1000.0, "cash_krw": 1500000.0},
        is_approved=True,
        last_data_update=datetime.now(UTC),
        market_time=market_time,
    )
    assert res2["status"] == "pass"


# 6. Notification Policy Engine Tests
def test_notification_policy_engine(temp_dirs):
    engine = NotificationPolicyEngine(temp_dirs["state_dir"])
    
    # Classify tests
    assert engine.classify("risk_blocked", "critical") == "urgent"
    assert engine.classify("signal_created", "info") == "daily"

    # Add unsent notifications for same ticker (throttling check)
    engine.add_to_inbox(event_type="signal_created", message="Buy SOXL at $35.2", ticker="SOXL")
    engine.add_to_inbox(event_type="signal_created", message="Target adjust for SOXL", ticker="SOXL")
    
    batched = engine.process_and_batch_unsent()
    # Since there are 2 unsent notifications for SOXL, they should be batched
    soxl_batch = [b for b in batched if b["ticker"] == "SOXL"]
    assert len(soxl_batch) == 1
    assert soxl_batch[0]["items_count"] == 2
    assert "알림 2건 묶음 발송" in soxl_batch[0]["message"]


# 7. Stock Knowledge Card Tests
def test_stock_knowledge_card_manager(temp_dirs):
    manager = StockKnowledgeCardManager(temp_dirs["state_dir"])
    
    # Save card
    card = manager.save_card(
        ticker="SOXL",
        card_data={
            "investment_hypothesis": "Bull market leveraged play",
            "reason_for_holding": "High beta semiconductor demand",
        }
    )
    assert card["ticker"] == "SOXL"
    assert card["investment_hypothesis"] == "Bull market leveraged play"

    # Get card
    card_get = manager.get_card("SOXL")
    assert card_get["reason_for_holding"] == "High beta semiconductor demand"

    # List cards
    cards = manager.list_cards()
    assert len(cards) == 1
    assert cards[0]["ticker"] == "SOXL"

    # Delete card
    assert manager.delete_card("SOXL") is True
    assert manager.get_card("SOXL")["investment_hypothesis"] == "투자 가설이 등록되지 않았습니다."


# 8. Dashboard Permission Mode Tests
def test_dashboard_permission_mode_manager():
    manager = DashboardPermissionModeManager(default_mode="read_only")
    
    # read_only checks
    assert manager.get_mode() == "read_only"
    assert manager.is_action_allowed("view") is True
    assert manager.is_action_allowed("write_memo") is False
    assert manager.is_action_allowed("trigger_backup") is False

    # review_only checks
    manager.set_mode("review_only")
    assert manager.is_action_allowed("write_memo") is True
    assert manager.is_action_allowed("record_approval") is False

    # approve_enabled checks
    manager.set_mode("approve_enabled")
    assert manager.is_action_allowed("record_approval") is True
    assert manager.is_action_allowed("modify_settings") is False

    # admin checks
    manager.set_mode("admin")
    assert manager.is_action_allowed("modify_settings") is True
    assert manager.is_action_allowed("trigger_restore") is True


# 9. Strategy Risk Budget Tests
def test_strategy_risk_budget_manager(temp_dirs):
    # Write custom budget config
    config_file = temp_dirs["project_root"] / "configs" / "strategy_risk_budgets.json"
    config_file.write_text(json.dumps({
        "budgets": {
            "Momentum_V4": {
                "monthly_loss_limit": 1000.0,
                "max_trade_count": 3,
                "max_capital_allocation": 0.4
            }
        }
    }), encoding="utf-8")

    manager = StrategyRiskBudgetManager(temp_dirs["project_root"], temp_dirs["state_dir"])
    
    # 1. Normal state (no trade history yet)
    status1 = manager.evaluate_strategy("Momentum_V4", current_allocation_ratio=0.1)
    assert status1["suspended"] is False
    assert status1["current_usage"]["remaining_loss_budget"] == 1000.0

    # 2. Record trade (loss)
    manager.record_trade("Momentum_V4", pnl=-400.0)
    manager.record_trade("Momentum_V4", pnl=-700.0)  # Total loss = 1100.0 > 1000.0
    
    # 3. Suspended state check (loss exceeded)
    status2 = manager.evaluate_strategy("Momentum_V4")
    assert status2["suspended"] is True
    assert "월간 누적 손실 한도 초과" in status2["reason"]
