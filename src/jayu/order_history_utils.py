from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


KRW_PER_USD_FALLBACK = 1350.0


def order_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("orders", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return [dict(item) for item in value if isinstance(item, Mapping)]
            if isinstance(value, Mapping):
                nested = order_rows(value)
                if nested:
                    return nested
        if payload.get("orderId") or payload.get("symbol"):
            return [dict(payload)]
        return []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def first_text(row: Mapping[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        num = to_float(value)
        if num is not None:
            return num
    return None


def nested_number(row: Mapping[str, Any], parent: str, *keys: str) -> float | None:
    value = row.get(parent)
    if not isinstance(value, Mapping):
        return None
    return first_number(value, *keys)


def nested_text(row: Mapping[str, Any], parent: str, *keys: str, default: str = "") -> str:
    value = row.get(parent)
    if not isinstance(value, Mapping):
        return default
    return first_text(value, *keys, default=default)


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_ordered_at(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def symbol(row: Mapping[str, Any]) -> str:
    return first_text(row, "symbol", "ticker", "stockCode", "stock_code").upper()


def side(row: Mapping[str, Any]) -> str:
    return first_text(row, "side", "orderSide").upper()


def status(row: Mapping[str, Any]) -> str:
    return first_text(row, "status", "historyStatus", "orderStatus").upper()


def currency(row: Mapping[str, Any]) -> str:
    return first_text(row, "currency", default="KRW").upper()


def quantity(row: Mapping[str, Any]) -> float | None:
    return first_number(row, "quantity", "orderQuantity", "qty")


def filled_quantity(row: Mapping[str, Any]) -> float | None:
    return nested_number(row, "execution", "filledQuantity", "filled_quantity") or first_number(
        row,
        "filledQuantity",
        "filled_quantity",
    )


def price(row: Mapping[str, Any]) -> float | None:
    return (
        nested_number(row, "execution", "averageFilledPrice", "average_filled_price")
        or first_number(row, "price", "orderPrice")
        or first_number(row, "averageFilledPrice", "average_filled_price")
    )


def filled_amount(row: Mapping[str, Any]) -> float | None:
    return nested_number(row, "execution", "filledAmount", "filled_amount") or first_number(
        row,
        "filledAmount",
        "filled_amount",
        "orderAmount",
    )


def commission(row: Mapping[str, Any]) -> float:
    return (
        nested_number(row, "execution", "commission", "fee")
        or first_number(row, "commission", "fee")
        or 0.0
    )


def tax(row: Mapping[str, Any]) -> float:
    return nested_number(row, "execution", "tax") or first_number(row, "tax") or 0.0


def is_filled(row: Mapping[str, Any]) -> bool:
    return status(row) in {"FILLED", "PARTIAL_FILLED", "CLOSED"}


def order_amount(row: Mapping[str, Any]) -> float | None:
    amount = filled_amount(row)
    if amount is not None:
        return amount
    px = price(row)
    qty = filled_quantity(row) or quantity(row)
    if px is None or qty is None:
        return None
    return px * qty


def amount_krw(row: Mapping[str, Any], *, usd_krw: float = KRW_PER_USD_FALLBACK) -> float | None:
    amount = order_amount(row)
    if amount is None:
        return None
    return amount * usd_krw if currency(row) == "USD" else amount


def order_id(row: Mapping[str, Any]) -> str:
    return first_text(row, "orderId", "order_id", "id")
