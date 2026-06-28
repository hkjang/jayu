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
from src.jayu.dividend_data_quality_gate import DividendDataQualityGate, DividendQuality
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

# --- Advanced Stabilization Regression Tests (14 Cases) ---

def test_toss_holdings_snapshot_preferred_detailed(temp_project_root):
    state_dir = temp_project_root / "state"
    state_dir.mkdir()
    (state_dir / "toss_account_snapshot.json").write_text(
        json.dumps([
            {
                "symbol": "TSLA",
                "holdingQuantity": "5",
                "currentPrice": "200",
                "avgPrice": "180",
                "currency": "USD",
                "exchange": "NASDAQ",
            }
        ]),
        encoding="utf-8",
    )
    (temp_project_root / "toss_portfolio.csv").write_text("symbol,quantity,price\nMSFT,10,400\n", encoding="utf-8")

    simulator = DividendCashflowSimulator(temp_project_root)
    res = simulator.simulate_cashflow()
    assert res["holdings_source"] == "state/toss_account_snapshot.json"
    assert res["fallback_used"] is False
    assert len(res["holdings"]) == 1
    assert res["holdings"][0]["symbol"] == "TSLA"

def test_toss_portfolio_csv_fallback_detailed(temp_project_root):
    state_dir = temp_project_root / "state"
    state_dir.mkdir() # No snapshot json
    (temp_project_root / "toss_portfolio.csv").write_text("symbol,quantity,price\nMSFT,10,400\n", encoding="utf-8")

    simulator = DividendCashflowSimulator(temp_project_root)
    res = simulator.simulate_cashflow()
    assert res["holdings_source"] == "toss_portfolio.csv"
    assert res["fallback_used"] is True
    assert len(res["holdings"]) == 1
    assert res["holdings"][0]["symbol"] == "MSFT"

def test_yahoo_ticker_mapping_failed_dashboard(temp_project_root):
    mapper = DividendSecurityMapper(temp_project_root)
    mapper.save_override("BADSTOCK", "FAIL") # Explicitly fail mapping

    holdings = [{"symbol": "BADSTOCK", "quantity": 10, "price": 100}]
    mapped = mapper.map_all_holdings(holdings)
    assert mapped[0]["mapping_status"] == "failed"
    assert mapped[0]["yahoo_ticker"] == ""

    # Check if dashboard API reports this unmapped holding
    (temp_project_root / "toss_portfolio.csv").write_text("symbol,quantity,price\nBADSTOCK,10,100\n", encoding="utf-8")
    
    # Force delete cache file if exists to avoid stale hits
    cache_file = temp_project_root / "state" / "dividend_dashboard_cache.json"
    if cache_file.exists():
        cache_file.unlink()

    dashboard = dividend_dashboard_api.build_dividend_dashboard(temp_project_root, force_refresh=True)
    assert dashboard["data_quality_summary"]["unmapped_count"] == 1
    assert dashboard["data_quality_summary"]["unmapped_items"][0]["symbol"] == "BADSTOCK"

def test_yahoo_dividend_history_empty(temp_project_root):
    source = DividendSourceYahoo(temp_project_root)
    # yfinance fetch exception simulation by sending dummy ticker that returns empty
    payload = source.fetch_dividend_history("EMPTY_DIVIDEND_STK", force=True)
    assert payload["cache_status"] == "refreshed"
    assert payload["error_reason"] == "empty_dividend_history"

def test_ex_date_based_estimated_pay_date(temp_project_root):
    engine = DividendForecastEngine(temp_project_root)
    gate = DividendDataQualityGate(temp_project_root)
    
    # Event has ex_date but pay_date is None
    events = [
        DividendEvent(
            symbol="O", security_name="Realty Income", market="US", currency="USD",
            ex_date="2026-06-15", record_date=None, pay_date=None, declared_date=None,
            amount_per_share=0.26, source="yahoo", source_confidence=70.0, source_hash="h1",
            status="estimated", is_special=False, frequency="monthly"
        )
    ]
    quality = gate.evaluate_symbol("O", events)
    start_dt = datetime(2026, 6, 1)
    
    forecasts = engine.forecast_symbol("O", events, quality, start_date=start_dt)
    june_forecast = [f for f in forecasts if f.forecast_month == "2026-06"][0]
    
    assert june_forecast.is_confirmed is False
    assert june_forecast.estimated_pay_date is True

def test_supplemental_pay_date_override(temp_project_root):
    master = DividendEventMaster(temp_project_root)
    
    # Yahoo event lacks pay_date, supplemental event provides it
    yahoo_payload = {"dividends": [{"date": "2026-06-15", "amount": 0.25}]}
    supplemental = [{
        "ex_date": "2026-06-15",
        "pay_date": "2026-06-30",
        "amount": 0.25
    }]
    
    events = master.build_and_merge_events("O", "O", "US", "USD", yahoo_payload, supplemental)
    assert events[0].pay_date == "2026-06-30"
    assert events[0].status == "confirmed"

def test_special_dividend_excluded_from_forecast(temp_project_root):
    engine = DividendForecastEngine(temp_project_root)
    
    # We have 1 special dividend and 3 regular quarterly dividends to establish quarterly payout_months
    events = [
        DividendEvent(
            symbol="SPEC", security_name="Spec", market="US", currency="USD",
            ex_date="2025-12-15", record_date=None, pay_date="2025-12-25", declared_date=None,
            amount_per_share=0.50, source="yahoo", source_confidence=80.0, source_hash="a",
            status="confirmed", is_special=False, frequency="quarterly"
        ),
        DividendEvent(
            symbol="SPEC", security_name="Spec", market="US", currency="USD",
            ex_date="2026-03-15", record_date=None, pay_date="2026-03-25", declared_date=None,
            amount_per_share=0.50, source="yahoo", source_confidence=80.0, source_hash="b",
            status="confirmed", is_special=False, frequency="quarterly"
        ),
        DividendEvent(
            symbol="SPEC", security_name="Spec", market="US", currency="USD",
            ex_date="2026-06-15", record_date=None, pay_date="2026-06-25", declared_date=None,
            amount_per_share=5.00, source="yahoo", source_confidence=80.0, source_hash="1",
            status="confirmed", is_special=True, frequency="quarterly"
        ),
        DividendEvent(
            symbol="SPEC", security_name="Spec", market="US", currency="USD",
            ex_date="2026-09-15", record_date=None, pay_date="2026-09-25", declared_date=None,
            amount_per_share=0.50, source="yahoo", source_confidence=80.0, source_hash="2",
            status="confirmed", is_special=False, frequency="quarterly"
        )
    ]
    
    # Manually create a high quality decision to avoid block/exclude filtering in forecast
    quality = DividendQuality(
        symbol="SPEC", data_sources=["yahoo"], missing_fields=[], stale_fields=[],
        trust_score=95.0, decision="pass", block_reason=None, checks={}
    )
    start_dt = datetime(2026, 6, 1)
    
    forecasts = engine.forecast_symbol("SPEC", events, quality, start_date=start_dt)
    
    # The special dividend (amount 5.00) in June should NOT be repeated as baseline
    # Only the regular dividend (0.50) should be forecasted
    sept_forecast = [f for f in forecasts if f.forecast_month == "2026-09"]
    dec_forecast = [f for f in forecasts if f.forecast_month == "2026-12"]
    
    # June is confirmed special, so it will show up as confirmed for that month
    june_forecast = [f for f in forecasts if f.forecast_month == "2026-06"][0]
    assert june_forecast.expected_amount == 5.00
    
    # But December forecast (extrapolated) should use the regular baseline of 0.50, not 5.00
    assert len(dec_forecast) == 1
    assert dec_forecast[0].expected_amount == 0.50

def test_trust_score_below_60_excluded_from_goal(temp_project_root):
    from src.jayu.dividend_living_expense_simulator import DividendLivingExpenseSimulator
    
    # Stock has a very low trust score of 50.0 (decision = "block")
    # It has a high dividend, but it must be excluded from Goal simulator
    state_dir = temp_project_root / "state"
    state_dir.mkdir()
    (state_dir / "toss_account_snapshot.json").write_text(
        json.dumps([
            {
                "symbol": "LOWTR",
                "holdingQuantity": "1000",
                "currentPrice": "10",
                "avgPrice": "10",
                "currency": "USD",
                "exchange": "NASDAQ",
            }
        ]),
        encoding="utf-8",
    )
    
    # Supplemental events lack pay_date/record_date, dragging trust_score down
    # Low trust score because we have no events
    simulator = DividendCashflowSimulator(temp_project_root)
    res = simulator.simulate_cashflow()
    assert res["holdings"][0]["decision"] in {"block", "exclude"}
    assert res["annual_dividend_krw"] == 0.0 # Excluded from totals!
    
    goal_sim = DividendLivingExpenseSimulator(temp_project_root)
    goal_res = goal_sim.simulate()
    assert goal_res["current_monthly_dividend_krw"] == 0.0

def test_trust_score_below_40_excluded_from_report_and_autotrade(temp_project_root):
    from src.jayu.monthly_dividend_report import MonthlyDividendReport
    from src.jayu.autotrade_security_guard import AutotradeSecurityGuard
    
    # We will simulate a stock with trust_score < 40
    # No events found -> decision = "exclude", trust_score = 0
    (temp_project_root / "toss_portfolio.csv").write_text("symbol,quantity,price\nTRASH,10,100\n", encoding="utf-8")
    
    # Test AutotradeSecurityGuard blocks it
    # We need to add TRASH to security master first to pass metadata check
    state_dir = temp_project_root / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "toss_security_master.json").write_text(
        json.dumps({
            "TRASH": {
                "name": "Trash Stock",
                "market": "US",
                "currency": "USD",
                "warnings": {}
            }
        }),
        encoding="utf-8"
    )
    
    guard = AutotradeSecurityGuard(temp_project_root)
    res_trade = guard.evaluate_order("TRASH", 1000.0)
    assert res_trade["verdict"] == "block"
    assert "품질" in res_trade["reason"]

    report = MonthlyDividendReport(temp_project_root)
    res_report = report.generate(2026, 6)
    with open(res_report["markdown"], "r", encoding="utf-8") as f:
        md = f.read()
    assert "TRASH" in md
    assert "TRASH" in md and "품질 및 이상 탐지 요약" in md

def test_usd_krw_fx_rate_cache(temp_project_root):
    engine = DividendTaxFxEngine(temp_project_root)
    # Save a rate of 1450.0 to cache
    engine._save_cache(1450.0)
    
    rate = engine.get_live_fx_rate()
    assert rate == 1450.0
    assert engine.fx_source == "cache"
    assert engine.fx_cache_status == "hit"

def test_reconciliation_amount_diff_detailed(temp_project_root):
    reconciler = DividendReconciler(temp_project_root)
    
    forecasts = [
        DividendForecast(
            symbol="AAPL", forecast_month="2026-06", expected_amount=0.25,
            expected_amount_krw=350.0, tax_estimate=52.5, net_amount=297.5,
            confidence=0.8, forecast_method="recent_carry", is_confirmed=False
        )
    ]
    
    # Actual receipt is 200 KRW (Expected was 297.5) -> Diff is > 5%
    receipts = [
        {"symbol": "AAPL", "date": "2026-06-15", "amount": 200.0, "currency": "KRW", "source": "manual"}
    ]
    
    res = reconciler.reconcile(forecasts, receipts)
    assert res[0].status == "amount_diff"
    assert res[0].diff == -97.5

def test_ex_date_proximity_chasing_warning_detailed(temp_project_root):
    from src.jayu.pre_trade_checklist import PreTradeChecklistEvaluator
    
    # Ex-date is tomorrow
    tomorrow_str = (datetime.now() + pytest.importorskip("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Mock dividend cache to have this ex_date
    state_dir = temp_project_root / "state"
    state_dir.mkdir(exist_ok=True)
    
    # Setup security master and overrides so mapper resolves it
    (state_dir / "dividend_symbol_overrides.json").write_text(json.dumps({"CHASE": "CHASE"}), encoding="utf-8")
    
    # Write yahoo cache for CHASE
    source = DividendSourceYahoo(temp_project_root)
    source.save_cache("CHASE", {
        "ticker": "CHASE",
        "fetched_at": time.time(),
        "dividends": [{"date": tomorrow_str, "amount": 1.50}],
        "splits": []
    })
    
    evaluator = PreTradeChecklistEvaluator(temp_project_root / "configs" / "rules.yaml")
    
    signal_data = {
        "symbol": "CHASE",
        "price": 100.0,
        "score": 0.9,
        "risk_passed": True
    }
    account_data = {
        "cash_usd": 1000.0,
        "cash_krw": 1000000.0
    }
    
    # Use timezone-aware Monday morning NY time to pass market hours check
    from zoneinfo import ZoneInfo
    market_time = datetime(2026, 6, 29, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    
    res = evaluator.evaluate(
        signal_data=signal_data,
        account_data=account_data,
        is_approved=True,
        last_data_update=datetime.now(),
        market_time=market_time
    )
    
    assert res["status"] == "warning"
    assert any("배당락일" in r for r in res["reasons"])

def test_price_drop_value_trap_block_detailed(temp_project_root):
    from src.jayu.autotrade_security_guard import AutotradeSecurityGuard
    from src.jayu.toss_security_master import TossSecurityMaster
    
    # Price dropped by 25% (100 -> 75)
    state_dir = temp_project_root / "state"
    state_dir.mkdir(exist_ok=True)
    
    # Mock cache for TRAP with upcoming dividend
    source = DividendSourceYahoo(temp_project_root)
    source.save_cache("TRAP", {
        "ticker": "TRAP",
        "fetched_at": time.time(),
        "dividends": [{"date": "2026-07-15", "amount": 2.00}],
        "splits": []
    })
    
    # We trigger the evaluate_symbol_simple with a 30-day drop
    guard = DividendChasingGuard(temp_project_root)
    
    # 30-day history shows a drop from 100 to 75 (25% drop)
    res_guard = guard.evaluate_symbol_simple("TRAP", price=75.0, price_history_30d=[100.0, 90.0, 80.0, 75.0])
    assert res_guard["verdict"] == "block"
    assert "price_drop_value_trap" in res_guard["reasons"]

    # AutotradeSecurityGuard should block it if we evaluate it with drop
    original_eval = DividendChasingGuard.evaluate_symbol_simple
    
    def mock_eval_simple(self_guard, symbol, price=None, price_history_30d=None):
        return original_eval(self_guard, symbol, price=75.0, price_history_30d=[100.0, 75.0])
        
    # Using python's unittest.mock patch to mock both chasing guard and security master
    from unittest.mock import patch
    mock_master_data = {
        "TRAP": {
            "name": "Value Trap",
            "market": "US",
            "currency": "USD",
            "warnings": {}
        }
    }
    with patch.object(DividendChasingGuard, 'evaluate_symbol_simple', mock_eval_simple):
        with patch.object(TossSecurityMaster, 'get_security_master', return_value=mock_master_data):
            sec_guard = AutotradeSecurityGuard(temp_project_root)
            res_trade = sec_guard.evaluate_order("TRAP", 1000.0)
            assert res_trade["verdict"] == "block"
            assert "배당 보호 가드 차단" in res_trade["reason"]

def test_monthly_dividend_report_forecast_based_detailed(temp_project_root):
    from src.jayu.monthly_dividend_report import MonthlyDividendReport
    
    # SCHD has a dividend in June 2026 (0.82)
    state_dir = temp_project_root / "state"
    state_dir.mkdir(exist_ok=True)
    
    # Write toss snapshot
    (state_dir / "toss_account_snapshot.json").write_text(
        json.dumps([{
            "symbol": "SCHD",
            "holdingQuantity": "100",
            "currentPrice": "75",
            "avgPrice": "70",
            "currency": "USD",
            "exchange": "NYSE"
        }]),
        encoding="utf-8"
    )
    
    # Write yahoo cache
    source = DividendSourceYahoo(temp_project_root)
    source.save_cache("SCHD", {
        "ticker": "SCHD",
        "fetched_at": time.time(),
        "dividends": [
            {"date": "2026-06-15", "amount": 0.82},
            {"date": "2026-09-15", "amount": 0.82}
        ],
        "splits": []
    })
    
    report = MonthlyDividendReport(temp_project_root)
    res = report.generate(2026, 6) # Generate for June 2026
    
    with open(res["markdown"], "r", encoding="utf-8") as f:
        md = f.read()
    
    assert "SCHD" in md
    assert "matched" in md or "estimated" in md or "amount_diff" in md or "missing" in md

