from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

@dataclass
class DividendQuality:
    symbol: str
    data_sources: list[str]
    missing_fields: list[str]
    stale_fields: list[str]
    trust_score: float
    decision: str                # "pass", "review", "block", "exclude"
    block_reason: str | None
    checks: dict[str, Any]

class DividendDataQualityGate:
    """Evaluates the quality and reliability of dividend data, assigning trust scores."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.weights = {
            "amount_validity": 0.25,
            "date_completeness": 0.25,
            "source_agreement": 0.20,
            "freshness": 0.15,
            "history_consistency": 0.15,
        }

    def evaluate_symbol(
        self,
        symbol: str,
        events: list[Any], # list of DividendEvent objects
        yahoo_payload: dict[str, Any] | None = None
    ) -> DividendQuality:
        """
        Calculates a trust score from 0 to 100 for a symbol's dividend data.
        """
        missing_fields = []
        stale_fields = []
        data_sources = list(set(getattr(e, "source", "unknown") for e in events)) if events else []
        
        # 1. Amount Validity (0.25)
        # Check if amounts are > 0 and consistent
        amount_score = 100.0
        if not events:
            amount_score = 0.0
            missing_fields.append("amount")
        else:
            invalid_count = sum(1 for e in events if getattr(e, "amount_per_share", 0) <= 0)
            if invalid_count > 0:
                amount_score = max(0.0, 100.0 - (invalid_count / len(events)) * 100.0)
                missing_fields.append("positive_amount")

        # 2. Date Completeness (0.25)
        # Check if ex_date, pay_date, record_date are present
        date_score = 100.0
        if not events:
            date_score = 0.0
            missing_fields.extend(["ex_date", "pay_date", "record_date"])
        else:
            missing_pay_date = sum(1 for e in events if not getattr(e, "pay_date", None))
            missing_record_date = sum(1 for e in events if not getattr(e, "record_date", None))
            
            total_missing = missing_pay_date + missing_record_date
            if total_missing > 0:
                # Deduct points for missing dates
                penalty = (total_missing / (len(events) * 2)) * 100.0
                date_score = max(0.0, 100.0 - penalty)
                if missing_pay_date > 0:
                    missing_fields.append("pay_date")
                if missing_record_date > 0:
                    missing_fields.append("record_date")

        # 3. Source Agreement (0.20)
        # If we have multiple sources, check if they agree. Otherwise, default to 80.
        agreement_score = 80.0
        disagreements = 0
        if events:
            # Check if there are any events with lowered confidence (which indicates disagreement during merge)
            low_confidence_events = sum(1 for e in events if getattr(e, "source_confidence", 100.0) < 60.0)
            if low_confidence_events > 0:
                disagreements = low_confidence_events
                agreement_score = max(0.0, 100.0 - (low_confidence_events / len(events)) * 50.0)
            elif len(data_sources) >= 2:
                # Multiple sources agreeing
                agreement_score = 100.0

        # 4. Freshness (0.15)
        # Check when the data was last fetched
        freshness_score = 100.0
        if yahoo_payload:
            fetched_at = yahoo_payload.get("fetched_at", 0)
            age_hours = (time.time() - fetched_at) / 3600.0
            if age_hours > 48:
                freshness_score = 60.0
                stale_fields.append("yahoo_cache")
            elif age_hours > 24:
                freshness_score = 80.0
                stale_fields.append("yahoo_cache_24h")
        else:
            freshness_score = 50.0
            stale_fields.append("no_recent_fetch")

        # 5. History Consistency (0.15)
        # Check if dividend intervals and amounts are relatively consistent
        consistency_score = 100.0
        if not events or len(events) < 3:
            consistency_score = 70.0 # Not enough history to judge consistency
        else:
            # Check for sudden drop in amount (excluding special dividends)
            regular_amounts = [e.amount_per_share for e in events if not getattr(e, "is_special", False)]
            if len(regular_amounts) >= 3:
                # Compare latest to average of previous
                latest = regular_amounts[-1]
                prev_avg = sum(regular_amounts[:-1]) / len(regular_amounts[:-1])
                if prev_avg > 0 and latest < prev_avg * 0.5:
                    # Dividend cut detected!
                    consistency_score -= 40.0
                    stale_fields.append("dividend_cut_detected")
                
                # Check for high variance in regular payouts
                variance_indicators = []
                for i in range(1, len(regular_amounts)):
                    diff_pct = abs(regular_amounts[i] - regular_amounts[i-1]) / (regular_amounts[i-1] or 1.0)
                    variance_indicators.append(diff_pct)
                
                avg_variance = sum(variance_indicators) / len(variance_indicators) if variance_indicators else 0.0
                if avg_variance > 0.3: # > 30% fluctuation between consecutive regular payouts
                    consistency_score = max(0.0, consistency_score - 20.0)

        # Calculate weighted trust score
        trust_score = round(
            amount_score * self.weights["amount_validity"] +
            date_score * self.weights["date_completeness"] +
            agreement_score * self.weights["source_agreement"] +
            freshness_score * self.weights["freshness"] +
            consistency_score * self.weights["history_consistency"],
            2
        )

        # Make decision
        # score >= 80 -> pass
        # score >= 60 -> review (warn)
        # score >= 40 -> block (exclude from goals)
        # score < 40 -> exclude (entirely exclude from reports/autotrading)
        block_reason = None
        if trust_score >= 80:
            decision = "pass"
        elif trust_score >= 60:
            decision = "review"
            block_reason = "Trust score in review range (60-79)"
        elif trust_score >= 40:
            decision = "block"
            block_reason = "Trust score too low (40-59), blocked from goals"
        else:
            decision = "exclude"
            block_reason = "Trust score critical (<40), excluded from autotrading and reports"

        # Hard blocks
        if not events:
            decision = "exclude"
            block_reason = "No dividend events found"

        checks = {
            "amount_score": amount_score,
            "date_score": date_score,
            "agreement_score": agreement_score,
            "freshness_score": freshness_score,
            "consistency_score": consistency_score,
            "disagreements_count": disagreements
        }

        return DividendQuality(
            symbol=symbol,
            data_sources=data_sources,
            missing_fields=missing_fields,
            stale_fields=stale_fields,
            trust_score=trust_score,
            decision=decision,
            block_reason=block_reason,
            checks=checks
        )

    def evaluate_all(
        self,
        events_by_symbol: dict[str, list[Any]],
        yahoo_payloads: dict[str, dict[str, Any]]
    ) -> dict[str, DividendQuality]:
        results = {}
        for symbol, events in events_by_symbol.items():
            payload = yahoo_payloads.get(symbol)
            results[symbol] = self.evaluate_symbol(symbol, events, payload)
        return results
