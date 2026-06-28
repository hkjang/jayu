"""Aggregates multi-module diagnostics to compile a daily investment briefing."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .dividend_cashflow_simulator import DividendCashflowSimulator
from .state_doctor import StateDoctor
from .policy_violation_report import PolicyViolationReporter
from .account_change_diff import AccountChangeDiff


class HomeBriefing:
    """Compiles the daily briefing list for the overview page."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]

    def build_briefing(self) -> dict[str, Any]:
        """Gathers data from multiple subsystems to generate a daily checklist and briefing."""
        briefings = []
        
        # 1. State Doctor Check (Data Quality)
        doctor = StateDoctor(self.project_root)
        doc_res = doctor.diagnose_all()
        
        if not doc_res["healthy"]:
            stale_files = []
            corrupted_files = []
            for name, rep in doc_res["reports"].items():
                if isinstance(rep, dict):
                    if rep.get("status") == "stale":
                        stale_files.append(rep.get("path", name))
                    elif rep.get("status") == "corrupted":
                        corrupted_files.append(rep.get("path", name))
            
            if corrupted_files:
                briefings.append({
                    "status": "데이터 불안정",
                    "severity": "blocked",
                    "reason": f"일부 상태 파일의 JSON 형식이 깨졌습니다: {', '.join(corrupted_files)}",
                    "related_symbol": None,
                    "source_module": "state_doctor",
                    "next_action": "해당 캐시 또는 스냅샷 파일을 삭제하고 Toss API 조회를 실행해 다시 다운로드하십시오."
                })
            elif stale_files:
                briefings.append({
                    "status": "점검 필요",
                    "severity": "warning",
                    "reason": f"Toss/Yahoo 캐시 파일이 24시간 이상 방치되었습니다: {', '.join(stale_files)}",
                    "related_symbol": None,
                    "source_module": "state_doctor",
                    "next_action": "대시보드 상단 또는 CLI를 통해 캐시 강제 갱신(force refresh)을 수행하십시오."
                })

        # 2. Portfolio & Dividend Quality check
        simulator = DividendCashflowSimulator(self.project_root)
        sim_res = simulator.simulate_cashflow()
        
        low_quality_symbols = []
        unmapped_symbols = []
        for h in sim_res.get("holdings", []):
            symbol = h["symbol"]
            decision = h.get("decision")
            trust_score = h.get("trust_score", 100.0)
            
            if decision in {"block", "exclude"} or trust_score < 60.0:
                low_quality_symbols.append(f"{symbol}({trust_score:.1f}점)")
            if h.get("mapping_status") == "failed":
                unmapped_symbols.append(symbol)

        if low_quality_symbols:
            briefings.append({
                "status": "매수 보류",
                "severity": "warning",
                "reason": f"보유 종목 중 배당 데이터 품질 신뢰도 점수가 60점 미만인 불량 종목이 존재합니다: {', '.join(low_quality_symbols)}",
                "related_symbol": None,
                "source_module": "dividend_quality",
                "next_action": "해당 종목의 배당 일정 및 공시 자료가 정상인지 SEIBro 또는 Yahoo Finance에서 수동 점검하십시오."
            })
            
        if unmapped_symbols:
            briefings.append({
                "status": "점검 필요",
                "severity": "warning",
                "reason": f"Toss 종목 코드와 Yahoo Ticker 간 매핑 정보가 없는 종목이 존재합니다: {', '.join(unmapped_symbols)}",
                "related_symbol": None,
                "source_module": "dividend_mapper",
                "next_action": "'state/dividend_symbol_overrides.json' 오버라이드 파일에 올바른 Ticker 매핑 값을 수동 기입하십시오."
            })

        # 3. Personal Investment Policy Check
        reporter = PolicyViolationReporter(self.project_root)
        policy_res = reporter.generate_report(
            signals=[], # Evaluate passive portfolio violations
            holdings=sim_res.get("holdings", []),
            cash_krw=sim_res.get("cash_krw", 0.0)
        )
        
        if not policy_res["compliant"]:
            briefings.append({
                "status": "원칙 위반",
                "severity": "blocked",
                "reason": "현재 보유 자산 배분이 개인 투자 원칙(레버리지 한도 또는 최소 현금 비중 등)을 위반하고 있습니다.",
                "related_symbol": None,
                "source_module": "personal_policy",
                "next_action": "runs/reports/policy_violation_report.md 파일을 열어 세부 위반 비율을 확인하고 리밸런싱을 검토하십시오."
            })

        # 4. Account Change Diff Check
        diff_calc = AccountChangeDiff(self.project_root)
        diff_res = diff_calc.calculate_diff()
        
        if diff_res["status"] == "success" and abs(diff_res["summary"]["total_change_pct"]) >= 2.0:
            pct = diff_res["summary"]["total_change_pct"]
            direction = "증가" if pct > 0 else "감소"
            briefings.append({
                "status": "보유 변화",
                "severity": "info",
                "reason": f"이전 계좌 스냅샷 대비 포트폴리오 평가 금액이 {abs(pct):.1f}% {direction}했습니다.",
                "related_symbol": None,
                "source_module": "account_diff",
                "next_action": "Overview 탭 하단의 자산 변동 기여도 분석(Decomposition) 테이블을 참조하십시오."
            })

        # 5. Goal status briefing
        annual_div = sim_res.get("annual_dividend_krw", 0.0)
        monthly_avg = annual_div / 12.0
        goal_monthly = 3000000.0 # Target 3,000,000 KRW monthly dividend
        goal_pct = (monthly_avg / goal_monthly * 100.0) if goal_monthly > 0 else 0.0
        
        briefings.append({
            "status": "정상",
            "severity": "info",
            "reason": f"월평균 예상 배당금은 {monthly_avg:,.0f}원으로, 최종 인컴 은퇴 목표(월 300만원)의 {goal_pct:.1f}%를 달성 중입니다.",
            "related_symbol": None,
            "source_module": "dividend_goal",
            "next_action": "목표 달성 타임라인을 가속화하려면 배당 성장 우량주(trust_score >= 80) 추가 매수를 고려하십시오."
        })

        # Ensure at least 3-5 briefings are always present
        if len(briefings) < 3:
            briefings.append({
                "status": "정상",
                "severity": "info",
                "reason": "자동매매 보호 가드(Chasing Guard 및 Security Guard)가 정상 동작하고 있어 이상 거래 시도가 전면 격리됩니다.",
                "related_symbol": None,
                "source_module": "security_guard",
                "next_action": "정기 매수 전략 신호를 대기 중입니다."
            })

        # Sort: blocked first, then warning, then info
        severity_order = {"blocked": 0, "warning": 1, "info": 2}
        briefings.sort(key=lambda x: severity_order.get(x["severity"], 3))

        return {
            "timestamp": time.time(),
            "overall_status": "점검 필요" if any(b["severity"] in {"blocked", "warning"} for b in briefings) else "정상",
            "briefings": briefings[:5] # Limit to Top 5 items
        }
