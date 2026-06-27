from __future__ import annotations

from collections.abc import Mapping
from typing import Any


BLOCKING_PATTERN_CODES = {"repeated_loss_symbol", "quick_loss_reentry", "averaging_down_loss", "leveraged_loss"}


def evaluate_historical_trade_risk_gate(
    signals_payload: Any,
    feature_store: dict[str, Any],
    patterns_report: dict[str, Any] | None = None,
    memory_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signals = _signal_rows(signals_payload)
    patterns_by_symbol = _patterns_by_symbol(patterns_report or {})
    memory_by_symbol = {
        str(row.get("symbol") or "").upper(): row for row in (memory_report or {}).get("symbol_scores", [])
    }
    evaluated = []
    blocked = []
    review = []
    for sig in signals:
        ticker = str(sig.get("ticker") or sig.get("symbol") or "").upper()
        action = str(sig.get("action") or sig.get("side") or "").upper()
        if not ticker or action not in {"BUY", "SELL", "HOLD"}:
            continue
        reasons: list[str] = []
        status = "pass"
        memory = memory_by_symbol.get(ticker)
        memory_score = float(memory.get("score")) if memory and memory.get("score") is not None else None
        symbol_patterns = patterns_by_symbol.get(ticker, [])
        blocking_patterns = [item for item in symbol_patterns if item.get("code") in BLOCKING_PATTERN_CODES]

        if action == "BUY" and blocking_patterns:
            status = "blocked"
            reasons.extend(str(item.get("code")) for item in blocking_patterns)
        if action == "BUY" and memory_score is not None and memory_score < 45:
            status = "blocked"
            reasons.append("low_trade_memory_score")
        elif action == "BUY" and memory_score is not None and memory_score < 65 and status != "blocked":
            status = "review"
            reasons.append("weak_trade_memory_score")

        result = {
            "ticker": ticker,
            "action": action,
            "status": status,
            "allowed": status != "blocked",
            "memory_score": memory_score,
            "reason_codes": sorted(set(reasons)),
            "message": _message(ticker, action, status, reasons),
            "source": "Toss Order History getOrders - historical_trade_risk_gate.py",
        }
        evaluated.append(result)
        if status == "blocked":
            blocked.append(result)
        elif status == "review":
            review.append(result)

    if not signals and not feature_store.get("orders"):
        status = "not_evaluated"
    elif blocked:
        status = "blocked"
    elif review:
        status = "warning"
    else:
        status = "success"
    return {
        "status": status,
        "allowed": not blocked,
        "summary": {
            "evaluated_count": len(evaluated),
            "blocked_count": len(blocked),
            "review_count": len(review),
        },
        "evaluated_signals": evaluated,
        "blocked_signals": blocked,
        "review_signals": review,
        "source": "today_signals.json - Toss order feature store - historical_trade_risk_gate.py",
    }


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


def _patterns_by_symbol(patterns_report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in patterns_report.get("patterns") or []:
        sym = str(item.get("symbol") or "").upper()
        if not sym:
            continue
        grouped.setdefault(sym, []).append(item)
    return grouped


def _message(ticker: str, action: str, status: str, reasons: list[str]) -> str:
    if status == "blocked":
        return f"{ticker} {action} is blocked because historical orders match loss-prone patterns: {', '.join(sorted(set(reasons)))}."
    if status == "review":
        return f"{ticker} {action} needs review because historical trade memory is weak."
    return f"{ticker} {action} passes historical order-memory gate."
