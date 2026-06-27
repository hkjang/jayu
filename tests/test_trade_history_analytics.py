from __future__ import annotations

import pytest


def sample_orders() -> list[dict]:
    return [
        {
            "orderId": "buy-aapl-1",
            "symbol": "AAPL",
            "side": "BUY",
            "status": "FILLED",
            "price": "100",
            "quantity": "10",
            "currency": "USD",
            "orderedAt": "2026-01-01T09:30:00+09:00",
            "execution": {
                "filledQuantity": "10",
                "averageFilledPrice": "100",
                "filledAmount": "1000",
                "commission": "1",
                "tax": "0",
            },
        },
        {
            "orderId": "buy-aapl-2",
            "symbol": "AAPL",
            "side": "BUY",
            "status": "FILLED",
            "price": "120",
            "quantity": "5",
            "currency": "USD",
            "orderedAt": "2026-02-01T09:30:00+09:00",
            "execution": {
                "filledQuantity": "5",
                "averageFilledPrice": "120",
                "filledAmount": "600",
                "commission": "1",
                "tax": "0",
            },
        },
        {
            "orderId": "sell-aapl-1",
            "symbol": "AAPL",
            "side": "SELL",
            "status": "FILLED",
            "price": "130",
            "quantity": "8",
            "currency": "USD",
            "orderedAt": "2026-03-01T09:30:00+09:00",
            "execution": {
                "filledQuantity": "8",
                "averageFilledPrice": "130",
                "filledAmount": "1040",
                "commission": "1",
                "tax": "0",
            },
        },
        {
            "orderId": "buy-soxl-1",
            "symbol": "SOXL",
            "side": "BUY",
            "status": "FILLED",
            "price": "20",
            "quantity": "3",
            "currency": "USD",
            "orderedAt": "2026-03-02T09:30:00+09:00",
            "execution": {
                "filledQuantity": "3",
                "averageFilledPrice": "20",
                "filledAmount": "60",
                "commission": "0.5",
                "tax": "0",
            },
        },
        {
            "orderId": "cancel-1",
            "symbol": "SOXL",
            "side": "BUY",
            "status": "CANCELED",
            "price": "21",
            "quantity": "3",
            "currency": "USD",
            "orderedAt": "2026-03-02T10:30:00+09:00",
        },
    ]


def test_order_history_quality_flags_duplicates_and_missing_fields() -> None:
    from jayu.order_history_quality_check import check_order_history_quality

    orders = sample_orders() + [{"orderId": "cancel-1", "symbol": "", "status": "FILLED"}]
    report = check_order_history_quality(orders)

    assert report["status"] in {"warning", "failed"}
    assert report["summary"]["order_count"] == 6
    assert report["summary"]["duplicate_order_count"] == 1
    assert any(issue["code"] == "duplicate_order_id" for issue in report["issues"])
    assert any(issue["code"] == "missing_symbol" for issue in report["issues"])


def test_trade_history_analytics_uses_fifo_realized_pnl() -> None:
    from jayu.trade_history_analytics import build_trade_history_analytics

    report = build_trade_history_analytics(sample_orders(), usd_krw=1350.0)
    summary = report["summary"]

    assert summary["trade_count"] == 4
    assert summary["buy_count"] == 3
    assert summary["sell_count"] == 1
    assert summary["total_buy_krw"] == pytest.approx(2241000.0)
    assert summary["total_sell_krw"] == pytest.approx(1404000.0)
    assert summary["realized_pnl_krw"] == pytest.approx(321570.0)
    assert summary["win_rate_pct"] == 100.0
    assert report["by_symbol"][0]["symbol"] == "AAPL"


def test_trade_behavior_review_flags_cancel_and_leverage_patterns() -> None:
    from jayu.trade_behavior_review import review_trade_behavior

    orders = sample_orders()
    for i in range(6):
        row = dict(orders[-1])
        row["orderId"] = f"cancel-extra-{i}"
        orders.append(row)
    report = review_trade_behavior(orders)

    assert report["status"] in {"warning", "failed"}
    assert report["summary"]["cancel_ratio_pct"] >= 25.0
    assert any(warning["code"] == "high_cancel_ratio" for warning in report["warnings"])
    assert report["summary"]["leveraged_trade_count"] == 1
