from __future__ import annotations

from typing import Any

from .order_history_utils import (
    KRW_PER_USD_FALLBACK,
    amount_krw,
    commission,
    currency,
    filled_quantity,
    is_filled,
    order_id,
    order_rows,
    price,
    quantity,
    side,
    symbol,
    tax,
    to_float,
)


def analyze_execution_quality_from_orders(
    orders_payload: Any,
    *,
    usd_krw: float = KRW_PER_USD_FALLBACK,
) -> dict[str, Any]:
    rows = []
    for row in order_rows(orders_payload):
        if not is_filled(row):
            continue
        sym = symbol(row)
        qty = filled_quantity(row) or quantity(row)
        px = price(row)
        amount = amount_krw(row, usd_krw=usd_krw)
        if not sym or qty is None or px is None or amount is None or qty <= 0 or px <= 0:
            continue
        cur = currency(row)
        costs = _to_krw(commission(row) + tax(row), cur, usd_krw)
        fee_bps = costs / max(amount, 1.0) * 10000.0
        reference_price = _reference_price(row)
        slippage_bps = None
        if reference_price and reference_price > 0:
            raw = (px - reference_price) / reference_price * 10000.0
            slippage_bps = raw if side(row) == "BUY" else -raw
        rows.append(
            {
                "order_id": order_id(row),
                "symbol": sym,
                "side": side(row),
                "price": round(px, 6),
                "quantity": round(qty, 6),
                "amount_krw": round(amount, 2),
                "fee_bps": round(fee_bps, 2),
                "slippage_bps": round(slippage_bps, 2) if slippage_bps is not None else None,
            }
        )
    fee_values = [float(row["fee_bps"]) for row in rows]
    slippage_values = [float(row["slippage_bps"]) for row in rows if row.get("slippage_bps") is not None]
    high_fee_orders = [row for row in rows if float(row.get("fee_bps") or 0.0) >= 30.0]
    adverse_slippage = [row for row in rows if row.get("slippage_bps") is not None and float(row["slippage_bps"]) >= 20.0]
    status = "failed" if adverse_slippage else "warning" if high_fee_orders else "success" if rows else "not_evaluated"
    return {
        "status": status,
        "summary": {
            "order_count": len(rows),
            "avg_fee_bps": round(sum(fee_values) / len(fee_values), 2) if fee_values else None,
            "avg_slippage_bps": round(sum(slippage_values) / len(slippage_values), 2) if slippage_values else None,
            "high_fee_order_count": len(high_fee_orders),
            "adverse_slippage_order_count": len(adverse_slippage),
        },
        "orders": rows,
        "high_fee_orders": high_fee_orders[:20],
        "adverse_slippage_orders": adverse_slippage[:20],
        "source": "Toss Order History getOrders/getOrder - execution_quality_from_orders.py",
        "assumptions": {
            "reference_price": "uses arrivalMid, marketPrice, referencePrice, or close when present; otherwise fee-only quality",
            "usd_krw": usd_krw,
        },
    }


def _reference_price(row: dict[str, Any]) -> float | None:
    for key in ("arrivalMid", "arrival_mid", "marketPrice", "market_price", "referencePrice", "reference_price", "close"):
        value = to_float(row.get(key))
        if value is not None:
            return value
    return None


def _to_krw(value: float, cur: str, usd_krw: float) -> float:
    return value * usd_krw if cur == "USD" else value
