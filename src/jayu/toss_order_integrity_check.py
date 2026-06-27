from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .api_response_contracts import validate_api_response_contract
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


def check_toss_order_integrity(
    orders_payload: Any,
    *,
    expected_from: str | None = None,
    expected_to: str | None = None,
) -> dict[str, Any]:
    rows = order_rows(orders_payload)
    contract = validate_api_response_contract(
        "orders",
        rows,
        provider="toss",
        source="Toss Order History getOrders - GET /api/v1/orders",
    )
    issues = [dict(item) for item in contract.get("violations", [])]
    seen_ids: Counter[str] = Counter()
    account_refs: Counter[str] = Counter()
    dates = []

    for index, row in enumerate(rows):
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
        account_ref = _account_ref(row)

        if oid:
            seen_ids[oid] += 1
        if account_ref:
            account_refs[account_ref] += 1
        if ordered_at is not None:
            dates.append(ordered_at)
        if is_filled(row):
            if filled_qty is None or filled_qty <= 0:
                _issue(issues, "missing_execution_quantity", "failed", index, oid or sym, "Filled order has no positive filled quantity.")
            if amount is None or amount <= 0:
                _issue(issues, "missing_execution_amount", "failed", index, oid or sym, "Filled order has no positive filled amount.")
            if qty is not None and filled_qty is not None and filled_qty - qty > 1e-9:
                _issue(issues, "filled_quantity_exceeds_order", "failed", index, oid or sym, "Filled quantity exceeds order quantity.")
            if px is not None and filled_qty is not None and amount is not None:
                expected = px * filled_qty
                tolerance = max(1.0, expected * 0.005)
                if abs(amount - expected) > tolerance:
                    _issue(
                        issues,
                        "filled_amount_mismatch",
                        "failed",
                        index,
                        oid or sym,
                        f"filledAmount {amount:g} differs from price*filledQuantity {expected:g}.",
                    )
            if commission(row) < 0 or tax(row) < 0:
                _issue(issues, "negative_fee_or_tax", "failed", index, oid or sym, "Commission or tax is negative.")
        if st in {"CANCELED", "CANCELLED"} and not (row.get("canceledAt") or row.get("canceled_at")):
            _issue(issues, "missing_canceled_at", "warning", index, oid or sym, "Canceled order has no canceledAt timestamp.")
        if sd not in {"BUY", "SELL"}:
            _issue(issues, "unknown_side", "warning", index, oid or sym, f"Unknown side: {sd or '-'}")
        if cur not in {"KRW", "USD"}:
            _issue(issues, "unknown_currency", "warning", index, oid or sym, f"Unknown currency: {cur or '-'}")

    for oid, count in seen_ids.items():
        if count > 1:
            _issue(issues, "duplicate_order_id", "failed", None, oid, f"Duplicate orderId appears {count} times.")

    if len(account_refs) > 1:
        _issue(
            issues,
            "multiple_account_refs",
            "warning",
            None,
            ", ".join(sorted(account_refs)),
            "Order history contains more than one account reference.",
        )

    _check_expected_coverage(issues, dates, expected_from=expected_from, expected_to=expected_to)

    if not rows:
        return {
            "status": "not_evaluated",
            "integrity_score": 75,
            "summary": {
                "order_count": 0,
                "unique_order_count": 0,
                "duplicate_order_count": 0,
                "account_ref_count": 0,
                "failed_issue_count": 0,
                "warning_issue_count": 0,
                "date_range": {"from": None, "to": None},
                "expected_range": {"from": expected_from, "to": expected_to},
            },
            "contract": contract,
            "issues": [],
            "source": "state/toss_orders.json - Toss Order History getOrders",
        }

    failed_count = sum(1 for item in issues if item.get("severity") == "failed")
    warning_count = sum(1 for item in issues if item.get("severity") == "warning")
    score = max(0, 100 - failed_count * 10 - warning_count * 3)
    status_label = "failed" if failed_count else "success" if score >= 90 else "warning"
    return {
        "status": status_label,
        "integrity_score": score,
        "summary": {
            "order_count": len(rows),
            "unique_order_count": len(seen_ids),
            "duplicate_order_count": sum(count - 1 for count in seen_ids.values() if count > 1),
            "account_ref_count": len(account_refs),
            "failed_issue_count": failed_count,
            "warning_issue_count": warning_count,
            "date_range": {
                "from": min(dates).date().isoformat() if dates else None,
                "to": max(dates).date().isoformat() if dates else None,
            },
            "expected_range": {"from": expected_from, "to": expected_to},
        },
        "contract": contract,
        "issues": issues[:150],
        "source": "state/toss_orders.json - Toss Order History getOrders",
    }


def _check_expected_coverage(
    issues: list[dict[str, Any]],
    dates: list[datetime],
    *,
    expected_from: str | None,
    expected_to: str | None,
) -> None:
    if not dates or not (expected_from or expected_to):
        return
    earliest = min(dates).date().isoformat()
    latest = max(dates).date().isoformat()
    if expected_from and earliest > expected_from:
        _issue(issues, "order_history_starts_late", "warning", None, earliest, f"Expected orders from {expected_from}, first cached order is {earliest}.")
    if expected_to and latest < expected_to:
        _issue(issues, "order_history_ends_early", "warning", None, latest, f"Expected orders through {expected_to}, last cached order is {latest}.")


def _account_ref(row: dict[str, Any]) -> str:
    for key in ("accountSeq", "account_seq", "accountNo", "account_no"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


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
