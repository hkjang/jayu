from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime
from jayu.paths import RuntimePaths
from jayu.io import read_json

def index_artifacts(paths: RuntimePaths) -> list[dict[str, Any]]:
    """프로젝트 내 모든 runs, signals, reports, state 산출물들을 스캔하여 인덱싱 리스트를 반환합니다."""
    artifacts = []
    
    # 1. Runs & Signals & Reports 스캔 (runs_dir 하위)
    if paths.runs_dir.exists():
        for run_dir in sorted(paths.runs_dir.iterdir(), key=lambda x: x.name, reverse=True):
            if not run_dir.is_dir() or not run_dir.name.startswith("run-"):
                continue
                
            run_id = run_dir.name
            manifest = read_json(run_dir / "manifest.json", default={})
            mode = manifest.get("execution_mode") or manifest.get("result", {}).get("mode") or "unknown"
            failure_code = manifest.get("failure_code")
            
            # 리스크 판결 파일 확인하여 failure_code 보완
            verdict = read_json(run_dir / "safety_verdict.json", default={})
            if not failure_code and verdict.get("overall") == "blocked":
                reasons = verdict.get("reasons", [])
                if reasons:
                    failure_code = reasons[0].get("code")
            
            # 이 런에 관련된 종목들 추출
            tickers = set()
            signals_data = read_json(run_dir / "signals_risk.json", default={})
            if isinstance(signals_data, dict):
                tickers.update(signals_data.keys())
                
            dq_data = read_json(run_dir / "data_sources.json", default={})
            for src in dq_data.get("sources", []):
                t = src.get("ticker")
                if t:
                    tickers.add(t)
            
            # 디렉토리 내 파일들 순회
            for item in run_dir.iterdir():
                if not item.is_file():
                    continue
                    
                fname = item.name
                # 파일 타입 분류
                if fname in ("report.html", "report.md"):
                    atype = "report"
                elif fname in ("signals_risk.json", "signals.json") or "signal" in fname:
                    atype = "signal"
                elif fname in ("manifest.json", "safety_verdict.json", "risk_explanation.json", "data_sources.json", "provider_disagreement_report.json"):
                    atype = "run"
                else:
                    atype = "run"  # 기본적으로 실행 관련 증거로 취급
                    
                mtime = datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                
                artifacts.append({
                    "name": fname,
                    "type": atype,
                    "path": str(item.resolve()),
                    "run_id": run_id,
                    "mode": mode,
                    "failure_code": failure_code,
                    "tickers": sorted(list(tickers)),
                    "size_bytes": item.stat().st_size,
                    "modified_at": mtime
                })
                
    # 2. State 스캔 (state_dir 하위)
    if paths.state_dir.exists():
        for item in paths.state_dir.iterdir():
            if not item.is_file() or item.name.startswith("."):
                continue
                
            mtime = datetime.fromtimestamp(item.stat().st_mtime).isoformat()
            artifacts.append({
                "name": item.name,
                "type": "state",
                "path": str(item.resolve()),
                "run_id": None,
                "mode": None,
                "failure_code": None,
                "tickers": [],
                "size_bytes": item.stat().st_size,
                "modified_at": mtime
            })
            
    return artifacts

def search_artifacts(
    paths: RuntimePaths,
    *,
    query: str | None = None,
    run_id: str | None = None,
    ticker: str | None = None,
    failure_code: str | None = None,
    mode: str | None = None,
    artifact_type: str | None = None
) -> list[dict[str, Any]]:
    """조건들을 적용하여 인덱싱된 산출물을 검색하고 필터링합니다."""
    items = index_artifacts(paths)
    filtered = []
    
    for item in items:
        # 1. 일반 검색 쿼리 (파일명, run_id, ticker, failure_code 내 검색)
        if query:
            q = query.lower()
            name_match = q in item["name"].lower()
            run_match = item["run_id"] and q in item["run_id"].lower()
            ticker_match = any(q in t.lower() for t in item["tickers"])
            fail_match = item["failure_code"] and q in item["failure_code"].lower()
            if not (name_match or run_match or ticker_match or fail_match):
                continue
                
        # 2. run_id 필터링
        if run_id and item["run_id"] != run_id:
            continue
            
        # 3. ticker 필터링
        if ticker and ticker not in item["tickers"]:
            continue
            
        # 4. failure_code 필터링
        if failure_code and item["failure_code"] != failure_code:
            continue
            
        # 5. 실행 모드 필터링
        if mode and item["mode"] != mode:
            continue
            
        # 6. 산출물 타입 필터링
        if artifact_type and item["type"] != artifact_type:
            continue
            
        filtered.append(item)
        
    return filtered
