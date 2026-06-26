from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from datetime import datetime
from jayu.paths import RuntimePaths
from jayu.io import read_json
from jayu.evidence_completeness_score import calculate_completeness_score
from jayu.provider_sla_policy import evaluate_provider_sla

logger = logging.getLogger(__name__)

def calculate_ops_slo_score(paths: RuntimePaths, run_id: str = "latest") -> dict[str, Any]:
    """특정 실행(Run)의 데이터, 리스크, 증거, SLA, 건강 상태를 종합하여 0~100점의 운영 품질 점수(Ops SLO Score)를 계산합니다."""
    # 1. Resolve run directory
    run_dir = paths.runs_dir / run_id
    if run_id == "latest":
        if paths.runs_dir.exists():
            dirs = sorted(
                [d for d in paths.runs_dir.iterdir() if d.is_dir()],
                key=lambda x: x.name,
                reverse=True
            )
            if dirs:
                run_dir = dirs[0]
                run_id = run_dir.name
                
    if not run_dir.exists():
        return {
            "score": 0.0,
            "status": "blocked",
            "breakdown": {"data_quality": 0.0, "risk_gate": 0.0, "evidence_completeness": 0.0, "provider_sla": 0.0, "health": 0.0}
        }
        
    # Load manifest and files
    manifest = read_json(run_dir / "manifest.json", default={})
    safety_verdict = read_json(run_dir / "safety_verdict.json", default={})
    
    # A. Data Quality Verification Rate (30% weight)
    # Heuristic: from manifest or data_sources
    data_rate = 100.0
    dq = read_json(run_dir / "data_sources.json", default={})
    sources = dq.get("sources", [])
    if sources:
        success_sources = sum(1 for s in sources if s.get("status") == "success")
        data_rate = (success_sources / len(sources)) * 100.0
        
    # B. Risk Gate Approval Rate (25% weight)
    risk_rate = 100.0
    risk = read_json(run_dir / "signals_risk.json", default={})
    rows = risk.get("rows", [])
    if rows:
        approved = sum(1 for r in rows if r.get("status") != "blocked")
        risk_rate = (approved / len(rows)) * 100.0
        
    # C. Evidence Completeness Score (20% weight)
    comp = calculate_completeness_score(run_dir)
    evidence_score = float(comp.get("score", 0))
    
    # D. Provider SLA Compliance (15% weight)
    sla_rate = 100.0
    try:
        sla_report = evaluate_provider_sla(paths, limit=5)
        providers = sla_report.get("providers", {})
        if providers:
            compliant = sum(1 for p in providers.values() if p.get("sla_compliant"))
            sla_rate = (compliant / len(providers)) * 100.0
    except Exception:
        pass
        
    # E. Health Score (10% weight)
    health_score = float(manifest.get("health", {}).get("score", 100.0))
    
    # Weighted Sum
    total_score = (
        0.30 * data_rate +
        0.25 * risk_rate +
        0.20 * evidence_score +
        0.15 * sla_rate +
        0.10 * health_score
    )
    
    total_score = round(total_score, 1)
    
    status = "success"
    if total_score < 70.0:
        status = "blocked"
    elif total_score < 90.0:
        status = "warning"
        
    return {
        "run_id": run_id,
        "score": total_score,
        "status": status,
        "breakdown": {
            "data_quality": round(data_rate, 1),
            "risk_gate": round(risk_rate, 1),
            "evidence_completeness": round(evidence_score, 1),
            "provider_sla": round(sla_rate, 1),
            "health": round(health_score, 1)
        }
    }

def get_ops_slo_trends(paths: RuntimePaths, limit: int = 30) -> list[dict[str, Any]]:
    """최근 N회 실행을 기준으로 일자별 통합 운영 품질 점수(Ops SLO Score) 추세를 산출합니다."""
    trends = []
    if not paths.runs_dir.exists():
        return trends
        
    dirs = sorted(
        [d for d in paths.runs_dir.iterdir() if d.is_dir()],
        key=lambda x: x.name,
        reverse=True
    )[:limit]
    
    for d in reversed(dirs): # Chronological order
        score_data = calculate_ops_slo_score(paths, run_id=d.name)
        # Parse date for easy UI rendering (first 8 chars of run_id e.g. 20260626)
        date_str = d.name[:8] if len(d.name) >= 8 else "Unknown"
        trends.append({
            "run_id": d.name,
            "date": date_str,
            "score": score_data["score"],
            "status": score_data["status"]
        })
    return trends
