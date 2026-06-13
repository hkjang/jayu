"""Post-trade execution analytics (roadmap module ``jayu.execution.analytics`` #14, #56, #115).

Once an order is worked, you need to know *where* the cost went so alpha decay
and execution drag can be told apart (roadmap #115). This module computes
Perold's implementation shortfall from the lifecycle prices and splits it into:

* **delay cost** — decision → arrival (signal latency: the price moved before the
  order reached the market),
* **impact cost** — arrival → fill (what working the order cost),
* **opportunity cost** — the alpha missed on the *unfilled* quantity
  (decision → final), i.e. missed alpha,
* **vs VWAP** — fill price against the interval VWAP benchmark (#56).

All costs are signed so that **positive means worse for the trader** (a buy that
paid up, a sell that got hit down), normalised by the decision price, and
additive: ``delay + impact == per-share realised``; ``realised + opportunity ==
implementation shortfall``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from .execution import OrderSide


def _bps(fraction: float) -> float:
    return round(fraction * 10_000.0, 4)


def implementation_shortfall(
    *,
    side: OrderSide,
    decision_price: float,
    arrival_price: float,
    fill_price: float,
    final_price: float,
    target_quantity: float,
    filled_quantity: float,
    interval_vwap: float | None = None,
) -> dict[str, Any]:
    """Decompose one order's implementation shortfall (fractions + bps).

    ``decision_price`` is the price when the signal fired; ``arrival_price`` when
    the order reached the market; ``fill_price`` the realised average; and
    ``final_price`` the price used to value the unfilled remainder (missed alpha).
    """
    if decision_price <= 0:
        raise ValueError("decision_price must be positive")
    if target_quantity <= 0:
        raise ValueError("target_quantity must be positive")
    if filled_quantity < 0 or filled_quantity > target_quantity:
        raise ValueError("filled_quantity must be between 0 and target_quantity")

    sign = 1.0 if side == "buy" else -1.0
    fill_fraction = filled_quantity / target_quantity
    unfilled_fraction = 1.0 - fill_fraction

    delay = sign * (arrival_price - decision_price) / decision_price
    impact = sign * (fill_price - arrival_price) / decision_price
    per_share_realised = sign * (fill_price - decision_price) / decision_price
    realised = per_share_realised * fill_fraction
    opportunity = sign * (final_price - decision_price) / decision_price * unfilled_fraction
    shortfall = realised + opportunity
    vs_vwap = (
        sign * (fill_price - interval_vwap) / decision_price
        if interval_vwap is not None and interval_vwap > 0
        else None
    )

    return {
        "side": side,
        "fill_rate": round(fill_fraction, 6),
        "delay_cost": round(delay, 8),
        "impact_cost": round(impact, 8),
        "realised_cost": round(realised, 8),
        "opportunity_cost": round(opportunity, 8),
        "missed_alpha": round(opportunity, 8),
        "implementation_shortfall": round(shortfall, 8),
        "vs_vwap": round(vs_vwap, 8) if vs_vwap is not None else None,
        "delay_cost_bps": _bps(delay),
        "impact_cost_bps": _bps(impact),
        "realised_cost_bps": _bps(realised),
        "opportunity_cost_bps": _bps(opportunity),
        "implementation_shortfall_bps": _bps(shortfall),
        "vs_vwap_bps": _bps(vs_vwap) if vs_vwap is not None else None,
    }


def interval_vwap(prices: Sequence[float], volumes: Sequence[float]) -> float:
    """Volume-weighted average price over an interval (for the VWAP benchmark)."""
    price_array = np.asarray(prices, dtype=float)
    volume_array = np.asarray(volumes, dtype=float)
    if price_array.size == 0 or price_array.size != volume_array.size:
        raise ValueError("prices and volumes must be non-empty and the same length")
    total_volume = volume_array.sum()
    if total_volume <= 0:
        return float(price_array.mean())
    return float(np.dot(price_array, volume_array) / total_volume)


def aggregate_execution_quality(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Average the shortfall components across orders (in bps), plus fill rate.

    ``vs_vwap`` is averaged only over orders that carry a benchmark.
    """
    if not records:
        return {"orders": 0}

    def mean_bps(key: str) -> float:
        values = [float(record[key]) for record in records if record.get(key) is not None]
        return round(float(np.mean(values)), 4) if values else 0.0

    vwap_values = [
        float(record["vs_vwap_bps"]) for record in records if record.get("vs_vwap_bps") is not None
    ]
    return {
        "orders": len(records),
        "avg_fill_rate": round(
            float(np.mean([float(record["fill_rate"]) for record in records])), 6
        ),
        "avg_delay_cost_bps": mean_bps("delay_cost_bps"),
        "avg_impact_cost_bps": mean_bps("impact_cost_bps"),
        "avg_opportunity_cost_bps": mean_bps("opportunity_cost_bps"),
        "avg_implementation_shortfall_bps": mean_bps("implementation_shortfall_bps"),
        "avg_vs_vwap_bps": round(float(np.mean(vwap_values)), 4) if vwap_values else None,
    }
