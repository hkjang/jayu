from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
import pytest
from datetime import datetime

from src.jayu import dividend_dashboard_api
from src.jayu.dividend_security_mapper import DividendSecurityMapper
from src.jayu.dividend_event_master import DividendEventMaster, DividendEvent
from src.jayu.dividend_data_quality_gate import DividendDataQualityGate
from src.jayu.dividend_forecast_engine import DividendForecastEngine, DividendForecast
from src.jayu.dividend_tax_fx_engine import DividendTaxFxEngine
from src.jayu.dividend_chasing_guard import DividendChasingGuard
from src.jayu.dividend_reconciliation import DividendReconciler
from src.jayu.dividend_cashflow_simulator import DividendCashflowSimulator
from src.jayu.dividend_source_yahoo import DividendSourceYahoo
from src.jayu.dividend_goal_bridge import DividendGoalBridge
from src.jayu.dividend_symbol_mapper import DividendSymbolMapper
from src.jayu.dividend_yahoo_source import DividendYahooSource

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

    mapped = mapper.map_all_holdings([
        {"symbol": "AAPL", "quantity": "1,200.5", "price": "$150.25", "average_cost": "120.10"}
    ])
    assert mapped[0]["quantity"] == 1200.5
    assert mapped[0]["price"] == 150.25

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


def test_event_master_marks_yahoo_only_as_estimated_and_supplement_confirms(temp_project_root):
    master = DividendEventMaster(temp_project_root)

    yahoo_only = master.build_and_merge_events(
        symbol="YHOO",
        name="Yahoo Only",
        market="US",
        currency="USD",
        yahoo_payload={"dividends": [{"date": "2026-01-10", "amount": 1.0}]},
    )
    assert yahoo_only[0].status == "estimated"
    assert yahoo_only[0].source_confidence == 70.0

    merged = master.build_and_merge_events(
        symbol="MERG",
        name="Merged",
        market="US",
        currency="USD",
        yahoo_payload={"dividends": [{"date": "2026-01-10", "amount": 1.0}]},
        supplemental_events=[
            {
                "ex_date": "2026-01-10",
                "record_date": "2026-01-11",
                "pay_date": "2026-01-25",
                "amount": 1.0,
            }
        ],
    )
    assert merged[0].status == "confirmed"
    assert merged[0].pay_date == "2026-01-25"
    assert merged[0].source == "yahoo+supplemental"
    assert merged[0].source_confidence >= 85.0

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
    
    engine.apply_tax_and_fx(forecasts, holdings, toss_client=None, fx_rate=1400.0)
    
    # 0.25 * 100 = 25 USD Gross. Net = 25 * 0.85 = 21.25 USD.
    # 25 * 1400 = 35,000 KRW Gross
    # 21.25 * 1400 = 29,750 KRW Net
    assert forecasts[0].expected_amount_krw == 35000.0
    assert forecasts[0].tax_estimate == 5250.0
    assert forecasts[0].net_amount == 29750.0

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

    receipts_usd = [
        {"symbol": "O", "date": "2026-06-15", "amount": 0.2125, "currency": "USD", "source": "toss"}
    ]
    results_usd = reconciler.reconcile(forecasts, receipts_usd, fx_rate=1400.0)
    assert results_usd[0].status == "matched"
    assert results_usd[0].actual_amount == 297.5
    
    # Case 2: Amount Mismatch (>5% difference)
    receipts_mismatch = [
        {"symbol": "O", "date": "2026-06-15", "amount": 200.0, "currency": "KRW", "source": "manual"}
    ]
    results_mismatch = reconciler.reconcile(forecasts, receipts_mismatch)
    assert results_mismatch[0].status == "amount_diff"


def test_cashflow_simulator_loads_currency_formatted_csv(temp_project_root):
    csv_path = temp_project_root / "holdings.csv"
    csv_path.write_text(
        'symbol,quantity,price,average_cost,market,currency\n'
        'AAPL,"1,000","$150.50","$120.00",US,USD\n',
        encoding="utf-8",
    )

    simulator = DividendCashflowSimulator(temp_project_root)
    holdings = simulator.load_holdings_from_csv(csv_path)
    assert holdings[0]["quantity"] == 1000.0
    assert holdings[0]["price"] == 150.5
    assert holdings[0]["market"] == "US"


def test_cashflow_simulator_prefers_toss_holdings_snapshot(temp_project_root):
    state_dir = temp_project_root / "state"
    state_dir.mkdir()
    (state_dir / "toss_account_snapshot.json").write_text(
        json.dumps({
            "holdings": {
                "result": {
                    "holdings": [
                        {
                            "symbol": "AAPL",
                            "stockName": "Apple",
                            "holdingQuantity": "3",
                            "currentPrice": "150",
                            "avgPrice": "120",
                            "currency": "USD",
                            "exchange": "NASDAQ",
                        }
                    ]
                }
            }
        }),
        encoding="utf-8",
    )
    (temp_project_root / "toss_portfolio.csv").write_text(
        "symbol,quantity,price\nMSFT,10,400\n",
        encoding="utf-8",
    )

    simulator = DividendCashflowSimulator(temp_project_root)
    holdings = simulator.load_holdings_snapshot()

    assert holdings[0]["symbol"] == "AAPL"
    assert holdings[0]["quantity"] == 3.0
    assert holdings[0]["source"] == "state/toss_account_snapshot.json"


def test_dividend_compatibility_aliases(temp_project_root):
    assert isinstance(DividendSymbolMapper(temp_project_root), DividendSecurityMapper)
    assert isinstance(DividendYahooSource(temp_project_root), DividendSourceYahoo)


def test_dividend_goal_bridge_calculates_shortfall_and_capital(temp_project_root):
    bridge = DividendGoalBridge(temp_project_root)
    result = bridge.build({
        "annual_net_dividend_krw": 1200000.0,
        "portfolio_value_krw": 100000000.0,
        "aggregate_yield_pct": 4.0,
    })

    assert result["monthly_target_krw"] == 3000000.0
    assert result["current_monthly_net_krw"] == 100000.0
    assert result["monthly_shortfall_krw"] == 2900000.0
    assert result["needed_additional_capital_krw"] == 870000000.0


def test_yahoo_source_can_reuse_stale_history_cache(temp_project_root):
    source = DividendSourceYahoo(temp_project_root, cache_ttl_seconds=1)
    cache_path = source._get_cache_path("AAPL")
    cache_path.write_text(
        json.dumps(
            {
                "ticker": "AAPL",
                "fetched_at": time.time() - 3600,
                "dividends": [{"date": "2026-01-10", "amount": 0.25}],
                "splits": [],
                "source": "yahoo_finance",
            }
        ),
        encoding="utf-8",
    )

    payload = source.fetch_dividend_history("AAPL", allow_stale=True)

    assert payload["cache_status"] == "stale_hit"
    assert payload["dividends"][0]["amount"] == 0.25


def test_dividend_dashboard_response_cache_reuses_unchanged_inputs(temp_project_root, monkeypatch):
    calls = {"count": 0}

    def fake_simulate(self, *args, **kwargs):
        calls["count"] += 1
        return {
            "portfolio_value_krw": 1000000.0,
            "annual_dividend_krw": 12000.0,
            "annual_net_dividend_krw": 10200.0,
            "aggregate_yield_pct": 1.2,
            "monthly_payouts_krw": [1000.0] + [0.0] * 11,
            "monthly_net_payouts_krw": [850.0] + [0.0] * 11,
            "months": ["2026-06"] + [f"2026-{month:02d}" for month in range(7, 18)],
            "holdings": [
                {
                    "symbol": "AAPL",
                    "name": "Apple",
                    "quantity": 1.0,
                    "value_krw": 1000000.0,
                    "dividend_yield": 1.2,
                    "annual_payout_krw": 12000.0,
                    "net_annual_payout_krw": 10200.0,
                    "trust_score": 90.0,
                    "decision": "pass",
                    "data_sources": ["yahoo"],
                    "next_ex_date": None,
                    "next_pay_date": None,
                    "growth_rate_3y_pct": 0.0,
                    "stability_score": 81.0,
                }
            ],
            "reinvestment_projections": {
                "1_year_value_krw": 1010000.0,
                "3_year_value_krw": 1100000.0,
                "5_year_value_krw": 1250000.0,
            },
            "target_goal": {
                "monthly_target_krw": 3000000.0,
                "current_monthly_net_krw": 850.0,
                "achievement_rate_pct": 0.03,
                "shortfall_krw": 2999150.0,
            },
            "goal_bridge": {
                "monthly_target_krw": 3000000.0,
                "current_monthly_net_krw": 850.0,
                "monthly_shortfall_krw": 2999150.0,
                "achievement_rate_pct": 0.03,
                "needed_additional_capital_krw": 299915000.0,
                "required_monthly_investment": {
                    "1_year": 24992916.67,
                    "3_year": 8330972.22,
                    "5_year": 4998583.33,
                },
            },
            "usd_krw_rate": 1400.0,
            "source_summary": {"price_and_history": "Yahoo Finance dividend history"},
        }

    monkeypatch.setattr(
        dividend_dashboard_api.DividendCashflowSimulator,
        "simulate_cashflow",
        fake_simulate,
    )

    first = dividend_dashboard_api.build_dividend_dashboard(
        temp_project_root,
        cache_ttl_seconds=3600,
    )
    second = dividend_dashboard_api.build_dividend_dashboard(
        temp_project_root,
        cache_ttl_seconds=3600,
    )
    cache_path = dividend_dashboard_api._dashboard_cache_path(temp_project_root)
    cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_payload["created_at"] = time.time() - 7200
    cache_path.write_text(json.dumps(cache_payload), encoding="utf-8")
    stale = dividend_dashboard_api.build_dividend_dashboard(
        temp_project_root,
        cache_ttl_seconds=1,
    )
    refreshed = dividend_dashboard_api.build_dividend_dashboard(
        temp_project_root,
        force_refresh=True,
        cache_ttl_seconds=3600,
    )

    assert calls["count"] == 2
    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert stale["cache"]["status"] == "stale_hit"
    assert refreshed["cache"]["status"] == "refresh"
    assert first["goal_bridge"]["monthly_shortfall_krw"] == 2999150.0
    assert first["data_quality_summary"]["pass_count"] == 1
    assert first["autotrading_guard"]["status"] == "pass"
