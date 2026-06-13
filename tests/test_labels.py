from __future__ import annotations

import pandas as pd
import pytest

from jayu.labels import (
    BarrierConfig,
    effective_barriers,
    label_summary,
    triple_barrier_labels,
)


def _ohlc(rows):
    """rows: list of (Open, High, Low, Close)."""
    index = pd.RangeIndex(len(rows))
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=index)


def test_config_validation():
    with pytest.raises(ValueError):
        BarrierConfig(upper_pct=0, lower_pct=0.02, max_holding=5)
    with pytest.raises(ValueError):
        BarrierConfig(upper_pct=0.03, lower_pct=0.02, max_holding=0)
    with pytest.raises(ValueError):
        BarrierConfig(upper_pct=0.03, lower_pct=0.02, max_holding=5, side=2)


def test_effective_barriers_are_cost_floored():
    config = BarrierConfig(
        upper_pct=0.01, lower_pct=0.005, max_holding=5, cost_pct=0.02, barrier_cost_multiple=1.0
    )
    upper, lower = effective_barriers(config)
    # Both widened up to the 2% cost floor (spread-aware): no barrier inside costs.
    assert upper == pytest.approx(0.02)
    assert lower == pytest.approx(0.02)


def test_profit_barrier_hit_first_labels_plus_one():
    # Bar 1 spikes high enough to touch the +3% profit barrier.
    frame = _ohlc([(100, 100, 100, 100), (101, 104, 100, 103), (103, 103, 103, 103)])
    config = BarrierConfig(upper_pct=0.03, lower_pct=0.05, max_holding=2)

    labels = triple_barrier_labels(frame, [0], config)
    row = labels.iloc[0]

    assert row["label"] == 1
    assert row["barrier"] == "profit"
    assert row["exit_price"] == pytest.approx(103.0)  # entry 100 * 1.03
    assert row["holding_bars"] == 1


def test_stop_barrier_hit_first_labels_minus_one():
    frame = _ohlc([(100, 100, 100, 100), (99, 100, 94, 95), (95, 95, 95, 95)])
    config = BarrierConfig(upper_pct=0.10, lower_pct=0.05, max_holding=2)

    row = triple_barrier_labels(frame, [0], config).iloc[0]

    assert row["label"] == -1
    assert row["barrier"] == "stop"
    assert row["exit_price"] == pytest.approx(95.0)  # entry 100 * 0.95


def test_vertical_barrier_labels_zero_or_sign():
    # Price drifts but never touches either barrier within the horizon.
    frame = _ohlc([(100, 100, 100, 100), (100, 101, 99, 100.5), (100, 101, 100, 101)])
    base = dict(upper_pct=0.10, lower_pct=0.10, max_holding=2)

    zero = triple_barrier_labels(frame, [0], BarrierConfig(**base)).iloc[0]
    assert zero["barrier"] == "vertical"
    assert zero["label"] == 0

    signed = triple_barrier_labels(frame, [0], BarrierConfig(**base, vertical_zero=False)).iloc[0]
    assert signed["barrier"] == "vertical"
    assert signed["label"] == 1  # net return positive at the time barrier


def test_tie_breaker_prefers_stop_by_default():
    # Bar 1 touches BOTH +3% and -3% in the same bar.
    frame = _ohlc([(100, 100, 100, 100), (100, 104, 96, 100)])
    conservative = BarrierConfig(upper_pct=0.03, lower_pct=0.03, max_holding=1)
    optimistic = BarrierConfig(upper_pct=0.03, lower_pct=0.03, max_holding=1, tie_breaker="profit")

    assert triple_barrier_labels(frame, [0], conservative).iloc[0]["barrier"] == "stop"
    assert triple_barrier_labels(frame, [0], optimistic).iloc[0]["barrier"] == "profit"


def test_short_side_mirrors_direction():
    # Price falls 3%: a profit for a short.
    frame = _ohlc([(100, 100, 100, 100), (99, 100, 96, 97)])
    config = BarrierConfig(upper_pct=0.03, lower_pct=0.10, max_holding=1, side=-1)

    row = triple_barrier_labels(frame, [0], config).iloc[0]

    assert row["label"] == 1
    assert row["barrier"] == "profit"
    assert row["gross_return"] == pytest.approx(0.03)  # short gains as price drops


def test_spread_aware_plus_one_is_net_nonnegative():
    # Cost 1% floors both barriers to >=1%; a +1 must clear that cost.
    frame = _ohlc([(100, 100, 100, 100), (100, 106, 100, 105)])
    config = BarrierConfig(
        upper_pct=0.005, lower_pct=0.005, max_holding=1, cost_pct=0.01, barrier_cost_multiple=2.0
    )

    row = triple_barrier_labels(frame, [0], config).iloc[0]

    assert row["label"] == 1
    # barrier floored to 2 * 1% = 2%, so gross >= 2% and net = gross - 1% >= 0.
    assert row["gross_return"] >= 0.02 - 1e-9
    assert row["net_return"] >= 0.0


def test_close_only_series_input():
    series = pd.Series([100, 100, 103.5], index=pd.RangeIndex(3))
    config = BarrierConfig(upper_pct=0.03, lower_pct=0.05, max_holding=2)

    row = triple_barrier_labels(series, [0], config).iloc[0]

    # No High/Low: close crossing the profit barrier at bar 2 triggers +1.
    assert row["label"] == 1
    assert row["barrier"] == "profit"


def test_label_summary_aggregates():
    frame = _ohlc(
        [
            (100, 100, 100, 100),
            (100, 104, 100, 103),  # event 0 -> profit
            (100, 100, 94, 95),  # event 1 entry
            (95, 95, 89, 90),  # -> stop
        ]
    )
    config = BarrierConfig(upper_pct=0.03, lower_pct=0.03, max_holding=1)

    labels = triple_barrier_labels(frame, [0, 2], config)
    summary = label_summary(labels)

    assert summary["events"] == 2
    assert summary["counts"]["profit"] == 1
    assert summary["counts"]["stop"] == 1
    assert summary["hit_rate"] == 0.5
