"""test_decision_os.py — 한국어 투자 판단 OS 신규 모듈들에 대한 단위 테스트."""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

# 신규 모듈 임포트
from src.jayu.market_regime_router import determine_market_regime, REGIME_WEIGHTS
from src.jayu.playbook_engine import evaluate_playbook
from src.jayu.strategy_governance import check_strategy_approval
from src.jayu.behavior_guard import check_behavioral_risk
from src.jayu.cost_sensitivity_guard import evaluate_cost_sensitivity
from src.jayu.strategy_retirement_candidates import generate_retirement_report
from src.jayu.rule_violation_audit import log_playbook_violation, get_violation_logs, clear_violation_logs

class TestDecisionOS(unittest.TestCase):
    
    def test_market_regime_router(self):
        """시장 국면 라우터 판정이 예외 없이 실행되고 유효한 국면과 가중치를 반환하는지 테스트."""
        regime_res = determine_market_regime()
        self.assertIn("regime", regime_res)
        self.assertIn("description", regime_res)
        self.assertIn("weights", regime_res)
        self.assertIn("metrics", regime_res)
        
        regime = regime_res["regime"]
        self.assertIn(regime, REGIME_WEIGHTS)
        self.assertEqual(regime_res["weights"], REGIME_WEIGHTS[regime])

    def test_playbook_engine_evaluation(self):
        """투자 플레이북 규칙 평가 엔진이 조건에 부합하는 규칙을 올바르게 트리거하는지 테스트."""
        # A. 데이터 불일치 상황 테스트 (매수 차단)
        context_dq = {"data_quality": "disagreement", "portfolio_type": "short_term"}
        res_dq = evaluate_playbook(context_dq)
        self.assertFalse(res_dq["allow_buy"])
        self.assertEqual(res_dq["action"], "block_buy")
        self.assertTrue(any(r["id"] == "RULE_DATA_DISAGREEMENT" for r in res_dq["triggered_rules"]))
        
        # B. 하락장 레버리지 ETF 단타 상황 테스트 (매수 차단)
        context_bear_lev = {"regime": "bear", "portfolio_type": "short_term", "is_leveraged": True}
        res_bear_lev = evaluate_playbook(context_bear_lev)
        self.assertFalse(res_bear_lev["allow_buy"])
        self.assertEqual(res_bear_lev["action"], "block_buy")
        self.assertTrue(any(r["id"] == "RULE_BEAR_LEVERAGE_LIMIT" for r in res_bear_lev["triggered_rules"]))

        # C. 정상 상승장 단타 상황 테스트 (모두 허용)
        context_ok = {"regime": "bull", "portfolio_type": "short_term", "is_leveraged": False, "consecutive_losses": 0}
        res_ok = evaluate_playbook(context_ok)
        self.assertTrue(res_ok["allow_buy"])
        self.assertEqual(res_ok["action"], "allow")
        self.assertEqual(len(res_ok["triggered_rules"]), 0)

    def test_strategy_governance(self):
        """전략 지배 구조에 따른전략 작동 승인/비승인 로직 테스트."""
        # 승인된 전략의 허용 국면 검사
        res_approved = check_strategy_approval("ensemble", "swing", "bull")
        self.assertTrue(res_approved["approved"])
        self.assertIsNone(res_approved["reason_ko"])
        
        # 비활성화된 전략 검사 (volume_breakout)
        res_inactive = check_strategy_approval("volume_breakout", "short_term", "bull")
        self.assertFalse(res_inactive["approved"])
        self.assertIn("최근 2개월 간의 백테스트 결과", res_inactive["reason_ko"])

        # 허용되지 않는 시장 국면 검사 (connors_rsi2는 bear 국면에서 허용 안 됨)
        res_regime_block = check_strategy_approval("connors_rsi2", "short_term", "bear")
        self.assertFalse(res_regime_block["approved"])
        self.assertIn("시장 국면 조건 미충족", res_regime_block["reason_ko"])

    def test_behavior_guard(self):
        """사용자 투자 심리 및 행동 위험 경고 감지 테스트."""
        # A. 단일 종목 과다 비중 경고 테스트
        warns_concentration = check_behavioral_risk("TSLA", {}, "long_term", current_exposure_pct=0.18)
        self.assertTrue(any("단일 종목 집중 경고" in w for w in warns_concentration))

        # B. 손절 후 뇌동 매매 경고 테스트
        warns_stoploss = check_behavioral_risk("IONQ", {}, "short_term", is_below_prev_stop_loss=True)
        self.assertTrue(any("손절 기준 무시" in w for w in warns_stoploss))

        # C. 연속 손실 후 쿨다운 권장 테스트
        warns_losses = check_behavioral_risk("SOXL", {}, "short_term", consecutive_losses=3)
        self.assertTrue(any("뇌동매매나 손실 복구 심리" in w for w in warns_losses))

    def test_cost_sensitivity_guard(self):
        """거래 비용 민감도 및 가중치 강등 조치 테스트."""
        # 기대수익 대비 비용 비율이 높아 강등 경고가 발생하는 케이스 (미국 주식 잦은 거래 비용 부담)
        res_high = evaluate_cost_sensitivity("SOXL", expected_return_pct=1.2, portfolio_type="short_term")
        self.assertTrue(res_high["priority_downgrade"])
        self.assertIsNotNone(res_high["warning_msg"])
        self.assertIn("거래 비용 부담 과다", res_high["warning_msg"])

        # 기대수익률이 높아 제비용 부담이 미미한 케이스
        res_low = evaluate_cost_sensitivity("005930.KS", expected_return_pct=8.0, portfolio_type="swing")
        self.assertFalse(res_low["priority_downgrade"])
        # 단순 주의 정도만 반환하거나 warning_msg가 None/비비용과다 수준이어야 함
        if res_low["warning_msg"]:
            self.assertNotIn("거래 비용 부담 과다", res_low["warning_msg"])

    def test_strategy_retirement_candidates(self):
        """성과가 악화된 전략 폐기 후보 자동 분류 테스트."""
        report = generate_retirement_report()
        self.assertIn("candidates", report)
        self.assertGreater(report["candidate_count"], 0)
        
        # connors_rsi2와 volume_breakout은 폐기 후보군에 포함되어야 함
        candidate_ids = [c["id"] for c in report["candidates"]]
        self.assertIn("connors_rsi2", candidate_ids)
        self.assertIn("volume_breakout", candidate_ids)

    def test_rule_violation_audit(self):
        """규칙 위반 이력에 대한 로깅 및 로드 감사 추적 기능 테스트."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "violations.jsonl"
            
            # 위반 로그 기록
            log_playbook_violation(
                ticker="SOXL",
                portfolio_type="short_term",
                rule_id="RULE_SHORT_TERM_COOLDOWN",
                rule_name="단타 연속 손실 시 쿨다운",
                action="cooldown",
                reason_ko="단타 연속 손실 3회 발생으로 냉각 기간 작동",
                file_path=log_file
            )
            
            # 로그 읽어오기
            logs = get_violation_logs(file_path=log_file)
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["ticker"], "SOXL")
            self.assertEqual(logs[0]["rule_id"], "RULE_SHORT_TERM_COOLDOWN")
            
            # 로그 청소
            clear_violation_logs(file_path=log_file)
            self.assertFalse(log_file.exists())

if __name__ == "__main__":
    unittest.main()
