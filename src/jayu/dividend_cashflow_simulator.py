from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from datetime import datetime

from .dividend_security_mapper import DividendSecurityMapper
from .dividend_source_yahoo import DividendSourceYahoo
from .dividend_source_supplemental import DividendSupplementalSource
from .dividend_event_master import DividendEventMaster
from .dividend_data_quality_gate import DividendDataQualityGate
from .dividend_forecast_engine import DividendForecastEngine, DividendForecast
from .dividend_tax_fx_engine import DividendTaxFxEngine

class DividendCashflowSimulator:
    """Estimates expected monthly/quarterly dividend cashflow and projects reinvestment scenarios using real data."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.mapper = DividendSecurityMapper(project_root)
        self.yahoo_source = DividendSourceYahoo(project_root)
        self.supplemental_source = DividendSupplementalSource(project_root)
        self.event_master = DividendEventMaster(project_root)
        self.quality_gate = DividendDataQualityGate(project_root)
        self.forecast_engine = DividendForecastEngine(project_root)
        self.tax_fx_engine = DividendTaxFxEngine(project_root)

    def load_holdings_from_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        if not csv_path.exists():
            return []
        holdings = []
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Support case-insensitive headers
                    row_lower = {k.lower() if k else "": v for k, v in row.items()}
                    
                    symbol = row_lower.get("symbol") or row_lower.get("ticker") or row_lower.get("티커")
                    qty = row_lower.get("qty") or row_lower.get("quantity") or row_lower.get("보유 수량") or "0"
                    price = row_lower.get("price") or row_lower.get("current_price") or row_lower.get("현재가") or "0"
                    avg_cost = row_lower.get("average_cost") or row_lower.get("avg_price") or row_lower.get("매수 평단가") or "0"
                    market = row_lower.get("market") or row_lower.get("exchange")
                    currency = row_lower.get("currency")
                    
                    if symbol:
                        holdings.append({
                            "symbol": symbol.strip().upper(),
                            "quantity": _to_float(qty),
                            "price": _to_float(price),
                            "average_cost": _to_float(avg_cost),
                            "market": market,
                            "currency": currency,
                        })
        except Exception:
            pass
        return holdings

    def simulate_cashflow(
        self,
        holdings: list[dict[str, Any]] | None = None,
        fx_rate: float | None = None,
        scenario: dict[str, Any] | None = None,
        force_history_refresh: bool = False,
        allow_stale_history: bool = True,
    ) -> dict[str, Any]:
        """
        Runs the dividend simulation pipeline using real-time Yahoo Finance data.
        """
        if holdings is None:
            csv_path = self.project_root / "toss_portfolio.csv"
            holdings = self.load_holdings_from_csv(csv_path)

        # 1. Map holdings to Yahoo tickers
        mapped_holdings = self.mapper.map_all_holdings(holdings)
        holdings_by_symbol = {h["symbol"]: h for h in mapped_holdings}

        # 2. Fetch histories & build events & evaluate quality
        all_forecasts: list[DividendForecast] = []
        quality_map = {}
        
        # Determine start date
        start_date = datetime.now()

        from concurrent.futures import ThreadPoolExecutor

        def process_holding(h):
            symbol = h["symbol"]
            yahoo_ticker = h["yahoo_ticker"]
            
            # Fetch Yahoo dividend history
            try:
                yahoo_payload = self.yahoo_source.fetch_dividend_history(
                    yahoo_ticker,
                    force=force_history_refresh,
                    allow_stale=allow_stale_history,
                )
            except Exception:
                yahoo_payload = {"dividends": [], "fetched_at": 0, "cache_status": "error"}

            supplemental_events = self.supplemental_source.get_supplemental_events(symbol)

            # Build and merge events
            events = self.event_master.build_and_merge_events(
                symbol=symbol,
                name=h["name"],
                market=h["market"],
                currency=h["currency"],
                yahoo_payload=yahoo_payload,
                supplemental_events=supplemental_events,
            )

            # Quality gate evaluation
            quality = self.quality_gate.evaluate_symbol(symbol, events, yahoo_payload)
            
            # Forecast
            forecasts = self.forecast_engine.forecast_symbol(symbol, events, quality, start_date=start_date)
            
            return symbol, quality, forecasts

        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_holding, mapped_holdings))

        for symbol, quality, forecasts in results:
            quality_map[symbol] = quality
            all_forecasts.extend(forecasts)

        # 3. Apply Tax and FX Engine
        # We can pass a mock/temporary client or let the engine use cache
        usd_krw = fx_rate or self.tax_fx_engine.get_live_fx_rate()
        
        # Apply scenario adjustments to forecasts if requested
        if scenario:
            all_forecasts = self._apply_scenario_adjustments(all_forecasts, scenario)

        # Run tax & fx conversion
        self.tax_fx_engine.apply_tax_and_fx(all_forecasts, holdings_by_symbol, fx_rate=usd_krw)

        # 4. Aggregate results
        portfolio_value_krw = 0.0
        for h in mapped_holdings:
            is_us = (h["currency"] == "USD")
            rate = usd_krw if is_us else 1.0
            portfolio_value_krw += h["quantity"] * h["price"] * rate

        monthly_payouts = [0.0] * 12
        monthly_net_payouts = [0.0] * 12
        
        # Generate 12 months list
        target_months = []
        curr = start_date
        for _ in range(12):
            target_months.append(curr.strftime("%Y-%m"))
            # next month
            year = curr.year
            month = curr.month + 1
            if month > 12:
                month = 1
                year += 1
            curr = datetime(year, month, 1)

        month_to_index = {m: i for i, m in enumerate(target_months)}

        for f in all_forecasts:
            idx = month_to_index.get(f.forecast_month)
            if idx is not None:
                monthly_payouts[idx] += f.expected_amount_krw
                # net_amount is already in KRW inside apply_tax_and_fx
                monthly_net_payouts[idx] += f.net_amount

        annual_dividend_krw = sum(monthly_payouts)
        annual_net_dividend_krw = sum(monthly_net_payouts)
        aggregate_yield = (annual_dividend_krw / portfolio_value_krw) if portfolio_value_krw > 0 else 0.0

        # Build holding details
        holdings_detail = []
        for h in mapped_holdings:
            symbol = h["symbol"]
            qty = h["quantity"]
            price = h["price"]
            is_us = (h["currency"] == "USD")
            rate = usd_krw if is_us else 1.0
            val_krw = qty * price * rate

            # Sum projected dividend for this symbol
            sym_forecasts = [f for f in all_forecasts if f.symbol == symbol]
            sym_annual_krw = sum(f.expected_amount_krw for f in sym_forecasts)
            sym_net_annual_krw = sum(f.net_amount for f in sym_forecasts)

            q = quality_map.get(symbol)
            trust_score = q.trust_score if q else 0.0
            decision = q.decision if q else "exclude"
            data_sources = q.data_sources if q else []

            # Find next ex/pay dates from events
            sym_events = self.event_master.get_events_for_symbol(symbol)
            upcoming = [e for e in sym_events if e.ex_date >= start_date.strftime("%Y-%m-%d")]
            next_ex = upcoming[0].ex_date if upcoming else None
            next_pay = upcoming[0].pay_date if upcoming else None

            # Calculate growth rate (simple CAGR of past 3 years if available)
            growth_rate = 0.0
            regular_events = [e for e in sym_events if not e.is_special]
            if len(regular_events) >= 8:
                # Compare average of last 4 to average of 4 before that
                last_year = sum(e.amount_per_share for e in regular_events[-4:])
                prev_year = sum(e.amount_per_share for e in regular_events[-8:-4])
                if prev_year > 0:
                    growth_rate = round(((last_year / prev_year) - 1.0) * 100.0, 2)

            holdings_detail.append({
                "symbol": symbol,
                "name": h["name"],
                "quantity": qty,
                "value_krw": round(val_krw, 2),
                "dividend_yield": round((sym_annual_krw / val_krw * 100.0), 2) if val_krw > 0 else 0.0,
                "annual_payout_krw": round(sym_annual_krw, 2),
                "net_annual_payout_krw": round(sym_net_annual_krw, 2),
                "trust_score": trust_score,
                "decision": decision,
                "data_sources": data_sources,
                "next_ex_date": next_ex,
                "next_pay_date": next_pay,
                "growth_rate_3y_pct": growth_rate,
                "stability_score": round(trust_score * 0.9, 2) # Stability proxy
            })

        # Calculate reinvestment compound projections
        def compound_projection(years: int) -> float:
            monthly_rate = (annual_dividend_krw / portfolio_value_krw) / 12.0 if portfolio_value_krw > 0 else 0.0
            return portfolio_value_krw * ((1.0 + monthly_rate) ** (years * 12))

        projections = {
            "1_year_value_krw": round(compound_projection(1), 2),
            "3_year_value_krw": round(compound_projection(3), 2),
            "5_year_value_krw": round(compound_projection(5), 2),
        }

        # Target Goal achievements
        target_path = self.project_root / "state" / "dividend_target.json"
        target_krw = 3000000.0 # Default 3,000,000 KRW monthly
        if target_path.exists():
            try:
                with open(target_path, "r") as f:
                    target_krw = json.load(f).get("target_krw", 3000000.0)
            except Exception:
                pass

        avg_monthly_net = annual_net_dividend_krw / 12.0
        achievement_rate = round((avg_monthly_net / target_krw) * 100.0, 2) if target_krw > 0 else 0.0

        return {
            "portfolio_value_krw": round(portfolio_value_krw, 2),
            "annual_dividend_krw": round(annual_dividend_krw, 2),
            "annual_net_dividend_krw": round(annual_net_dividend_krw, 2),
            "aggregate_yield_pct": round(aggregate_yield * 100.0, 2),
            "monthly_payouts_krw": [round(val, 2) for val in monthly_payouts],
            "monthly_net_payouts_krw": [round(val, 2) for val in monthly_net_payouts],
            "months": target_months,
            "holdings": holdings_detail,
            "reinvestment_projections": projections,
            "target_goal": {
                "monthly_target_krw": target_krw,
                "current_monthly_net_krw": round(avg_monthly_net, 2),
                "achievement_rate_pct": achievement_rate,
                "shortfall_krw": round(max(0.0, target_krw - avg_monthly_net), 2)
            },
            "usd_krw_rate": usd_krw,
            "source_summary": {
                "price_and_history": "Yahoo Finance dividend history",
                "holdings": "Toss holdings CSV/API when available",
                "supplemental": "state/dividend_supplements.json or external dividend sources",
                "quality_gate": "DividendDataQualityGate",
            },
            "history_cache_policy": {
                "allow_stale_history": allow_stale_history,
                "force_history_refresh": force_history_refresh,
            },
        }

    def _apply_scenario_adjustments(
        self,
        forecasts: list[DividendForecast],
        scenario: dict[str, Any]
    ) -> list[DividendForecast]:
        """
        Applies scenario parameters (cut, growth, etc.) to forecasts.
        """
        # 1. Dividend Cut Scenario
        cut_rate = float(scenario.get("dividend_cut_rate", 0.0)) / 100.0
        # 2. Dividend Growth Scenario
        growth_rate = float(scenario.get("dividend_growth_rate", 0.0)) / 100.0
        
        for f in forecasts:
            if cut_rate > 0:
                f.expected_amount *= (1.0 - cut_rate)
            if growth_rate > 0:
                f.expected_amount *= (1.0 + growth_rate)

        return forecasts


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    text = str(value).replace(",", "").replace("₩", "").replace("$", "").strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0
