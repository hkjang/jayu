from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def quarantine_outliers(
    rows_payload: Any,
    *,
    dataset: str,
    max_abs_return: float = 0.50,
    amount_limit: float | None = None,
) -> dict[str, Any]:
    rows = _rows(rows_payload)
    verified = []
    quarantined = []
    previous_by_symbol: dict[str, float] = {}
    for index, row in enumerate(rows):
        symbol = _text(row, "symbol", "ticker", "stockCode").upper() or "-"
        price = _number(row.get("close") or row.get("Close") or row.get("price"))
        amount = _number(row.get("amount") or row.get("filledAmount") or row.get("orderAmount"))
        reasons = []
        if price is not None and price <= 0:
            reasons.append("non_positive_price")
        if amount_limit is not None and amount is not None and abs(amount) > amount_limit:
            reasons.append("amount_exceeds_limit")
        previous = previous_by_symbol.get(symbol)
        if previous is not None and price is not None and previous > 0:
            abs_return = abs(price / previous - 1.0)
            if abs_return > max_abs_return:
                reasons.append("price_jump_outlier")
        if price is not None and price > 0:
            previous_by_symbol[symbol] = price
        item = {"index": index, "symbol": symbol, "row": dict(row), "reasons": reasons}
        if reasons:
            quarantined.append(item)
        else:
            verified.append(dict(row))
    return {
        "status": "warning" if quarantined else "success",
        "summary": {
            "row_count": len(rows),
            "verified_count": len(verified),
            "quarantined_count": len(quarantined),
        },
        "verified": verified,
        "quarantined": quarantined[:200],
        "source": f"outlier_quarantine.py - {dataset}",
    }


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        for key in ("rows", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return [dict(item) for item in value if isinstance(item, Mapping)]
        return [dict(payload)]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
