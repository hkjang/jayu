from typing import Any
from pathlib import Path
from .toss_security_master import TossSecurityMaster

class SecurityMetadataQualityChecker:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)

    def check_quality(self) -> dict[str, Any]:
        """
        Validates the completeness of cached security master data.
        Returns a trust score and list of identified anomalies.
        """
        master = self.security_master.get_security_master()
        
        anomalies = []
        total_fields_checked = 0
        missing_fields_count = 0
        
        for sym, sec in master.items():
            # Fields to check
            checks = {
                "name": sec.get("name"),
                "market": sec.get("market"),
                "currency": sec.get("currency"),
                "security_type": sec.get("security_type"),
                "warnings": sec.get("warnings"),
            }
            
            for field, val in checks.items():
                total_fields_checked += 1
                if not val or val == "UNKNOWN" or val == "NONE" and field != "warnings":
                    missing_fields_count += 1
                    anomalies.append({
                        "symbol": sym,
                        "field": field,
                        "issue": "값이 비어있거나 누락됨"
                    })
                    
            # Check warning details completeness
            warnings = sec.get("warnings") or {}
            if not warnings or "marketWarning" not in warnings:
                missing_fields_count += 1
                anomalies.append({
                    "symbol": sym,
                    "field": "warnings.marketWarning",
                    "issue": "경고 정보 조회 실패 또는 누락"
                })

        score = 100.0
        if total_fields_checked > 0:
            score = max(0.0, 100.0 - (missing_fields_count / total_fields_checked * 100.0))

        return {
            "score": round(score, 1),
            "total_securities_checked": len(master),
            "total_fields_checked": total_fields_checked,
            "missing_fields_count": missing_fields_count,
            "anomalies": anomalies[:50],  # Limit to top 50 anomalies
            "status": "healthy" if score >= 95 else "warning" if score >= 80 else "critical"
        }
