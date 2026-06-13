from __future__ import annotations

import pytest

from jayu.settings import Settings
from jayu.signal_generation import cost_survival_gate, round_trip_cost_bps


def test_round_trip_cost_bps_from_settings():
    settings = Settings(transaction_fee=0.0015, slippage=0.0005)
    # (0.0015 + 0.0005) * 2 sides * 10000 = 40 bps round trip.
    assert round_trip_cost_bps(settings) == pytest.approx(40.0)


def test_cost_survival_gate_blocks_when_edge_dies_at_cost():
    data = {"metrics": {"max_survivable_bps": 20.0, "breakeven_round_trip_bps": 25.0}}

    gate = cost_survival_gate(data, round_trip_bps=40.0)

    assert gate["checked"] is True
    assert gate["survives"] is False
    assert gate["required_round_trip_bps"] == pytest.approx(50.0)
    assert gate["breakeven_round_trip_bps"] == pytest.approx(25.0)


def test_cost_survival_gate_passes_when_edge_clears_cost():
    data = {"metrics": {"max_survivable_bps": 50.0}}
    gate = cost_survival_gate(data, round_trip_bps=40.0)
    assert gate["checked"] is True
    assert gate["survives"] is True


def test_cost_survival_gate_rejects_missing_metrics():
    gate = cost_survival_gate({"params": {}}, round_trip_bps=40.0)
    assert gate["checked"] is False
    assert gate["survives"] is False
    assert gate["status"] == "not_evaluated"
    assert gate["max_survivable_bps"] is None

    none_gate = cost_survival_gate(None, round_trip_bps=40.0)
    assert none_gate["checked"] is False
    assert none_gate["survives"] is False
