from typing import Any
from pathlib import Path
from .toss_security_master import TossSecurityMaster
from .security_risk_profile import SecurityRiskProfiler
from .toss_order_feature_store import build_toss_order_feature_store

class AutotradeSecurityGuard:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)

    def evaluate_order(self, symbol: str, proposed_amount_krw: float, orders_payload: Any = None) -> dict[str, Any]:
        """
        Evaluates whether an automated order should be allowed, scaled down, or blocked.
        Returns:
            {
                "symbol": str,
                "verdict": "allow" | "reduce" | "block",
                "proposed_amount": float,
                "allowed_amount": float,
                "reasons": list[str]
            }
        """
        symbol = symbol.strip().upper()
        master_data = self.security_master.get_security_master()
        sec_info = master_data.get(symbol)
        
        reasons = []
        verdict = "allow"
        scale_factor = 1.0

        if not sec_info:
            # Unknown symbol, apply caution
            verdict = "reduce"
            scale_factor = 0.5
            reasons.append("Toss 종목 정보에 없음 (신규/미조회 종목)")
            risk_profile = {"grade": "caution", "autotrade_allowed": True}
        else:
            # 1. Risk Profile check
            risk_profile = SecurityRiskProfiler.evaluate_risk(sec_info)
            if not risk_profile["autotrade_allowed"] or risk_profile["grade"] == "blocked":
                verdict = "block"
                scale_factor = 0.0
                reasons.extend(risk_profile["reasons"])
            elif risk_profile["grade"] == "high_risk":
                verdict = "reduce"
                scale_factor = min(scale_factor, 0.3)  # Reduce to 30% for high risk
                reasons.extend(risk_profile["reasons"])
            elif risk_profile["grade"] == "caution":
                verdict = "reduce"
                scale_factor = min(scale_factor, 0.6)  # Reduce to 60% for caution
                reasons.extend(risk_profile["reasons"])

        # 2. Past performance check (Chronic losses)
        if verdict != "block" and orders_payload:
            try:
                features = build_toss_order_feature_store(orders_payload)
                # Find performance for this symbol
                symbol_stats = {}
                for s_stat in features.get("by_symbol", {}).values():
                    if s_stat.get("symbol") == symbol:
                        symbol_stats = s_stat
                        break
                
                if symbol_stats:
                    trades_count = symbol_stats.get("buy_count", 0) + symbol_stats.get("sell_count", 0)
                    net_pnl = symbol_stats.get("realized_pnl_krw", 0.0)
                    
                    # If we have at least 3 trades and a net loss
                    if trades_count >= 3 and net_pnl < -100000:  # Loss over 100k KRW
                        # Further scale down or block if extreme
                        if net_pnl < -1000000:  # Loss over 1M KRW
                            verdict = "block"
                            scale_factor = 0.0
                            reasons.append(f"과거 누적 손실 극심 ({net_pnl:,.0f} KRW)")
                        else:
                            verdict = "reduce"
                            scale_factor = min(scale_factor, 0.5)
                            reasons.append(f"과거 만성 손실 종목 (누적 {net_pnl:,.0f} KRW)")
            except Exception:
                pass

        allowed_amount = round(proposed_amount_krw * scale_factor, 2)
        if scale_factor == 0.0:
            verdict = "block"
        elif scale_factor < 1.0:
            verdict = "reduce"

        return {
            "symbol": symbol,
            "verdict": verdict,
            "proposed_amount": proposed_amount_krw,
            "allowed_amount": allowed_amount,
            "reasons": reasons,
            "risk_grade": risk_profile.get("grade", "normal")
        }
