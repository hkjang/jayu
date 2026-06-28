from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from datetime import datetime

from .dividend_cashflow_simulator import DividendCashflowSimulator
from .dividend_reconciliation import DividendReconciler

DIVIDEND_DASHBOARD_CACHE_VERSION = 3
DEFAULT_DASHBOARD_CACHE_TTL_SECONDS = 3600


def build_dividend_dashboard(
    project_root: Path,
    *,
    force_refresh: bool = False,
    cache_ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """
    Builds the consolidated data required for the Dividend Dashboard.
    """
    ttl_seconds = (
        cache_ttl_seconds
        if cache_ttl_seconds is not None
        else _env_int(
            "JAYU_DIVIDEND_DASHBOARD_CACHE_TTL_SECONDS",
            DEFAULT_DASHBOARD_CACHE_TTL_SECONDS,
        )
    )
    request_fingerprint = _dashboard_fingerprint(project_root)
    if not force_refresh and ttl_seconds > 0:
        cached = _load_dashboard_cache(project_root, request_fingerprint, ttl_seconds)
        if cached is not None:
            return cached

    dashboard = _build_dividend_dashboard_uncached(
        project_root,
        force_history_refresh=force_refresh,
    )
    saved_fingerprint = _dashboard_fingerprint(project_root)
    _save_dashboard_cache(project_root, dashboard, saved_fingerprint, ttl_seconds)
    return _with_cache_meta(
        dashboard,
        status="refresh" if force_refresh else "miss",
        created_at=time.time(),
        fingerprint=saved_fingerprint,
        ttl_seconds=ttl_seconds,
    )


def _build_dividend_dashboard_uncached(
    project_root: Path,
    *,
    force_history_refresh: bool = False,
) -> dict[str, Any]:
    """
    Build the dashboard without the response-level cache.
    """
    simulator = DividendCashflowSimulator(project_root)
    
    # 1. Run base simulation
    sim_data = simulator.simulate_cashflow(force_history_refresh=force_history_refresh)
    
    # 2. Get reconciliation data
    reconciler = DividendReconciler(project_root)
    receipts = reconciler.load_actual_receipts()
    
    holdings = sim_data.get("holdings", [])
    usd_krw = float(sim_data.get("usd_krw_rate") or 1350.0)
    
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
        actual = sum(
            _receipt_amount_krw(r, usd_krw)
            for r in receipts
            if r["symbol"] == symbol and r["date"].startswith(today_str)
        )
        
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
    months = sim_data.get("months") or _next_month_labels(len(sim_data["monthly_payouts_krw"]))

    # 5. Alerts
    alerts = _build_alerts(calendar_events)

    # 6. Resolve unmapped symbols
    unmapped_holdings = [
        {
            "symbol": h["symbol"],
            "name": h["name"],
            "market": h.get("market", ""),
            "currency": h.get("currency", ""),
            "reason": "Yahoo Ticker 매핑 불가능 (state/dividend_symbol_overrides.json 확인 필요)"
        }
        for h in sim_data.get("holdings", [])
        if h.get("mapping_status") == "failed"
    ]

    return {
        "portfolio_value_krw": sim_data["portfolio_value_krw"],
        "reinvestment_projections": sim_data.get("reinvestment_projections", {}),
        "target_goal": sim_data.get("target_goal", {}),
        "goal_bridge": sim_data.get("goal_bridge", {}),
        "usd_krw_rate": sim_data.get("usd_krw_rate"),
        "holdings_source": sim_data.get("holdings_source"),
        "fallback_used": sim_data.get("fallback_used"),
        "source_snapshot_path": sim_data.get("source_snapshot_path"),
        "last_refreshed_at": sim_data.get("calculation_timestamp"),
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
                "month": month,
                "gross": round(g, 1),
                "net": round(n, 1),
                "source": "DividendCashflowSimulator",
            }
            for month, g, n in zip(
                months,
                sim_data["monthly_payouts_krw"],
                sim_data["monthly_net_payouts_krw"],
            )
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
        "alerts": alerts,
        "data_quality_summary": {
            **_build_quality_summary(sim_data["holdings"]),
            "unmapped_count": len(unmapped_holdings),
            "unmapped_items": unmapped_holdings
        },
        "autotrading_guard": _build_autotrading_guard(sim_data["holdings"], calendar_events),
        "source_summary": sim_data.get("source_summary", {}),
    }


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


def _build_alerts(calendar_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    today = datetime.now().date()
    for event in calendar_events:
        ex_date = event.get("ex_date")
        if not ex_date:
            continue
        try:
            ex_dt = datetime.strptime(ex_date, "%Y-%m-%d").date()
        except Exception:
            continue
        days_left = (ex_dt - today).days
        if 0 <= days_left <= 7:
            symbol = str(event.get("symbol", ""))
            alerts.append({
                "type": "ex_date_proximity",
                "symbol": symbol,
                "severity": "warning",
                "message": f"{symbol}의 배당락일({ex_date})이 {days_left}일 남았습니다.",
            })
    return alerts


def _build_quality_summary(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(holdings)
    pass_count = sum(1 for item in holdings if item.get("decision") == "pass")
    review_count = sum(1 for item in holdings if item.get("decision") == "review")
    blocked_count = sum(1 for item in holdings if item.get("decision") in {"block", "exclude"})
    avg_trust = (
        sum(_to_float(item.get("trust_score")) for item in holdings) / total
        if total > 0
        else 0.0
    )
    return {
        "holding_count": total,
        "pass_count": pass_count,
        "review_count": review_count,
        "blocked_count": blocked_count,
        "average_trust_score": round(avg_trust, 2),
        "source": "DividendDataQualityGate",
    }


def _build_autotrading_guard(
    holdings: list[dict[str, Any]],
    calendar_events: list[dict[str, Any]],
) -> dict[str, Any]:
    blocked_symbols = []
    warning_symbols = []
    reasons = []
    for item in holdings:
        symbol = str(item.get("symbol", ""))
        decision = item.get("decision")
        trust_score = _to_float(item.get("trust_score"))
        if decision in {"block", "exclude"} or trust_score < 60.0:
            blocked_symbols.append(symbol)
            reasons.append({
                "symbol": symbol,
                "reason": "dividend_data_trust_below_autotrading_threshold",
                "trust_score": trust_score,
            })
        elif decision == "review" or trust_score < 80.0:
            warning_symbols.append(symbol)

    today = datetime.now().date()
    for event in calendar_events:
        symbol = str(event.get("symbol", ""))
        ex_date = event.get("ex_date")
        if not ex_date:
            continue
        try:
            days_to_ex = (datetime.strptime(ex_date, "%Y-%m-%d").date() - today).days
        except Exception:
            continue
        if 0 <= days_to_ex <= 3 and symbol not in blocked_symbols:
            warning_symbols.append(symbol)
            reasons.append({
                "symbol": symbol,
                "reason": "ex_date_chasing_risk",
                "days_to_ex": days_to_ex,
            })

    blocked_symbols = sorted(set(sym for sym in blocked_symbols if sym))
    warning_symbols = sorted(set(sym for sym in warning_symbols if sym and sym not in blocked_symbols))
    return {
        "status": "blocked" if blocked_symbols else "warning" if warning_symbols else "pass",
        "blocked_symbols": blocked_symbols,
        "warning_symbols": warning_symbols,
        "reasons": reasons,
        "source": "DividendDataQualityGate · dividend calendar proximity",
    }


def _next_month_labels(count: int) -> list[str]:
    labels = []
    curr = datetime.now()
    for _ in range(count):
        labels.append(curr.strftime("%Y-%m"))
        month = curr.month + 1
        year = curr.year
        if month > 12:
            month = 1
            year += 1
        curr = curr.replace(year=year, month=month, day=1)
    return labels


def _dashboard_cache_path(project_root: Path) -> Path:
    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "dividend_dashboard_cache.json"


def _load_dashboard_cache(
    project_root: Path,
    fingerprint: str,
    ttl_seconds: int,
) -> dict[str, Any] | None:
    cache_path = _dashboard_cache_path(project_root)
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        created_at = float(payload.get("created_at", 0.0))
        if payload.get("version") != DIVIDEND_DASHBOARD_CACHE_VERSION:
            return None
        if payload.get("fingerprint") != fingerprint:
            return None
        expired = time.time() - created_at > ttl_seconds
        response = payload.get("response")
        if not isinstance(response, dict):
            return None
        return _with_cache_meta(
            response,
            status="stale_hit" if expired else "hit",
            created_at=created_at,
            fingerprint=fingerprint,
            ttl_seconds=ttl_seconds,
        )
    except Exception:
        return None


def _save_dashboard_cache(
    project_root: Path,
    response: dict[str, Any],
    fingerprint: str,
    ttl_seconds: int,
) -> None:
    if ttl_seconds <= 0:
        return
    cache_path = _dashboard_cache_path(project_root)
    created_at = time.time()
    payload = {
        "version": DIVIDEND_DASHBOARD_CACHE_VERSION,
        "created_at": created_at,
        "created_at_iso": datetime.fromtimestamp(created_at).isoformat(),
        "fingerprint": fingerprint,
        "ttl_seconds": ttl_seconds,
        "response": response,
    }
    try:
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _with_cache_meta(
    response: dict[str, Any],
    *,
    status: str,
    created_at: float,
    fingerprint: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    enriched = json.loads(json.dumps(response, ensure_ascii=False))
    age_seconds = max(0.0, time.time() - created_at)
    enriched["cache"] = {
        "status": status,
        "created_at": datetime.fromtimestamp(created_at).isoformat(),
        "age_seconds": round(age_seconds, 2),
        "ttl_seconds": ttl_seconds,
        "expires_in_seconds": max(0, int(ttl_seconds - age_seconds)),
        "fingerprint": fingerprint,
        "source": "state/dividend_dashboard_cache.json",
    }
    if isinstance(enriched.get("calendar_events"), list):
        enriched["alerts"] = _build_alerts(enriched["calendar_events"])
    return enriched


def _dashboard_fingerprint(project_root: Path) -> str:
    state_dir = project_root / "state"
    watched_files = [
        project_root / "toss_portfolio.csv",
        state_dir / "toss_account_snapshot.json",
        state_dir / "dividend_ticker_overrides.json",
        state_dir / "dividend_supplements.json",
        state_dir / "dividend_manual_events.json",
        state_dir / "dividend_actual_receipts.csv",
        state_dir / "dividend_target.json",
        state_dir / "toss_fx_cache.json",
    ]
    payload = {
        "version": DIVIDEND_DASHBOARD_CACHE_VERSION,
        "month": datetime.now().strftime("%Y-%m"),
        "files": [_file_fingerprint(path) for path in watched_files],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "path": str(path),
            "exists": True,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": digest,
        }
    except Exception:
        return {"path": str(path), "exists": True, "unreadable": True}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default
