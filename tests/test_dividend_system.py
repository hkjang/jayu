from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
from datetime import datetime

from src.jayu.dividend_security_mapper import DividendSecurityMapper
from src.jayu.dividend_event_master import DividendEventMaster, DividendEvent
from src.jayu.dividend_data_quality_gate import DividendDataQualityGate
from src.jayu.dividend_forecast_engine import DividendForecastEngine, DividendForecast
from src.jayu.dividend_tax_fx_engine import DividendTaxFxEngine
from src.jayu.dividend_chasing_guard import DividendChasingGuard
from src.jayu.dividend_reconciliation import DividendReconciler
from src.jayu.dividend_cashflow_simulator import DividendCashflowSimulator

@pytest.fixture
def temp_project_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

def test_security_mapper_kr_stock(temp_project_root):
    mapper = DividendSecurityMapper(temp_project_root)
    # Test auto mapping
    assert mapper.auto_map("005930", "KOSPI") == "005930.KS"
    assert mapper.auto_map("095660", "KOSDAQ") == "095660.KQ"
    assert mapper.auto_map("AAPL", "US") == "AAPL"
    
    # Test overrides
    mapper.save_override("AAPL", "AAPL.OVERRIDE")
    assert mapper.auto_map("AAPL") == "AAPL.OVERRIDE"

def test_event_master_special_and_frequency(temp_project_root):
    master = DividendEventMaster(temp_project_root)
    
    # Construct regular quarterly events
    events = [
        DividendEvent(
            symbol="TEST", security_name="Test", market="US", currency="USD",
            ex_date="2025-03-15", record_date=None, pay_date="2025-03-30", declared_date=None,
            amount_per_share=1.0, source="yahoo", source_confidence=80.0, source_hash="1",
            status="confirmed", is_special=False, frequency=None
        ),
        DividendEvent(
            symbol="TEST", security_name="Test", market="US", currency="USD",
            ex_date="2025-06-15", record_date=None, pay_date="2025-06-30", declared_date=None,
            amount_per_share=1.0, source="yahoo", source_confidence=80.0, source_hash="2",
            status="confirmed", is_special=False, frequency=None
        ),
        # Special one-off dividend (amount is 2.5x of previous)
        DividendEvent(
            symbol="TEST", security_name="Test", market="US", currency="USD",
            ex_date="2025-08-01", record_date=None, pay_date="2025-08-15", declared_date=None,
            amount_per_share=2.5, source="yahoo", source_confidence=80.0, source_hash="3",
            status="confirmed", is_special=False, frequency=None
        ),
        DividendEvent(
            symbol="TEST", security_name="Test", market="US", currency="USD",
            ex_date="2025-09-15", record_date=None, pay_date="2025-09-30", declared_date=None,
            amount_per_share=1.0, source="yahoo", source_confidence=80.0, source_hash="4",
            status="confirmed", is_special=False, frequency=None
        )
    ]
    
    # 1. Test special dividend detection
    detected = master.detect_special_dividends(events)
    assert detected[2].is_special is True
    assert detected[0].is_special is False
    
    # 2. Test frequency estimation
    freq_estimated = master.estimate_frequencies(detected)
    assert freq_estimated[0].frequency == "quarterly"

def test_data_quality_gate(temp_project_root):
    gate = DividendDataQualityGate(temp_project_root)
    
    # Case 1: Missing pay_date and record_date
    events_missing_dates = [
        DividendEvent(
            symbol="BAD", security_name="Bad", market="US", currency="USD",
            ex_date="2025-03-15", record_date=None, pay_date=None, declared_date=None,
            amount_per_share=1.0, source="yahoo", source_confidence=80.0, source_hash="1",
            status="confirmed", is_special=False, frequency="quarterly"
        )
    ]
    quality = gate.evaluate_symbol("BAD", events_missing_dates)
    # Missing dates should lower completeness score, resulting in decision = "block" or "review"
    assert quality.trust_score < 80.0
    assert "pay_date" in quality.missing_fields

def test_forecast_engine_confirmed_vs_estimated(temp_project_root):
    engine = DividendForecastEngine(temp_project_root)
    gate = DividendDataQualityGate(temp_project_root)
    
    events = [
        DividendEvent(
            symbol="SCHD", security_name="SCHD", market="US", currency="USD",
            ex_date="2026-06-15", record_date="2026-06-16", pay_date="2026-06-25", declared_date="2026-06-10",
            amount_per_share=0.82, source="yahoo", source_confidence=80.0, source_hash="1",
            status="confirmed", is_special=False, frequency="quarterly"
        )
    ]
    
    quality = gate.evaluate_symbol("SCHD", events)
    start_dt = datetime(2026, 6, 1)
    
    forecasts = engine.forecast_symbol("SCHD", events, quality, start_date=start_dt)
    
    # The June 2026 payout should be flagged as confirmed
    june_forecast = [f for f in forecasts if f.forecast_month == "2026-06"]
    assert len(june_forecast) == 1
    assert june_forecast[0].is_confirmed is True
    assert june_forecast[0].expected_amount == 0.82

def test_tax_fx_calculation(temp_project_root):
    engine = DividendTaxFxEngine(temp_project_root)
    
    # US Withholding tax = 15%
    assert engine.get_tax_rate("US") == 0.15
    # KR Withholding tax = 15.4%
    assert engine.get_tax_rate("KR") == 0.154
    
    forecasts = [
        DividendForecast(
            symbol="AAPL", forecast_month="2026-07", expected_amount=0.25,
            expected_amount_krw=0.0, tax_estimate=0.0, net_amount=0.0,
            confidence=0.8, forecast_method="recent_carry", is_confirmed=False
        )
    ]
    
    holdings = {
        "AAPL": {"quantity": 100.0, "market": "US", "currency": "USD"}
    }
    
    # Assume 1400.0 USD/KRW exchange rate
    engine.apply_tax_and_fx(forecasts, holdings, toss_client=None)
    
    # 0.25 * 100 = 25 USD Gross. Net = 25 * 0.85 = 21.25 USD.
    # Conversion with default 1350.0 rate if client is None
    # 25 * 1350 = 33,750 KRW Gross
    # 21.25 * 1350 = 28,687.5 KRW Net
    assert forecasts[0].expected_amount_krw > 0.0
    assert forecasts[0].net_amount > 0.0

def test_chasing_guard_ex_date_proximity(temp_project_root):
    guard = DividendChasingGuard(temp_project_root)
    gate = DividendDataQualityGate(temp_project_root)
    
    # Next ex-date is tomorrow
    tomorrow_str = (datetime.now() + pytest.importorskip("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
    events = [
        DividendEvent(
            symbol="ALERT", security_name="Alert", market="US", currency="USD",
            ex_date=tomorrow_str, record_date=None, pay_date=None, declared_date=None,
            amount_per_share=1.5, source="yahoo", source_confidence=80.0, source_hash="1",
            status="confirmed", is_special=False, frequency="quarterly"
        )
    ]
    quality = gate.evaluate_symbol("ALERT", events)
    result = guard.evaluate("ALERT", 100.0, events, quality)
    
    assert result["verdict"] == "warning"
    assert "ex_date_proximity_warning" in result["reasons"]

def test_reconciliation(temp_project_root):
    reconciler = DividendReconciler(temp_project_root)
    
    forecasts = [
        DividendForecast(
            symbol="O", forecast_month="2026-06", expected_amount=0.26,
            expected_amount_krw=350.0, tax_estimate=52.5, net_amount=297.5,
            confidence=0.8, forecast_method="recent_carry", is_confirmed=False
        )
    ]
    
    # Case 1: Exact Match
    receipts_matched = [
        {"symbol": "O", "date": "2026-06-15", "amount": 297.5, "currency": "KRW", "source": "manual"}
    ]
    results = reconciler.reconcile(forecasts, receipts_matched)
    assert results[0].status == "matched"
    
    # Case 2: Amount Mismatch (>5% difference)
    receipts_mismatch = [
        {"symbol": "O", "date": "2026-06-15", "amount": 200.0, "currency": "KRW", "source": "manual"}
    ]
    results_mismatch = reconciler.reconcile(forecasts, receipts_mismatch)
    assert results_mismatch[0].status == "amount_diff"
