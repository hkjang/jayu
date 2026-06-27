from __future__ import annotations

from typing import Any

from .autotrade_guard_from_history import build_autotrade_guard_from_history
from .execution_quality_from_orders import analyze_execution_quality_from_orders
from .historical_trade_risk_gate import evaluate_historical_trade_risk_gate
from .order_history_reconciliation import reconcile_order_history
from .toss_order_feature_store import build_toss_order_feature_store
from .trade_journal_from_orders import build_trade_journal_from_orders
from .trade_memory_score import build_trade_memory_score
from .trade_pattern_miner import mine_trade_patterns


def build_order_history_summary(
    orders_payload: Any,
    *,
    signals_payload: Any | None = None,
    holdings_payload: Any | None = None,
    tax_lots_payload: Any | None = None,
    portfolio_mapping: dict[str, Any] | None = None,
    usd_krw: float = 1350.0,
    compact: bool = True,
    raw_limit: int = 100,
) -> dict[str, Any]:
    feature_store = build_toss_order_feature_store(
        orders_payload,
        usd_krw=usd_krw,
        portfolio_mapping=portfolio_mapping,
    )
    patterns = mine_trade_patterns(feature_store)
    memory = build_trade_memory_score(feature_store, patterns)
    risk_gate = evaluate_historical_trade_risk_gate(signals_payload, feature_store, patterns, memory)
    autotrade_guard = build_autotrade_guard_from_history(feature_store, patterns, memory)
    execution_quality = analyze_execution_quality_from_orders(orders_payload, usd_krw=usd_krw)
    journal = build_trade_journal_from_orders(feature_store, patterns)
    reconciliation = reconcile_order_history(
        orders_payload,
        holdings_payload,
        tax_lots_payload,
        usd_krw=usd_krw,
    )
    status = _rollup_status(
        [
            feature_store.get("status"),
            patterns.get("status"),
            memory.get("status"),
            risk_gate.get("status"),
            autotrade_guard.get("status"),
            execution_quality.get("status"),
            reconciliation.get("status"),
        ]
    )
    if compact:
        _compact_feature_store(feature_store, raw_limit=raw_limit)
        _compact_execution_quality(execution_quality, raw_limit=raw_limit)
        _compact_reconciliation(reconciliation, raw_limit=raw_limit)
    return {
        "status": status,
        "summary": {
            "order_count": feature_store.get("summary", {}).get("trade_count", 0),
            "round_count": feature_store.get("summary", {}).get("round_count", 0),
            "realized_pnl_krw": feature_store.get("summary", {}).get("realized_pnl_krw", 0.0),
            "win_rate_pct": feature_store.get("summary", {}).get("win_rate_pct"),
            "avg_memory_score": memory.get("summary", {}).get("avg_score"),
            "pattern_count": patterns.get("summary", {}).get("pattern_count", 0),
            "risk_block_count": risk_gate.get("summary", {}).get("blocked_count", 0),
            "autotrade_block_rule_count": autotrade_guard.get("summary", {}).get("block_rule_count", 0),
            "reconciliation_status": reconciliation.get("status"),
        },
        "feature_store": feature_store,
        "patterns": patterns,
        "memory": memory,
        "risk_gate": risk_gate,
        "autotrade_guard": autotrade_guard,
        "execution_quality": execution_quality,
        "journal": journal,
        "reconciliation": reconciliation,
        "source": "GET /api/v1/toss/orders - state/toss_orders.json - order_history_summary.py",
    }


def _rollup_status(statuses: list[Any]) -> str:
    values = {str(status or "") for status in statuses}
    if "blocked" in values or "failed" in values:
        return "failed"
    if "warning" in values:
        return "warning"
    if values <= {"", "not_evaluated"}:
        return "not_evaluated"
    return "success"


def _compact_feature_store(feature_store: dict[str, Any], *, raw_limit: int) -> None:
    for key in ("orders", "trade_rounds", "by_symbol", "open_lots"):
        if isinstance(feature_store.get(key), list):
            feature_store[key] = feature_store[key][:raw_limit]
    if isinstance(feature_store.get("by_month"), list):
        feature_store["by_month"] = feature_store["by_month"][-min(raw_limit, 72) :]


def _compact_execution_quality(execution_quality: dict[str, Any], *, raw_limit: int) -> None:
    for key in ("orders", "high_fee_orders", "adverse_slippage_orders"):
        if isinstance(execution_quality.get(key), list):
            execution_quality[key] = execution_quality[key][:raw_limit]


def _compact_reconciliation(reconciliation: dict[str, Any], *, raw_limit: int) -> None:
    realized = reconciliation.get("realized_pnl")
    holdings = reconciliation.get("holdings")
    if isinstance(realized, dict):
        for key in ("position_discrepancies", "order_positions", "tax_lot_positions", "holding_positions"):
            if isinstance(realized.get(key), list):
                realized[key] = realized[key][:raw_limit]
    if isinstance(holdings, dict) and isinstance(holdings.get("discrepancies"), list):
        holdings["discrepancies"] = holdings["discrepancies"][:raw_limit]
