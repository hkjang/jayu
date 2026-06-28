from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .dividend_forecast_engine import DividendForecast

class DividendTaxFxEngine:
    """Calculates dividend taxes and applies currency conversion rates."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.cache_path = self.project_root / "state" / "toss_fx_cache.json"
        self.fx_source = "fallback"
        self.fx_timestamp = 0.0
        self.fx_cache_status = "miss"

    def get_tax_rate(self, market: str) -> float:
        """
        Returns the withholding tax rate for the market.
        - US: 15% (0.15)
        - KR: 15.4% (0.154)
        - Others: Default to 15.4% (0.154)
        """
        m = market.upper()
        if "US" in m or "NASDAQ" in m or "NYSE" in m:
            return 0.15
        elif "KR" in m or "KOSPI" in m or "KOSDAQ" in m:
            return 0.154
        return 0.154

    def get_live_fx_rate(self, toss_client: Any = None, fallback_rate: float = 1350.0) -> float:
        """
        Fetches the USD/KRW exchange rate.
        Checks cache first, then calls Toss API if client is provided, otherwise falls back.
        """
        # 1. Check cache
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                
                timestamp = float(cache.get("timestamp", 0.0))
                # TTL 1 hour (3600 seconds)
                if time.time() - timestamp < 3600:
                    self.fx_source = "cache"
                    self.fx_timestamp = timestamp
                    self.fx_cache_status = "hit"
                    return float(cache.get("usd_krw", fallback_rate))
                else:
                    self.fx_cache_status = "stale"
            except Exception:
                self.fx_cache_status = "corrupted"

        rate = fallback_rate
        self.fx_source = "fallback"
        self.fx_timestamp = time.time()

        # 2. Try to fetch from Toss API
        if toss_client:
            try:
                res = toss_client.exchange_rate("USD", "KRW")
                if res and isinstance(res, dict):
                    rate_val = res.get("rate") or res.get("exchangeRate") or res.get("baseRate")
                    if rate_val:
                        rate = float(rate_val)
                        self.fx_source = "toss_api"
                        self.fx_timestamp = time.time()
                        self.fx_cache_status = "refreshed"
                        self._save_cache(rate)
                        return rate
            except Exception:
                pass

        # 3. Default fallback
        if self.fx_cache_status == "stale":
            # If API fails but we have stale cache, use it as fallback rather than hardcoded rate
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                rate = float(cache.get("usd_krw", fallback_rate))
                self.fx_source = "stale_cache"
            except Exception:
                pass
        return rate

    def _save_cache(self, rate: float) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": time.time(),
                    "usd_krw": rate
                }, f, indent=2)
        except Exception:
            pass

    def apply_tax_and_fx(
        self,
        forecasts: list[DividendForecast],
        holdings_by_symbol: dict[str, dict[str, Any]],
        toss_client: Any = None,
        fx_rate: float | None = None,
    ) -> list[DividendForecast]:
        """
        Enriches forecasts with KRW converted amounts and estimated taxes.
        """
        usd_krw = fx_rate if fx_rate is not None else self.get_live_fx_rate(toss_client)

        for f in forecasts:
            holding = holdings_by_symbol.get(f.symbol, {})
            qty = _to_float(holding.get("quantity", 0))
            market = holding.get("market", "US")
            currency = holding.get("currency", "USD")

            # 1. Calculate total gross amount for the holding
            total_gross = f.expected_amount * qty

            # 2. Calculate tax
            tax_rate = self.get_tax_rate(market)
            total_tax = total_gross * tax_rate
            total_net = total_gross - total_tax

            # 3. Convert to KRW
            is_us = (currency.upper() == "USD")
            rate = usd_krw if is_us else 1.0

            f.expected_amount_krw = round(total_gross * rate, 2)
            f.tax_estimate = round(total_tax * rate, 2)
            f.net_amount = round(total_net * rate, 2)

        return forecasts


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
