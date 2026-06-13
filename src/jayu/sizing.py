"""Position sizing (extracted from ``backtest_core`` for testability).

Separates the *position sizing* responsibility (project task #3) from the
backtest loop. The computation is behaviour-preserving — identical to the
previous inline block — and is pinned by ``tests/test_golden_backtest.py``.

The size is a fraction of capital:

1. a confidence-scaled, Kelly-fraction-scaled base off ``pos_size``;
2. optionally capped by a volatility (per-trade risk budget) target;
3. clamped to ``[min_position, max_position]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def resolve_position_fraction(
    params: Mapping[str, Any],
    *,
    optional_met: int,
    optional_count: int,
    atr: float,
    close: float,
    atr_pct: float | None = None,
    max_position: float,
    min_position: float = 0.05,
    default_kelly_fraction: float = 0.50,
) -> float:
    """Capital fraction for one entry (Kelly + optional volatility sizing).

    ``atr_pct`` is the precomputed per-bar ATR% when available; otherwise it
    falls back to ``atr / close`` (matching the original inline behaviour).
    """
    confidence_score = optional_met / optional_count if optional_count else 0.6
    confidence_score = max(0.2, min(confidence_score, 1.0))
    base_pos_size = (
        params["pos_size"] * confidence_score * params.get("kelly_fraction", default_kelly_fraction)
    )

    if params.get("use_volatility_sizing", False):
        effective_atr_pct = atr_pct if atr_pct is not None else (atr / close)
        atr_mult_stop = (
            params.get("atr_mult_stop", 2.0)
            if params["use_atr_stop"]
            else (params["stop_pct"] / (atr / close))
        )
        max_risk = params.get("max_risk_per_trade_pct", 0.015)
        risk_adjusted_size = max_risk / (atr_mult_stop * effective_atr_pct)
        actual_pos_size = min(base_pos_size, risk_adjusted_size)
    else:
        actual_pos_size = base_pos_size

    return max(min(actual_pos_size, max_position), min_position)
