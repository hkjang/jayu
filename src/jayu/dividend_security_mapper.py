from __future__ import annotations

import json
from pathlib import Path
from typing import Any

class DividendSecurityMapper:
    """Maps Toss securities to Yahoo Finance tickers, supporting overrides and automatic suffixes."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.state_dir = self.project_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.override_path = self.state_dir / "dividend_ticker_overrides.json"
        self.overrides = self.load_overrides()

    def load_overrides(self) -> dict[str, str]:
        if not self.override_path.exists():
            return {}
        try:
            with open(self.override_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_override(self, toss_symbol: str, yahoo_ticker: str) -> None:
        self.overrides[toss_symbol.upper()] = yahoo_ticker.upper()
        try:
            with open(self.override_path, "w", encoding="utf-8") as f:
                json.dump(self.overrides, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def auto_map(self, toss_symbol: str, market: str | None = None, currency: str | None = None) -> str:
        """
        Maps a Toss symbol to a Yahoo Finance ticker.
        Appends .KS for KOSPI, .KQ for KOSDAQ.
        """
        toss_symbol = toss_symbol.strip().upper()
        
        # 1. Check manual overrides first
        if toss_symbol in self.overrides:
            return self.overrides[toss_symbol]

        # 2. Check if it's already a Korean digit-based ticker
        if toss_symbol.isdigit() and len(toss_symbol) == 6:
            # If market info is provided, use it
            if market:
                market = market.upper()
                if "KOSPI" in market or "유가" in market:
                    return f"{toss_symbol}.KS"
                elif "KOSDAQ" in market or "코스닥" in market:
                    return f"{toss_symbol}.KQ"
            
            # Default to KOSPI for digit tickers if market is unknown
            return f"{toss_symbol}.KS"

        # 3. Standard US tickers (e.g. AAPL, TSLA, SCHD)
        # Usually they match directly
        return toss_symbol

    def map_all_holdings(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Maps a list of holdings to Yahoo tickers.
        Expected holding keys: symbol/ticker, market, currency, name
        """
        mapped_holdings = []
        for h in holdings:
            # support both 'symbol' and 'ticker' keys
            symbol = h.get("symbol") or h.get("ticker")
            if not symbol:
                continue
            
            market = h.get("market")
            currency = h.get("currency")
            name = h.get("name") or h.get("security_name") or symbol
            
            yahoo_ticker = self.auto_map(symbol, market, currency)
            
            # Identify asset_type and currency
            is_us = not yahoo_ticker.endswith(".KS") and not yahoo_ticker.endswith(".KQ") and not symbol.isdigit()
            resolved_currency = currency or ("USD" if is_us else "KRW")
            resolved_market = market or ("US" if is_us else "KR")
            
            mapped_holdings.append({
                "symbol": symbol,
                "yahoo_ticker": yahoo_ticker,
                "name": name,
                "market": resolved_market,
                "currency": resolved_currency,
                "quantity": float(h.get("quantity", 0)),
                "price": float(h.get("price") or h.get("current_price", 0)),
                "average_cost": float(h.get("average_cost") or h.get("avg_price", 0)),
            })
        return mapped_holdings
