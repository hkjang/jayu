import json
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster

class TossReferenceReconciler:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)
        self.orders_file = self.project_root / "state" / "toss_orders.json"

    def reconcile(self) -> dict[str, Any]:
        """
        Reconciles symbols in order history and portfolio against the security master.
        Identifies unmapped, delisted, suspended, or currency-mismatched symbols.
        """
        master = self.security_master.get_security_master()
        
        unmapped_symbols = set()
        delisted_symbols = []
        suspended_symbols = []
        currency_mismatches = []
        stale_symbols = []
        warning_query_failures = []
        
        order_symbols = set()
        
        if self.orders_file.exists():
            try:
                with open(self.orders_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    orders = data if isinstance(data, list) else data.get("orders", [])
                    for o in orders:
                        sym = o.get("symbol")
                        if sym:
                            clean_sym = sym.strip().upper()
                            order_symbols.add(clean_sym)
                            
                            # Check currency mismatch
                            order_cur = str(o.get("currency") or "KRW").upper()
                            sec = master.get(clean_sym)
                            if sec:
                                sec_cur = str(sec.get("currency") or "KRW").upper()
                                if order_cur != sec_cur:
                                    currency_mismatches.append({
                                        "symbol": clean_sym,
                                        "order_currency": order_cur,
                                        "security_currency": sec_cur
                                    })
            except Exception:
                pass

        for sym in order_symbols:
            sec = master.get(sym)
            if not sec:
                unmapped_symbols.add(sym)
            else:
                warnings = sec.get("warnings") or {}
                if "marketWarning" not in warnings:
                    warning_query_failures.append(sym)
                if warnings.get("tradingSuspended"):
                    suspended_symbols.append({
                        "symbol": sym,
                        "name": sec.get("name") or sym
                    })
                if sec.get("is_tradable") is False and not warnings.get("tradingSuspended"):
                    delisted_symbols.append({
                        "symbol": sym,
                        "name": sec.get("name") or sym
                    })

        total_checked = len(order_symbols)
        unmapped_count = len(unmapped_symbols)
        delisted_count = len(delisted_symbols)
        suspended_count = len(suspended_symbols)
        
        # Calculate reconciliation score
        penalty = (unmapped_count * 10) + (delisted_count * 5) + (suspended_count * 2)
        max_penalty = total_checked * 10 if total_checked > 0 else 100
        score = int((1.0 - (min(penalty, max_penalty) / max_penalty)) * 100) if max_penalty > 0 else 100

        return {
            "score": max(0, score),
            "total_order_symbols_checked": total_checked,
            "unmapped_symbols": sorted(list(unmapped_symbols)),
            "delisted_symbols": delisted_symbols,
            "suspended_symbols": suspended_symbols,
            "currency_mismatches": currency_mismatches,
            "warning_query_failures": warning_query_failures,
            "stale_symbols": stale_symbols
        }
