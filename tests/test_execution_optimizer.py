from __future__ import annotations

import numpy as np
import pytest

from jayu.execution_optimizer import (
    almgren_chriss_schedule,
    dynamic_participation_rate,
    participation_cap_schedule,
    twap_schedule,
    u_shape_volume_curve,
    vwap_schedule,
)


def test_twap_is_equal_and_sums_to_total():
    schedule = twap_schedule(1000.0, 4)
    assert list(schedule) == [250.0, 250.0, 250.0, 250.0]
    with pytest.raises(ValueError):
        twap_schedule(100.0, 0)


def test_u_shape_curve_is_humped_and_normalised():
    weights = u_shape_volume_curve(5, intensity=1.0)
    assert weights.sum() == pytest.approx(1.0)
    # Open and close heavier than midday.
    assert weights[0] > weights[2]
    assert weights[-1] > weights[2]
    assert weights[0] == pytest.approx(weights[-1])  # symmetric


def test_vwap_follows_volume_weights():
    schedule = vwap_schedule(900.0, np.array([1.0, 2.0, 3.0]))
    assert schedule.sum() == pytest.approx(900.0)
    assert list(schedule) == [150.0, 300.0, 450.0]
    # Degenerate weights fall back to TWAP.
    assert list(vwap_schedule(300.0, np.array([0.0, 0.0, 0.0]))) == [100.0, 100.0, 100.0]


def test_almgren_chriss_reduces_to_twap_without_risk_aversion():
    schedule = almgren_chriss_schedule(1000.0, 5, risk_aversion=0.0)
    assert schedule == pytest.approx(twap_schedule(1000.0, 5))


def test_almgren_chriss_front_loads_with_risk_aversion():
    schedule = almgren_chriss_schedule(
        1000.0, 5, risk_aversion=2.0, volatility=0.5, temporary_impact=0.1
    )
    assert schedule.sum() == pytest.approx(1000.0)
    # Risk-averse trader trades more early to cut exposure.
    assert schedule[0] > schedule[-1]
    assert np.all(schedule >= -1e-9)
    # Monotonically decreasing trade sizes.
    assert np.all(np.diff(schedule) <= 1e-9)


def test_participation_cap_rolls_overflow_forward():
    desired = np.array([100.0, 100.0, 100.0])
    volume = np.array([1000.0, 1000.0, 1000.0])
    # Cap = 5% * 1000 = 50 per slice; 300 wanted, 150 capacity -> 150 shortfall.
    filled, shortfall = participation_cap_schedule(desired, volume, participation_rate=0.05)

    assert list(filled) == [50.0, 50.0, 50.0]
    assert shortfall == pytest.approx(150.0)


def test_participation_cap_absorbs_when_capacity_allows():
    desired = np.array([100.0, 0.0, 0.0])
    volume = np.array([1000.0, 1000.0, 1000.0])
    # Cap 60/slice: slice0 places 60, carries 40 -> slice1 places 40, no shortfall.
    filled, shortfall = participation_cap_schedule(desired, volume, participation_rate=0.06)

    assert filled[0] == pytest.approx(60.0)
    assert filled[1] == pytest.approx(40.0)
    assert shortfall == pytest.approx(0.0)


def test_dynamic_participation_shrinks_under_stress():
    base = 0.1
    assert dynamic_participation_rate(base) == pytest.approx(base)  # no stress
    stressed = dynamic_participation_rate(base, spread_z=2.0, volatility_z=1.0)
    assert stressed < base
    # Never below the floor.
    floored = dynamic_participation_rate(base, spread_z=100.0, minimum_fraction=0.2)
    assert floored == pytest.approx(base * 0.2)
