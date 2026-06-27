from __future__ import annotations

from collections import Counter
from typing import Any

from .order_history_utils import is_filled, order_rows, parse_ordered_at, status, symbol
from .trade_history_analytics import build_trade_history_analytics


LEVERAGED_SYMBOLS = {"TQQQ", "SOXL", "NVDL", "NVDX", "MSTX", "UPRO", "SPXL", "SQQQ", "SOXS"}


def review_trade_behavior(orders_payload: Any) -> dict[str, Any]:
    orders = order_rows(orders_payload)
    analytics = build_trade_history_analytics(orders)
    warnings: list[dict[str, Any]] = []
    filled_orders = [row for row in orders if is_filled(row)]
    status_counts = Counter(status(row) or "UNKNOWN" for row in orders)
    month_counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    leverage_count = 0

    for row in filled_orders:
        dt = parse_ordered_at(row.get("orderedAt") or row.get("ordered_at"))
        if dt:
            month_counts[f"{dt.year:04d}-{dt.month:02d}"] += 1
        sym = symbol(row)
        if sym:
            symbol_counts[sym] += 1
        if sym in LEVERAGED_SYMBOLS:
            leverage_count += 1

    peak_month, peak_count = month_counts.most_common(1)[0] if month_counts else ("-", 0)
    if peak_count >= 12:
        warnings.append(
            _warning(
                "overtrading",
                "warning",
                f"{peak_month} month has {peak_count} filled trades.",
                "Add cooldown or monthly trade budget before enabling automation.",
            )
        )

    cancel_count = status_counts.get("CANCELED", 0)
    cancel_ratio = cancel_count / max(len(orders), 1)
    if cancel_ratio >= 0.25:
        warnings.append(
            _warning(
                "high_cancel_ratio",
                "warning",
                f"Canceled orders are {cancel_ratio * 100:.1f}% of order history.",
                "Review limit-price discipline and reduce impulsive order edits.",
            )
        )

    trade_count = max(len(filled_orders), 1)
    leverage_ratio = leverage_count / trade_count
    if leverage_ratio >= 0.35:
        warnings.append(
            _warning(
                "leveraged_etf_concentration",
                "warning",
                f"Leveraged ETF trades are {leverage_ratio * 100:.1f}% of filled trades.",
                "Require explicit leverage budget and max holding period rules.",
            )
        )

    losers = analytics.get("top_losers", [])
    quick_losses = [row for row in losers if row.get("holding_days") is not None and row["holding_days"] <= 14]
    if quick_losses:
        warnings.append(
            _warning(
                "quick_loss_realization",
                "failed",
                f"{len(quick_losses)} loss trades were closed within 14 days in the matched sample.",
                "Review stop-loss sizing, entry confirmation, and revenge-trade risk.",
            )
        )

    winners = analytics.get("top_winners", [])
    quick_winners = [row for row in winners if row.get("holding_days") is not None and row["holding_days"] <= 7]
    if quick_winners and len(winners) >= 3:
        warnings.append(
            _warning(
                "early_profit_taking",
                "warning",
                f"{len(quick_winners)} winning trades were closed within 7 days.",
                "Check whether profit-taking rules are cutting long-term compounding too early.",
            )
        )

    most_traded = symbol_counts.most_common(5)
    score = max(0, 100 - len([w for w in warnings if w["severity"] == "failed"]) * 25 - len(warnings) * 8)
    status_label = "failed" if any(w["severity"] == "failed" for w in warnings) else "warning" if warnings or score < 80 else "success"
    return {
        "status": status_label,
        "behavior_score": score,
        "summary": {
            "filled_trade_count": len(filled_orders),
            "peak_trade_month": peak_month,
            "peak_trade_month_count": peak_count,
            "cancel_count": cancel_count,
            "cancel_ratio_pct": round(cancel_ratio * 100, 2),
            "leveraged_trade_count": leverage_count,
            "leveraged_trade_ratio_pct": round(leverage_ratio * 100, 2),
            "most_traded_symbols": [{"symbol": sym, "count": count} for sym, count in most_traded],
        },
        "warnings": warnings,
        "source": "state/toss_orders.json · trade_history_analytics.py · trade_behavior_review.py",
    }


def _warning(code: str, severity: str, message: str, recommendation: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "recommendation": recommendation,
    }
