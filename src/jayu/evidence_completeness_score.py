from __future__ import annotations

from pathlib import Path
from typing import Any

def calculate_completeness_score(run_dir: Path) -> dict[str, Any]:
    """실행 디렉토리 내 필수 운영 증거 파일들의 존재 여부를 검사하여 완성도 점수(0~100점)를 계산합니다."""
    if not run_dir.exists() or not run_dir.is_dir():
        return {
            "score": 0,
            "present": [],
            "missing": [
                "manifest", "data_sources", "provider_disagreement_report",
                "signals", "risk_explanation", "safety_verdict", "report"
            ],
            "total_checked": 7
        }
        
    checklist = {
        "manifest": ["manifest.json"],
        "data_sources": ["data_sources.json"],
        "provider_disagreement_report": ["provider_disagreement_report.json"],
        "signals": ["signals_risk.json"],
        "risk_explanation": ["risk_explanation.json"],
        "safety_verdict": ["safety_verdict.json"],
        "report": ["report.md", "report.html"]  # 둘 중 하나만 존재해도 성공
    }
    
    present = []
    missing = []
    
    for key, filenames in checklist.items():
        has_file = False
        for fname in filenames:
            if (run_dir / fname).exists():
                has_file = True
                break
        if has_file:
            present.append(key)
        else:
            missing.append(key)
            
    total = len(checklist)
    score = int((len(present) / total) * 100) if total else 0
    
    return {
        "score": score,
        "present": present,
        "missing": missing,
        "total_checked": total
    }
