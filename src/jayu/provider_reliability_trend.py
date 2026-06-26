from __future__ import annotations

from pathlib import Path
from typing import Any
from jayu.paths import RuntimePaths
from jayu.io import read_json

def calculate_provider_trends(paths: RuntimePaths, limit: int = 10) -> dict[str, Any]:
    """최근 N개의 실행을 분석하여 데이터 제공자(Provider)별 수집 성공률, 실패율, 불일치 횟수, 차단 종목 수 추세를 분석합니다."""
    if not paths.runs_dir.exists():
        return {"limit": limit, "runs_analyzed": 0, "providers": {}}
        
    # 실행 디렉토리 목록 조회 및 정렬 (최신 순)
    dirs = sorted(
        [d for d in paths.runs_dir.iterdir() if d.is_dir() and d.name.startswith("run-")],
        key=lambda x: x.name,
        reverse=True
    )[:limit]
    
    if not dirs:
        return {"limit": limit, "runs_analyzed": 0, "providers": {}}
        
    providers_data: dict[str, dict[str, Any]] = {}
    
    for run_dir in dirs:
        # 1. 데이터 소스 분석
        dq = read_json(run_dir / "data_sources.json", default={})
        sources = dq.get("sources", [])
        
        # 2. 불일치 분석
        disagree = read_json(run_dir / "provider_disagreement_report.json", default={})
        disagreements = disagree.get("disagreements", [])
        disagree_tickers = {item.get("ticker") for item in disagreements if item.get("ticker")}
        
        # 3. 리스크/차단 상태 분석
        verdict = read_json(run_dir / "safety_verdict.json", default={})
        blocked_tickers_overall = []
        
        # 만약 DATA_DISAGREEMENT 등이 있으면 이 런의 종목들을 불일치로 차단되었다고 볼 수 있음
        risk = read_json(run_dir / "risk_explanation.json", default={})
        for sig in risk.get("signals", []):
            if sig.get("action") == "buy" and sig.get("eligible") is not True:
                ticker = sig.get("ticker")
                if ticker:
                    blocked_tickers_overall.append(ticker)
                    
        # 제공자별 통계 집계
        for src in sources:
            name = src.get("provider")
            if not name:
                continue
                
            ticker = src.get("ticker")
            status = src.get("status")
            
            if name not in providers_data:
                providers_data[name] = {
                    "success": 0,
                    "failure": 0,
                    "disagreements": 0,
                    "blocked_tickers": set(),
                }
                
            # 성공/실패 카운트
            if status == "success":
                providers_data[name]["success"] += 1
            else:
                providers_data[name]["failure"] += 1
                
            # 불일치 여부 검사
            if ticker in disagree_tickers:
                providers_data[name]["disagreements"] += 1
                
            # 차단 종목 여부 검사
            if ticker in blocked_tickers_overall:
                providers_data[name]["blocked_tickers"].add(ticker)
                
    # 최종 요약 결과 생성
    formatted_providers = {}
    for name, stats in providers_data.items():
        success = stats["success"]
        failure = stats["failure"]
        total = success + failure
        
        success_rate = round((success / total) * 100, 1) if total else 0.0
        failure_rate = round((failure / total) * 100, 1) if total else 0.0
        
        formatted_providers[name] = {
            "provider": name,
            "total_attempts": total,
            "success_count": success,
            "failure_count": failure,
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "disagreement_count": stats["disagreements"],
            "blocked_ticker_count": len(stats["blocked_tickers"]),
            "blocked_tickers": sorted(list(stats["blocked_tickers"]))
        }
        
    return {
        "limit": limit,
        "runs_analyzed": len(dirs),
        "runs": [d.name for d in dirs],
        "providers": formatted_providers
    }
