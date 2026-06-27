import json
import time
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster
from .security_data_quality import SecurityDataQuality
from .order_security_reconciliation import OrderSecurityReconciler
from .security_exposure_analyzer import SecurityExposureAnalyzer

class TossReferenceDataReport:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.state_dir = self.project_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.quality = SecurityDataQuality(self.project_root)
        self.reconciler = OrderSecurityReconciler(self.project_root)
        self.exposure = SecurityExposureAnalyzer(self.project_root)

    def generate_report(self) -> dict[str, Any]:
        q_res = self.quality.check_quality()
        r_res = self.reconciler.reconcile()
        e_res = self.exposure.calculate_exposure()
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # Build Markdown
        md_lines = [
            f"# Toss Reference Data & Reconciliation Report",
            f"Generated At: {timestamp}",
            f"",
            f"## 1. Summary Metrics",
            f"- **Metadata Quality Score**: {q_res['score']}/100",
            f"- **Reconciliation Score**: {r_res['score']}/100",
            f"- **Total Checked Securities**: {q_res['total_securities_checked']}",
            f"- **Total Portfolio Value**: {e_res['total_value_krw']:,.0f} KRW",
            f"",
            f"## 2. Security Warnings & Anomalies",
        ]
        
        if q_res["anomalies"]:
            md_lines.append("| Symbol | Field | Issue |")
            md_lines.append("| --- | --- | --- |")
            for a in q_res["anomalies"][:15]:
                md_lines.append(f"| {a['symbol']} | {a['field']} | {a['issue']} |")
        else:
            md_lines.append("No metadata anomalies detected.")
            
        md_lines.extend([
            f"",
            f"## 3. Reconciliation Gaps",
            f"- **Unmapped Symbols**: {', '.join(r_res['unmapped_symbols']) or 'None'}",
        ])
        
        if r_res["delisted_symbols"]:
            md_lines.append("\n### Delisted Symbols Suspected")
            for d in r_res["delisted_symbols"]:
                md_lines.append(f"- {d['symbol']} ({d['name']})")
                
        if r_res["suspended_symbols"]:
            md_lines.append("\n### Suspended Symbols")
            for s in r_res["suspended_symbols"]:
                md_lines.append(f"- {s['symbol']} ({s['name']})")

        md_lines.extend([
            f"",
            f"## 4. Portfolio Exposure",
            f"### By Asset Type",
        ])
        md_lines.append("| Asset Type | Value (KRW) | Percentage |")
        md_lines.append("| --- | --- | --- |")
        for t in e_res["by_type"]:
            md_lines.append(f"| {t['name']} | {t['value_krw']:,.0f} | {t['percentage']}% |")

        md_lines.extend([
            f"",
            f"### By Currency",
        ])
        md_lines.append("| Currency | Value (KRW) | Percentage |")
        md_lines.append("| --- | --- | --- |")
        for c in e_res["by_currency"]:
            md_lines.append(f"| {c['name']} | {c['value_krw']:,.0f} | {c['percentage']}% |")

        md_content = "\n".join(md_lines)
        
        # Build HTML
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Toss Reference Data Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1, h2, h3 {{ color: #111; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f5f5f5; }}
        .score {{ font-size: 24px; font-weight: bold; color: #2e7d32; }}
        .warning {{ color: #c62828; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>Toss Reference Data & Reconciliation Report</h1>
    <p>Generated At: {timestamp}</p>
    
    <h2>1. Summary Scores</h2>
    <p>Metadata Quality Score: <span class="score">{q_res['score']}/100</span></p>
    <p>Reconciliation Score: <span class="score">{r_res['score']}/100</span></p>
    <p>Total Portfolio Value: <strong>{e_res['total_value_krw']:,.0f} KRW</strong></p>
    
    <h2>2. Metadata Anomalies</h2>
    {"<table><tr><th>Symbol</th><th>Field</th><th>Issue</th></tr>" + "".join(f"<tr><td>{a['symbol']}</td><td>{a['field']}</td><td>{a['issue']}</td></tr>" for a in q_res['anomalies']) + "</table>" if q_res['anomalies'] else "<p>No metadata anomalies detected.</p>"}
    
    <h2>3. Reconciliation Details</h2>
    <p>Unmapped Symbols: <strong>{', '.join(r_res['unmapped_symbols']) or 'None'}</strong></p>
    
    <h2>4. Portfolio Exposure by Type</h2>
    <table>
        <tr><th>Asset Type</th><th>Value (KRW)</th><th>Percentage</th></tr>
        {"".join(f"<tr><td>{t['name']}</td><td>{t['value_krw']:,.0f}</td><td>{t['percentage']}%</td></tr>" for t in e_res['by_type'])}
    </table>
</body>
</html>
"""

        # Save files
        try:
            with open(self.state_dir / "toss_reference_data_report.md", "w", encoding="utf-8") as f:
                f.write(md_content)
            with open(self.state_dir / "toss_reference_data_report.html", "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception:
            pass

        return {
            "timestamp": timestamp,
            "markdown_path": str(self.state_dir / "toss_reference_data_report.md"),
            "html_path": str(self.state_dir / "toss_reference_data_report.html"),
            "quality": q_res,
            "reconciliation": r_res,
            "exposure": e_res
        }
