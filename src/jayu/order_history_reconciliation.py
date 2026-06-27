from __future__ import annotations

from typing import Any

from .holdings_reconciliation import reconcile_holdings_against_orders
from .realized_pnl_reconciliation import reconcile_realized_pnl


def reconcile_order_history(
    orders_payload: Any,
    holdings_payload: Any | None = None,
    tax_lots_payload: Any | None = None,
    *,
    usd_krw: float = 1350.0,
) -> dict[str, Any]:
    realized = reconcile_realized_pnl(
        orders_payload,
        tax_lots_payload,
        holdings_payload,
        usd_krw=usd_krw,
    )
    holdings = reconcile_holdings_against_orders(
        orders_payload,
        holdings_payload or [],
        tax_lots_payload,
        usd_krw=usd_krw,
    )
    status = "failed" if "failed" in {realized.get("status"), holdings.get("status")} else (
        "warning" if "warning" in {realized.get("status"), holdings.get("status")} else realized.get("status")
    )
    return {
        "status": status,
        "realized_pnl": realized,
        "holdings": holdings,
        "summary": {
            "realized_pnl_diff_krw": realized.get("summary", {}).get("realized_pnl_diff_krw"),
            "position_discrepancy_count": realized.get("summary", {}).get("position_discrepancy_count", 0),
            "holding_discrepancy_count": holdings.get("summary", {}).get("discrepancy_count", 0),
        },
        "source": "order_history_reconciliation.py - Toss orders vs tax lots vs holdings",
    }
