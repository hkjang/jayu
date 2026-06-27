from __future__ import annotations

from typing import Any

from .realized_pnl_reconciliation import reconcile_realized_pnl


def reconcile_holdings_against_orders(
    orders_payload: Any,
    holdings_payload: Any,
    tax_lots_payload: Any | None = None,
    *,
    usd_krw: float = 1350.0,
) -> dict[str, Any]:
    report = reconcile_realized_pnl(
        orders_payload,
        tax_lots_payload,
        holdings_payload,
        usd_krw=usd_krw,
    )
    discrepancies = report.get("position_discrepancies", [])
    return {
        "status": report.get("status"),
        "summary": {
            "holding_symbol_count": report.get("summary", {}).get("holding_symbol_count", 0),
            "order_open_symbol_count": report.get("summary", {}).get("order_open_symbol_count", 0),
            "tax_lot_open_symbol_count": report.get("summary", {}).get("tax_lot_open_symbol_count", 0),
            "discrepancy_count": len(discrepancies),
            "failed_discrepancy_count": sum(
                1 for item in discrepancies if item.get("severity") == "failed"
            ),
        },
        "discrepancies": discrepancies,
        "source": "holdings_reconciliation.py - orders vs tax lots vs Toss holdings",
    }
