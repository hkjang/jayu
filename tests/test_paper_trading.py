from __future__ import annotations

import pytest

from jayu.execution import QuotedSpreadModel
from jayu.kill_switch import KillSwitch, KillSwitchConfig
from jayu.paper_trading import OrderIntent, PaperBroker, run_paper_session


def _switch(**overrides):
    return KillSwitch(KillSwitchConfig(**overrides), starting_equity=1_000_000.0)


def test_broker_crosses_spread_and_partial_fills():
    broker = PaperBroker(spread_model=QuotedSpreadModel(floor_rate=0.001), fill_ratio=0.5)
    filled, price = broker.fill(
        OrderIntent(
            ticker="SOXL",
            side="buy",
            quantity=100.0,
            decision_price=100.0,
            arrival_mid=100.0,
            final_price=101.0,
        )
    )
    assert filled == pytest.approx(50.0)  # 50% partial fill
    assert price > 100.0  # buy pays above the mid


def test_session_books_pnl_and_execution_quality():
    intents = [
        OrderIntent(
            ticker="SOXL",
            side="buy",
            quantity=100.0,
            decision_price=100.0,
            arrival_mid=100.0,
            final_price=103.0,
            latency_ms=50.0,
        ),
        OrderIntent(
            ticker="TQQQ",
            side="buy",
            quantity=50.0,
            decision_price=50.0,
            arrival_mid=50.0,
            final_price=52.0,
        ),
    ]

    report = run_paper_session(intents, starting_equity=1_000_000.0, kill_switch=_switch())

    assert report["orders_filled"] == 2
    assert report["orders_blocked"] == 0
    assert report["ending_equity"] > report["starting_equity"]  # both winners
    assert report["realized_pnl"] > 0
    assert report["execution_quality"]["orders"] == 2
    assert report["kill_switch"]["tripped"] is False


def test_kill_switch_blocks_remaining_orders_after_trip():
    # First order loses ~5% of equity -> trips the 3% daily-loss limit;
    # the second order is then blocked.
    intents = [
        OrderIntent(
            ticker="SOXL",
            side="buy",
            quantity=100_000.0,
            decision_price=100.0,
            arrival_mid=100.0,
            final_price=99.5,  # -0.5 * 100k = -50k = -5% of 1M
        ),
        OrderIntent(
            ticker="TQQQ",
            side="buy",
            quantity=10.0,
            decision_price=50.0,
            arrival_mid=50.0,
            final_price=55.0,
        ),
    ]

    report = run_paper_session(
        intents,
        starting_equity=1_000_000.0,
        kill_switch=_switch(max_daily_loss_pct=0.03),
    )

    assert report["orders_filled"] == 1
    assert report["orders_blocked"] == 1
    assert report["kill_switch"]["tripped"] is True
    assert "daily_loss_limit" in report["kill_switch"]["reasons"]
    blocked = [fill for fill in report["fills"] if fill["status"] == "blocked"]
    assert blocked and "daily_loss_limit" in blocked[0]["reasons"]


def test_sell_side_pnl_and_shortfall():
    intent = OrderIntent(
        ticker="SOXL",
        side="sell",
        quantity=100.0,
        decision_price=100.0,
        arrival_mid=100.0,
        final_price=98.0,  # price fell after we sold -> a gain for a short
    )

    report = run_paper_session([intent], starting_equity=1_000_000.0, kill_switch=_switch())

    assert report["orders_filled"] == 1
    assert report["realized_pnl"] > 0  # sold high, covered low
    # Sell fills at/below mid (hit the bid).
    fill = report["fills"][0]
    assert fill["fill_price"] <= 100.0
