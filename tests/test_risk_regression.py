"""test_risk_regression.py — 리스크 룰 회귀 검증 테스트 세트.

각 리스크 룰 코드별 입력 Fixture와 기대되는 통과/차단 판결(Verdict) 결과가 일치하는지 검증하여
리스크 규칙 변경 시 발생할 수 있는 회귀 버그를 잡아냅니다.
"""

from __future__ import annotations

import pytest
from typing import Any

from jayu.risk import (
    evaluate_signal_risk,
    apply_portfolio_risk,
    apply_data_trust,
    risk_explanation,
)
from jayu.settings import RiskSettings


@pytest.fixture
def signals_risk_fixture() -> dict[str, dict[str, Any]]:
    """각 리스크 규칙별 입력 조건 및 예상 결과를 정의하는 Fixture.
    
    UNMAPPED_TICKER 경고를 피하기 위해 포트폴리오 매핑(portfolio_mapping.json)에 존재하는
    실제 티커(TSLA, NVDA, SOXL)들을 활용합니다.
    """
    return {
        # 1. 포지션 한도 초과 규칙
        "single_position_limit": {
            "ticker": "TSLA",
            "suggested_position_pct": 0.15,  # 한도(10%) 초과
            "portfolio": {
                "adjusted_gross_exposure": 0.0,
                "leveraged_etf_value_pct": 0.0,
                "underlying_exposure_pct": {},
                "sector_exposure_pct": {},
                "factor_exposure_pct": {},
                "positions": [],
            },
            "settings": RiskSettings(max_single_position_pct=0.10),
            "expected_verdict": "blocked",
            "expected_code": "SINGLE_POSITION_EXCEEDED",
        },
        # 2. 섹터 노출 초과 규칙 (NVDA의 섹터는 semiconductors)
        "sector_exposure_limit": {
            "ticker": "NVDA",
            "suggested_position_pct": 0.05,
            "portfolio": {
                "adjusted_gross_exposure": 0.0,
                "leveraged_etf_value_pct": 0.0,
                "underlying_exposure_pct": {},
                "sector_exposure_pct": {"semiconductors": 0.55},  # 한도(50%) 초과
                "factor_exposure_pct": {},
                "positions": [],
            },
            "settings": RiskSettings(max_sector_exposure=0.50),
            "expected_verdict": "blocked",
            "expected_code": "SECTOR_EXPOSURE_EXCEEDED",
        },
        # 3. 레버리지 ETF 한도 초과 규칙 (SOXL은 3X 레버리지)
        "leveraged_etf_limit": {
            "ticker": "SOXL",
            "suggested_position_pct": 0.05,
            "portfolio": {
                "adjusted_gross_exposure": 0.0,
                "leveraged_etf_value_pct": 0.35,  # 한도(30%) 초과
                "underlying_exposure_pct": {},
                "sector_exposure_pct": {},
                "factor_exposure_pct": {},
                "positions": [],
            },
            "settings": RiskSettings(max_leveraged_etf_value=0.30),
            "expected_verdict": "blocked",
            "expected_code": "LEVERAGED_ETF_VALUE_EXCEEDED",
        },
        # 4. 일간 손실 한도 초과 규칙
        "daily_loss_limit": {
            "ticker": "TSLA",
            "suggested_position_pct": 0.05,
            "portfolio": {
                "adjusted_gross_exposure": 0.0,
                "leveraged_etf_value_pct": 0.0,
                "underlying_exposure_pct": {},
                "sector_exposure_pct": {},
                "factor_exposure_pct": {},
                "positions": [],
                "risk_status": {"daily_return": -0.04},  # 한도(-3%) 초과 손실
            },
            "settings": RiskSettings(daily_loss_limit=0.03),
            "expected_verdict": "blocked",
            "expected_code": "DAILY_LOSS_LIMIT_BREACHED",
        },
        # 5. 매핑되지 않은 종목 규칙
        "unmapped_ticker": {
            "ticker": "ZZZZ",  # 매핑 사전에 없는 티커
            "suggested_position_pct": 0.05,
            "portfolio": {
                "adjusted_gross_exposure": 0.0,
                "leveraged_etf_value_pct": 0.0,
                "underlying_exposure_pct": {},
                "sector_exposure_pct": {},
                "factor_exposure_pct": {},
                "positions": [],
            },
            "settings": RiskSettings(block_unmapped_tickers=True),
            "expected_verdict": "blocked",
            "expected_code": "UNMAPPED_TICKER",
        },
        # 6. 정상 통과(Pass) 규칙
        "normal_pass": {
            "ticker": "NVDA",
            "suggested_position_pct": 0.05,
            "portfolio": {
                "adjusted_gross_exposure": 0.20,
                "leveraged_etf_value_pct": 0.0,
                "underlying_exposure_pct": {"nvidia": 0.10},
                "sector_exposure_pct": {"semiconductors": 0.10},
                "factor_exposure_pct": {},
                "positions": [],
            },
            "settings": RiskSettings(max_single_position_pct=0.10, max_sector_exposure=0.50),
            "expected_verdict": "pass",
            "expected_code": None,
        },
    }


def test_portfolio_risk_rule_regression(signals_risk_fixture):
    """Fixture 데이터셋을 활용해 개별 포트폴리오 리스크 규칙들의 작동 상태를 회귀 검증한다."""
    for rule_name, case in signals_risk_fixture.items():
        ticker = case["ticker"]
        suggested = case["suggested_position_pct"]
        portfolio = case["portfolio"]
        settings = case["settings"]
        expected_verdict = case["expected_verdict"]
        expected_code = case["expected_code"]

        decision = evaluate_signal_risk(ticker, suggested, portfolio, settings)

        if expected_verdict == "blocked":
            assert not decision.eligible, f"Rule '{rule_name}' should have blocked the signal."
            assert decision.violations, f"Rule '{rule_name}' should have recorded violations."
            
            # 상세 위반 코드 검사
            violation_codes = {detail["code"] for detail in decision.violation_details}
            assert expected_code in violation_codes, f"Expected violation code '{expected_code}' in rule '{rule_name}', got {violation_codes}."
        else:
            assert decision.eligible, f"Rule '{rule_name}' should have passed the signal."
            assert not decision.violations, f"Rule '{rule_name}' should have no violations."


def test_data_trust_risk_rule_regression():
    """데이터 신뢰성 관련 차단 규칙들(가격 미검증, 참조 데이터 불일치, 제공자 불일치)을 회귀 검증한다."""
    signals = {
        "TEST_OK": {
            "signal": "entry",
            "action": "buy",
            "eligible": True,
            "approved_position_pct": 0.1,
            "risk": {},
        },
        "TEST_UNVERIFIED": {
            "signal": "entry",
            "action": "buy",
            "eligible": True,
            "approved_position_pct": 0.1,
            "risk": {},
        },
        "TEST_CONFLICT": {
            "signal": "entry",
            "action": "buy",
            "eligible": True,
            "approved_position_pct": 0.1,
            "risk": {},
        },
        "TEST_DISAGREEMENT": {
            "signal": "entry",
            "action": "buy",
            "eligible": True,
            "approved_position_pct": 0.1,
            "risk": {},
        },
        "TEST_HOLD_NOT_EVALUATED": {
            "signal": "wait",
            "action": "hold",
            "eligible": False,
            "approved_position_pct": 0.0,
            "risk": {},
        }
    }

    price_trust = {
        "TEST_OK": {"verified": True},
        "TEST_UNVERIFIED": {"verified": False},
        "TEST_CONFLICT": {"verified": True},
        "TEST_DISAGREEMENT": {"verified": True, "provider_disagreements": [{"field": "Close", "diff": 1.5}]},
    }
    
    reference_audits = {
        "TEST_CONFLICT": {"status": "conflict"},
    }

    result = apply_data_trust(
        signals=signals,
        price_trust=price_trust,
        reference_audits=reference_audits,
        event_notes={},
        require_verified_price=True,
        reference_conflict_policy="block",
    )

    # 1. 정상 데이터 검증 통과 (pass)
    assert result["TEST_OK"]["eligible"] is True

    # 2. 가격 데이터 미검증으로 차단 (blocked - UNVERIFIED_PRICE_DATA)
    assert result["TEST_UNVERIFIED"]["eligible"] is False
    unverified_codes = {detail["code"] for detail in result["TEST_UNVERIFIED"]["risk"]["violation_details"]}
    assert "UNVERIFIED_PRICE_DATA" in unverified_codes

    # 3. 참조 데이터 정합성 실패로 차단 (blocked - REFERENCE_DATA_CONFLICT)
    assert result["TEST_CONFLICT"]["eligible"] is False
    conflict_codes = {detail["code"] for detail in result["TEST_CONFLICT"]["risk"]["violation_details"]}
    assert "REFERENCE_DATA_CONFLICT" in conflict_codes

    # 4. 제공자 간 데이터 불일치로 차단 (blocked - DATA_DISAGREEMENT)
    assert result["TEST_DISAGREEMENT"]["eligible"] is False
    disagree_codes = {detail["code"] for detail in result["TEST_DISAGREEMENT"]["risk"]["violation_details"]}
    assert "DATA_DISAGREEMENT" in disagree_codes

    # 5. 매매 신호가 아닌 종목 (not_evaluated - 관망/대기 상태이므로 리스크 검사 대상 제외)
    assert result["TEST_HOLD_NOT_EVALUATED"]["eligible"] is False
    # violation_details 리스트가 비어있거나 혹은 존재하지 않는지 검사
    assert not result["TEST_HOLD_NOT_EVALUATED"]["risk"].get("violation_details")


def test_risk_explanation_summary_regression():
    """risk_explanation 요약 보고서가 신호들의 승인/차단 상태 및 탑 블로커를 올바르게 점수화하고 요약하는지 검증한다."""
    signals_input = {
        "TSLA": {
            "signal": "entry",
            "action": "buy",
            "eligible": False,
            "risk": {
                "violation_details": [
                    {"code": "DAILY_LOSS_LIMIT_BREACHED", "message": "일간 손실 초과"}
                ]
            }
        },
        "SOXL": {
            "signal": "entry",
            "action": "buy",
            "eligible": False,
            "risk": {
                "violation_details": [
                    {"code": "LEVERAGED_ETF_LIMIT_EXCEEDED", "message": "레버리지 한도 초과"},
                    {"code": "DAILY_LOSS_LIMIT_BREACHED", "message": "일간 손실 초과"}
                ]
            }
        },
        "AAPL": {
            "signal": "entry",
            "action": "buy",
            "eligible": True,
            "risk": {
                "pass_details": [
                    {"metric": "single_position_pct", "observed": 0.05, "limit": 0.10}
                ]
            }
        },
        "MSFT": {
            "signal": "wait",
            "action": "hold",
            "eligible": False,
            "risk": {}
        }
    }

    explanation = risk_explanation(signals_input)

    # 기본 수치 요약 검증
    assert explanation["approved_count"] == 1  # AAPL
    assert explanation["blocked_count"] == 2   # TSLA, SOXL
    assert explanation["hold_count"] == 1      # MSFT

    # 탑 블로커 리스트 검증
    top_blockers = {item["code"]: item["count"] for item in explanation["top_block_reasons"]}
    assert top_blockers.get("DAILY_LOSS_LIMIT_BREACHED") == 2
    assert top_blockers.get("LEVERAGED_ETF_LIMIT_EXCEEDED") == 1
