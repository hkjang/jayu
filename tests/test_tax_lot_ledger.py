import pytest
import json
from pathlib import Path
from jayu.tax_lot_ledger import TaxLotLedger
from jayu.approval_audit_ledger import log_approval_decision, load_approval_history

@pytest.fixture
def temp_ledger_path(tmp_path):
    return tmp_path / "tax_lot_ledger.json"

@pytest.fixture
def temp_state_paths(tmp_path):
    class FakePaths:
        def __init__(self):
            self.state_dir = tmp_path / "state"
            self.state_dir.mkdir(parents=True, exist_ok=True)
    return FakePaths()

def test_tax_lot_buy_and_fifo_sell(temp_ledger_path):
    ledger = TaxLotLedger(temp_ledger_path)
    
    # 1. Add Buy lot: 10 shares of NVDA at $120.0 (FX rate 1300.0, fee $1.50)
    lot = ledger.add_buy(
        ticker="NVDA",
        quantity=10.0,
        unit_price=120.0,
        fx_rate=1300.0,
        currency="USD",
        commission=1.50 * 1300.0, # in KRW
        buy_date="20260620"
    )
    
    assert lot["ticker"] == "NVDA"
    assert lot["remaining_quantity"] == 10.0
    
    # 2. Sell FIFO: 4 shares of NVDA at $135.0 (FX rate 1310.0, fee $1.00)
    realized_pnl, sold_details = ledger.sell_fifo(
        ticker="NVDA",
        sell_quantity=4.0,
        sell_price=135.0,
        sell_fx_rate=1310.0,
        commission=1.00 * 1310.0, # in KRW
        sell_date="20260626"
    )
    
    # Math check:
    # Buy Cost: 4 * 120.0 * 1300.0 = 624,000 KRW
    # Pro-rata Buy Fee: (4/10) * 1.50 * 1300.0 = 0.6 * 1300.0 = 780 KRW
    # Total Buy Cost: 624,780 KRW
    # Sell Value: 4 * 135.0 * 1310.0 = 707,400 KRW
    # Sell Fee: 1.00 * 1310.0 = 1,310 KRW
    # Net Sell Value: 706,090 KRW
    # Expected Realized P&L: 706,090 - 624,780 = 81,310 KRW
    
    assert realized_pnl == 81310.0
    assert len(sold_details) == 1
    assert sold_details[0]["quantity_sold"] == 4.0
    
    # Verify remaining quantity
    lots = ledger.load_lots()
    assert lots[0]["remaining_quantity"] == 6.0

def test_tax_lot_reconciliation(temp_ledger_path):
    ledger = TaxLotLedger(temp_ledger_path)
    
    # Add active NVDA lot (6 remaining)
    ledger.add_buy(
        ticker="NVDA",
        quantity=6.0,
        unit_price=120.0,
        fx_rate=1300.0,
        buy_date="20260620"
    )
    
    # Case A: Toss holdings match ledger (NVDA = 6)
    toss_holdings = [{"ticker": "NVDA", "quantity": 6.0, "avg_cost": 120.0}]
    recon = ledger.reconcile_with_toss(toss_holdings)
    assert recon["reconciled"] is True
    assert recon["discrepancy_count"] == 0
    
    # Case B: Toss holdings mismatch (NVDA = 8) -> discrepancy +2
    toss_holdings_mismatch = [{"ticker": "NVDA", "quantity": 8.0, "avg_cost": 120.0}]
    recon_mismatch = ledger.reconcile_with_toss(toss_holdings_mismatch)
    assert recon_mismatch["reconciled"] is False
    assert recon_mismatch["discrepancy_count"] == 1
    assert recon_mismatch["discrepancies"][0]["qty_diff"] == 2.0

def test_user_approval_audit_ledger(temp_state_paths):
    # Log a user decision to approve a NVDA buy signal
    log_approval_decision(
        paths=temp_state_paths,
        run_id="20260626_130000",
        ticker="NVDA",
        action="buy",
        rec_verdict="approved",
        user_decision="approve",
        rationale="NVDA broke out of resistance"
    )
    
    history = load_approval_history(temp_state_paths, limit=5)
    assert len(history) == 1
    assert history[0]["ticker"] == "NVDA"
    assert history[0]["user_decision"] == "approve"
    assert history[0]["rationale"] == "NVDA broke out of resistance"
