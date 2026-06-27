import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock
from jayu.toss_security_master import TossSecurityMaster
from jayu.security_risk_profile import SecurityRiskProfiler
from jayu.autotrade_security_guard import AutotradeSecurityGuard
from jayu.portfolio_security_exposure import PortfolioSecurityExposure
from jayu.toss_trade_context_builder import TossTradeContextBuilder
from jayu.order_stock_reconciliation import OrderStockReconciler
from jayu.security_metadata_quality_check import SecurityMetadataQualityChecker
from jayu.signal_security_context import SignalSecurityContext

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

def test_toss_security_master_and_risk_profile(setup_project_root: Path):
    master = TossSecurityMaster(setup_project_root)
    
    # Mock client
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
            },
            {
                "symbol": "SUSPENDED_STOCK",
                "name": "정지회사",
                "englishName": "SuspendedCo",
                "market": "KOSPI",
                "securityType": "STOCK",
                "currency": "KRW",
                "leverageFactor": 1.0,
                "status": "ACTIVE"
            }
        ]
    }
    mock_client.stock_warnings.side_effect = lambda sym: {
        "result": {
            "symbol": sym,
            "marketWarning": "NONE",
            "administrative": False,
            "delistingCaution": False,
            "tradingSuspended": True if sym == "SUSPENDED_STOCK" else False
        }
    }

    sec_master = master.get_security_master(mock_client)
    
    # Verify AAPL
    aapl_info = sec_master.get("AAPL")
    assert aapl_info is not None
    assert aapl_info["name"] == "애플"
    assert aapl_info["is_tradable"] is True
    
    # Verify Suspended Stock
    suspended_info = sec_master.get("SUSPENDED_STOCK")
    assert suspended_info is not None
    assert suspended_info["is_tradable"] is False
    assert suspended_info["warnings"]["tradingSuspended"] is True

    # Test Risk Profiler
    aapl_risk = SecurityRiskProfiler.evaluate_risk(aapl_info)
    assert aapl_risk["grade"] == "normal"
    assert aapl_risk["autotrade_allowed"] is True
    
    suspended_risk = SecurityRiskProfiler.evaluate_risk(suspended_info)
    assert suspended_risk["grade"] == "blocked"
    assert suspended_risk["autotrade_allowed"] is False

def test_autotrade_security_guard(setup_project_root: Path):
    guard = AutotradeSecurityGuard(setup_project_root)
    
    # Create mock security master cache manually
    cache_data = {
        "AAPL": {
            "symbol": "AAPL",
            "name": "애플",
            "security_type": "STOCK",
            "leverage_factor": 1.0,
            "warnings": {"tradingSuspended": False},
            "is_tradable": True
        },
        "SOXL": {
            "symbol": "SOXL",
            "name": "SOXL",
            "security_type": "ETF",
            "leverage_factor": 3.0,
            "warnings": {"tradingSuspended": False},
            "is_tradable": True
        },
        "SUSPENDED_STOCK": {
            "symbol": "SUSPENDED_STOCK",
            "name": "정지회사",
            "security_type": "STOCK",
            "leverage_factor": 1.0,
            "warnings": {"tradingSuspended": True},
            "is_tradable": False
        }
    }
    with open(setup_project_root / "state" / "toss_security_master_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache_data, f)

    # AAPL - Should be Allowed
    eval_aapl = guard.evaluate_order("AAPL", 1000000.0)
    assert eval_aapl["verdict"] == "allow"
    assert eval_aapl["allowed_amount"] == 1000000.0
    
    # SOXL - Should be Reduced (3x Leverage)
    eval_soxl = guard.evaluate_order("SOXL", 1000000.0)
    assert eval_soxl["verdict"] == "reduce"
    assert eval_soxl["allowed_amount"] == 300000.0
    
    # SUSPENDED_STOCK - Should be Blocked
    eval_susp = guard.evaluate_order("SUSPENDED_STOCK", 1000000.0)
    assert eval_susp["verdict"] == "block"
    assert eval_susp["allowed_amount"] == 0.0

def test_portfolio_exposure_and_quality(setup_project_root: Path):
    # Set up cache first
    cache_data = {
        "AAPL": {
            "symbol": "AAPL",
            "name": "애플",
            "security_type": "STOCK",
            "market": "NASDAQ",
            "currency": "USD",
            "leverage_factor": 1.0,
            "warnings": {"marketWarning": "NONE"},
            "is_tradable": True
        },
        "TSLA": {
            "symbol": "TSLA",
            "name": "테슬라",
            "security_type": "STOCK",
            "market": "NASDAQ",
            "currency": "USD",
            "leverage_factor": 1.0,
            "warnings": {"marketWarning": "NONE"},
            "is_tradable": True
        }
    }
    with open(setup_project_root / "state" / "toss_security_master_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache_data, f)
        
    exposure = PortfolioSecurityExposure(setup_project_root)
    exp_res = exposure.calculate_exposure()
    
    assert exp_res["total_value_krw"] == 3350000.0
    # AAPL (2,000,000) and TSLA (1,350,000) are both USD
    assert exp_res["by_currency"][0]["name"] == "USD"
    assert exp_res["by_currency"][0]["percentage"] == 100.0

    # Trade Context Builder
    builder = TossTradeContextBuilder(setup_project_root)
    context = builder.build_context("AAPL")
    assert context["symbol"] == "AAPL"
    assert context["holding"]["qty"] == 10.0
    assert context["performance"]["total_trades"] > 0

    # Quality and Reconciler
    quality = SecurityMetadataQualityChecker(setup_project_root).check_quality()
    assert quality["score"] > 80
    
    reconciliation = OrderStockReconciler(setup_project_root).reconcile()
    assert reconciliation["score"] > 50

    # Signal Security Context
    sig_context = SignalSecurityContext(setup_project_root).get_signal_context("AAPL")
    assert sig_context["symbol"] == "AAPL"
    assert sig_context["autotrade_allowed"] is True
