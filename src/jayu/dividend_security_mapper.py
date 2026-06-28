from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DividendSecurityMapper:
    """Map Toss securities to Yahoo Finance tickers with manual overrides."""

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
                data = json.load(f)
            return {
                str(key).upper(): str(value).upper()
                for key, value in data.items()
                if value
            } if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_override(self, toss_symbol: str, yahoo_ticker: str) -> None:
        self.overrides[toss_symbol.upper()] = yahoo_ticker.upper()
        try:
            with open(self.override_path, "w", encoding="utf-8") as f:
                json.dump(self.overrides, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def auto_map(
        self,
        toss_symbol: str,
        market: str | None = None,
        currency: str | None = None,
    ) -> str:
        """Map a Toss symbol to a Yahoo ticker.

        Korean six-digit symbols need an exchange suffix on Yahoo Finance. When
        the source market is ambiguous, KOSPI is the conservative default and a
        user override can replace it later.
        """
        clean_symbol = str(toss_symbol or "").strip().upper()
        if not clean_symbol:
            return ""
        if clean_symbol in self.overrides:
            return self.overrides[clean_symbol]
        if clean_symbol.endswith((".KS", ".KQ")):
            return clean_symbol
        if clean_symbol.isdigit() and len(clean_symbol) == 6:
            market_text = str(market or "").upper()
            currency_text = str(currency or "").upper()
            if "KOSDAQ" in market_text or "KQ" in market_text:
                return f"{clean_symbol}.KQ"
            if "KOSPI" in market_text or "KRX" in market_text or currency_text == "KRW":
                return f"{clean_symbol}.KS"
            return f"{clean_symbol}.KS"
        return clean_symbol

    def map_all_holdings(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mapped_holdings = []
        for holding in holdings:
            symbol = holding.get("symbol") or holding.get("ticker")
            if not symbol:
                continue
            market = holding.get("market")
            currency = holding.get("currency")
            name = holding.get("name") or holding.get("security_name") or symbol
            yahoo_ticker = self.auto_map(str(symbol), market, currency)
            is_korean = yahoo_ticker.endswith((".KS", ".KQ"))
            resolved_currency = str(currency or ("KRW" if is_korean else "USD")).upper()
            resolved_market = str(market or ("KR" if is_korean else "US")).upper()
            mapped_holdings.append(
                {
                    "symbol": str(symbol).strip().upper(),
                    "yahoo_ticker": yahoo_ticker,
                    "name": str(name),
                    "market": resolved_market,
                    "currency": resolved_currency,
                    "quantity": _to_float(holding.get("quantity", 0)),
                    "price": _to_float(holding.get("price") or holding.get("current_price", 0)),
                    "average_cost": _to_float(
                        holding.get("average_cost") or holding.get("avg_price", 0)
                    ),
                }
            )
        return mapped_holdings


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    text = str(value).replace(",", "").replace("₩", "").replace("$", "").strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0
