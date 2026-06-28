from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .dividend_data_quality_gate import DividendQuality
from .dividend_event_master import DividendEvent

class DividendChasingGuard:
    """Guards against buying value traps, chasing ex-dates blindly, or misinterpreting dividend drops."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def evaluate_symbol_simple(
        self,
        symbol: str,
        price: float | None = None,
        price_history_30d: list[float] | None = None
    ) -> dict[str, Any]:
        """
        Convenience wrapper that resolves symbol mapping, fetches dividend history,
        builds events, evaluates quality, and performs guard checks.
        """
        from .dividend_cashflow_simulator import DividendCashflowSimulator
        simulator = DividendCashflowSimulator(self.project_root)
        
        mapped = simulator.mapper.map_all_holdings([{"symbol": symbol}])
        if not mapped:
            return {
                "symbol": symbol,
                "verdict": "allow",
                "reasons": ["mapping_failed"],
                "checks": []
            }
        h = mapped[0]
        
        try:
            yahoo_payload = simulator.yahoo_source.fetch_dividend_history(
                h["yahoo_ticker"],
                allow_stale=True
            )
        except Exception:
            yahoo_payload = {"dividends": [], "fetched_at": 0, "cache_status": "error"}
            
        supp = simulator.supplemental_source.get_supplemental_events(symbol)
        events = simulator.event_master.build_and_merge_events(
            symbol=symbol,
            name=h["name"],
            market=h["market"],
            currency=h["currency"],
            yahoo_payload=yahoo_payload,
            supplemental_events=supp
        )
        quality = simulator.quality_gate.evaluate_symbol(symbol, events, yahoo_payload)
        
        use_price = price if price is not None else h["price"]
        return self.evaluate(symbol, use_price, events, quality, price_history_30d)

    def evaluate(
        self,
        symbol: str,
        price: float,
        events: list[DividendEvent],
        quality: DividendQuality,
        price_history_30d: list[float] | None = None
    ) -> dict[str, Any]:
        """
        Evaluates dividend safety and generates trading warnings or blocks.
        """
        verdict = "allow"
        reasons = []
        checks = []

        # 1. Ex-date proximity check
        # Warn or block if trying to buy right before the ex-date (e.g., within 3 days)
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        upcoming_events = [e for e in events if e.ex_date >= today_str]
        upcoming_events.sort(key=lambda x: x.ex_date)
        
        if upcoming_events:
            next_ex = datetime.strptime(upcoming_events[0].ex_date, "%Y-%m-%d").date()
            days_to_ex = (next_ex - today).days
            if 0 <= days_to_ex <= 3:
                reasons.append("ex_date_proximity_warning")
                verdict = "warning"
                checks.append({
                    "type": "ex_date_proximity",
                    "status": "warning",
                    "message": (
                        f"배당락일({upcoming_events[0].ex_date})이 {days_to_ex}일 남았습니다. "
                        "배당만 노린 추격 매수는 위험할 수 있습니다."
                    )
                })
        
        # 2. Special dividend illusion
        # Warn if the high yield is driven by a one-off special dividend
        has_special = any(e.is_special for e in events[-4:]) # any special in last 4
        if has_special:
            reasons.append("special_dividend_illusion")
            if verdict == "allow":
                verdict = "warning"
            checks.append({
                "type": "special_dividend_illusion",
                "status": "warning",
                "message": "최근 이력에 특별배당이 포함되어 있어 겉보기 배당률이 왜곡되었을 수 있습니다."
            })

        # 3. Price drop high yield (Value Trap)
        # Block if the stock has dropped >20% in the last 30 days and has a suspiciously high yield
        if price_history_30d and len(price_history_30d) >= 2:
            start_p = price_history_30d[0]
            end_p = price_history_30d[-1]
            drop_pct = ((end_p - start_p) / start_p) * 100.0 if start_p > 0 else 0.0
            
            if drop_pct <= -20.0:
                reasons.append("price_drop_value_trap")
                verdict = "block"
                checks.append({
                    "type": "price_drop_high_yield",
                    "status": "block",
                    "message": (
                        f"최근 30일간 주가가 {round(drop_pct, 1)}% 급락했습니다. "
                        "배당률이 높아 보이는 착시일 수 있으므로 매수를 제한합니다."
                    )
                })

        # 4. Dividend cut risk
        # Warn if trust score or stability is very low
        if quality.trust_score < 60.0:
            reasons.append("dividend_cut_risk")
            if verdict == "allow":
                verdict = "warning"
            checks.append({
                "type": "dividend_cut_risk",
                "status": "warning",
                "message": f"배당 데이터 신뢰도({quality.trust_score}점)가 낮아 배당 삭감 위험이 있습니다."
            })

        return {
            "symbol": symbol,
            "verdict": verdict,
            "reasons": reasons,
            "checks": checks
        }
