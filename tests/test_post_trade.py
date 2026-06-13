from __future__ import annotations

import pytest

from jayu.post_trade import (
    aggregate_execution_quality,
    implementation_shortfall,
    interval_vwap,
)


def test_full_fill_buy_decomposes_additively():
    record = implementation_shortfall(
        side="buy",
        decision_price=100.0,
        arrival_price=100.5,
        fill_price=101.0,
        final_price=103.0,
        target_quantity=100.0,
        filled_quantity=100.0,
        interval_vwap=100.8,
    )

    assert record["delay_cost_bps"] == pytest.approx(50.0)  # 100 -> 100.5
    assert record["impact_cost_bps"] == pytest.approx(50.0)  # 100.5 -> 101
    # delay + impact == realised (fully filled).
    assert record["realised_cost_bps"] == pytest.approx(100.0)
    assert record["opportunity_cost_bps"] == pytest.approx(0.0)
    assert record["implementation_shortfall_bps"] == pytest.approx(100.0)
    # Paid 20 bps above the interval VWAP.
    assert record["vs_vwap_bps"] == pytest.approx(20.0)


def test_partial_fill_adds_missed_alpha():
    record = implementation_shortfall(
        side="buy",
        decision_price=100.0,
        arrival_price=100.0,
        fill_price=101.0,
        final_price=103.0,
        target_quantity=100.0,
        filled_quantity=60.0,
    )

    assert record["fill_rate"] == pytest.approx(0.6)
    # realised = 100 bps * 0.6 = 60 bps; opportunity = 300 bps * 0.4 = 120 bps.
    assert record["realised_cost_bps"] == pytest.approx(60.0)
    assert record["opportunity_cost_bps"] == pytest.approx(120.0)
    assert record["missed_alpha"] == record["opportunity_cost"]
    assert record["implementation_shortfall_bps"] == pytest.approx(180.0)


def test_sell_side_sign_flips():
    # A sell that gets hit DOWN from decision is a cost (positive).
    record = implementation_shortfall(
        side="sell",
        decision_price=100.0,
        arrival_price=99.5,
        fill_price=99.0,
        final_price=97.0,
        target_quantity=100.0,
        filled_quantity=100.0,
    )

    assert record["delay_cost_bps"] == pytest.approx(50.0)  # sold lower -> cost
    assert record["impact_cost_bps"] == pytest.approx(50.0)
    assert record["implementation_shortfall_bps"] == pytest.approx(100.0)


def test_favourable_execution_is_negative_cost():
    # A buy filled BELOW decision is a gain (negative cost).
    record = implementation_shortfall(
        side="buy",
        decision_price=100.0,
        arrival_price=99.5,
        fill_price=99.0,
        final_price=99.0,
        target_quantity=100.0,
        filled_quantity=100.0,
    )
    assert record["implementation_shortfall_bps"] < 0


def test_input_validation():
    with pytest.raises(ValueError):
        implementation_shortfall(
            side="buy",
            decision_price=0.0,
            arrival_price=1.0,
            fill_price=1.0,
            final_price=1.0,
            target_quantity=1.0,
            filled_quantity=1.0,
        )
    with pytest.raises(ValueError):
        implementation_shortfall(
            side="buy",
            decision_price=100.0,
            arrival_price=100.0,
            fill_price=100.0,
            final_price=100.0,
            target_quantity=100.0,
            filled_quantity=200.0,  # > target
        )


def test_interval_vwap_weights_by_volume():
    assert interval_vwap([10.0, 20.0], [1.0, 3.0]) == pytest.approx(17.5)
    # Zero volume falls back to simple mean.
    assert interval_vwap([10.0, 20.0], [0.0, 0.0]) == pytest.approx(15.0)


def test_aggregate_execution_quality():
    records = [
        implementation_shortfall(
            side="buy",
            decision_price=100.0,
            arrival_price=100.0,
            fill_price=101.0,
            final_price=101.0,
            target_quantity=100.0,
            filled_quantity=100.0,
            interval_vwap=100.5,
        ),
        implementation_shortfall(
            side="buy",
            decision_price=100.0,
            arrival_price=100.0,
            fill_price=100.0,
            final_price=100.0,
            target_quantity=100.0,
            filled_quantity=50.0,
        ),
    ]

    summary = aggregate_execution_quality(records)

    assert summary["orders"] == 2
    assert summary["avg_fill_rate"] == pytest.approx(0.75)
    # Only the first record carried a VWAP benchmark.
    assert summary["avg_vs_vwap_bps"] is not None
    assert aggregate_execution_quality([]) == {"orders": 0}
