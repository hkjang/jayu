from typing import Any

class SecurityRiskProfiler:
    @staticmethod
    def evaluate_risk(security_data: dict[str, Any]) -> dict[str, Any]:
        """
        Evaluates security master data and returns a risk profile.
        Returns:
            {
                "grade": "normal" | "caution" | "high_risk" | "blocked",
                "reasons": list[str],
                "autotrade_allowed": bool
            }
        """
        symbol = security_data.get("symbol", "UNKNOWN")
        warnings = security_data.get("warnings") or {}
        leverage = float(security_data.get("leverage_factor") or 1.0)
        sec_type = str(security_data.get("security_type") or "STOCK").upper()
        
        grade = "normal"
        reasons = []
        autotrade_allowed = True

        # 1. Blocked conditions (Delisting, trading suspension, administrative)
        if warnings.get("tradingSuspended") or not security_data.get("is_tradable", True):
            grade = "blocked"
            reasons.append("거래정지 상태 (Trading Suspended)")
            autotrade_allowed = False
        if warnings.get("administrative"):
            grade = "blocked"
            reasons.append("관리종목 지정 (Administrative)")
            autotrade_allowed = False
        if warnings.get("delistingCaution"):
            grade = "blocked"
            reasons.append("상장폐지 우려 (Delisting Caution)")
            autotrade_allowed = False

        # 2. High Risk conditions
        if grade != "blocked":
            market_warning = str(warnings.get("marketWarning") or "NONE").upper()
            if market_warning in {"INVESTMENT_WARNING", "INVESTMENT_DANGER", "DANGER", "WARNING"}:
                grade = "high_risk"
                reasons.append(f"투자경고/위험 지정 ({market_warning})")
            elif leverage >= 2.0:
                grade = "high_risk"
                reasons.append(f"{leverage}배 고레버리지 상품")
            elif sec_type == "ETN":
                grade = "high_risk"
                reasons.append("ETN 상품 (신용위험 존재)")

        # 3. Caution conditions
        if grade not in {"blocked", "high_risk"}:
            market_warning = str(warnings.get("marketWarning") or "NONE").upper()
            if market_warning == "INVESTMENT_CAUTION" or market_warning == "CAUTION":
                grade = "caution"
                reasons.append("투자주의 지정 (Investment Caution)")
            elif leverage > 1.0:
                grade = "caution"
                reasons.append(f"{leverage}배 레버리지 상품")

        if grade == "blocked":
            autotrade_allowed = False

        return {
            "symbol": symbol,
            "grade": grade,
            "reasons": reasons,
            "autotrade_allowed": autotrade_allowed
        }
