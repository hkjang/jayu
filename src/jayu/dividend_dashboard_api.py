from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime

from .dividend_cashflow_simulator import DividendCashflowSimulator
from .dividend_reconciliation import DividendReconciler

def build_dividend_dashboard(project_root: Path) -> dict[str, Any]:
    """
    Builds the consolidated data required for the Dividend Dashboard.
    """
    simulator = DividendCashflowSimulator(project_root)
    
    # 1. Run base simulation
    sim_data = simulator.simulate_cashflow()
    
    # 2. Get reconciliation data
    reconciler = DividendReconciler(project_root)
    receipts = reconciler.load_actual_receipts()
    
    # Simple reconciliation matching
    # Map forecasts to actual receipts
    # Generate mock/dummy forecasts for reconciliation
    forecasts = []
    holdings = sim_data.get("holdings", [])
    
    # Construct reconciliation summary
    reconciliation_list = []
    matched_count = 0
    missing_count = 0
    diff_count = 0
    total_expected = 0.0
    total_actual = 0.0
    
    today_str = datetime.now().strftime("%Y-%m")
    
    for h in holdings:
        symbol = h["symbol"]
        expected = h["annual_payout_krw"] / 12.0
        actual = sum(r["amount"] for r in receipts if r["symbol"] == symbol and r["date"].startswith(today_str))
        
        total_expected += expected
        total_actual += actual
        
        diff = actual - expected
        if actual > 0:
            if abs(diff) < expected * 0.05:
                status = "matched"
                matched_count += 1
            else:
                status = "amount_diff"
                diff_count += 1
        else:
            status = "missing"
            missing_count += 1
            
        reconciliation_list.append({
            "symbol": symbol,
            "expected_amount": round(expected, 1),
            "actual_amount": round(actual, 1),
            "diff": round(diff, 1),
            "status": status
        })
        
    # 3. Calendar Events
    # Build events for the next 90 days
    calendar_events = []
    for h in holdings:
        symbol = h["symbol"]
        sym_events = simulator.event_master.get_events_for_symbol(symbol)
        for e in sym_events:
            # Keep recent or upcoming events
            calendar_events.append({
                "symbol": symbol,
                "ex_date": e.ex_date,
                "pay_date": e.pay_date,
                "record_date": e.record_date,
                "declared_date": e.declared_date,
                "amount": e.amount_per_share,
                "source": e.source,
                "is_confirmed": e.status in {"confirmed", "manual"}
            })
            
    calendar_events.sort(key=lambda x: x["ex_date"])
    
    # 4. Scenario comparisons
    # Run a few common scenarios
    scenarios = {
        "current_hold": sim_data["monthly_payouts_krw"],
        "drip_reinvest": [val * 1.05 for val in sim_data["monthly_payouts_krw"]], # simple projection
        "dividend_cut": [val * 0.70 for val in sim_data["monthly_payouts_krw"]],   # 30% cut
        "dividend_growth": [val * 1.07 for val in sim_data["monthly_payouts_krw"]] # 7% growth
    }

    # 5. Alerts
    alerts = []
    # Check if any ex-date is within 7 days
    today = datetime.now()
    for e in calendar_events:
        if e["ex_date"]:
            try:
                ex_dt = datetime.strptime(e["ex_date"], "%Y-%m-%d")
                days_left = (ex_dt - today).days
                if 0 <= days_left <= 7:
                    alerts.append({
                        "type": "ex_date_proximity",
                        "symbol": e["symbol"],
                        "severity": "warning",
                        "message": f"{e['symbol']}의 배당락일({e['ex_date']})이 {days_left}일 남았습니다."
                    })
            except Exception:
                pass

    return {
        "overview": {
            "this_month_expected": round(sim_data["monthly_payouts_krw"][0], 1),
            "this_month_net": round(sim_data["monthly_net_payouts_krw"][0], 1),
            "annual_dividend_krw": sim_data["annual_dividend_krw"],
            "annual_net_dividend_krw": sim_data["annual_net_dividend_krw"],
            "aggregate_yield_pct": sim_data["aggregate_yield_pct"],
            "goal_achievement_pct": sim_data["target_goal"]["achievement_rate_pct"],
            "monthly_target_krw": sim_data["target_goal"]["monthly_target_krw"]
        },
        "monthly_cashflows": [
            {
                "month": datetime.now().strftime("%m"), # current month index for chart
                "gross": round(g, 1),
                "net": round(n, 1)
            } for g, n in zip(sim_data["monthly_payouts_krw"], sim_data["monthly_net_payouts_krw"])
        ],
        "holdings_table": sim_data["holdings"],
        "calendar_events": calendar_events[:50], # limit
        "scenarios": scenarios,
        "reconciliation": {
            "items": reconciliation_list,
            "summary": {
                "matched_count": matched_count,
                "missing_count": missing_count,
                "diff_count": diff_count,
                "total_expected": round(total_expected, 1),
                "total_actual": round(total_actual, 1)
            }
        },
        "alerts": alerts
    }
