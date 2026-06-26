from __future__ import annotations

import logging
from typing import Any
from jayu.paths import RuntimePaths

logger = logging.getLogger(__name__)

ROUTINES = {
    "pre_market": {
        "id": "pre_market",
        "title": "장전 점검 (Pre-market)",
        "description": "정규장 시작 전에 데이터 상태와 필수 점검 항목을 확인합니다.",
        "tasks": [
            {"id": "data_sla", "label": "데이터 제공자(Provider) SLA 및 최신 상태 검사", "required": True},
            {"id": "risk_gate", "label": "포트폴리오 내 경고/차단 위험 종목 파악", "required": True},
            {"id": "toss_sync", "label": "Toss Securities Open API 계좌 연동 상태 대조", "required": False}
        ],
        "commands": [
            {"label": "Toss 계좌 상태 확인", "command": "jayu toss status"},
            {"label": "포트폴리오 리스크 검사", "command": "jayu portfolio check-risk"}
        ]
    },
    "intraday": {
        "id": "intraday",
        "title": "장중 감시 (Intraday)",
        "description": "실시간 거래 신호와 리스크 차단 상황을 상시 감시합니다.",
        "tasks": [
            {"id": "live_signals", "label": "실시간 발생 신호 및 우선순위 조정 결과 확인", "required": True},
            {"id": "shadow_audit", "label": "Shadow 모드 전략의 정상 실행 주기 및 상태 점검", "required": True}
        ],
        "commands": [
            {"label": "실시간 신호 조회", "command": "jayu run active-signals"}
        ]
    },
    "post_market": {
        "id": "post_market",
        "title": "장후 회고 (Post-market)",
        "description": "정규장 마감 후 거래 결과와 계좌 변동의 구체적 원인을 분석합니다.",
        "tasks": [
            {"id": "account_attrib", "label": "일일 계좌 가치 변화 원인 분해(Attribution) 보고서 확인", "required": True},
            {"id": "violation_audit", "label": "당일 발생한 플레이북 규칙 위반 감사 로그 심사", "required": True},
            {"id": "evidence_check", "label": "오늘 완료된 실행의 7대 핵심 운영 증거 파일 완성도 점수 확인", "required": True}
        ],
        "commands": [
            {"label": "일일 기여도 보고서 생성", "command": "jayu report daily --attribution"},
            {"label": "감사 장부 조회", "command": "jayu run audit-log"}
        ]
    },
    "weekly": {
        "id": "weekly",
        "title": "주간 리밸런싱 (Weekly)",
        "description": "주말 동안 전체 전략의 비중 조절 및 가중치를 조율합니다.",
        "tasks": [
            {"id": "allocation_sim", "label": "자금 배분 시뮬레이션 가중치 변경 시나리오 검토", "required": True},
            {"id": "oos_governance", "label": "전략별 OOS(Out of Sample) 최소 요건 만족 현황 평가", "required": True}
        ],
        "commands": [
            {"label": "포트폴리오 비중 리밸런싱 프리뷰", "command": "jayu portfolio rebalance --preview"}
        ]
    },
    "monthly": {
        "id": "monthly",
        "title": "월간 성과 점검 (Monthly)",
        "description": "월간 단위의 전략 수명 관리와 장기 운영 품질 동향을 검토합니다.",
        "tasks": [
            {"id": "strategy_retirement", "label": "장기 저성과 및 리스크 초과 전략의 폐기 대상 후보 심사", "required": True},
            {"id": "slo_trend", "label": "통합 운영 품질 점수(SLO) 최근 30일 추세 분석", "required": True}
        ],
        "commands": [
            {"label": "전략 폐기 대상 조회", "command": "jayu portfolio retire-candidates"}
        ]
    }
}

def get_routine_schedule(paths: RuntimePaths) -> dict[str, Any]:
    """현재 정의된 투자 루틴의 명세와 오늘 점검 완료 상태를 조회합니다."""
    # We can check the existence of today's runs to set some initial status
    # In a real environment, this might query user_approval_audit or task logs.
    today_stamp = datetime.now().strftime("%Y%m%d")
    
    # We mock or calculate completion based on files
    has_today_run = False
    if paths.runs_dir.exists():
        for item in paths.runs_dir.iterdir():
            if item.is_dir() and item.name.startswith(today_stamp):
                has_today_run = True
                break
                
    result = {}
    for key, routine in ROUTINES.items():
        r_copy = routine.copy()
        tasks = []
        for t in routine["tasks"]:
            t_copy = t.copy()
            # Simple completion heuristic
            if key == "pre_market":
                t_copy["completed"] = has_today_run
            elif key == "post_market":
                t_copy["completed"] = has_today_run and (paths.state_dir / "playbook_violations.jsonl").exists()
            else:
                t_copy["completed"] = False
            tasks.append(t_copy)
        r_copy["tasks"] = tasks
        result[key] = r_copy
        
    return {
        "routines": result,
        "has_today_run": has_today_run
    }

from datetime import datetime
