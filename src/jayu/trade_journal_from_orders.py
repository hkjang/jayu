from __future__ import annotations

from typing import Any


def build_trade_journal_from_orders(
    feature_store: dict[str, Any],
    patterns_report: dict[str, Any] | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    pattern_by_symbol: dict[str, list[str]] = {}
    for pattern in (patterns_report or {}).get("patterns") or []:
        sym = str(pattern.get("symbol") or "")
        if sym:
            pattern_by_symbol.setdefault(sym, []).append(str(pattern.get("code") or "pattern"))
    entries = []
    for trade in feature_store.get("trade_rounds") or []:
        sym = str(trade.get("symbol") or "")
        pnl = float(trade.get("realized_pnl_krw") or 0.0)
        label = "winner" if pnl > 0 else "loser" if pnl < 0 else "flat"
        entries.append(
            {
                "symbol": sym,
                "label": label,
                "sell_at": trade.get("sell_at"),
                "holding_days": trade.get("holding_days"),
                "realized_pnl_krw": round(pnl, 2),
                "return_pct": trade.get("return_pct"),
                "patterns": pattern_by_symbol.get(sym, []),
                "note": _note(sym, pnl, trade.get("holding_days"), pattern_by_symbol.get(sym, [])),
                "source": "Toss Order History getOrders - trade_journal_from_orders.py",
            }
        )
    entries = sorted(entries, key=lambda item: abs(float(item.get("realized_pnl_krw") or 0.0)), reverse=True)[:limit]
    winners = [item for item in entries if item["label"] == "winner"]
    losers = [item for item in entries if item["label"] == "loser"]
    return {
        "status": "success" if entries else "not_evaluated",
        "summary": {
            "entry_count": len(entries),
            "winner_count": len(winners),
            "loser_count": len(losers),
        },
        "entries": entries,
        "source": "toss_order_feature_store.py - trade_journal_from_orders.py",
    }


def _note(symbol: str, pnl: float, holding_days: Any, pattern_codes: list[str]) -> str:
    horizon = "unknown holding period" if holding_days is None else f"{holding_days} day hold"
    if pnl < 0 and pattern_codes:
        return f"{symbol} loss after {horizon}; matched patterns: {', '.join(sorted(set(pattern_codes)))}."
    if pnl < 0:
        return f"{symbol} loss after {horizon}; review entry timing and sizing."
    if pnl > 0 and holding_days is not None and float(holding_days) <= 7:
        return f"{symbol} profit after {horizon}; check whether exit was too early."
    if pnl > 0:
        return f"{symbol} profit after {horizon}; keep the conditions as a positive reference."
    return f"{symbol} flat trade after {horizon}."
