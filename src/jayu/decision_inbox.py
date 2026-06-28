from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .investment_decision_graph import build_investment_decision_graph
from .order_history_summary import build_order_history_summary
from .toss_freshness_ledger import build_toss_freshness_ledger
from .toss_orders import TossOrdersManager
from .unified_quality_policy import evaluate_unified_quality_policy


def build_decision_inbox(
    project_root: Path,
    *,
    data_trust: Mapping[str, Any] | None = None,
    toss_freshness: Mapping[str, Any] | None = None,
    dividend_dashboard: Mapping[str, Any] | None = None,
    order_history_summary: Mapping[str, Any] | None = None,
    decision_graph: Mapping[str, Any] | None = None,
    signals_payload: Any | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    toss_freshness = dict(toss_freshness or build_toss_freshness_ledger(project_root, write=False))
    dividend_dashboard = dict(dividend_dashboard or load_cached_dividend_dashboard_snapshot(project_root))
    order_history_summary = dict(order_history_summary or _load_order_summary(project_root, signals_payload))
    decision_graph = dict(
        decision_graph
        or build_investment_decision_graph(
            project_root,
            signals_payload=signals_payload,
            dividend_dashboard=dividend_dashboard,
            data_trust=data_trust,
            order_history_summary=order_history_summary,
            toss_freshness=toss_freshness,
        )
    )

    items: list[dict[str, Any]] = []
    _add_quality_items(items, data_trust)
    _add_toss_freshness_items(items, toss_freshness)
    _add_dividend_items(items, dividend_dashboard)
    _add_order_history_items(items, order_history_summary)
    _add_decision_graph_items(items, decision_graph)
    deduped = _dedupe(items)
    deduped.sort(key=lambda item: (item["priority"], item["category"], item.get("symbol") or "", item["code"]))
    deduped = deduped[: max(1, limit)]
    status = "blocked" if any(item["severity"] == "blocked" for item in deduped) else "warning" if deduped else "success"
    return {
        "status": status,
        "summary": {
            "item_count": len(deduped),
            "blocked_count": sum(item["severity"] == "blocked" for item in deduped),
            "warning_count": sum(item["severity"] == "warning" for item in deduped),
            "review_count": sum(item["severity"] == "review" for item in deduped),
            "by_menu": _count_by(deduped, "menu"),
            "by_category": _count_by(deduped, "category"),
        },
        "items": deduped,
        "source": "decision_inbox.py - data quality, Toss freshness, dividend dashboard, order history, investment decision graph",
    }


def build_unified_quality_snapshot(
    *,
    data_trust: Mapping[str, Any] | None = None,
    toss_freshness: Mapping[str, Any] | None = None,
    dividend_dashboard: Mapping[str, Any] | None = None,
    order_history_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    items: dict[str, Any] = {}
    if data_trust:
        gate = data_trust.get("gate") if isinstance(data_trust.get("gate"), Mapping) else data_trust
        items["data_trust_gate"] = {
            "domain": "data_quality",
            "decision": gate.get("decision"),
            "status": gate.get("status") or data_trust.get("status"),
            "trust_score": gate.get("overall_score") or data_trust.get("trust", {}).get("overall_score"),
            "allowed": gate.get("allowed", True),
            "reasons": gate.get("blocking") or gate.get("review") or [],
            "source": data_trust.get("source") or "GET /api/v1/data-trust-score",
        }
    if toss_freshness:
        items["toss_freshness"] = {
            "domain": "toss",
            "decision": toss_freshness.get("decision"),
            "status": toss_freshness.get("status"),
            "trust_score": toss_freshness.get("summary", {}).get("average_trust_score"),
            "allowed": toss_freshness.get("allowed", True),
            "reasons": toss_freshness.get("policy", {}).get("blocking") or [],
            "source": toss_freshness.get("source") or "toss_freshness_ledger.py",
        }
    if dividend_dashboard:
        summary = dividend_dashboard.get("data_quality_summary", {})
        items["dividend_quality"] = {
            "domain": "dividend",
            "decision": "block" if summary.get("blocked_count") else "review" if summary.get("review_count") else "pass",
            "trust_score": summary.get("average_trust_score"),
            "reasons": summary.get("unmapped_items") or [],
            "source": summary.get("source") or "DividendDataQualityGate",
        }
        guard = dividend_dashboard.get("autotrading_guard", {})
        items["dividend_autotrading_guard"] = {
            "domain": "autotrading",
            "status": guard.get("status"),
            "decision": "block" if guard.get("status") == "blocked" else "review" if guard.get("status") == "warning" else "pass",
            "trust_score": 45.0 if guard.get("status") == "blocked" else 70.0 if guard.get("status") == "warning" else 90.0,
            "reasons": guard.get("reasons") or [],
            "source": guard.get("source") or "dividend_dashboard_api.py",
        }
    if order_history_summary:
        items["order_history"] = {
            "domain": "order_history",
            "status": order_history_summary.get("status"),
            "decision": "block" if order_history_summary.get("status") == "failed" else "review" if order_history_summary.get("status") == "warning" else "pass",
            "trust_score": 45.0 if order_history_summary.get("status") == "failed" else 70.0 if order_history_summary.get("status") == "warning" else 90.0,
            "reasons": order_history_summary.get("risk_gate", {}).get("blocked_signals") or [],
            "source": order_history_summary.get("source") or "order_history_summary.py",
        }
    return evaluate_unified_quality_policy(items, default_domain="investment_os")


def load_cached_dividend_dashboard_snapshot(project_root: Path) -> dict[str, Any]:
    cache_path = project_root / "state" / "dividend_dashboard_cache.json"
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    response = data.get("response") if isinstance(data, Mapping) else None
    if isinstance(response, Mapping):
        return dict(response)
    return {}


def _load_order_summary(project_root: Path, signals_payload: Any | None) -> dict[str, Any]:
    orders = TossOrdersManager(project_root).load_orders()
    return build_order_history_summary(orders, signals_payload=signals_payload, compact=True)


def _add_quality_items(items: list[dict[str, Any]], data_trust: Mapping[str, Any] | None) -> None:
    if not data_trust:
        return
    gate = data_trust.get("gate") if isinstance(data_trust.get("gate"), Mapping) else {}
    for row in list(gate.get("blocking") or []) + list(gate.get("review") or []):
        dataset = str(row.get("dataset") or row.get("name") or "data_quality")
        items.append(_item(
            menu="Data Quality",
            category="data_quality",
            code="DATA_QUALITY_REVIEW",
            severity="blocked" if row.get("decision") in {"block", "exclude"} else "review",
            title=f"{dataset} data quality needs review",
            detail=", ".join(str(reason) for reason in row.get("reasons") or []) or "Unified data gate returned a non-pass result.",
            source=data_trust.get("source") or "GET /api/v1/data-trust-score",
        ))


def _add_toss_freshness_items(items: list[dict[str, Any]], ledger: Mapping[str, Any]) -> None:
    for row in ledger.get("endpoints") or []:
        if row.get("decision") == "pass":
            continue
        endpoint = str(row.get("endpoint") or "toss")
        items.append(_item(
            menu="Data Quality",
            category="toss_freshness",
            code=f"TOSS_{endpoint.upper()}_{str(row.get('cache_status') or 'REVIEW').upper()}",
            severity="blocked" if row.get("decision") in {"block", "exclude"} else "review",
            title=f"{row.get('label') or endpoint} freshness check",
            detail=f"cache={row.get('cache_status')} age={row.get('age_hours')}h reasons={', '.join(row.get('reasons') or []) or '-'}",
            source=row.get("source") or ledger.get("source") or "toss_freshness_ledger.py",
        ))


def _add_dividend_items(items: list[dict[str, Any]], dashboard: Mapping[str, Any]) -> None:
    for alert in dashboard.get("alerts") or []:
        symbol = str(alert.get("symbol") or "").upper() or None
        items.append(_item(
            menu="Dividend",
            category="dividend",
            code=str(alert.get("type") or "DIVIDEND_REVIEW").upper(),
            severity="warning",
            title=f"{symbol or 'Dividend'} calendar review",
            detail=str(alert.get("message") or "Dividend event needs review."),
            symbol=symbol,
            source="dividend_dashboard_api.py alerts",
        ))
    quality = dashboard.get("data_quality_summary", {})
    for row in quality.get("unmapped_items") or []:
        symbol = str(row.get("symbol") or "").upper() or None
        items.append(_item(
            menu="Dividend",
            category="dividend_quality",
            code="DIVIDEND_SYMBOL_UNMAPPED",
            severity="blocked",
            title=f"{symbol or 'Symbol'} dividend mapping missing",
            detail=str(row.get("reason") or "Dividend ticker mapping needs review."),
            symbol=symbol,
            source="DividendSecurityMapper",
        ))


def _add_order_history_items(items: list[dict[str, Any]], summary: Mapping[str, Any]) -> None:
    risk = summary.get("risk_gate", {})
    for row in risk.get("blocked_signals") or []:
        symbol = str(row.get("ticker") or row.get("symbol") or "").upper() or None
        items.append(_item(
            menu="Signal",
            category="order_history_risk",
            code="HISTORICAL_TRADE_RISK_BLOCK",
            severity="blocked",
            title=f"{symbol or 'Signal'} blocked by historical trade memory",
            detail=str(row.get("message") or ", ".join(row.get("reason_codes") or [])),
            symbol=symbol,
            source=row.get("source") or risk.get("source") or "historical_trade_risk_gate.py",
        ))
    for row in summary.get("autotrade_guard", {}).get("rules") or []:
        symbol = str(row.get("symbol") or "").upper() or None
        action = str(row.get("action") or "")
        items.append(_item(
            menu="Autotrading",
            category="autotrading_guard",
            code=str(row.get("rule") or "AUTOTRADE_HISTORY_GUARD").upper(),
            severity="blocked" if action == "block_auto_order" else "review",
            title=f"{symbol or 'Order'} autotrading history guard",
            detail=str(row.get("message") or action),
            symbol=symbol,
            source=row.get("source") or "autotrade_guard_from_history.py",
        ))


def _add_decision_graph_items(items: list[dict[str, Any]], graph: Mapping[str, Any]) -> None:
    for row in graph.get("graphs") or []:
        decision = str(row.get("decision") or "")
        if decision == "pass":
            continue
        symbol = str(row.get("symbol") or "").upper() or None
        items.append(_item(
            menu="Overview",
            category="decision_graph",
            code="INVESTMENT_DECISION_GRAPH_REVIEW",
            severity="blocked" if decision in {"block", "exclude"} else "review",
            title=f"{symbol or 'Portfolio'} decision graph",
            detail=str(row.get("headline") or ", ".join(row.get("reason_codes") or [])),
            symbol=symbol,
            source=row.get("source") or graph.get("source") or "investment_decision_graph.py",
        ))


def _item(
    *,
    menu: str,
    category: str,
    code: str,
    severity: str,
    title: str,
    detail: str,
    source: str,
    symbol: str | None = None,
) -> dict[str, Any]:
    priority = 1 if severity == "blocked" else 2 if severity == "review" else 3
    return {
        "id": f"{category}:{symbol or '-'}:{code}",
        "menu": menu,
        "category": category,
        "code": code,
        "severity": severity,
        "status": "blocked" if severity == "blocked" else "warning",
        "priority": priority,
        "symbol": symbol,
        "title": title,
        "detail": detail,
        "source": source,
    }


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("id"))
        current = by_id.get(key)
        if current is None or int(item.get("priority", 9)) < int(current.get("priority", 9)):
            by_id[key] = item
    return list(by_id.values())


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts
