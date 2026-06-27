from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class MonthlyInvestmentReport:
    """Compiles monthly operational metrics and generates HTML/Markdown reports."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.reports_dir = project_root / "runs" / "reports"

    def generate_report(
        self,
        year: int,
        month: int,
        report_data: dict[str, Any]
    ) -> dict[str, str]:
        """Compile and write monthly reports. Returns the generated absolute paths."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        month_str = f"{year}_{month:02d}"
        md_file = self.reports_dir / f"monthly_{month_str}.md"
        html_file = self.reports_dir / f"monthly_{month_str}.html"

        # Extract metrics
        return_pct = report_data.get("return_pct", 0.0)
        dividend_krw = report_data.get("dividend_krw", 0.0)
        cost_krw = report_data.get("cost_krw", 0.0)
        fx_effect_krw = report_data.get("fx_effect_krw", 0.0)
        risk_blocks = report_data.get("risk_blocks_count", 0)
        signals_count = report_data.get("signals_count", 0)
        win_rate = report_data.get("win_rate_pct", 0.0)
        goal_achievement = report_data.get("goal_achievement_pct", 0.0)

        # 1. Compile Markdown
        md_content = f"""# 📊 Jayu 월간 투자 & 운영 리포트 ({year}년 {month}월)

본 보고서는 Jayu 투자 에이전트 플랫폼에 의해 자동 생성된 월간 자산 관리 요약 문서입니다.

---

## 📈 1. 종합 성과 지표
- **월간 수익률:** `{return_pct:+.2f}%`
- **월간 배당금 유입:** `{dividend_krw:,.0f}원`
- **총 매매 수수료 & 비용:** `{cost_krw:,.0f}원`
- **원/달러 환율 변동 효과:** `{fx_effect_krw:+,.0f}원`

## 🛡️ 2. 리스크 및 신호 운영 통계
- **리스크 게이트 자동 차단:** `{risk_blocks}건`
- **발생한 매매 신호 총합:** `{signals_count}건`
- **매수 신호 백테스트 평균 승률:** `{win_rate:.1f}%`

## 🎯 3. 장기 투자 목표 현황
- **대표 목표 달성률:** `{goal_achievement:.1f}%`

---
*보고서 생성일시: {report_data.get("generated_at", "N/A")}*
"""

        # 2. Compile HTML with sleek, modern stylesheet
        html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jayu 월간 투자 리포트 - {year}년 {month}월</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --text: #f8fafc;
            --muted: #94a3b8;
            --accent: #3b82f6;
            --border: #334155;
            --success: #10b981;
            --danger: #ef4444;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 2rem;
            line-height: 1.5;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: var(--surface);
            padding: 2rem;
            border-radius: 12px;
            border: 1px solid var(--border);
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }}
        h1 {{
            color: var(--accent);
            border-bottom: 2px solid var(--border);
            padding-bottom: 0.5rem;
            margin-top: 0;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
            margin: 2rem 0;
        }}
        .card {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border);
            padding: 1.2rem;
            border-radius: 8px;
        }}
        .card-title {{
            font-size: 0.85rem;
            color: var(--muted);
            margin-bottom: 0.5rem;
            text-transform: uppercase;
        }}
        .card-value {{
            font-size: 1.5rem;
            font-weight: bold;
        }}
        .up {{ color: var(--success); }}
        .down {{ color: var(--danger); }}
        .footer {{
            text-align: center;
            font-size: 0.8rem;
            color: var(--muted);
            margin-top: 3rem;
            border-top: 1px solid var(--border);
            padding-top: 1rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Jayu 월간 투자 리포트 ({year}년 {month}월)</h1>
        <p style="color: var(--muted)">Jayu 투자 에이전트 플랫폼에 의해 실시간 컴파일된 자금 흐름과 운영 성과 종합 리포트입니다.</p>
        
        <div class="grid">
            <div class="card">
                <div class="card-title">월간 수익률</div>
                <div class="card-value {"up" if return_pct >= 0 else "down"}">{return_pct:+.2f}%</div>
            </div>
            <div class="card">
                <div class="card-title">월간 유입 배당금</div>
                <div class="card-value" style="color: var(--success)">{dividend_krw:,.0f}원</div>
            </div>
            <div class="card">
                <div class="card-title">매매 비용 & 수수료</div>
                <div class="card-value" style="color: var(--danger)">{cost_krw:,.0f}원</div>
            </div>
            <div class="card">
                <div class="card-title">환율 변동 효과</div>
                <div class="card-value {"up" if fx_effect_krw >= 0 else "down"}">{fx_effect_krw:+,.0f}원</div>
            </div>
            <div class="card">
                <div class="card-title">리스크 게이트 차단</div>
                <div class="card-value">{risk_blocks}건</div>
            </div>
            <div class="card">
                <div class="card-title">투자 목표 달성률</div>
                <div class="card-value" style="color: var(--accent)">{goal_achievement:.1f}%</div>
            </div>
        </div>

        <div class="footer">
            보고서 생성일시: {report_data.get("generated_at", "N/A")} | Jayu Operations Platform
        </div>
    </div>
</body>
</html>
"""

        with open(md_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        return {
            "markdown": str(md_file.resolve()),
            "html": str(html_file.resolve())
        }
