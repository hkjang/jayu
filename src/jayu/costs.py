"""Cost-after-everything analytics built on the per-trade gross→net bridge.

The backtester records, per trade, an after-slippage but *pre-fee* return in
``gross_return_pct``. Because the round-trip fee is applied uniformly, we can
re-cost a finished strategy under any hypothetical fee level analytically —
without re-running the backtest — by subtracting a different round-trip cost
from each trade's pre-fee return.

Two questions follow directly:

* **breakeven_transaction_cost** — what round-trip cost makes net expectancy
  zero? (the strategy's cost head-room).
* **cost_sensitivity** — does the strategy still earn a positive net expectancy
  at 0/5/10/20/50 bps round-trip cost? (its cost robustness).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

# Default round-trip cost levels (in basis points) for the sensitivity sweep.
DEFAULT_FEE_LEVELS_BPS: tuple[int, ...] = (0, 5, 10, 20, 50)
DEFAULT_SLIPPAGE_LEVELS_BPS: tuple[int, ...] = (0, 5, 10, 20)


def _pre_fee_return_pct(trade: Mapping[str, Any]) -> tuple[float, bool]:
    """A trade's after-slippage, pre-fee return in percent.

    Returns ``(value, has_cost_detail)``. ``has_cost_detail`` is ``False`` when
    we could only fall back to the net return (i.e. no separable fee), so the
    caller can distinguish a true pre-fee figure from a degraded estimate.
    """
    gross = trade.get("gross_return_pct")
    if isinstance(gross, (int, float)) and np.isfinite(gross):
        return float(gross), True
    net = trade.get("net_return_pct")
    fee = trade.get("fee_cost_pct")
    if (
        isinstance(net, (int, float))
        and np.isfinite(net)
        and isinstance(fee, (int, float))
        and np.isfinite(fee)
    ):
        return float(net) + float(fee), True
    for key in ("ret", "net_return_pct"):
        value = trade.get(key)
        if isinstance(value, (int, float)) and np.isfinite(value):
            return float(value), False
    return 0.0, False


def _position_fraction(trade: Mapping[str, Any]) -> float | None:
    value = trade.get("position_pct")
    if isinstance(value, (int, float)) and np.isfinite(value) and value > 0:
        return float(value) / 100.0
    return None


def _pre_fee_returns(trades: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, bool]:
    if not trades:
        return np.array([], dtype=float), False
    pairs = [_pre_fee_return_pct(trade) for trade in trades]
    values = np.array([value for value, _ in pairs], dtype=float)
    has_detail = any(detail for _, detail in pairs)
    return values, has_detail


def breakeven_transaction_cost(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Round-trip cost (per equal-weighted trade) at which net expectancy is zero.

    Net expectancy per trade as a function of round-trip cost ``f`` is
    ``mean(pre_fee_i) - f``; the breakeven is therefore ``mean(pre_fee)``.
    A higher breakeven means more head-room before costs erase the edge.
    """
    pre_fee, has_detail = _pre_fee_returns(trades)
    if pre_fee.size == 0:
        return {
            "trades": 0,
            "has_cost_detail": False,
            "breakeven_round_trip_pct": 0.0,
            "breakeven_round_trip_bps": 0.0,
        }
    breakeven_pct = float(np.mean(pre_fee))
    return {
        "trades": int(pre_fee.size),
        "has_cost_detail": has_detail,
        # Positive => the average trade clears this much cost before going to zero.
        "breakeven_round_trip_pct": round(breakeven_pct, 4),
        "breakeven_round_trip_bps": round(breakeven_pct * 100.0, 2),
    }


def _total_return_pct(
    pre_fee_pct: np.ndarray, fee_pct: float, fractions: np.ndarray | None
) -> float:
    """Recompound per-trade net returns into a total return (percent).

    Uses each trade's actual position fraction when available so the figure
    reflects sizing; otherwise falls back to an unleveraged compounding of the
    raw per-trade returns.
    """
    net = (pre_fee_pct - fee_pct) / 100.0
    if fractions is not None:
        growth = 1.0 + fractions * net
    else:
        growth = 1.0 + net
    # Guard against a single ruinous trade driving the product negative.
    growth = np.clip(growth, 1e-9, None)
    return float(np.prod(growth) - 1.0) * 100.0


def cost_sensitivity(
    trades: Sequence[Mapping[str, Any]],
    fee_levels_bps: Sequence[int] = DEFAULT_FEE_LEVELS_BPS,
) -> dict[str, Any]:
    """Net expectancy and recompounded total return at several round-trip costs.

    ``survives`` flags whether the average trade still has positive net
    expectancy at that cost level.
    """
    pre_fee, has_detail = _pre_fee_returns(trades)
    if pre_fee.size == 0:
        return {"trades": 0, "has_cost_detail": False, "levels": []}

    fraction_values = [_position_fraction(trade) for trade in trades]
    fractions = (
        np.array([value for value in fraction_values], dtype=float)
        if all(value is not None for value in fraction_values)
        else None
    )

    levels: list[dict[str, Any]] = []
    for bps in fee_levels_bps:
        fee_pct = float(bps) / 100.0
        net_expectancy = float(np.mean(pre_fee)) - fee_pct
        levels.append(
            {
                "round_trip_bps": int(bps),
                "net_expectancy_pct": round(net_expectancy, 4),
                "total_return_pct": round(_total_return_pct(pre_fee, fee_pct, fractions), 2),
                "survives": net_expectancy > 0,
            }
        )

    survivable = [level["round_trip_bps"] for level in levels if level["survives"]]
    return {
        "trades": int(pre_fee.size),
        "has_cost_detail": has_detail,
        "position_weighted": fractions is not None,
        "max_survivable_bps": max(survivable) if survivable else None,
        "levels": levels,
    }


def cost_sensitivity_grid(
    trades: Sequence[Mapping[str, Any]],
    *,
    fee_levels_bps: Sequence[int] = DEFAULT_FEE_LEVELS_BPS,
    slippage_levels_bps: Sequence[int] = DEFAULT_SLIPPAGE_LEVELS_BPS,
) -> dict[str, Any]:
    """Sweep fee and additional-slippage combinations.

    ``gross_return_pct`` is already after the backtest's baseline slippage, so
    the slippage axis represents extra round-trip slippage stress.
    """
    pre_fee, has_detail = _pre_fee_returns(trades)
    if pre_fee.size == 0:
        return {
            "trades": 0,
            "has_cost_detail": False,
            "slippage_basis": "additional_round_trip_bps",
            "combinations": [],
        }
    fraction_values = [_position_fraction(trade) for trade in trades]
    fractions = (
        np.array([value for value in fraction_values], dtype=float)
        if all(value is not None for value in fraction_values)
        else None
    )
    combinations: list[dict[str, Any]] = []
    for fee_bps in fee_levels_bps:
        for slippage_bps in slippage_levels_bps:
            combined_bps = int(fee_bps) + int(slippage_bps)
            combined_pct = float(combined_bps) / 100.0
            net_expectancy = float(np.mean(pre_fee)) - combined_pct
            combinations.append(
                {
                    "fee_round_trip_bps": int(fee_bps),
                    "additional_slippage_round_trip_bps": int(slippage_bps),
                    "combined_round_trip_bps": combined_bps,
                    "net_expectancy_pct": round(net_expectancy, 4),
                    "total_return_pct": round(
                        _total_return_pct(pre_fee, combined_pct, fractions),
                        2,
                    ),
                    "survives": net_expectancy > 0,
                }
            )
    return {
        "trades": int(pre_fee.size),
        "has_cost_detail": has_detail,
        "position_weighted": fractions is not None,
        "slippage_basis": "additional_round_trip_bps",
        "combinations": combinations,
    }
