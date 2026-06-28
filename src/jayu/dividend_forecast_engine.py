from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .dividend_data_quality_gate import DividendQuality
from .dividend_event_master import DividendEvent

@dataclass
class DividendForecast:
    symbol: str
    forecast_month: str          # "YYYY-MM"
    expected_amount: float       # per share
    expected_amount_krw: float
    tax_estimate: float
    net_amount: float
    confidence: float            # 0.0 ~ 1.0
    forecast_method: str         # "confirmed", "recent_carry", "four_quarter_avg", "seasonal", "conservative"
    is_confirmed: bool

class DividendForecastEngine:
    """Generates a 12-month forward dividend forecast based on historical patterns and confirmed events."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def forecast_symbol(
        self,
        symbol: str,
        events: list[DividendEvent],
        quality: DividendQuality,
        start_date: datetime | None = None,
        months_ahead: int = 12
    ) -> list[DividendForecast]:
        """
        Generates 12-month forward dividend forecasts for a specific symbol.
        """
        if quality.decision in {"block", "exclude"} or not events:
            return []

        if start_date is None:
            start_date = datetime.now()

        # Filter out special dividends for pattern estimation
        regular_events = [e for e in events if not e.is_special]
        if not regular_events:
            # Fallback to all events if no regular events
            regular_events = events

        # Sort chronologically
        regular_events.sort(key=lambda x: x.ex_date)
        events.sort(key=lambda x: x.ex_date)

        # 1. Determine forecast method & baseline amount
        method = "recent_carry"
        baseline_amount = 0.0
        confidence = 0.8

        # If trust score is low (60-79), use conservative estimation (85% of baseline)
        is_conservative = quality.trust_score < 80.0
        
        # Estimate frequency
        freq = regular_events[-1].frequency if regular_events else "quarterly"

        if freq == "monthly" and len(regular_events) >= 3:
            # Monthly payouts are usually stable, carry forward the last one
            baseline_amount = regular_events[-1].amount_per_share
            method = "recent_carry"
            confidence = 0.85
        elif freq == "quarterly" and len(regular_events) >= 4:
            # Quarterly payouts: use 4-quarter average to smooth out fluctuations
            last_4 = [e.amount_per_share for e in regular_events[-4:]]
            baseline_amount = sum(last_4) / len(last_4)
            method = "four_quarter_avg"
            confidence = 0.75
        elif freq == "annual" and len(regular_events) >= 1:
            baseline_amount = regular_events[-1].amount_per_share
            method = "seasonal"
            confidence = 0.70
        elif regular_events:
            baseline_amount = regular_events[-1].amount_per_share
            method = "recent_carry"
            confidence = 0.60

        if is_conservative:
            baseline_amount *= 0.85
            method = "conservative"
            confidence = 0.50

        # Adjust for split if any recent splits occurred (for simplicity, we assume events are already adjusted,
        # but if we need to adjust, we'd do it here).

        # 2. Project future months
        forecasts = []
        
        # Generate target months
        target_months = []
        curr = start_date
        for _ in range(months_ahead):
            target_months.append(curr.strftime("%Y-%m"))
            # Move to next month
            # Simple next month logic
            year = curr.year
            month = curr.month + 1
            if month > 12:
                month = 1
                year += 1
            curr = datetime(year, month, 1)

        # Map historical payout months (1-12) to project future payout months
        # Let's find out which months this stock typically pays out in.
        payout_months = set()
        for e in regular_events[-8:]: # Look at last 8 payouts
            if e.pay_date:
                try:
                    payout_dt = datetime.strptime(e.pay_date, "%Y-%m-%d")
                    payout_months.add(payout_dt.month)
                except Exception:
                    pass
            elif e.ex_date:
                try:
                    ex_dt = datetime.strptime(e.ex_date, "%Y-%m-%d")
                    # Usually pay_date is in the same month or next month. Assume same month for simplicity.
                    payout_months.add(ex_dt.month)
                except Exception:
                    pass

        if not payout_months:
            # Fallback based on frequency
            if freq == "monthly":
                payout_months = set(range(1, 13))
            elif freq == "quarterly":
                # Guess based on last ex_date
                try:
                    last_m = datetime.strptime(regular_events[-1].ex_date, "%Y-%m-%d").month
                    payout_months = {last_m, (last_m+3)%12 or 12, (last_m+6)%12 or 12, (last_m+9)%12 or 12}
                except Exception:
                    payout_months = {3, 6, 9, 12}
            else:
                payout_months = {12}

        # 3. Check for confirmed upcoming events
        # Events that have a pay_date in the future
        confirmed_events = []
        for e in events:
            if e.pay_date and e.status in {"confirmed", "manual"}:
                try:
                    pay_dt = datetime.strptime(e.pay_date, "%Y-%m-%d")
                    if pay_dt >= start_date:
                        confirmed_events.append(e)
                except Exception:
                    pass

        for m_str in target_months:
            year_val, month_val = map(int, m_str.split("-"))
            
            # Check if there is a confirmed event in this month
            matched_confirmed = None
            for ce in confirmed_events:
                ce_dt = datetime.strptime(ce.pay_date, "%Y-%m-%d")
                if ce_dt.year == year_val and ce_dt.month == month_val:
                    matched_confirmed = ce
                    break

            if matched_confirmed:
                forecasts.append(DividendForecast(
                    symbol=symbol,
                    forecast_month=m_str,
                    expected_amount=matched_confirmed.amount_per_share,
                    expected_amount_krw=0.0, # Filled by tax/fx engine
                    tax_estimate=0.0,        # Filled by tax/fx engine
                    net_amount=0.0,          # Filled by tax/fx engine
                    confidence=1.0,
                    forecast_method="confirmed",
                    is_confirmed=True
                ))
            elif month_val in payout_months:
                # Predict payout based on baseline
                # If seasonal method, we can try to match the exact month from last year if available
                amount = baseline_amount
                if method == "seasonal" and len(regular_events) >= 2:
                    # Look for payout in the same month in the past
                    for prev_e in reversed(regular_events):
                        try:
                            prev_dt = datetime.strptime(prev_e.pay_date or prev_e.ex_date, "%Y-%m-%d")
                            if prev_dt.month == month_val:
                                amount = prev_e.amount_per_share
                                break
                        except Exception:
                            pass

                forecasts.append(DividendForecast(
                    symbol=symbol,
                    forecast_month=m_str,
                    expected_amount=amount,
                    expected_amount_krw=0.0,
                    tax_estimate=0.0,
                    net_amount=0.0,
                    confidence=confidence,
                    forecast_method=method,
                    is_confirmed=False
                ))

        return forecasts

    def forecast_all(
        self,
        events_by_symbol: dict[str, list[DividendEvent]],
        quality_map: dict[str, DividendQuality],
        start_date: datetime | None = None,
        months_ahead: int = 12
    ) -> dict[str, list[DividendForecast]]:
        results = {}
        for symbol, events in events_by_symbol.items():
            quality = quality_map.get(symbol)
            if quality:
                results[symbol] = self.forecast_symbol(symbol, events, quality, start_date, months_ahead)
        return results
