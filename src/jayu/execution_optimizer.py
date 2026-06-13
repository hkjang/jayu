"""Order-scheduling / execution optimisation (roadmap module ``jayu.execution.optimizer``).

How an order is *worked* over time drives realised cost as much as the entry
signal does (roadmap #11, #62–#65). This module turns a target quantity into a
per-slice schedule:

* **twap_schedule** — equal slices over time (the naive baseline).
* **u_shape_volume_curve / vwap_schedule** — trade in proportion to expected
  volume, so a bigger share executes into the open/close liquidity humps.
* **almgren_chriss_schedule** — the risk-averse optimal trajectory: balancing
  market impact against timing (volatility) risk front-loads the schedule as
  risk aversion rises, and degenerates to TWAP when it is zero.
* **participation_cap_schedule** — clip each slice to a max share of expected
  volume and push the overflow forward (caps market impact / liquidity use).
* **dynamic_participation_rate** — shrink participation when the spread is wide
  or volatility is high.

Pure numpy, no network; quantities are returned as float arrays summing (up to
clipping) to the target.
"""

from __future__ import annotations

import math

import numpy as np


def twap_schedule(total_quantity: float, slices: int) -> np.ndarray:
    """Equal-sized slices over ``slices`` intervals (time-weighted)."""
    if slices < 1:
        raise ValueError("slices must be >= 1")
    return np.full(slices, total_quantity / slices, dtype=float)


def u_shape_volume_curve(slices: int, *, intensity: float = 1.0) -> np.ndarray:
    """Canonical intraday U-shape volume weights (summing to 1).

    Heavier at the open and close, lighter midday. ``intensity`` controls how
    pronounced the smile is (0 == flat/uniform).
    """
    if slices < 1:
        raise ValueError("slices must be >= 1")
    if slices == 1:
        return np.array([1.0])
    positions = np.linspace(-1.0, 1.0, slices)
    weights = 1.0 + intensity * positions**2
    return weights / weights.sum()


def vwap_schedule(total_quantity: float, volume_weights: np.ndarray) -> np.ndarray:
    """Slice sizes proportional to expected volume weights.

    ``volume_weights`` need not be normalised; non-positive totals fall back to
    an equal (TWAP) split.
    """
    weights = np.asarray(volume_weights, dtype=float)
    if weights.size == 0:
        raise ValueError("volume_weights must be non-empty")
    total_weight = weights.sum()
    if total_weight <= 0:
        return twap_schedule(total_quantity, weights.size)
    return total_quantity * weights / total_weight


def almgren_chriss_schedule(
    total_quantity: float,
    slices: int,
    *,
    risk_aversion: float = 0.0,
    volatility: float = 0.0,
    temporary_impact: float = 1.0,
    tau: float = 1.0,
) -> np.ndarray:
    """Almgren–Chriss optimal-execution trade list.

    The holdings trajectory is ``x_j = X * sinh(κ(T - t_j)) / sinh(κT)`` with
    ``κ = sqrt(risk_aversion * volatility² / temporary_impact)``. With zero risk
    aversion (κ→0) this is exactly TWAP; as risk aversion rises the schedule
    front-loads to cut exposure to price moves. Returns per-slice trade sizes
    (length ``slices``) that sum to ``total_quantity``.
    """
    if slices < 1:
        raise ValueError("slices must be >= 1")
    if temporary_impact <= 0:
        raise ValueError("temporary_impact must be positive")
    horizon = slices * tau
    kappa_squared = risk_aversion * volatility**2 / temporary_impact
    if kappa_squared <= 0:
        return twap_schedule(total_quantity, slices)
    kappa = math.sqrt(kappa_squared)
    times = np.arange(slices + 1) * tau
    holdings = total_quantity * np.sinh(kappa * (horizon - times)) / math.sinh(kappa * horizon)
    holdings[0] = total_quantity
    holdings[-1] = 0.0
    return -np.diff(holdings)


def participation_cap_schedule(
    desired: np.ndarray,
    expected_volume: np.ndarray,
    *,
    participation_rate: float,
) -> tuple[np.ndarray, float]:
    """Clip each slice to ``participation_rate * expected_volume`` and roll overflow forward.

    Returns ``(filled, shortfall)`` where ``filled`` respects every cap and any
    quantity that could not be placed within the horizon's caps is reported as
    ``shortfall`` (it would need more time or a higher participation rate).
    """
    target = np.asarray(desired, dtype=float)
    volume = np.asarray(expected_volume, dtype=float)
    if target.shape != volume.shape:
        raise ValueError("desired and expected_volume must have the same shape")
    if not 0.0 < participation_rate <= 1.0:
        raise ValueError("participation_rate must be in (0, 1]")
    caps = participation_rate * volume
    filled = np.zeros_like(target)
    carry = 0.0
    for index in range(target.size):
        want = target[index] + carry
        place = min(want, caps[index])
        filled[index] = place
        carry = want - place
    return filled, float(carry)


def dynamic_participation_rate(
    base_rate: float,
    *,
    spread_z: float = 0.0,
    volatility_z: float = 0.0,
    sensitivity: float = 0.5,
    minimum_fraction: float = 0.2,
) -> float:
    """Shrink participation when the spread or volatility is elevated.

    ``spread_z`` / ``volatility_z`` are standardised deviations from normal; only
    positive (worse-than-normal) values reduce the rate. The result never falls
    below ``minimum_fraction * base_rate``.
    """
    stress = sensitivity * (max(0.0, spread_z) + max(0.0, volatility_z))
    adjusted = base_rate / (1.0 + stress)
    return max(adjusted, minimum_fraction * base_rate)
