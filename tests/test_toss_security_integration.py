import pytest
import json
import time
from pathlib import Path
from unittest.mock import MagicMock
from jayu.toss_security_master import TossSecurityMaster
from jayu.toss_reference_reconciliation import TossReferenceReconciler
from jayu.security_decision_gate import SecurityDecisionGate
from jayu.autotrade_security_guard import AutotradeSecurityGuard
from jayu.toss_trade_feature_store import build_toss_order_feature_store
from jayu.security_trade_context import SecurityTradeContext
from jayu.portfolio_security_exposure import PortfolioSecurityExposure
from jayu.toss_reference_data_report import TossReferenceDataReport

@pytest.fixture
def setup_project_root(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # Create mock orders file
    orders_data = {
        "orders": [
            {
                "symbol": "AAPL",
                "side": "BUY",
                "price": 150.0,
                "quantity": 10,
                "orderedAt": "2026-06-25T10:00:00Z",
                "status": "FILLED",
                "currency": "USD"
            },
            {
                "symbol": "TSLA",
                "side": "SELL",
                "price": 200.0,
                "quantity": 5,
                "orderedAt": "2026-06-26T14:30:00Z",
                "status": "FILLED",
                "currency": "USD"
            },
            {
                "symbol": "SUSPENDED_STOCK",
                "side": "BUY",
                "price": 10.0,
                "quantity": 100,
                "orderedAt": "2026-06-27T09:00:00Z",
                "status": "FILLED",
                "currency": "KRW"
            },
            {
                "symbol": "MISMATCH_STOCK",
                "side": "BUY",
                "price": 50.0,
                "quantity": 10,
                "orderedAt": "2026-06-27T11:00:00Z",
                "status": "FILLED",
                "currency": "USD" # Order in USD, but Master has KRW
            },
            {
                "symbol": "NO_WARNING_STOCK",
                "side": "BUY",
                "price": 30.0,
                "quantity": 10,
                "orderedAt": "2026-06-27T12:00:00Z",
                "status": "FILLED",
                "currency": "USD"
            }
        ]
    }
    with open(state_dir / "toss_orders.json", "w", encoding="utf-8") as f:
        json.dump(orders_data, f)
        
    # Create mock portfolio file
    portfolio_content = "Symbol,Qty,KRW value,P/L KRW,P/L %,Buy Price,Sector,Category\n" \
                        "AAPL,10,2000000.0,500000.0,33.3,150.0,IT,STOCK\n" \
                        "TSLA,5,1350000.0,-150000.0,-10.0,200.0,Consumer,STOCK\n"
    with open(tmp_path / "toss_portfolio.csv", "w", encoding="utf-8") as f:
        f.write(portfolio_content)
        
    return tmp_path

@pytest.fixture
def mock_security_master_cache(setup_project_root: Path):
    cache_data = {
        "AAPL": {
            "symbol": "AAPL",
            "name": "애플",
            "market": "NASDAQ",
            "currency": "USD",
            "security_type": "STOCK",
            "is_etf": False,
            "is_leverage": False,
            "leverage_factor": 1.0,
            "warnings": {"marketWarning": "NONE"},
            "is_tradable": True,
            "updated_at": time.time(),
            "source_hash": "mock_hash_aapl"
        },
        "SOXL": {
            "symbol": "SOXL",
            "name": "SOXL",
            "market": "NYSE",
            "currency": "USD",
            "security_type": "ETF",
            "is_etf": True,
            "is_leverage": True,
            "leverage_factor": 3.0,
            "warnings": {"marketWarning": "NONE"},
            "is_tradable": True,
            "updated_at": time.time(),
            "source_hash": "mock_hash_soxl"
        },
        "SUSPENDED_STOCK": {
            "symbol": "SUSPENDED_STOCK",
            "name": "정지회사",
            "market": "KOSPI",
            "currency": "KRW",
            "security_type": "STOCK",
            "is_etf": False,
            "is_leverage": False,
            "leverage_factor": 1.0,
            "warnings": {"tradingSuspended": True},
            "is_tradable": False,
            "updated_at": time.time(),
            "source_hash": "mock_hash_suspended"
        },
        "MISMATCH_STOCK": {
            "symbol": "MISMATCH_STOCK",
            "name": "일치하지않는회사",
            "market": "KOSPI",
            "currency": "KRW", # Master has KRW, but Order has USD
            "security_type": "STOCK",
            "is_etf": False,
            "is_leverage": False,
            "leverage_factor": 1.0,
            "warnings": {"marketWarning": "NONE"},
            "is_tradable": True,
            "updated_at": time.time(),
            "source_hash": "mock_hash_mismatch"
        },
        "STALE_STOCK": {
            "symbol": "STALE_STOCK",
            "name": "오래된회사",
            "market": "NASDAQ",
            "currency": "USD",
            "security_type": "STOCK",
            "is_etf": False,
            "is_leverage": False,
            "leverage_factor": 1.0,
            "warnings": {"marketWarning": "NONE"},
            "is_tradable": True,
            "updated_at": time.time() - 86400 * 10, # 10 days old
            "source_hash": "mock_hash_stale"
        },
        "NO_WARNING_STOCK": {
            "symbol": "NO_WARNING_STOCK",
            "name": "경고정보조회실패회사",
            "market": "NASDAQ",
            "currency": "USD",
            "security_type": "STOCK",
            "is_etf": False,
            "is_leverage": False,
            "leverage_factor": 1.0,
            "warnings": {}, # Missing warning query keys
            "is_tradable": True,
            "updated_at": time.time(),
            "source_hash": "mock_hash_no_warning"
        }
    }
    with open(setup_project_root / "state" / "toss_security_master_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache_data, f)
    return setup_project_root

def test_toss_security_master_generation(setup_project_root: Path):
    master = TossSecurityMaster(setup_project_root)
    mock_client = MagicMock()
    mock_client.stocks.return_value = {
        "result": [
            {
                "symbol": "AAPL",
                "name": "애플",
                "englishName": "Apple",
                "market": "NASDAQ",
                "securityType": "STOCK",
                "currency": "USD",
                "leverageFactor": 1.0,
                "status": "ACTIVE"
            }
        ]
    }
    mock_client.stock_warnings.return_value = {
        "result": {
            "symbol": "AAPL",
            "marketWarning": "NONE",
            "administrative": False,
            "delistingCaution": False,
            "tradingSuspended": False
        }
    }

    sec_master = master.get_security_master(mock_client)
    assert "AAPL" in sec_master
    assert sec_master["AAPL"]["is_etf"] is False
    assert sec_master["AAPL"]["is_leverage"] is False
    assert sec_master["AAPL"]["source_hash"] != ""

def test_reference_reconciliation(mock_security_master_cache: Path):
    reconciler = TossReferenceReconciler(mock_security_master_cache)
    res = reconciler.reconcile()
    
    # 1. Unmapped (e.g. UNMAPPED_STOCK in orders, or we didn't add it in cache)
    # 2. Currency mismatch (MISMATCH_STOCK is USD in orders, KRW in master)
    assert len(res["currency_mismatches"]) > 0
    assert res["currency_mismatches"][0]["symbol"] == "MISMATCH_STOCK"
    
    # 3. Suspended symbols
    assert len(res["suspended_symbols"]) > 0
    assert res["suspended_symbols"][0]["symbol"] == "SUSPENDED_STOCK"
    
    # 4. Warning query failures
    assert "NO_WARNING_STOCK" in res["warning_query_failures"]

def test_security_decision_gate(mock_security_master_cache: Path):
    gate = SecurityDecisionGate(mock_security_master_cache)
    
    # AAPL - Should pass
    res_aapl = gate.evaluate_gate("AAPL")
    assert res_aapl["allow"] is True
    
    # SUSPENDED_STOCK - Should be blocked
    res_susp = gate.evaluate_gate("SUSPENDED_STOCK")
    assert res_susp["allow"] is False
    assert res_susp["category"] == "warning"
    
    # STALE_STOCK - Should be blocked (> 7 days)
    res_stale = gate.evaluate_gate("STALE_STOCK")
    assert res_stale["allow"] is False
    assert res_stale["category"] == "freshness"

def test_autotrade_security_guard_limits(mock_security_master_cache: Path):
    guard = AutotradeSecurityGuard(mock_security_master_cache)
    
    # SOXL - 3x Leverage -> should scale down to 33.3%
    res_soxl = guard.evaluate_order("SOXL", 90000.0)
    assert res_soxl["verdict"] == "reduce"
    assert res_soxl["allowed_amount"] == 30000.0
    
    # SUSPENDED_STOCK - should block
    res_susp = guard.evaluate_order("SUSPENDED_STOCK", 100000.0)
    assert res_susp["verdict"] == "block"
    assert res_susp["allowed_amount"] == 0.0
