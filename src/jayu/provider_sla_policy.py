from __future__ import annotations

import logging
from typing import Any
from datetime import datetime
from jayu.paths import RuntimePaths
from jayu.provider_reliability_trend import calculate_provider_trends

logger = logging.getLogger(__name__)

# SLA Thresholds
LATENCY_BUDGET_SEC = 2.0
FAILURE_RATE_LIMIT_PCT = 5.0
STALE_LIMIT_HOURS = 24.0

DEFAULT_SLA_POLICY = {
    "yahoo": {"latency_budget": LATENCY_BUDGET_SEC, "failure_rate_limit": FAILURE_RATE_LIMIT_PCT, "stale_limit": STALE_LIMIT_HOURS, "priority": 1},
    "tiingo": {"latency_budget": LATENCY_BUDGET_SEC, "failure_rate_limit": FAILURE_RATE_LIMIT_PCT, "stale_limit": STALE_LIMIT_HOURS, "priority": 2},
    "massive": {"latency_budget": LATENCY_BUDGET_SEC, "failure_rate_limit": FAILURE_RATE_LIMIT_PCT, "stale_limit": STALE_LIMIT_HOURS, "priority": 3}
}

def evaluate_provider_sla(paths: RuntimePaths, limit: int = 10) -> dict[str, Any]:
    """최근 N회 실행의 데이터 제공자 신뢰도 추세를 기반으로 SLA 위반 여부와 순위를 분석합니다."""
    # We can reuse the provider reliability trend
    trends = calculate_provider_trends(paths, limit=limit)
    providers = trends.get("providers", {})
    
    sla_report: dict[str, Any] = {
        "evaluated_at": datetime.now().isoformat(),
        "runs_analyzed": trends.get("runs_analyzed", 0),
        "sla_compliant": True,
        "providers": {}
    }
    
    for name, stats in providers.items():
        policy = DEFAULT_SLA_POLICY.get(name.lower(), {
            "latency_budget": LATENCY_BUDGET_SEC,
            "failure_rate_limit": FAILURE_RATE_LIMIT_PCT,
            "stale_limit": STALE_LIMIT_HOURS,
            "priority": 99
        })
        
        failure_rate = stats.get("failure_rate", 0.0)
        disagreements = stats.get("disagreement_count", 0)
        
        violations = []
        status = "success"
        
        # 1. Check failure rate SLA
        if failure_rate > policy["failure_rate_limit"]:
            violations.append(f"실패율 {failure_rate}% 가 허용치 {policy['failure_rate_limit']}% 를 초과했습니다.")
            status = "blocked"
            
        # 2. Check disagreement SLA (warning if too many)
        if disagreements > 3:
            violations.append(f"제공자 간 불일치 횟수 {disagreements}회가 기준치를 초과했습니다.")
            if status == "success":
                status = "warning"
                
        # Mock latency for simulation (actual latency could be added in data_sources.json in future)
        # We simulate a slight variance based on provider name
        latency = 1.1 if name.lower() == "yahoo" else (1.5 if name.lower() == "tiingo" else 1.8)
        if latency > policy["latency_budget"]:
            violations.append(f"평균 응답속도 {latency}초가 지연 예산 {policy['latency_budget']}초를 초과했습니다.")
            if status == "success":
                status = "warning"
                
        is_compliant = len(violations) == 0
        if not is_compliant and status == "blocked":
            sla_report["sla_compliant"] = False
            
        sla_report["providers"][name] = {
            "provider": name,
            "sla_compliant": is_compliant,
            "status": status,
            "priority": policy["priority"],
            "failure_rate": failure_rate,
            "latency_avg_sec": latency,
            "disagreement_count": disagreements,
            "blocked_ticker_count": stats.get("blocked_ticker_count", 0),
            "violations": violations
        }
        
    return sla_report
