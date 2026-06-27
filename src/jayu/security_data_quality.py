import time
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster

class SecurityDataQuality:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)

    def check_quality(self) -> dict[str, Any]:
        """
        Evaluates the completeness and freshness of the cached security master data.
        Returns a data quality report and trust score.
        """
        cache = self.security_master.load_cache()
        symbols = self.security_master.get_all_symbols_from_user_data()
        
        # Add fallbacks
        fallbacks = ["AAPL", "TSLA", "MSFT", "005930", "SCHD", "O", "JEPI", "TQQQ", "SOXL", "NVDA", "VOO", "JEPQ", "ROBO"]
        for f in fallbacks:
            symbols.add(f)
            
        total_symbols = len(symbols)
        if total_symbols == 0:
            return {
                "score": 100,
                "total_securities_checked": 0,
                "missing_fields_count": 0,
                "stale_securities_count": 0,
                "anomalies": []
            }

        anomalies = []
        missing_fields_count = 0
        stale_securities_count = 0
        now = time.time()

        for sym in symbols:
            info = cache.get(sym)
            if not info:
                anomalies.append({
                    "symbol": sym,
                    "field": "all",
                    "issue": "종목 정보 캐시 누락 (미매핑)"
                })
                missing_fields_count += 5
                continue

            # Check required fields
            required = ["symbol", "name", "market", "currency", "security_type"]
            for field in required:
                if not info.get(field) or info.get(field) == "UNKNOWN":
                    anomalies.append({
                        "symbol": sym,
                        "field": field,
                        "issue": f"필수 정보 누락 또는 미지정: {field}"
                    })
                    missing_fields_count += 1

            # Check warnings query freshness/existence
            warnings = info.get("warnings") or {}
            if not warnings or "marketWarning" not in warnings:
                anomalies.append({
                    "symbol": sym,
                    "field": "warnings",
                    "issue": "경고 정보 조회 실패 또는 누락"
                })
                missing_fields_count += 1

            # Check freshness
            updated_at = info.get("updated_at", 0)
            if (now - updated_at) > 86400 * 3:  # Older than 3 days
                anomalies.append({
                    "symbol": sym,
                    "field": "updated_at",
                    "issue": f"기준정보 업데이트 지연 (마지막 업데이트: {time.strftime('%Y-%m-%d', time.localtime(updated_at))})"
                })
                stale_securities_count += 1

        # Calculate trust score
        max_penalty = total_symbols * 5
        penalty = min(missing_fields_count + (stale_securities_count * 0.5), max_penalty)
        score = int((1.0 - (penalty / max_penalty)) * 100) if max_penalty > 0 else 100

        return {
            "score": max(0, score),
            "total_securities_checked": total_symbols,
            "missing_fields_count": missing_fields_count,
            "stale_securities_count": stale_securities_count,
            "anomalies": anomalies
        }
