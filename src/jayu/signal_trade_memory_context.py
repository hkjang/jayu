import json
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster
from .toss_order_feature_store import build_toss_order_feature_store

class SignalTradeMemoryContext:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)
        self.orders_file = self.project_root / "state" / "toss_orders.json"

    def get_memory_context(self, symbol: str) -> dict[str, Any]:
        """
        Retrieves the past trading memory, warning status, and risk metrics for a signal symbol.
        """
        symbol = symbol.strip().upper()
        master = self.security_master.get_security_master()
        
        sec_info = master.get(symbol) or {}
        warnings = sec_info.get("warnings") or {}
        
        # Default empty memory
        memory_score = 100
        pnl = 0.0
        trade_count = 0
        win_rate = None
        
        if self.orders_file.exists():
            try:
                with open(self.orders_file, "r", encoding="utf-8") as f:
                    orders_payload = json.load(f)
                features = build_toss_order_feature_store(orders_payload, security_master=master)
                
                for s_stat in features.get("by_symbol", []):
                    if s_stat.get("symbol") == symbol:
                        pnl = s_stat.get("realized_pnl_krw", 0.0)
                        trade_count = s_stat.get("buy_count", 0) + s_stat.get("sell_count", 0)
                        win_rate = s_stat.get("win_rate_pct")
                        
                        # Calculate a memory score (0 to 100) based on historical performance
                        # Start at 80, add/subtract based on win rate and net PnL
                        base_score = 80
                        if win_rate is not None:
                            # Shift based on win rate (e.g. 50% win rate -> 0 shift)
                            base_score += (win_rate - 50.0) * 0.4
                        if pnl < 0:
                            # Penalize for losses (-10 points per 1,000,000 KRW loss)
                            base_score -= abs(pnl) / 100000.0
                        else:
                            base_score += pnl / 200000.0
                            
                        memory_score = int(max(10, min(100, base_score)))
                        break
            except Exception:
                pass

        # Risk level determination
        m_warning = str(warnings.get("marketWarning") or "NONE").upper()
        has_risk = (m_warning != "NONE") or bool(warnings.get("administrative")) or bool(warnings.get("delistingCaution")) or bool(warnings.get("tradingSuspended"))
        
        return {
            "symbol": symbol,
            "name": sec_info.get("name") or symbol,
            "memory_score": memory_score,
            "realized_pnl_krw": round(pnl, 2),
            "trade_count": trade_count,
            "win_rate_pct": win_rate,
            "has_risk": has_risk,
            "market_warning": m_warning,
            "is_leverage": float(sec_info.get("leverage_factor") or 1.0) > 1.0
        }
