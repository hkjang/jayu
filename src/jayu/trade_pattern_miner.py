from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .trade_behavior_review import LEVERAGED_SYMBOLS


def mine_trade_patterns(feature_store: dict[str, Any]) -> dict[str, Any]:
    orders = list(feature_store.get("orders") or [])
    rounds = list(feature_store.get("trade_rounds") or [])
    patterns: list[dict[str, Any]] = []

    patterns.extend(_repeated_loss_symbols(feature_store.get("by_symbol") or []))
    patterns.extend(_quick_loss_reentries(orders, rounds))
    patterns.extend(_averaging_down_sequences(orders, rounds))
    patterns.extend(_early_profit_taking(rounds))
    patterns.extend(_excessive_short_term(rounds))
    patterns.extend(_leveraged_loss_patterns(feature_store.get("by_symbol") or []))

    severity_counts = Counter(item.get("severity", "warning") for item in patterns)
    status = "failed" if severity_counts.get("failed") else "warning" if patterns else "success"
    return {
        "status": status if orders else "not_evaluated",
        "summary": {
            "pattern_count": len(patterns),
            "failed_count": severity_counts.get("failed", 0),
            "warning_count": severity_counts.get("warning", 0),
            "symbol_count": len({item.get("symbol") for item in patterns if item.get("symbol")}),
        },
        "patterns": patterns,
        "source": "toss_order_feature_store.py - trade_pattern_miner.py",
    }


def _repeated_loss_symbols(by_symbol: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = []
    for row in by_symbol:
        symbol = row.get("symbol")
        rounds = int(row.get("round_count") or 0)
        loss_count = int(row.get("loss_count") or 0)
        pnl = float(row.get("realized_pnl_krw") or 0.0)
        win_rate = row.get("win_rate_pct")
        if not symbol or rounds < 2:
            continue
        if loss_count >= 2 and (pnl < 0 or (win_rate is not None and float(win_rate) < 45.0)):
            patterns.append(
                _pattern(
                    "repeated_loss_symbol",
                    "failed" if pnl < 0 else "warning",
                    str(symbol),
                    f"{symbol} has repeated realized losses in matched order history.",
                    {
                        "round_count": rounds,
                        "loss_count": loss_count,
                        "realized_pnl_krw": round(pnl, 2),
                        "win_rate_pct": win_rate,
                    },
                )
            )
    return patterns


def _quick_loss_reentries(orders: list[dict[str, Any]], rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buy_orders: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in orders:
        if row.get("side") == "BUY":
            buy_orders[str(row.get("symbol") or "")].append(row)
    patterns = []
    seen = set()
    for trade in rounds:
        sym = str(trade.get("symbol") or "")
        pnl = float(trade.get("realized_pnl_krw") or 0.0)
        sell_at = _parse_dt(trade.get("sell_at"))
        if not sym or pnl >= 0 or not sell_at:
            continue
        for buy in buy_orders.get(sym, []):
            buy_at = _parse_dt(buy.get("ordered_at"))
            if not buy_at:
                continue
            days = (buy_at - sell_at).days
            if 0 <= days <= 3:
                key = (sym, trade.get("sell_at"), buy.get("order_id"))
                if key in seen:
                    continue
                seen.add(key)
                patterns.append(
                    _pattern(
                        "quick_loss_reentry",
                        "failed",
                        sym,
                        f"{sym} was bought again within {days} days after a losing exit.",
                        {
                            "days_after_loss": days,
                            "loss_pnl_krw": round(pnl, 2),
                            "reentry_order_id": buy.get("order_id"),
                        },
                    )
                )
                break
    return patterns


def _averaging_down_sequences(orders: list[dict[str, Any]], rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    losing_symbols = {str(row.get("symbol")) for row in rounds if float(row.get("realized_pnl_krw") or 0.0) < 0}
    for row in orders:
        if row.get("side") == "BUY":
            by_symbol[str(row.get("symbol") or "")].append(row)
    patterns = []
    for sym, buys in by_symbol.items():
        if len(buys) < 2:
            continue
        buys = sorted(buys, key=lambda item: str(item.get("ordered_at") or ""))
        lower_adds = 0
        previous_price = None
        for row in buys:
            current_price = float(row.get("price") or 0.0)
            if previous_price is not None and current_price < previous_price:
                lower_adds += 1
            previous_price = current_price
        if lower_adds and sym in losing_symbols:
            patterns.append(
                _pattern(
                    "averaging_down_loss",
                    "failed" if lower_adds >= 2 else "warning",
                    sym,
                    f"{sym} shows averaging-down buys that later matched to losses.",
                    {"lower_price_add_count": lower_adds},
                )
            )
    return patterns


def _early_profit_taking(rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for trade in rounds:
        if float(trade.get("realized_pnl_krw") or 0.0) > 0 and (trade.get("holding_days") is not None):
            if float(trade.get("holding_days") or 0.0) <= 7:
                counter[str(trade.get("symbol") or "")] += 1
    return [
        _pattern(
            "early_profit_taking",
            "warning",
            sym,
            f"{sym} has winning trades closed within 7 days.",
            {"quick_winner_count": count},
        )
        for sym, count in counter.items()
        if sym and count >= 2
    ]


def _excessive_short_term(rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for trade in rounds:
        if trade.get("holding_days") is not None and float(trade.get("holding_days") or 0.0) <= 5:
            counter[str(trade.get("symbol") or "")] += 1
    return [
        _pattern(
            "excessive_short_term",
            "warning",
            sym,
            f"{sym} has many matched trades held 5 days or less.",
            {"short_term_round_count": count},
        )
        for sym, count in counter.items()
        if sym and count >= 4
    ]


def _leveraged_loss_patterns(by_symbol: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = []
    for row in by_symbol:
        sym = str(row.get("symbol") or "").upper()
        pnl = float(row.get("realized_pnl_krw") or 0.0)
        if sym in LEVERAGED_SYMBOLS and pnl < 0:
            patterns.append(
                _pattern(
                    "leveraged_loss",
                    "failed",
                    sym,
                    f"{sym} is a leveraged product with negative realized P/L.",
                    {"realized_pnl_krw": round(pnl, 2), "round_count": row.get("round_count")},
                )
            )
    return patterns


def _pattern(code: str, severity: str, symbol: str, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "symbol": symbol,
        "message": message,
        "evidence": evidence,
        "source": "Toss Order History getOrders - trade_pattern_miner.py",
    }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
