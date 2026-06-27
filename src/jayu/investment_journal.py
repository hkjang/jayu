from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import uuid

class InvestmentJournal:
    """Manages user's trade journal entries, reasons for overrides, and tracks subsequent returns."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.journal_file = project_root / "state" / "investment_journal.json"

    def load_journal(self) -> list[dict[str, Any]]:
        if not self.journal_file.exists():
            return []
        try:
            with open(self.journal_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_journal(self, journal: list[dict[str, Any]]) -> None:
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_file, "w", encoding="utf-8") as f:
            json.dump(journal, f, indent=2, ensure_ascii=False)

    def add_entry(
        self,
        ticker: str,
        action_type: str,  # 'approve', 'defer', 'ignore'
        entry_price: float,
        note: str,
    ) -> dict[str, Any]:
        journal = self.load_journal()
        
        entry = {
            "entry_id": str(uuid.uuid4())[:8],
            "ticker": ticker.upper(),
            "action_type": action_type,
            "entry_price": entry_price,
            "note": note,
            "created_at": datetime.now().isoformat(),
            "price_5d": None,
            "price_20d": None,
            "return_5d_pct": None,
            "return_20d_pct": None,
        }
        journal.append(entry)
        self.save_journal(journal)
        return entry

    def delete_entry(self, entry_id: str) -> bool:
        journal = self.load_journal()
        filtered = [e for e in journal if e["entry_id"] != entry_id]
        if len(filtered) == len(journal):
            return False
        self.save_journal(filtered)
        return True

    def update_outcomes(self) -> list[dict[str, Any]]:
        """Download historical prices using yfinance for past entries to calculate 5d/20d returns."""
        import yfinance as yf
        from .yahoo import get_yahoo_session

        journal = self.load_journal()
        updated = False
        session = get_yahoo_session()

        for entry in journal:
            # Check if we need to fetch prices
            needs_5d = entry.get("price_5d") is None
            needs_20d = entry.get("price_20d") is None
            if not (needs_5d or needs_20d):
                continue

            created_dt = datetime.fromisoformat(entry["created_at"])
            now = datetime.now()
            
            # 5 days check: wait at least 5 days from creation
            if needs_5d and (now - created_dt).days >= 5:
                p_5d = self._fetch_price_after_days(entry["ticker"], created_dt, 5, session, yf)
                if p_5d:
                    entry["price_5d"] = round(p_5d, 2)
                    entry["return_5d_pct"] = round((p_5d - entry["entry_price"]) / entry["entry_price"] * 100.0, 2)
                    updated = True

            # 20 days check: wait at least 20 days from creation
            if needs_20d and (now - created_dt).days >= 20:
                p_20d = self._fetch_price_after_days(entry["ticker"], created_dt, 20, session, yf)
                if p_20d:
                    entry["price_20d"] = round(p_20d, 2)
                    entry["return_20d_pct"] = round((p_20d - entry["entry_price"]) / entry["entry_price"] * 100.0, 2)
                    updated = True

        if updated:
            self.save_journal(journal)
        return journal

    def _fetch_price_after_days(self, ticker: str, start_dt: datetime, days: int, session: Any, yf: Any) -> float | None:
        """Fetch closing price on the closest trading date after target date."""
        target_date = start_dt + timedelta(days=days)
        # Fetch a small window around the target date
        start_str = target_date.strftime("%Y-%m-%d")
        end_str = (target_date + timedelta(days=5)).strftime("%Y-%m-%d")
        try:
            df = yf.download(ticker, start=start_str, end=end_str, session=session, auto_adjust=True, progress=False)
            if not df.empty:
                # Get the first available close price in this window
                if hasattr(df.columns, "levels"):
                    closes = df[("Close", ticker)].dropna()
                else:
                    closes = df["Close"].dropna()
                if not closes.empty:
                    return float(closes.iloc[0])
        except Exception:
            pass
        return None
