from __future__ import annotations


def lifecycle_orders() -> list[dict]:
    return [
        _order("aapl-buy", "AAPL", "BUY", 10, 100, "2026-01-01T09:30:00+09:00"),
        _order("aapl-sell", "AAPL", "SELL", 4, 130, "2026-02-01T09:30:00+09:00"),
        _order("tsla-buy", "TSLA", "BUY", 3, 200, "2026-02-05T09:30:00+09:00"),
        _order("meta-buy", "META", "BUY", 2, 300, "2026-03-01T09:30:00+09:00"),
        _order("meta-sell", "META", "SELL", 2, 320, "2026-03-10T09:30:00+09:00"),
        {
            "orderId": "qqq-cancel",
            "symbol": "QQQ",
            "side": "BUY",
            "status": "CANCELED",
            "price": "400",
            "quantity": "1",
            "currency": "USD",
            "orderedAt": "2026-03-11T09:30:00+09:00",
        },
    ]


def _order(order_id: str, symbol: str, side: str, qty: float, price: float, ordered_at: str) -> dict:
    return {
        "orderId": order_id,
        "symbol": symbol,
        "side": side,
        "status": "FILLED",
        "price": str(price),
        "quantity": str(qty),
        "currency": "USD",
        "orderedAt": ordered_at,
        "execution": {
            "filledQuantity": str(qty),
            "averageFilledPrice": str(price),
            "filledAmount": str(qty * price),
            "commission": "0",
            "tax": "0",
        },
    }


def test_realized_pnl_reconciliation_matches_tax_lots_and_holdings() -> None:
    from jayu.realized_pnl_reconciliation import reconcile_realized_pnl

    orders = [_order("buy", "AAPL", "BUY", 10, 100, "2026-01-01T09:30:00+09:00")]
    orders.append(_order("sell", "AAPL", "SELL", 4, 130, "2026-02-01T09:30:00+09:00"))
    tax_lots = [
        {
            "ticker": "AAPL",
            "quantity": 10,
            "remaining_quantity": 6,
            "unit_price": 100,
            "fx_rate": 1350,
            "currency": "USD",
        }
    ]
    holdings = [{"symbol": "AAPL", "quantity": 6, "average_price_krw": 135000}]

    report = reconcile_realized_pnl(orders, tax_lots, holdings, usd_krw=1350)

    assert report["status"] == "success"
    assert report["summary"]["order_open_symbol_count"] == 1
    assert report["summary"]["position_discrepancy_count"] == 0
    assert report["summary"]["order_realized_pnl_krw"] == 162000


def test_realized_pnl_reconciliation_flags_quantity_mismatch() -> None:
    from jayu.realized_pnl_reconciliation import reconcile_realized_pnl

    orders = [_order("buy", "AAPL", "BUY", 10, 100, "2026-01-01T09:30:00+09:00")]
    orders.append(_order("sell", "AAPL", "SELL", 4, 130, "2026-02-01T09:30:00+09:00"))
    tax_lots = [{"ticker": "AAPL", "remaining_quantity": 3, "unit_price": 100, "fx_rate": 1350}]
    holdings = [{"symbol": "AAPL", "quantity": 6, "average_price_krw": 135000}]

    report = reconcile_realized_pnl(orders, tax_lots, holdings, usd_krw=1350)

    assert report["status"] == "failed"
    assert report["summary"]["position_discrepancy_count"] == 1
    assert "order_tax_lot_quantity_mismatch" in report["position_discrepancies"][0]["issue_codes"]


def test_stock_trade_lifecycle_classifies_symbol_stages() -> None:
    from jayu.stock_trade_lifecycle import build_stock_trade_lifecycle

    report = build_stock_trade_lifecycle(
        lifecycle_orders(),
        holdings=[{"symbol": "AAPL", "quantity": 6}, {"symbol": "TSLA", "quantity": 3}],
        usd_krw=1350,
    )
    stages = {row["symbol"]: row["lifecycle_stage"] for row in report["symbols"]}

    assert report["status"] == "success"
    assert stages["AAPL"] == "trading_around"
    assert stages["TSLA"] == "accumulating"
    assert stages["META"] == "exited"
    assert stages["QQQ"] == "watch_only"
