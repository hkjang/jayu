import time
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster

class SecurityDecisionGate:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)

    def evaluate_gate(self, symbol: str) -> dict[str, Any]:
        """
        Evaluates whether a symbol passes the security decision gate.
        Returns a dictionary with 'allow' status and reasons for blocking.
        """
        symbol = symbol.strip().upper()
        master = self.security_master.get_security_master()
        sec_info = master.get(symbol)

        if not sec_info:
            return {
                "symbol": symbol,
                "allow": False,
                "reason": "종목 기준정보 부재 (Security Master 누락)",
                "category": "metadata"
            }

        # 1. Check required fields
        required = ["symbol", "name", "market", "currency", "security_type"]
        for f in required:
            if not sec_info.get(f) or sec_info.get(f) == "UNKNOWN":
                return {
                    "symbol": symbol,
                    "allow": False,
                    "reason": f"필수 메타데이터 누락 ({f})",
                    "category": "metadata"
                }

        # 2. Check warning registry / risk status
        warnings = sec_info.get("warnings") or {}
        m_warning = str(warnings.get("marketWarning") or "NONE").upper()
        admin = bool(warnings.get("administrative", False))
        delist = bool(warnings.get("delistingCaution", False))
        suspended = bool(warnings.get("tradingSuspended", False))

        if suspended:
            return {
                "symbol": symbol,
                "allow": False,
                "reason": "거래정지 종목",
                "category": "warning"
            }
        if admin:
            return {
                "symbol": symbol,
                "allow": False,
                "reason": "관리종목 지정",
                "category": "warning"
            }
        if delist:
            return {
                "symbol": symbol,
                "allow": False,
                "reason": "상장폐지 우려",
                "category": "warning"
            }
        if m_warning in {"INVESTMENT_DANGER", "DANGER"}:
            return {
                "symbol": symbol,
                "allow": False,
                "reason": "투자위험 종목 지정",
                "category": "warning"
            }

        # 3. Cache freshness
        now = time.time()
        updated_at = sec_info.get("updated_at", 0)
        if (now - updated_at) > 86400 * 7:  # Older than 7 days is considered stale block
            return {
                "symbol": symbol,
                "allow": False,
                "reason": "오래된 기준정보 캐시 (Stale Cache > 7일)",
                "category": "freshness"
            }

        return {
            "symbol": symbol,
            "allow": True,
            "reason": "의사결정 게이트 통과",
            "category": "allow"
        }
