"""Generates reports on personal investment policy violations in Korean."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .personal_investment_policy import PersonalInvestmentPolicy


class PolicyViolationReporter:
    """Generates user-friendly Markdown reports on policy violations for portfolio and orders."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.policy_manager = PersonalInvestmentPolicy(self.project_root)

    def generate_report(
        self,
        signals: list[dict[str, Any]],
        holdings: list[dict[str, Any]],
        cash_krw: float,
        daily_trade_count: int = 0,
        monthly_loss_krw: float = 0.0,
        recent_losses: dict[str, int] = None,
        dividend_scores: dict[str, float] = None
    ) -> dict[str, Any]:
        """Evaluates all signals and current portfolio state, producing a markdown report."""
        compliance_results = []
        overall_compliant = True
        
        # 1. Evaluate current portfolio violations (passive violations)
        # Check leverage ratio on current state
        total_value = sum(float(h.get("value_krw") or h.get("price", 0) * h.get("quantity", 0)) for h in holdings) + cash_krw
        leverage_symbols = {"SOXL", "TQQQ", "NVDL", "FNGU", "BULZ"}
        current_leverage_value = sum(
            float(h.get("value_krw") or h.get("price", 0) * h.get("quantity", 0))
            for h in holdings if h["symbol"].upper() in leverage_symbols
        )
        current_leverage_ratio = current_leverage_value / total_value if total_value > 0 else 0.0
        max_lev = self.policy_manager.get_rule("asset_allocation", "max_leverage_ratio", 0.15)
        
        portfolio_violations = []
        if current_leverage_ratio > max_lev:
            portfolio_violations.append(
                f"보유 중인 레버리지 비중({current_leverage_ratio*100:.1f}%)이 개인 투자 원칙 허용 한도({max_lev*100:.1f}%)를 초과했습니다."
            )
            
        # Check single position ratio on current holdings
        max_single = self.policy_manager.get_rule("asset_allocation", "max_single_position_ratio", 0.25)
        for h in holdings:
            val = float(h.get("value_krw") or h.get("price", 0) * h.get("quantity", 0))
            ratio = val / total_value if total_value > 0 else 0.0
            if ratio > max_single:
                portfolio_violations.append(
                    f"종목 {h['symbol']}의 비중({ratio*100:.1f}%)이 단일 종목 한도({max_single*100:.1f}%)를 초과했습니다."
                )

        # 2. Evaluate active violations (new signals)
        for sig in signals:
            symbol = sig["symbol"]
            price = float(sig.get("price", 0))
            qty = float(sig.get("quantity") or sig.get("qty", 0))
            order_amount = price * qty
            if order_amount == 0 and sig.get("order_amount_krw"):
                order_amount = float(sig["order_amount_krw"])
                
            is_div = sig.get("is_dividend_focus") or sig.get("purpose") == "dividend"
            div_score = (dividend_scores or {}).get(symbol.upper())
            
            res = self.policy_manager.evaluate_policy_compliance(
                symbol=symbol,
                order_amount_krw=order_amount,
                holdings=holdings,
                cash_krw=cash_krw,
                daily_trade_count=daily_trade_count,
                monthly_loss_krw=monthly_loss_krw,
                recent_losses=recent_losses,
                dividend_trust_score=div_score,
                is_dividend_focus=is_div
            )
            compliance_results.append(res)
            if not res["compliant"]:
                overall_compliant = False

        # 3. Build Markdown Report
        lines = [
            "# 🛡️ 개인 투자 원칙 검증 보고서 (Personal Investment Policy Audit)",
            "",
            f"검증 일시: `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC`",
            "",
        ]
        
        # Summary Banner
        if overall_compliant and not portfolio_violations:
            lines.extend([
                "> [!NOTE]",
                "> **모든 자산 및 대기 신호가 투자 원칙을 준수하고 있습니다.** ✅",
                ""
            ])
        else:
            lines.extend([
                "> [!WARNING]",
                "> **투자 원칙 준수 위반이 감지되었습니다. 아래 세부 내역을 검토하세요.** ⚠️",
                ""
            ])

        # Current Portfolio Audit Section
        lines.extend([
            "## 1. 현재 포트폴리오 자산 배분 상태",
            f"- **전체 평가 자산**: {total_value:,.0f} 원",
            f"- **보유 현금 비중**: {cash_krw / total_value * 100.0 if total_value > 0 else 0.0:.1f}% (최소 기준: {self.policy_manager.get_rule('asset_allocation', 'min_cash_ratio', 0.10)*100:.1f}%)",
            f"- **레버리지 자산 비중**: {current_leverage_ratio * 100.0:.1f}% (최대 한도: {max_lev*100:.1f}%)",
            ""
        ])
        
        if portfolio_violations:
            lines.append("### ⚠️ 보유 자산 원칙 위반 사항")
            for pv in portfolio_violations:
                lines.append(f"- {pv}")
            lines.append("")

        # Order Signals Audit Section
        lines.append("## 2. 대기 신호 및 매수 주문 검증 결과")
        if not compliance_results:
            lines.append("검증 대상 주문 또는 신호가 존재하지 않습니다.")
        else:
            lines.extend([
                "| 종목 | 주문 금액 | 준수 여부 | 위반 사유 및 조치 가이드 |",
                "| --- | ---: | :---: | --- |"
            ])
            for res in compliance_results:
                status_emoji = "✅ 준수" if res["compliant"] else "❌ 위반"
                reason_str = ", ".join(res["violations"]) if res["violations"] else "없음"
                lines.append(
                    f"| **{res['symbol']}** | {res['metrics'].get('post_order_position_ratio', 0)*total_value:,.0f} 원 | {status_emoji} | {reason_str} |"
                )
        lines.append("")

        # Policy Rules Reference Section
        lines.extend([
            "## 3. 적용 중인 투자 가이드라인 규칙",
            "| 원칙 구분 | 규칙 항목 | 설정값 |",
            "| --- | --- | ---: |",
            f"| 자산 배분 | 최대 레버리지 허용 비중 | {max_lev*100:.1f}% |",
            f"| 자산 배분 | 최소 유지 현금 비중 | {self.policy_manager.get_rule('asset_allocation', 'min_cash_ratio', 0.10)*100:.1f}% |",
            f"| 자산 배분 | 단일 종목 최대 노출도 | {max_single*100:.1f}% |",
            f"| 매매 빈도 | 일일 최대 매매 횟수 | {self.policy_manager.get_rule('trading_restrictions', 'max_daily_trades', 5)}회 |",
            f"| 리스크 | 손절 후 동일 종목 재진입 금지 | {self.policy_manager.get_rule('trading_restrictions', 'cool_down_days_after_loss', 5)}일 |",
            f"| 리스크 | 월간 누적 최대 손실 예산 | {self.policy_manager.get_rule('trading_restrictions', 'max_monthly_loss_krw', 2000000):,.0f} 원 |",
            f"| 배당 품질 | 배당 매수 종목 최소 신뢰도 | {self.policy_manager.get_rule('dividend_quality', 'min_dividend_trust_score', 80.0):.1f}점 |",
            ""
        ])

        report_md = "\n".join(lines)
        report_path = self.project_root / "runs" / "reports" / "policy_violation_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_md, encoding="utf-8")

        return {
            "compliant": overall_compliant and not portfolio_violations,
            "violations_count": len(portfolio_violations) + sum(len(r["violations"]) for r in compliance_results),
            "markdown_path": str(report_path.relative_to(self.project_root)),
            "markdown": report_md
        }
