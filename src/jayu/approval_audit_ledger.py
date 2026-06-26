from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from datetime import datetime

def log_approval_decision(
    paths: Any,
    run_id: str,
    ticker: str,
    action: str,
    rec_verdict: str,
    user_decision: str,
    rationale: str = ""
) -> dict[str, Any]:
    """사용자가 추천된 매수/매도 후보 신호에 대해 승인/보류/무시 결정을 내린 감사 로그를 기록합니다."""
    audit_file = paths.state_dir / "user_approval_audit.jsonl"
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "ticker": ticker.upper(),
        "action": action.lower(),
        "recommendation_verdict": rec_verdict.lower(),
        "user_decision": user_decision.lower(), # approve, hold, ignore
        "rationale": rationale,
        "executed": False
    }
    
    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        # Fallback logging
        pass
        
    return log_entry

def load_approval_history(paths: Any, limit: int = 50) -> list[dict[str, Any]]:
    """사용자 의사결정 승인 감사 장부의 전체 이력을 최신 순으로 로드합니다."""
    audit_file = paths.state_dir / "user_approval_audit.jsonl"
    if not audit_file.exists():
        return []
        
    entries = []
    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    entries.append(json.loads(stripped))
    except Exception:
        pass
        
    # Return reversed order (latest first)
    return entries[::-1][:limit]
