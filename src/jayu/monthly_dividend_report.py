from __future__ import annotations

from pathlib import Path
from typing import Any

from .dividend_cashflow_simulator import DividendCashflowSimulator
from .dividend_reconciliation import DividendReconciler

class MonthlyDividendReport:
    """Generates monthly dividend reports in Markdown and HTML formats."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.reports_dir = self.project_root / "runs" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.simulator = DividendCashflowSimulator(project_root)
        self.reconciler = DividendReconciler(project_root)

    def generate(self, year: int, month: int) -> dict[str, str]:
        """
        Generates the report for a specific year and month.
        """
        # Run simulation
        sim_data = self.simulator.simulate_cashflow()
        usd_krw = float(sim_data.get("usd_krw_rate") or 1350.0)
        
        # Get actual receipts and reconcile
        receipts = self.reconciler.load_actual_receipts()
        
        # Filter forecasts for this specific month
        month_str = f"{year}-{month:02d}"
        
        # Determine next month for upcoming events
        next_year = year
        next_month = month + 1
        if next_month > 12:
            next_month = 1
            next_year += 1
        next_month_str = f"{next_year}-{next_month:02d}"
        
        holdings = sim_data.get("holdings", [])
        
        reconciled_items = []
        total_expected = 0.0
        total_actual = 0.0
        
        # Find receipts in this month
        month_receipts = [r for r in receipts if r["date"].startswith(month_str)]
        
        # Resolve specific forecast for each holding in this month
        from datetime import datetime
        start_date = datetime(year, month, 1)
        
        excluded_symbols = []
        upcoming_ex_dates = []
        upcoming_pay_dates = []
        
        for h in holdings:
            symbol = h["symbol"]
            decision = h.get("decision")
            trust_score = h.get("trust_score", 0.0)
            
            # If trust score is low (< 40), it is excluded
            if decision == "exclude" or trust_score < 40.0:
                excluded_symbols.append(symbol)
                
            # Compute actual monthly forecast using forecast engine instead of /12
            expected = 0.0
            
            if decision not in {"block", "exclude"}:
                try:
                    # Resolve yahoo ticker
                    mapped = self.simulator.mapper.map_all_holdings([{"symbol": symbol}])
                    if mapped:
                        h_mapped = mapped[0]
                        yahoo_payload = self.simulator.yahoo_source.fetch_dividend_history(h_mapped["yahoo_ticker"], allow_stale=True)
                        supp = self.simulator.supplemental_source.get_supplemental_events(symbol)
                        events = self.simulator.event_master.build_and_merge_events(
                            symbol=symbol,
                            name=h_mapped["name"],
                            market=h_mapped["market"],
                            currency=h_mapped["currency"],
                            yahoo_payload=yahoo_payload,
                            supplemental_events=supp
                        )
                        quality = self.simulator.quality_gate.evaluate_symbol(symbol, events, yahoo_payload)
                        forecasts = self.simulator.forecast_engine.forecast_symbol(
                            symbol, events, quality, start_date=start_date, months_ahead=12
                        )
                        
                        # Apply tax and fx
                        holdings_by_sym = {symbol: h_mapped}
                        self.simulator.tax_fx_engine.apply_tax_and_fx(forecasts, holdings_by_sym, fx_rate=usd_krw)
                        
                        # Find matching month forecast
                        for f in forecasts:
                            if f.forecast_month == month_str:
                                expected = f.expected_amount_krw
                                break
                                
                        # Collect upcoming ex/pay dates for next month
                        for e in events:
                            if e.ex_date.startswith(next_month_str):
                                upcoming_ex_dates.append({"symbol": symbol, "date": e.ex_date, "amount": e.amount_per_share})
                            if e.pay_date and e.pay_date.startswith(next_month_str):
                                upcoming_pay_dates.append({"symbol": symbol, "date": e.pay_date, "amount": e.amount_per_share})
                except Exception:
                    # Fallback to /12 if anything fails
                    expected = h["annual_payout_krw"] / 12.0
            
            # Find actual
            actual = sum(
                _receipt_amount_krw(r, usd_krw)
                for r in month_receipts
                if r["symbol"] == symbol
            )
            
            total_expected += expected
            total_actual += actual
            
            diff = actual - expected
            status = "matched" if abs(diff) < expected * 0.05 else "amount_diff" if actual > 0 else "missing"
            
            reconciled_items.append({
                "symbol": symbol,
                "name": h["name"],
                "expected": expected,
                "actual": actual,
                "diff": diff,
                "status": status
            })
            
        sim_data["excluded_symbols"] = excluded_symbols
        sim_data["upcoming_ex_dates"] = upcoming_ex_dates
        sim_data["upcoming_pay_dates"] = upcoming_pay_dates

        # MD Generation
        md_content = self._build_markdown(year, month, sim_data, reconciled_items, total_expected, total_actual)
        html_content = self._build_html(year, month, sim_data, reconciled_items, total_expected, total_actual)

        md_path = self.reports_dir / f"dividend_report_{year}_{month:02d}.md"
        html_path = self.reports_dir / f"dividend_report_{year}_{month:02d}.html"

        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception:
            pass

        return {
            "markdown": str(md_path),
            "html": str(html_path)
        }

    def _build_markdown(
        self,
        year: int,
        month: int,
        sim_data: dict[str, Any],
        reconciled_items: list[dict[str, Any]],
        total_expected: float,
        total_actual: float
    ) -> str:
        target = sim_data["target_goal"]
        
        lines = [
            f"# {year}년 {month}월 배당 현금흐름 리포트",
            "",
            "## 1. 배당 요약",
            f"- **포트폴리오 평가 금액**: {sim_data['portfolio_value_krw']:,.0f} 원",
            f"- **연간 예상 배당금 (세전)**: {sim_data['annual_dividend_krw']:,.0f} 원",
            f"- **연간 예상 배당금 (세후)**: {sim_data['annual_net_dividend_krw']:,.0f} 원",
            f"- **평균 배당 수익률**: {sim_data['aggregate_yield_pct']}%",
            f"- **월 배당 목표 달성률**: {target['achievement_rate_pct']}% (목표: {target['monthly_target_krw']:,.0f} 원 / 현재 세후 평균: {target['current_monthly_net_krw']:,.0f} 원)",
            "",
            "## 2. 이번 달 예상 vs 실제 입금 대사",
            f"- **예상 배당금**: {total_expected:,.0f} 원",
            f"- **실제 입금액**: {total_actual:,.0f} 원",
            f"- **차액**: {total_actual - total_expected:,.0f} 원",
            "",
            "| 종목 | 종목명 | 예상 배당금 | 실제 입금액 | 차액 | 상태 |",
            "| --- | --- | --- | --- | --- | --- |"
        ]
        
        for item in reconciled_items:
            status_emoji = "✅" if item["status"] == "matched" else "⚠️" if item["status"] == "amount_diff" else "❌"
            lines.append(
                f"| {item['symbol']} | {item['name']} | {item['expected']:,.0f} 원 | {item['actual']:,.0f} 원 | {item['diff']:,.0f} 원 | {status_emoji} {item['status']} |"
            )
            
        lines.extend([
            "",
            "## 3. 보유 종목별 배당 정보",
            "| 종목 | 종목명 | 수량 | 평가 금액 | 연 배당금 | 배당률 | 데이터 신뢰도 |",
            "| --- | --- | --- | --- | --- | --- | --- |"
        ])
        
        for h in sim_data.get("holdings", []):
            lines.append(
                f"| {h['symbol']} | {h['name']} | {h['quantity']:.2f} | {h['value_krw']:,.0f} 원 | {h['annual_payout_krw']:,.0f} 원 | {h['dividend_yield']}% | {h['trust_score']}점 ({h['decision']}) |"
            )
            
        # 4. Excluded Stocks and Upcoming Events
        lines.extend([
            "",
            "## 4. 품질 및 이상 탐지 요약",
            f"- **데이터 품질 미달 제외 종목**: {', '.join(sim_data.get('excluded_symbols', [])) or '없음'}",
            "",
            "### 다음 달 배당락 예정 종목",
        ])
        
        up_ex = sim_data.get("upcoming_ex_dates", [])
        if up_ex:
            lines.append("| 종목 | 배당락일 | 주당 배당금 |")
            lines.append("| --- | --- | --- |")
            for item in up_ex:
                lines.append(f"| {item['symbol']} | {item['date']} | {item['amount']} |")
        else:
            lines.append("없음")
            
        lines.extend([
            "",
            "### 다음 달 배당 지급 예정 종목",
        ])
        
        up_pay = sim_data.get("upcoming_pay_dates", [])
        if up_pay:
            lines.append("| 종목 | 지급 예정일 | 주당 배당금 |")
            lines.append("| --- | --- | --- |")
            for item in up_pay:
                lines.append(f"| {item['symbol']} | {item['date']} | {item['amount']} |")
        else:
            lines.append("없음")

        return "\n".join(lines)

    def _build_html(
        self,
        year: int,
        month: int,
        sim_data: dict[str, Any],
        reconciled_items: list[dict[str, Any]],
        total_expected: float,
        total_actual: float
    ) -> str:
        # Simple HTML wrapper
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{year}년 {month}월 배당 리포트</title>
    <style>
        body {{ font-family: 'Malgun Gothic', sans-serif; margin: 40px; background: #121212; color: #e0e0e0; }}
        h1, h2 {{ color: #ffffff; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; border: 1px solid #333; text-align: left; }}
        th {{ background-color: #1e1e1e; }}
        tr:nth-child(even) {{ background-color: #1a1a1a; }}
        .summary {{ background: #1e1e1e; padding: 20px; border-radius: 8px; border-left: 5px solid #4caf50; }}
    </style>
</head>
<body>
    <div class="summary">
        <h1>{year}년 {month}월 배당 현금흐름 리포트</h1>
        <p>포트폴리오 평가 금액: {sim_data['portfolio_value_krw']:,.0f} 원</p>
        <p>평균 배당 수익률: {sim_data['aggregate_yield_pct']}%</p>
    </div>
    
    <h2>배당 입금 대사</h2>
    <table>
        <thead>
            <tr>
                <th>종목</th>
                <th>종목명</th>
                <th>예상 배당금</th>
                <th>실제 입금액</th>
                <th>차액</th>
                <th>상태</th>
            </tr>
        </thead>
        <tbody>
        """
        for item in reconciled_items:
            status_color = "#4caf50" if item["status"] == "matched" else "#ff9800" if item["status"] == "amount_diff" else "#f44336"
            html += f"""
            <tr>
                <td>{item['symbol']}</td>
                <td>{item['name']}</td>
                <td>{item['expected']:,.0f} 원</td>
                <td>{item['actual']:,.0f} 원</td>
                <td>{item['diff']:,.0f} 원</td>
                <td style="color: {status_color}">{item['status']}</td>
            </tr>
            """
        html += """
        </tbody>
    </table>
</body>
</html>
"""
        return html


def _receipt_amount_krw(receipt: dict[str, Any], fx_rate: float) -> float:
    amount = _to_float(receipt.get("amount", 0.0))
    currency = str(receipt.get("currency", "KRW")).upper()
    if currency == "USD":
        return round(amount * fx_rate, 2)
    return round(amount, 2)


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    text = str(value).replace(",", "").replace("₩", "").replace("$", "").strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0
