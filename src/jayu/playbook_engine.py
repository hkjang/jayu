"""playbook_engine.py — 선언적 투자 규칙집(playbook.json) 파싱 및 조건 평가 엔진."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("jayu.playbook_engine")

DEFAULT_PLAYBOOK_PATH = Path("configs/investment_playbook.json")

def load_playbook_rules(playbook_path: Path | None = None) -> list[dict[str, Any]]:
    """playbook JSON 파일을 로드한다. 파일이 없거나 오류 발생 시 기본 내장 규칙을 반환한다."""
    path = playbook_path or DEFAULT_PLAYBOOK_PATH
    if not path.exists():
        logger.warning(f"플레이북 파일이 존재하지 않습니다: {path}. 내장 규칙을 사용합니다.")
        return _get_builtin_rules()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("rules", [])
    except Exception as e:
        logger.error(f"플레이북 로딩 실패: {e}. 내장 규칙으로 대체합니다.")
        return _get_builtin_rules()

def _get_builtin_rules() -> list[dict[str, Any]]:
    return [
        {
            "id": "RULE_DATA_DISAGREEMENT",
            "name": "데이터 품질 불일치시 신규 매수 금지",
            "conditions": {"data_quality": "disagreement"},
            "verdict": {
                "action": "block_buy",
                "reason_ko": "데이터 공급자 간 가격 정합성 불일치가 발견되어 신규 매수를 차단합니다."
            }
        },
        {
            "id": "RULE_BEAR_LEVERAGE_LIMIT",
            "name": "하락장 레버리지 ETF 단타 제한",
            "conditions": {
                "regime": "bear",
                "portfolio_type": "short_term",
                "is_leveraged": True
            },
            "verdict": {
                "action": "block_buy",
                "reason_ko": "장기 하락세(Bear Market) 하에서 고위험 레버리지 ETF의 단타 신규 진입은 금지됩니다."
            }
        },
        {
            "id": "RULE_SHORT_TERM_COOLDOWN",
            "name": "단타 연속 손실 시 쿨다운",
            "conditions": {
                "consecutive_losses": 3,
                "portfolio_type": "short_term"
            },
            "verdict": {
                "action": "cooldown",
                "reason_ko": "단타 연속 손실 3회 발생으로 냉각 기간(Cooldown)이 작동하여 신규 진입을 대기합니다."
            }
        },
        {
            "id": "RULE_DIVIDEND_EX_DATE_IMMINENT",
            "name": "배당락 직전 무리한 진입 금지",
            "conditions": {
                "portfolio_type": "dividend",
                "days_to_ex_date_lte": 3
            },
            "verdict": {
                "action": "warn",
                "reason_ko": "배당락일이 3일 이내로 임박하여 배당락에 따른 주가 하락 위험이 크므로 신규 매수에 주의해야 합니다."
            }
        },
        {
            "id": "RULE_VOLATILE_REGIME_SHORTERM_BLOCK",
            "name": "고변동성 장세 시 단타 진입 금지",
            "conditions": {
                "regime_in": ["volatile", "risk_off"],
                "portfolio_type": "short_term"
            },
            "verdict": {
                "action": "block_buy",
                "reason_ko": "시장 변동성 급증(VIX 및 대형 지수 불안)으로 인해 단타 신규 진입을 전면 제한합니다."
            }
        }
    ]

def evaluate_playbook(context: dict[str, Any], playbook_path: Path | None = None) -> dict[str, Any]:
    """주어진 컨텍스트(시장 국면, 데이터 상태, 포트폴리오 타입 등)를 기준으로 규칙집을 평가한다.
    
    Returns:
        {
            "allow_buy": bool,
            "action": str ("allow" | "block_buy" | "cooldown" | "warn"),
            "triggered_rules": list[dict],
            "reasons_ko": list[str]
        }
    """
    rules = load_playbook_rules(playbook_path)
    triggered_rules = []
    reasons_ko = []
    
    allow_buy = True
    final_action = "allow"

    for rule in rules:
        conds = rule.get("conditions", {})
        match = True

        for key, expected in conds.items():
            val = context.get(key)

            # 특별 연산자: _lte (less than or equal)
            if key.endswith("_lte") and val is not None:
                real_key = key[:-4]
                real_val = context.get(real_key)
                if real_val is None or real_val > expected:
                    match = False
                continue

            # 특별 연산자: _in (list contains)
            if key.endswith("_in") and val is None:
                real_key = key[:-3]
                real_val = context.get(real_key)
                if real_val not in expected:
                    match = False
                continue

            # 일반 동등 비교
            if val != expected:
                match = False
                break

        if match:
            verdict = rule.get("verdict", {})
            action = verdict.get("action", "warn")
            reason_ko = verdict.get("reason_ko", "투자 규칙 위반이 감지되었습니다.")
            
            triggered_rules.append({
                "id": rule.get("id"),
                "name": rule.get("name"),
                "action": action,
                "reason_ko": reason_ko
            })
            reasons_ko.append(reason_ko)

            # 더 심각한 액션을 우선 적용: block_buy > cooldown > warn > allow
            action_hierarchy = {"block_buy": 3, "cooldown": 2, "warn": 1, "allow": 0}
            if action_hierarchy.get(action, 0) > action_hierarchy.get(final_action, 0):
                final_action = action
                if action in ("block_buy", "cooldown"):
                    allow_buy = False

    return {
        "allow_buy": allow_buy,
        "action": final_action,
        "triggered_rules": triggered_rules,
        "reasons_ko": reasons_ko
    }
