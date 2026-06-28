from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Any

@dataclass
class DividendEvent:
    symbol: str
    security_name: str
    market: str
    currency: str
    ex_date: str                 # YYYY-MM-DD
    record_date: str | None      # YYYY-MM-DD
    pay_date: str | None         # YYYY-MM-DD
    declared_date: str | None    # YYYY-MM-DD
    amount_per_share: float
    source: str                  # "yahoo", "supplemental", "manual"
    source_confidence: float     # 0.0 ~ 100.0
    source_hash: str
    status: str                  # "confirmed", "estimated", "manual", "rejected"
    is_special: bool             # Whether it is a special/one-off dividend
    frequency: str | None        # "monthly", "quarterly", "semi-annual", "annual"

class DividendEventMaster:
    """Consolidates and manages historical and upcoming dividend events from multiple sources."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.state_dir = self.project_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.state_dir / "dividend_events.json"
        self.manual_events_path = self.state_dir / "dividend_manual_events.json"

    def load_manual_events(self) -> list[dict[str, Any]]:
        if not self.manual_events_path.exists():
            return []
        try:
            with open(self.manual_events_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_manual_event(self, event_dict: dict[str, Any]) -> None:
        events = self.load_manual_events()
        # Update or append
        updated = False
        for i, e in enumerate(events):
            if e.get("symbol") == event_dict.get("symbol") and e.get("ex_date") == event_dict.get("ex_date"):
                events[i] = event_dict
                updated = True
                break
        if not updated:
            events.append(event_dict)
            
        try:
            with open(self.manual_events_path, "w", encoding="utf-8") as f:
                json.dump(events, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def load_events(self) -> list[DividendEvent]:
        if not self.events_path.exists():
            return []
        try:
            with open(self.events_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                return [DividendEvent(**item) for item in raw_list]
        except Exception:
            return []

    def save_events(self, events: list[DividendEvent]) -> None:
        raw_list = [asdict(e) for e in events]
        try:
            payload = json.dumps(raw_list, indent=2, ensure_ascii=False)
            if self.events_path.exists():
                try:
                    if self.events_path.read_text(encoding="utf-8") == payload:
                        return
                except Exception:
                    pass
            self.events_path.write_text(payload, encoding="utf-8")
        except Exception:
            pass

    def build_and_merge_events(
        self,
        symbol: str,
        name: str,
        market: str,
        currency: str,
        yahoo_payload: dict[str, Any],
        supplemental_events: list[dict[str, Any]] | None = None
    ) -> list[DividendEvent]:
        """
        Builds, normalizes, and merges dividend events for a symbol.
        """
        events_by_ex_date: dict[str, DividendEvent] = {}

        # 1. Process Yahoo events
        # yfinance usually gives ex_date and amount only. Treat Yahoo-only
        # events as estimates until another source confirms payment details.
        today = str(yahoo_payload.get("today_date") or date.today().isoformat())
        yahoo_divs = yahoo_payload.get("dividends", [])
        for item in yahoo_divs:
            ex_date = item.get("date")
            amount = _to_float(item.get("amount"))
            if not ex_date or amount <= 0:
                continue
            
            # Simple hash
            h = hashlib.md5(f"yahoo:{symbol}:{ex_date}:{amount}".encode("utf-8")).hexdigest()
            has_confirming_dates = bool(item.get("pay_date") or item.get("record_date"))
            status = "confirmed" if has_confirming_dates and ex_date <= today else "estimated"

            events_by_ex_date[ex_date] = DividendEvent(
                symbol=symbol,
                security_name=name,
                market=market,
                currency=currency,
                ex_date=ex_date,
                record_date=None,
                pay_date=None,
                declared_date=None,
                amount_per_share=amount,
                source="yahoo",
                source_confidence=80.0 if status == "confirmed" else 70.0,
                source_hash=h,
                status=status,
                is_special=False,
                frequency=None
            )

        # 2. Merge Supplemental sources (e.g. FMP, Polygon, SEIBro)
        if supplemental_events:
            for item in supplemental_events:
                ex_date = item.get("ex_date")
                if not ex_date:
                    continue
                
                amount = _to_float(item.get("amount_per_share") or item.get("amount"))
                if amount <= 0:
                    continue
                
                if ex_date in events_by_ex_date:
                    # Update dates: supplemental/manual pay_date, record_date, declared_date always take precedence
                    existing = events_by_ex_date[ex_date]
                    if item.get("pay_date"):
                        existing.pay_date = item["pay_date"]
                    if item.get("record_date"):
                        existing.record_date = item["record_date"]
                    if item.get("declared_date"):
                        existing.declared_date = item["declared_date"]
                    
                    # Strict 2% discrepancy check
                    difference_pct = abs(existing.amount_per_share - amount) / existing.amount_per_share if existing.amount_per_share > 0 else 0.0
                    if difference_pct > 0.02:
                        existing.source_confidence = max(30.0, existing.source_confidence - 25.0)
                        existing.status = "estimated"
                    else:
                        existing.source_confidence = min(95.0, existing.source_confidence + 15.0)
                        if existing.pay_date:
                            existing.status = "confirmed"
                    
                    if "supplemental" not in existing.source:
                        existing.source = f"{existing.source}+supplemental"
                    if item.get("is_special"):
                        existing.is_special = True
                    if item.get("frequency"):
                        existing.frequency = item.get("frequency")
                else:
                    # New event from supplemental
                    h = hashlib.md5(f"supplemental:{symbol}:{ex_date}:{amount}".encode("utf-8")).hexdigest()
                    status = "confirmed" if item.get("pay_date") else "estimated"
                    events_by_ex_date[ex_date] = DividendEvent(
                        symbol=symbol,
                        security_name=name,
                        market=market,
                        currency=currency,
                        ex_date=ex_date,
                        record_date=item.get("record_date"),
                        pay_date=item.get("pay_date"),
                        declared_date=item.get("declared_date"),
                        amount_per_share=amount,
                        source="supplemental",
                        source_confidence=85.0 if status == "confirmed" else 70.0,
                        source_hash=h,
                        status=status,
                        is_special=bool(item.get("is_special", False)),
                        frequency=item.get("frequency")
                    )

        # 3. Merge Manual events
        manual_events = self.load_manual_events()
        for item in manual_events:
            if item.get("symbol") != symbol:
                continue
            ex_date = item.get("ex_date")
            if not ex_date:
                continue
            
            amount = _to_float(item.get("amount_per_share") or item.get("amount"))
            if amount <= 0:
                continue
            h = hashlib.md5(f"manual:{symbol}:{ex_date}:{amount}".encode("utf-8")).hexdigest()
            
            events_by_ex_date[ex_date] = DividendEvent(
                symbol=symbol,
                security_name=name,
                market=market,
                currency=currency,
                ex_date=ex_date,
                record_date=item.get("record_date"),
                pay_date=item.get("pay_date"),
                declared_date=item.get("declared_date"),
                amount_per_share=amount,
                source="manual",
                source_confidence=100.0,
                source_hash=h,
                status="manual",
                is_special=item.get("is_special", False),
                frequency=item.get("frequency")
            )

        # Sort chronologically
        merged_list = list(events_by_ex_date.values())
        merged_list.sort(key=lambda x: x.ex_date)

        # 4. Detect special dividends & estimate frequencies
        merged_list = self.detect_special_dividends(merged_list)
        merged_list = self.estimate_frequencies(merged_list)

        # Merge with overall events_path
        all_events = self.load_events()
        # Remove old events for this symbol
        all_events = [e for e in all_events if e.symbol != symbol]
        all_events.extend(merged_list)
        self.save_events(all_events)

        return merged_list

    def detect_special_dividends(self, events: list[DividendEvent]) -> list[DividendEvent]:
        """
        Flag dividends that are significantly higher than the rolling average as special.
        """
        if len(events) < 3:
            return events

        for i in range(len(events)):
            # If manually flagged, keep it
            if events[i].is_special:
                continue
            
            # Look at previous 3 non-special payouts
            prev_payouts = []
            for j in range(i - 1, -1, -1):
                if not events[j].is_special:
                    prev_payouts.append(events[j].amount_per_share)
                if len(prev_payouts) == 3:
                    break
            
            if len(prev_payouts) >= 2:
                avg = sum(prev_payouts) / len(prev_payouts)
                if avg > 0 and events[i].amount_per_share >= avg * 2.0:
                    events[i].is_special = True
                    
        return events

    def estimate_frequencies(self, events: list[DividendEvent]) -> list[DividendEvent]:
        """
        Estimate dividend frequency (monthly, quarterly, semi-annual, annual) based on intervals.
        """
        if len(events) < 2:
            # Default to quarterly if we can't determine
            for e in events:
                if not e.frequency:
                    e.frequency = "quarterly"
            return events

        # Filter out special dividends for frequency estimation
        regular_events = [e for e in events if not e.is_special]
        if len(regular_events) < 2:
            for e in events:
                if not e.frequency:
                    e.frequency = "quarterly"
            return events

        from datetime import datetime
        intervals = []
        for i in range(1, len(regular_events)):
            try:
                d1 = datetime.strptime(regular_events[i-1].ex_date, "%Y-%m-%d")
                d2 = datetime.strptime(regular_events[i].ex_date, "%Y-%m-%d")
                days = (d2 - d1).days
                intervals.append(days)
            except Exception:
                pass

        if not intervals:
            return events

        avg_days = sum(intervals) / len(intervals)
        
        # Classify based on average interval days
        if 20 <= avg_days <= 40:
            freq = "monthly"
        elif 70 <= avg_days <= 110:
            freq = "quarterly"
        elif 160 <= avg_days <= 200:
            freq = "semi-annual"
        elif 330 <= avg_days <= 380:
            freq = "annual"
        else:
            freq = "quarterly" # default fallback

        for e in events:
            if not e.frequency:
                e.frequency = freq

        return events

    def get_events_for_symbol(self, symbol: str) -> list[DividendEvent]:
        all_events = self.load_events()
        return [e for e in all_events if e.symbol == symbol]


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
