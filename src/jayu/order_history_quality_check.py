from __future__ import annotations

from collections import Counter
from typing import Any

from .order_history_utils import (
    commission,
    currency,
    filled_amount,
    filled_quantity,
    is_filled,
    order_id,
    order_rows,
    parse_ordered_at,
    price,
    quantity,
    side,
    status,
    symbol,
    tax,
)


VALID_STATUS = {"OPEN", "FILLED", "PARTIAL_FILLED", "CANCELED", "REJECTED", "EXPIRED", "CLOSED"}
VALID_SIDE = {"BUY", "SELL"}
VALID_CURRENCY = {"KRW", "USD"}


def check_order_history_quality(orders_payload: Any) -> dict[str, Any]:
    orders = order_rows(orders_payload)
    issues: list[dict[str, Any]] = []
    seen_ids: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    currency_counts: Counter[str] = Counter()
    dates = []

    for idx, row in enumerate(orders):
        oid = order_id(row)
        sym = symbol(row)
        st = status(row)
        sd = side(row)
        cur = currency(row)
        ordered_at = parse_ordered_at(row.get("orderedAt") or row.get("ordered_at"))
        qty = quantity(row)
        filled_qty = filled_quantity(row)
        px = price(row)
        amount = filled_amount(row)

        if oid:
            seen_ids[oid] += 1
        else:
            _issue(issues, "missing_order_id", "warning", idx, sym, "Order id is missing.")
        if not sym:
            _issue(issues, "missing_symbol", "failed", idx, oid, "Symbol is missing.")
        if st not in VALID_STATUS:
            _issue(issues, "unknown_status", "warning", idx, oid or sym, f"Unknown status: {st or '-'}")
        if sd and sd not in VALID_SIDE:
            _issue(issues, "unknown_side", "warning", idx, oid or sym, f"Unknown side: {sd}")
        if cur not in VALID_CURRENCY:
            _issue(issues, "unknown_currency", "warning", idx, oid or sym, f"Unknown currency: {cur}")
        if ordered_at is None:
            _issue(issues, "missing_ordered_at", "failed", idx, oid or sym, "orderedAt is missing or invalid.")
        else:
            dates.append(ordered_at)
        if qty is not None and qty <= 0:
            _issue(issues, "non_positive_quantity", "failed", idx, oid or sym, "Quantity is not positive.")
        if px is not None and px <= 0:
            _issue(issues, "non_positive_price", "failed", idx, oid or sym, "Price is not positive.")
        if is_filled(row):
            if filled_qty is None or filled_qty <= 0:
                _issue(issues, "missing_filled_quantity", "warning", idx, oid or sym, "Filled quantity is missing.")
            if amount is None or amount <= 0:
                _issue(issues, "missing_filled_amount", "warning", idx, oid or sym, "Filled amount is missing.")
            if qty is not None and filled_qty is not None and filled_qty > qty:
                _issue(issues, "filled_quantity_exceeds_order", "failed", idx, oid or sym, "Filled quantity exceeds order quantity.")
            if commission(row) < 0 or tax(row) < 0:
                _issue(issues, "negative_cost", "failed", idx, oid or sym, "Commission or tax is negative.")

        status_counts[st or "UNKNOWN"] += 1
        currency_counts[cur or "UNKNOWN"] += 1

    for oid, count in seen_ids.items():
        if count > 1:
            _issue(issues, "duplicate_order_id", "failed", None, oid, f"Duplicate orderId appears {count} times.")

    failed_count = sum(1 for issue in issues if issue["severity"] == "failed")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    score = max(0, 100 - failed_count * 12 - warning_count * 4)
    status_label = "success" if score >= 90 else "warning" if score >= 70 else "failed"
    date_range = {
        "from": min(dates).date().isoformat() if dates else None,
        "to": max(dates).date().isoformat() if dates else None,
    }
    return {
        "status": status_label,
        "quality_score": score,
        "summary": {
            "order_count": len(orders),
            "unique_order_count": len(seen_ids),
            "duplicate_order_count": sum(count - 1 for count in seen_ids.values() if count > 1),
            "failed_issue_count": failed_count,
            "warning_issue_count": warning_count,
            "status_counts": dict(status_counts),
            "currency_counts": dict(currency_counts),
            "date_range": date_range,
        },
        "issues": issues[:100],
        "source": "state/toss_orders.json · Toss Order History getOrders",
    }


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    severity: str,
    index: int | None,
    ref: str,
    message: str,
) -> None:
    issues.append(
        {
            "code": code,
            "severity": severity,
            "index": index,
            "ref": ref or "-",
            "message": message,
        }
    )
