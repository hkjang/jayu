from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jayu.microstructure import (
    add_microstructure_features,
    classify_spread_regime,
    microprice,
    midpoint,
    order_flow_imbalance,
    queue_imbalance,
    relative_spread,
    signed_volume_imbalance,
    tick_rule_sign,
)


def test_midpoint_and_relative_spread():
    bid = pd.Series([10.0, 20.0])
    ask = pd.Series([10.1, 20.2])
    assert list(midpoint(bid, ask)) == [10.05, 20.1]
    rel = relative_spread(bid, ask)
    assert rel.iloc[0] == pytest.approx(0.1 / 10.05)


def test_microprice_leans_toward_heavier_side():
    bid = pd.Series([10.0])
    ask = pd.Series([10.10])
    # Bid depth dominates -> buyers likely lift the offer -> microprice > mid.
    heavy_bid = microprice(bid, ask, pd.Series([300.0]), pd.Series([100.0]))
    assert heavy_bid.iloc[0] == pytest.approx(10.075)
    assert heavy_bid.iloc[0] > midpoint(bid, ask).iloc[0]
    # Symmetric depth -> microprice equals the midpoint.
    balanced = microprice(bid, ask, pd.Series([100.0]), pd.Series([100.0]))
    assert balanced.iloc[0] == pytest.approx(10.05)


def test_microprice_falls_back_to_mid_on_zero_size():
    out = microprice(pd.Series([10.0]), pd.Series([10.1]), pd.Series([0.0]), pd.Series([0.0]))
    assert out.iloc[0] == pytest.approx(10.05)


def test_queue_imbalance_bounds():
    qi = queue_imbalance(pd.Series([300.0, 0.0, 100.0]), pd.Series([100.0, 100.0, 100.0]))
    assert qi.iloc[0] == pytest.approx(0.5)
    assert qi.iloc[1] == pytest.approx(-1.0)
    assert qi.iloc[2] == pytest.approx(0.0)


def test_order_flow_imbalance_signs():
    # Bid rises (buy pressure) then ask falls (sell pressure).
    bid = pd.Series([10.0, 10.0, 10.0])
    ask = pd.Series([10.1, 10.1, 10.0])
    bid_size = pd.Series([100.0, 150.0, 150.0])
    ask_size = pd.Series([100.0, 100.0, 100.0])

    ofi = order_flow_imbalance(bid, ask, bid_size, ask_size)

    assert ofi.iloc[0] == 0.0  # no prior quote
    # Row 1: bid price flat, size 100->150 => +50 bid pressure; ask unchanged => 0.
    assert ofi.iloc[1] == pytest.approx(50.0)
    # Row 2: ask price falls 10.1->10.0 => -ask_size_now = -100 (sell pressure).
    assert ofi.iloc[2] < 0.0


def test_tick_rule_sign_carries_zero_moves():
    price = pd.Series([10.0, 10.1, 10.1, 10.0])
    signs = list(tick_rule_sign(price))
    assert signs == [0.0, 1.0, 1.0, -1.0]  # flat tick inherits prior +1


def test_signed_volume_imbalance_window():
    volume = pd.Series([100.0, 200.0, 300.0])
    sign = pd.Series([1.0, 1.0, -1.0])
    imb = signed_volume_imbalance(volume, sign, window=3)
    # cumulative: buy=300, sell=300 -> 0 at the last bar.
    assert imb.iloc[2] == pytest.approx(0.0)
    assert imb.iloc[0] == pytest.approx(1.0)  # only a buy so far


def test_classify_spread_regime_partitions():
    spread = pd.Series(np.linspace(0.0001, 0.01, 100))
    regime = classify_spread_regime(spread)
    assert regime.iloc[0] == "tight"
    assert regime.iloc[-1] == "wide"
    assert set(regime.unique()) == {"tight", "normal", "wide"}


def test_classify_spread_regime_constant_is_normal():
    regime = classify_spread_regime(pd.Series([0.001] * 10))
    assert set(regime.unique()) == {"normal"}


def test_add_microstructure_features_adds_columns():
    frame = pd.DataFrame(
        {
            "bid": [10.0, 10.0, 10.1],
            "ask": [10.1, 10.1, 10.2],
            "bid_size": [300.0, 150.0, 200.0],
            "ask_size": [100.0, 100.0, 100.0],
        }
    )

    out = add_microstructure_features(frame, ofi_window=2)

    for column in (
        "mid",
        "quoted_spread",
        "relative_spread",
        "spread_regime",
        "microprice",
        "queue_imbalance",
        "ofi",
        "ofi_rolling",
    ):
        assert column in out.columns
    assert out["queue_imbalance"].iloc[0] == pytest.approx(0.5)


def test_add_microstructure_features_requires_quotes():
    with pytest.raises(ValueError):
        add_microstructure_features(pd.DataFrame({"bid": [10.0]}))


def test_add_microstructure_features_without_sizes():
    frame = pd.DataFrame({"bid": [10.0, 10.1], "ask": [10.1, 10.2]})
    out = add_microstructure_features(frame)
    assert "mid" in out.columns
    assert "microprice" not in out.columns  # size columns absent
