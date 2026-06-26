"""rule_violation_audit.py — 플레이북 투자 규칙 및 가드 위반 내역 감사 기록 및 관리 모듈.

발생한 모든 플레이북 차단/경고, 행동 위험 경고, 비용 민감도 초과 사항을 
'state/playbook_violations.jsonl' 파일에 로깅하고 대시보드 화면에 제공한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("jayu.rule_violation_audit")

DEFAULT_VIOLATIONS_FILE = Path("state/playbook_violations.jsonl")

def log_playbook_violation(
    ticker: str,
    portfolio_type: str,
    rule_id: str,
    rule_name: str,
    action: str,
    reason_ko: str,
    file_path: Path | None = None
) -> None:
    """규칙 위반 사항을 jsonl 로그 파일에 안전하게 누적 기록한다."""
    path = file_path or DEFAULT_VIOLATIONS_FILE
    
    # 디렉토리 자동 생성
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"감사 로그 디렉토리 생성 실패: {e}")
        return

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.upper(),
        "portfolio_type": portfolio_type,
        "rule_id": rule_id,
        "rule_name": rule_name,
        "action": action,
        "reason_ko": reason_ko
    }

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.info(f"규칙 위반 감사 기록 완료: {ticker} - {rule_id}")
    except Exception as e:
        logger.error(f"감사 로그 쓰기 실패: {e}")

def get_violation_logs(file_path: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """과거 발생한 규칙 위반 감사 로그를 역순(최신순)으로 읽어온다."""
    path = file_path or DEFAULT_VIOLATIONS_FILE
    if not path.exists():
        return []

    logs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        logs.append(json.loads(line))
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"감사 로그 읽기 실패: {e}")

    # 최신 위반 내역이 먼저 오도록 역순 정렬 후 제한 개수만큼 반환
    logs.reverse()
    return logs[:limit]

def clear_violation_logs(file_path: Path | None = None) -> None:
    """감사 로그 파일을 비운다. (관리자 초기화용)"""
    path = file_path or DEFAULT_VIOLATIONS_FILE
    if path.exists():
        try:
            path.unlink()
            logger.info("감사 로그 파일이 성공적으로 삭제되었습니다.")
        except Exception as e:
            logger.error(f"감사 로그 파일 삭제 실패: {e}")
            raise
