from typing import Any
from pathlib import Path
from .toss_security_master import TossSecurityMaster

class OrderStockReconciler:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)

    def reconcile(self) -> dict[str, Any]:
        """
        Reconciles the user's order history symbols against the security master.
        Identifies unmapped, delisted, or suspended symbols.
        """
        symbols = self.security_master.get_all_symbols_from_user_data()
        master = self.security_master.get_security_master()
        
        unmapped = []
        delisted = []
        suspended = []
        mismatched_currencies = []
        
        for sym in symbols:
            sec = master.get(sym)
            if not sec:
                unmapped.append(sym)
                continue
                
            warnings = sec.get("warnings") or {}
            
            # Check delisted
            if sec.get("status") == "DELISTED" or sec.get("delistDate") is not None:
                delisted.append({
                    "symbol": sym,
                    "name": sec.get("name", sym)
                })
                
            # Check suspended
            if warnings.get("tradingSuspended"):
                suspended.append({
                    "symbol": sym,
                    "name": sec.get("name", sym)
                })

        # Calculate a reconciliation score (0 to 100)
        total = len(symbols)
        issues_count = len(unmapped) + len(delisted) + len(suspended)
        score = 100.0
        if total > 0:
            score = max(0.0, 100.0 - (issues_count / total * 100.0))

        return {
            "score": round(score, 1),
            "total_symbols": total,
            "unmapped_symbols": unmapped,
            "delisted_symbols": delisted,
            "suspended_symbols": suspended,
            "status": "healthy" if score >= 90 else "warning" if score >= 70 else "critical"
        }
