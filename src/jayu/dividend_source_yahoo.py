from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from .yahoo import get_yahoo_session

class DividendSourceYahoo:
    """Fetches historical dividends, splits, and metadata from Yahoo Finance using yfinance."""

    def __init__(self, project_root: Path, cache_ttl_seconds: int = 86400) -> None:
        self.project_root = project_root
        self.cache_dir = self.project_root / "state" / "dividend_yahoo_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_ttl_seconds
        self.updating_tickers = set()

    def _get_cache_path(self, ticker: str) -> Path:
        # Avoid invalid characters in filename
        safe_ticker = ticker.replace("^", "_").replace("=", "_")
        return self.cache_dir / f"{safe_ticker.lower()}.json"

    def load_cache(self, ticker: str, *, allow_stale: bool = False) -> dict[str, Any] | None:
        cache_path = self._get_cache_path(ticker)
        if not cache_path.exists():
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Check TTL
            fetched_at = data.get("fetched_at", 0)
            age_seconds = time.time() - fetched_at
            if age_seconds > self.cache_ttl and not allow_stale:
                return None
            data["cache_status"] = "stale_hit" if age_seconds > self.cache_ttl else "hit"
            data["cache_age_seconds"] = round(max(0.0, age_seconds), 2)
            return data
        except Exception:
            return None

    def save_cache(self, ticker: str, data: dict[str, Any]) -> None:
        cache_path = self._get_cache_path(ticker)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def fetch_dividend_history(
        self,
        yahoo_ticker: str,
        force: bool = False,
        *,
        allow_stale: bool = False,
    ) -> dict[str, Any]:
        """
        Fetches historical dividends and splits from Yahoo Finance.
        Returns a normalized dictionary.
        """
        if not force:
            cached = self.load_cache(yahoo_ticker, allow_stale=allow_stale)
            if cached:
                # If it's a stale hit, trigger a background update
                if cached.get("cache_status") == "stale_hit" and yahoo_ticker not in self.updating_tickers:
                    import threading
                    self.updating_tickers.add(yahoo_ticker)
                    def bg_update():
                        try:
                            self.fetch_dividend_history(yahoo_ticker, force=True)
                        except Exception:
                            pass
                        finally:
                            self.updating_tickers.discard(yahoo_ticker)
                    threading.Thread(target=bg_update, daemon=True).start()
                return cached

        error_message = None
        error_reason = None
        raw_dividends = []
        raw_splits = []
        info_yield = 0.0
        info_rate = 0.0

        try:
            session = get_yahoo_session()
            ticker_obj = yf.Ticker(yahoo_ticker, session=session)

            # Get historical dividends & actions
            try:
                actions = ticker_obj.get_actions() # returns DataFrame with Dividends and Stock Splits
                dividends_series = ticker_obj.get_dividends()
            except Exception as exc:
                actions = None
                dividends_series = None
                error_message = str(exc)
                # Classify network error vs rate limit
                if "429" in error_message or "too many requests" in error_message.lower():
                    error_reason = "rate_limit"
                elif "unauthorized" in error_message.lower() or "401" in error_message:
                    error_reason = "unauthorized"
                else:
                    error_reason = "network_error"

            if dividends_series is not None and not dividends_series.empty:
                for timestamp, amount in dividends_series.items():
                    raw_dividends.append({
                        "date": timestamp.strftime("%Y-%m-%d"),
                        "amount": float(amount),
                        "source": "yahoo_finance",
                        "source_role": "fast_history"
                    })
            elif dividends_series is not None and dividends_series.empty and not error_reason:
                error_reason = "empty_dividend_history"

            if actions is not None and not actions.empty:
                for timestamp, row in actions.iterrows():
                    split_val = row.get("Stock Splits", 0)
                    if split_val and split_val != 0:
                        raw_splits.append({
                            "date": timestamp.strftime("%Y-%m-%d"),
                            "ratio": str(split_val), # e.g. "2:1" or "0.5"
                            "source": "yahoo_finance",
                        })

            # Try to fetch some metadata (yield, trailing rate) from info
            try:
                info = ticker_obj.info
                info_yield = info.get("dividendYield") or 0.0
                if info_yield:
                    info_yield = float(info_yield) * 100.0
                info_rate = float(info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0)
            except Exception:
                pass

        except Exception as outer_exc:
            error_message = str(outer_exc)
            error_reason = "network_error"

        # Sort dividends chronologically
        raw_dividends.sort(key=lambda x: x["date"])
        raw_splits.sort(key=lambda x: x["date"])

        payload = {
            "ticker": yahoo_ticker,
            "fetched_at": time.time(),
            "fetched_at_iso": datetime.now(timezone.utc).isoformat(),
            "info_yield_pct": info_yield,
            "info_annual_rate": info_rate,
            "dividends": raw_dividends,
            "splits": raw_splits,
            "source": "yahoo_finance",
            "source_role": "fast_history_not_final",
            "raw_payload_path": str(self._get_cache_path(yahoo_ticker)),
            "cache_status": "refreshed" if not error_reason or error_reason == "empty_dividend_history" else "error",
            "cache_age_seconds": 0.0,
        }
        if error_message:
            payload["warning"] = error_message
        if error_reason:
            payload["error_reason"] = error_reason

        # Calculate a hash of the dividend data to detect changes
        data_str = json.dumps(raw_dividends, sort_keys=True)
        payload["source_hash"] = hashlib.md5(data_str.encode("utf-8")).hexdigest()

        self.save_cache(yahoo_ticker, payload)
        return payload

    def fetch_batch(
        self,
        tickers: list[str],
        force: bool = False,
        *,
        allow_stale: bool = False,
    ) -> dict[str, dict[str, Any]]:
        results = {}
        for t in tickers:
            try:
                results[t] = self.fetch_dividend_history(t, force=force, allow_stale=allow_stale)
            except Exception as e:
                results[t] = {
                    "ticker": t,
                    "fetched_at": time.time(),
                    "fetched_at_iso": datetime.now(timezone.utc).isoformat(),
                    "info_yield_pct": 0.0,
                    "info_annual_rate": 0.0,
                    "dividends": [],
                    "splits": [],
                    "source": "yahoo_finance",
                    "source_role": "fast_history_not_final",
                    "cache_status": "error",
                    "error_reason": "network_error",
                    "error": str(e)
                }
        return results
