"""Strategy entry-condition evaluation (extracted from ``backtest_core``).

Separates the *entry condition* responsibility (project task #3) and gives the
``strategy_mode`` space a single, standardised entry interface (task #4):
``evaluate_entry`` takes a bar's indicator row + params and returns whether an
entry triggers, plus the optional-condition tally used for confidence sizing.

Behaviour-preserving — identical to the previous inline block in the backtest
loop — and pinned by ``tests/test_golden_backtest.py``. The same function is
intended to back the live ``signal_generation`` path in a follow-up so the two
can no longer drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EntryDecision:
    entered: bool
    optional_met: int
    optional_count: int


def evaluate_entry(
    row: Mapping[str, Any],
    params: Mapping[str, Any],
    *,
    close: float,
    ema: float,
    strategy_mode: str,
    market_ok: bool,
) -> EntryDecision:
    """Evaluate ensemble / strategy-mode entry conditions for one bar."""
    p = params
    conds = {
        "rsi": p["rsi_lo"] <= float(row["rsi"]) <= p["rsi_hi"],
        "ema": close > ema,
        "volume": float(row["vol_ratio"]) >= p["vol_mult"],
        "gap": float(row["gap"]) >= p["gap_min"],
        "macd": bool(row["macd_cross"]) if p["require_macd"] else True,
        "bb": float(row["bb_pct"]) < 0.4 if p["require_bb"] else True,
        "regime": row["regime"] != "bear" if p["regime_filter"] else True,
        "obv": bool(row["obv_trend"]),
        "stoch": float(row["stoch_rsi"]) < 0.8,
    }

    use_connors = strategy_mode == "connors_rsi2"
    use_williams = strategy_mode == "williams_breakout"
    use_volume = strategy_mode == "volume_breakout"
    mandatory = conds["volume"] and conds["gap"] and market_ok

    if use_williams:
        williams_target = float(row["Open"]) + float(row["prev_range"]) * float(
            row["k_dynamic"]
        ) * p.get("williams_k_multiplier", 1.0)
        williams_ok = (close > williams_target) and (close > float(row["sma200"]))
        return EntryDecision(bool(mandatory and williams_ok), 0, 0)

    if use_volume:
        vol_mult = p.get("volume_spike_mult", 2.0)
        vol_period = p.get("volume_breakout_period", 10)
        high_col = f"high_max_{vol_period}"
        volume_spike = float(row["Volume"]) > float(row["volume_ma20"]) * vol_mult
        price_break = close > float(row[high_col]) if high_col in row else False
        trend_ok = close > float(row["sma200"])
        volume_ok = volume_spike and price_break and trend_ok
        return EntryDecision(bool(mandatory and volume_ok), 0, 0)

    if use_connors:
        connors_ok = (close > float(row["sma200"])) and (
            float(row["rsi2"]) < p.get("connors_rsi2_limit", 10)
        )
        return EntryDecision(bool(mandatory and connors_ok), 0, 0)

    # Ensemble mode, with ADX-based switching of the mandatory/optional split.
    use_adx = p.get("use_adx_filter", False)
    adx_val = float(row["adx"]) if "adx" in row else 0.0

    if use_adx and adx_val > p.get("adx_threshold", 25):
        mandatory = mandatory and conds["ema"]
        if p["require_macd"]:
            mandatory = mandatory and conds["macd"]
        optionals = [
            conds["rsi"],
            conds["macd"] if not p["require_macd"] else True,
            conds["bb"],
            conds["regime"],
            conds["obv"],
            conds["stoch"],
        ]
    elif use_adx and adx_val < 20:
        mandatory = mandatory and conds["rsi"]
        if p["require_bb"]:
            mandatory = mandatory and conds["bb"]
        optionals = [
            conds["ema"],
            conds["macd"],
            conds["bb"] if not p["require_bb"] else True,
            conds["regime"],
            conds["obv"],
            conds["stoch"],
        ]
    else:
        mandatory = mandatory and conds["rsi"] and conds["ema"]
        optionals = [
            conds["macd"],
            conds["bb"],
            conds["regime"],
            conds["obv"],
            conds["stoch"],
        ]

    optional_met = sum(bool(cond) for cond in optionals)
    entered = bool(mandatory and optional_met >= p["ensemble_min"])
    return EntryDecision(entered, optional_met, len(optionals))
