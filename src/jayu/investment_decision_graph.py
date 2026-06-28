from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .order_history_summary import build_order_history_summary
from .toss_freshness_ledger import build_toss_freshness_ledger
from .toss_orders import TossOrdersManager
from .unified_quality_policy import evaluate_unified_quality_policy


def build_investment_decision_graph(
    project_root: Path,
    *,
    symbol: str | None = None,
    signals_payload: Any | None = None,
    dividend_dashboard: Mapping[str, Any] | None = None,
    data_trust: Mapping[str, Any] | None = None,
    order_history_summary: Mapping[str, Any] | None = None,
    toss_freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create per-symbol decision graphs that connect data, signal, risk, dividend, and history gates."""
    dividend_dashboard = dict(dividend_dashboard or {})
    data_trust = dict(data_trust or {})
    order_history_summary = dict(order_history_summary or _load_order_summary(project_root, signals_payload))
    toss_freshness = dict(toss_freshness or build_toss_freshness_ledger(project_root, write=False))

    target_symbols = _symbols(symbol, signals_payload, dividend_dashboard, order_history_summary)
    graphs = [
        _build_symbol_graph(
            sym,
            signals_payload=signals_payload,
            dividend_dashboard=dividend_dashboard,
            data_trust=data_trust,
            order_history_summary=order_history_summary,
            toss_freshness=toss_freshness,
        )
        for sym in target_symbols
    ]
    policy = evaluate_unified_quality_policy(
        {
            graph["symbol"]: {
                "domain": "investment_decision_graph",
                "decision": graph["decision"],
                "trust_score": graph["score"],
                "reasons": graph["reason_codes"],
                "source": graph["source"],
            }
            for graph in graphs
        },
        default_domain="investment_decision_graph",
    )
    return {
        "status": policy["status"],
        "decision": policy["decision"],
        "allowed": policy["allowed"],
        "summary": {
            "symbol_count": len(graphs),
            "pass_count": sum(graph["decision"] == "pass" for graph in graphs),
            "review_count": sum(graph["decision"] == "review" for graph in graphs),
            "blocked_count": sum(graph["decision"] in {"block", "exclude"} for graph in graphs),
            "average_score": policy["overall_score"],
        },
        "graphs": graphs,
        "policy": policy,
        "source": "investment_decision_graph.py - signals, data trust, Toss freshness, dividend dashboard, order history summary",
    }


def _build_symbol_graph(
    symbol: str,
    *,
    signals_payload: Any | None,
    dividend_dashboard: Mapping[str, Any],
    data_trust: Mapping[str, Any],
    order_history_summary: Mapping[str, Any],
    toss_freshness: Mapping[str, Any],
) -> dict[str, Any]:
    signal = _find_signal(signals_payload, symbol)
    dividend_row = _find_dividend_row(dividend_dashboard, symbol)
    memory = _find_memory(order_history_summary, symbol)
    risk_gate = _find_risk_gate(order_history_summary, symbol)
    autotrade_rule = _find_autotrade_rule(order_history_summary, symbol)

    nodes = [
        _node(
            "data_quality",
            "Unified data quality",
            data_trust.get("gate") or data_trust.get("trust") or data_trust,
            score_key="overall_score",
            source=data_trust.get("source") or "data_trust_score.py",
        ),
        _node(
            "toss_freshness",
            "Toss freshness ledger",
            toss_freshness,
            score_key="summary.average_trust_score",
            source=toss_freshness.get("source") or "toss_freshness_ledger.py",
        ),
        _node(
            "signal",
            "Signal",
            signal or {"status": "not_evaluated", "decision": "review", "score": 70.0},
            source=(signal or {}).get("source") or "today_signals.json",
        ),
        _node(
            "dividend",
            "Dividend quality",
            dividend_row or {"status": "not_evaluated", "decision": "review", "trust_score": 70.0},
            score_key="trust_score",
            source=(dividend_row or {}).get("source") or "dividend_dashboard_api.py",
        ),
        _node(
            "order_memory",
            "Order memory",
            memory or {"status": "not_evaluated", "decision": "review", "score": 70.0},
            score_key="score",
            source=(memory or {}).get("source") or "trade_memory_score.py",
        ),
        _node(
            "historical_risk",
            "Historical trade risk",
            risk_gate or {"status": "success", "decision": "pass", "score": 90.0},
            source=(risk_gate or {}).get("source") or "historical_trade_risk_gate.py",
        ),
        _node(
            "autotrading_guard",
            "Autotrading guard",
            autotrade_rule or {"status": "success", "decision": "pass", "score": 90.0},
            source=(autotrade_rule or {}).get("source") or "autotrade_guard_from_history.py",
        ),
    ]
    policy = evaluate_unified_quality_policy(
        {node["id"]: {**node, "trust_score": node["score"], "domain": "decision_graph"} for node in nodes},
        default_domain="decision_graph",
    )
    reason_codes = sorted({reason for node in nodes for reason in node.get("reasons", [])})
    decision = policy["decision"]
    return {
        "symbol": symbol,
        "status": policy["status"],
        "decision": decision,
        "allowed": policy["allowed"],
        "score": policy["overall_score"],
        "headline": _headline(symbol, decision, reason_codes),
        "reason_codes": reason_codes,
        "nodes": nodes,
        "edges": [
            {"from": "data_quality", "to": "signal"},
            {"from": "toss_freshness", "to": "signal"},
            {"from": "signal", "to": "historical_risk"},
            {"from": "dividend", "to": "autotrading_guard"},
            {"from": "order_memory", "to": "historical_risk"},
            {"from": "historical_risk", "to": "final_decision"},
            {"from": "autotrading_guard", "to": "final_decision"},
        ],
        "source": "investment_decision_graph.py",
    }


def _node(
    node_id: str,
    label: str,
    payload: Mapping[str, Any],
    *,
    score_key: str = "score",
    source: str,
) -> dict[str, Any]:
    score = _normalize_score(_nested_number(payload, score_key))
    decision = _decision(payload, score)
    status = "success" if decision == "pass" else "warning" if decision == "review" else "blocked"
    return {
        "id": node_id,
        "label": label,
        "status": status,
        "decision": decision,
        "allowed": decision not in {"block", "exclude"},
        "score": round(score if score is not None else _score_from_decision(decision), 2),
        "reasons": _reason_codes(payload, decision),
        "source": source,
    }


def _load_order_summary(project_root: Path, signals_payload: Any | None) -> dict[str, Any]:
    orders = TossOrdersManager(project_root).load_orders()
    return build_order_history_summary(orders, signals_payload=signals_payload, compact=True)


def _symbols(
    symbol: str | None,
    signals_payload: Any | None,
    dividend_dashboard: Mapping[str, Any],
    order_history_summary: Mapping[str, Any],
) -> list[str]:
    if symbol:
        return [symbol.upper()]
    values: set[str] = set()
    for row in _signal_rows(signals_payload):
        sym = str(row.get("ticker") or row.get("symbol") or "").upper()
        if sym:
            values.add(sym)
    for row in dividend_dashboard.get("holdings_table") or []:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            values.add(sym)
    for row in order_history_summary.get("memory", {}).get("symbol_scores") or []:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            values.add(sym)
    for row in order_history_summary.get("autotrade_guard", {}).get("rules") or []:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            values.add(sym)
    return sorted(values)[:50] or ["PORTFOLIO"]


def _signal_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("rows", "signals", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
        if payload.get("ticker") or payload.get("symbol"):
            return [dict(payload)]
        return []
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _find_signal(payload: Any, symbol: str) -> dict[str, Any] | None:
    for row in _signal_rows(payload):
        sym = str(row.get("ticker") or row.get("symbol") or "").upper()
        if sym == symbol:
            score = row.get("score")
            status = row.get("status") or ("success" if row.get("action") in {"BUY", "SELL"} else "not_evaluated")
            return {**row, "score": score if score is not None else 75.0, "status": status}
    return None


def _find_dividend_row(dashboard: Mapping[str, Any], symbol: str) -> dict[str, Any] | None:
    for row in dashboard.get("holdings_table") or []:
        if str(row.get("symbol") or "").upper() == symbol:
            return dict(row)
    return None


def _find_memory(summary: Mapping[str, Any], symbol: str) -> dict[str, Any] | None:
    for row in summary.get("memory", {}).get("symbol_scores") or []:
        if str(row.get("symbol") or "").upper() == symbol:
            decision = "pass" if float(row.get("score") or 0.0) >= 65 else "review" if float(row.get("score") or 0.0) >= 45 else "block"
            return {**row, "decision": decision, "source": row.get("source") or "trade_memory_score.py"}
    return None


def _find_risk_gate(summary: Mapping[str, Any], symbol: str) -> dict[str, Any] | None:
    risk = summary.get("risk_gate", {})
    for key, decision in (("blocked_signals", "block"), ("review_signals", "review"), ("evaluated_signals", "pass")):
        for row in risk.get(key) or []:
            if str(row.get("ticker") or row.get("symbol") or "").upper() == symbol:
                return {
                    **row,
                    "decision": decision if row.get("status") != "blocked" else "block",
                    "score": 45.0 if decision == "block" else 70.0 if decision == "review" else 90.0,
                    "source": row.get("source") or risk.get("source") or "historical_trade_risk_gate.py",
                    "reasons": row.get("reason_codes") or row.get("reasons") or [],
                }
    return None


def _find_autotrade_rule(summary: Mapping[str, Any], symbol: str) -> dict[str, Any] | None:
    for row in summary.get("autotrade_guard", {}).get("rules") or []:
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        action = str(row.get("action") or "")
        decision = "block" if action == "block_auto_order" else "review"
        return {
            **row,
            "decision": decision,
            "score": 40.0 if decision == "block" else 65.0,
            "reasons": [row.get("rule")],
            "source": row.get("source") or "autotrade_guard_from_history.py",
        }
    return None


def _decision(payload: Mapping[str, Any], score: float | None) -> str:
    raw = str(payload.get("decision") or "").lower()
    if raw in {"pass", "review", "block", "exclude"}:
        return raw
    status = str(payload.get("status") or "").lower()
    if status in {"blocked", "failed", "data_error", "error"}:
        return "block"
    if status in {"warning", "review", "partial", "stale", "not_evaluated"}:
        return "review"
    value = score if score is not None else _nested_number(payload, "trust_score")
    if value is None:
        return "pass" if status == "success" else "review"
    if value >= 80:
        return "pass"
    if value >= 60:
        return "review"
    if value >= 40:
        return "block"
    return "exclude"


def _reason_codes(payload: Mapping[str, Any], decision: str) -> list[str]:
    reasons: list[str] = []
    for key in ("reasons", "reason_codes"):
        values = payload.get(key)
        if isinstance(values, list):
            reasons.extend(str(item.get("code") if isinstance(item, Mapping) else item) for item in values if item)
    block_reason = payload.get("block_reason") or payload.get("rule")
    if block_reason:
        reasons.append(str(block_reason))
    if decision != "pass" and not reasons:
        reasons.append(f"{decision}_decision")
    return sorted(set(reasons))


def _nested_number(payload: Mapping[str, Any], key: str) -> float | None:
    current: Any = payload
    for part in key.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def _normalize_score(score: float | None) -> float | None:
    if score is None:
        return None
    if 0 <= score <= 1:
        return score * 100.0
    return score


def _score_from_decision(decision: str) -> float:
    return {"pass": 90.0, "review": 70.0, "block": 45.0, "exclude": 20.0}.get(decision, 70.0)


def _headline(symbol: str, decision: str, reasons: list[str]) -> str:
    if decision in {"block", "exclude"}:
        return f"{symbol} is blocked until the listed data, risk, or history issues are reviewed."
    if decision == "review":
        return f"{symbol} needs review before it can become an order candidate."
    return f"{symbol} passes the current decision graph."
