from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .order_history_utils import (
    KRW_PER_USD_FALLBACK,
    amount_krw,
    filled_quantity,
    first_number,
    first_text,
    is_filled,
    order_id,
    order_rows,
    parse_ordered_at,
    quantity,
    side,
    status,
    symbol,
)


def build_stock_trade_lifecycle(
    orders_payload: Any,
    holdings: Any | None = None,
    *,
    usd_krw: float = KRW_PER_USD_FALLBACK,
) -> dict[str, Any]:
    rows = sorted(
        order_rows(orders_payload),
        key=lambda row: str(row.get("orderedAt") or row.get("ordered_at") or ""),
    )
    holding_quantities = _holding_quantities(holdings)
    buckets: dict[str, dict[str, Any]] = defaultdict(_bucket)

    for row in rows:
        sym = symbol(row)
        if not sym:
            continue
        bucket = buckets[sym]
        bucket["symbol"] = sym
        sd = side(row)
        st = status(row)
        dt = parse_ordered_at(row.get("orderedAt") or row.get("ordered_at"))
        qty = filled_quantity(row) or quantity(row) or 0.0
        amount = amount_krw(row, usd_krw=usd_krw) or 0.0
        event = {
            "ordered_at": dt.isoformat() if dt else row.get("orderedAt") or row.get("ordered_at"),
            "order_id": order_id(row),
            "side": sd,
            "status": st,
            "quantity": _round(qty, 6),
            "amount_krw": _round(amount, 2),
        }
        bucket["events"].append(event)
        bucket["event_count"] += 1
        bucket["last_activity_at"] = event["ordered_at"] or bucket["last_activity_at"]
        if st in {"CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}:
            bucket["canceled_count"] += 1
            continue
        if not is_filled(row):
            bucket["open_or_pending_count"] += 1
            continue
        if sd == "BUY":
            bucket["buy_count"] += 1
            bucket["total_buy_krw"] += amount
            bucket["net_quantity"] += qty
            bucket["first_buy_at"] = bucket["first_buy_at"] or event["ordered_at"]
            bucket["last_buy_at"] = event["ordered_at"]
        elif sd == "SELL":
            bucket["sell_count"] += 1
            bucket["total_sell_krw"] += amount
            bucket["net_quantity"] -= qty
            bucket["last_sell_at"] = event["ordered_at"]

    for sym, holding_qty in holding_quantities.items():
        bucket = buckets[sym]
        bucket["symbol"] = sym
        bucket["holding_quantity"] = holding_qty

    lifecycles = []
    for sym, bucket in buckets.items():
        row = dict(bucket)
        holding_qty = holding_quantities.get(sym)
        row["holding_quantity"] = _round(holding_qty, 6) if holding_qty is not None else None
        row["currently_holding"] = bool(
            (holding_qty is not None and holding_qty > 1e-9) or row["net_quantity"] > 1e-9
        )
        row["lifecycle_stage"] = _stage(row)
        row["net_quantity"] = _round(row["net_quantity"], 6)
        row["total_buy_krw"] = _round(row["total_buy_krw"], 2)
        row["total_sell_krw"] = _round(row["total_sell_krw"], 2)
        row["events"] = sorted(row["events"], key=lambda item: str(item.get("ordered_at") or ""), reverse=True)[:20]
        lifecycles.append(row)

    lifecycles.sort(key=lambda item: str(item.get("last_activity_at") or ""), reverse=True)
    stage_counts: dict[str, int] = defaultdict(int)
    for item in lifecycles:
        stage_counts[item["lifecycle_stage"]] += 1

    return {
        "status": "success" if lifecycles else "not_evaluated",
        "summary": {
            "symbol_count": len(lifecycles),
            "currently_holding_count": sum(1 for item in lifecycles if item["currently_holding"]),
            "exited_count": stage_counts.get("exited", 0),
            "accumulating_count": stage_counts.get("accumulating", 0),
            "trading_around_count": stage_counts.get("trading_around", 0),
            "watch_only_count": stage_counts.get("watch_only", 0),
        },
        "stage_counts": dict(sorted(stage_counts.items())),
        "symbols": lifecycles,
        "source": "state/toss_orders.json · Toss Order History getOrders · Toss holdings",
        "assumptions": {
            "usd_krw": usd_krw,
            "stage_method": "BUY/SELL/cancel event counts plus current holding quantity when supplied",
        },
    }


def _bucket() -> dict[str, Any]:
    return {
        "symbol": "",
        "event_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "canceled_count": 0,
        "open_or_pending_count": 0,
        "total_buy_krw": 0.0,
        "total_sell_krw": 0.0,
        "net_quantity": 0.0,
        "holding_quantity": None,
        "first_buy_at": None,
        "last_buy_at": None,
        "last_sell_at": None,
        "last_activity_at": None,
        "events": [],
    }


def _stage(row: Mapping[str, Any]) -> str:
    if row.get("currently_holding"):
        return "trading_around" if int(row.get("sell_count") or 0) else "accumulating"
    if int(row.get("buy_count") or 0) and int(row.get("sell_count") or 0):
        return "exited"
    if int(row.get("buy_count") or 0):
        return "zero_position"
    return "watch_only"


def _holding_quantities(payload: Any) -> dict[str, float]:
    quantities: dict[str, float] = {}
    for row in _generic_rows(payload):
        sym = first_text(row, "symbol", "ticker", "stockCode", "stock_code").upper()
        if not sym:
            continue
        qty = first_number(
            row,
            "quantity",
            "qty",
            "holding_quantity",
            "holdingQuantity",
            "balance_quantity",
            "balanceQuantity",
        )
        if qty is not None:
            quantities[sym] = quantities.get(sym, 0.0) + qty
    return quantities


def _generic_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("holdings", "positions", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return [dict(item) for item in value if isinstance(item, Mapping)]
            if isinstance(value, Mapping):
                nested = _generic_rows(value)
                if nested:
                    return nested
        if any(key in payload for key in ("symbol", "ticker", "stockCode", "quantity")):
            return [dict(payload)]
        return []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _round(value: float, digits: int) -> float:
    return round(float(value), digits)
