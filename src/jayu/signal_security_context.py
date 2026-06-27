from typing import Any
from pathlib import Path
from .toss_security_master import TossSecurityMaster
from .security_risk_profile import SecurityRiskProfiler
from .autotrade_security_guard import AutotradeSecurityGuard

class SignalSecurityContext:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)
        self.security_guard = AutotradeSecurityGuard(self.project_root)

    def get_signal_context(self, symbol: str, orders_payload: Any = None) -> dict[str, Any]:
        """
        Retrieves the security context and risk evaluation for a trading signal.
        """
        symbol = symbol.strip().upper()
        master = self.security_master.get_security_master()
        sec_info = master.get(symbol) or {}
        
        # Risk Profile
        risk = SecurityRiskProfiler.evaluate_risk(sec_info)
        
        # Autotrade evaluation (proposed amount of 1M KRW as a test baseline)
        guard_eval = self.security_guard.evaluate_order(symbol, 1000000.0, orders_payload)
        
        return {
            "symbol": symbol,
            "name": sec_info.get("name", symbol),
            "market": sec_info.get("market", "UNKNOWN"),
            "currency": sec_info.get("currency", "KRW"),
            "security_type": sec_info.get("security_type", "STOCK"),
            "leverage_factor": sec_info.get("leverage_factor", 1.0),
            "risk_grade": risk["grade"],
            "risk_reasons": risk["reasons"],
            "autotrade_allowed": risk["autotrade_allowed"],
            "guard_verdict": guard_eval["verdict"],
            "guard_reasons": guard_eval["reasons"]
        }
