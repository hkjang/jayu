"""Spread-aware triple-barrier labelling (roadmap module ``jayu.labels.triple_barrier``).

The classic triple-barrier method (López de Prado) labels each entry event by
which of three barriers a path touches first: a profit-take barrier (+1), a
stop-loss barrier (-1), or a vertical time barrier (0 / sign of the return).

The *spread-aware* twist (roadmap #22): horizontal barriers are widened so that
neither sits inside the round-trip cost band. A +1 label therefore means the
move cleared fees + spread + impact — i.e. it was actually *net* tradeable, not
just noise inside the bid/ask. ``net_return`` is reported alongside the label so
a +1 is guaranteed non-negative when barriers are cost-floored.

Pure and offline-testable: works on any OHLCV ``DataFrame`` (uses High/Low for
intrabar touches) or a close-only ``Series``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

BarrierName = Literal["profit", "stop", "vertical"]


@dataclass(frozen=True)
class BarrierConfig:
    """Triple-barrier geometry.

    ``upper_pct`` / ``lower_pct`` are positive fractions (0.03 == 3%). ``side``
    is +1 for long, -1 for short. ``cost_pct`` is the round-trip cost (fraction)
    used both to floor the barriers (spread-aware) and to net the return. With
    ``barrier_cost_multiple`` you require a move of N× the cost before a profit
    counts. ``vertical_zero`` controls whether a time-barrier exit is labelled 0
    (default) or the sign of the net return. ``tie_breaker`` decides the label
    when both horizontal barriers are touched in the same bar (default ``stop``,
    matching the backtester's worst-case convention).
    """

    upper_pct: float
    lower_pct: float
    max_holding: int
    cost_pct: float = 0.0
    side: int = 1
    barrier_cost_multiple: float = 1.0
    vertical_zero: bool = True
    tie_breaker: Literal["profit", "stop"] = "stop"

    def __post_init__(self) -> None:
        if self.upper_pct <= 0 or self.lower_pct <= 0:
            raise ValueError("upper_pct and lower_pct must be positive fractions")
        if self.max_holding < 1:
            raise ValueError("max_holding must be at least 1 bar")
        if self.side not in (1, -1):
            raise ValueError("side must be +1 (long) or -1 (short)")
        if self.cost_pct < 0 or self.barrier_cost_multiple < 0:
            raise ValueError("cost_pct and barrier_cost_multiple must be non-negative")


def effective_barriers(config: BarrierConfig) -> tuple[float, float]:
    """Cost-floored (profit, stop) barrier widths.

    Each width is at least ``barrier_cost_multiple * cost_pct`` so a barrier
    never sits inside the round-trip cost band.
    """
    floor = config.barrier_cost_multiple * config.cost_pct
    return max(config.upper_pct, floor), max(config.lower_pct, floor)


def _ohlc_arrays(
    data: pd.DataFrame | pd.Series,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.Index]:
    if isinstance(data, pd.Series):
        close = data.to_numpy(dtype=float)
        return close, close, close, data.index
    if "Close" not in data.columns:
        raise ValueError("DataFrame input must contain a 'Close' column")
    close = data["Close"].to_numpy(dtype=float)
    has_hl = {"High", "Low"} <= set(data.columns)
    high = data["High"].to_numpy(dtype=float) if has_hl else close
    low = data["Low"].to_numpy(dtype=float) if has_hl else close
    return close, high, low, data.index


def triple_barrier_labels(
    data: pd.DataFrame | pd.Series,
    events: Iterable[int],
    config: BarrierConfig,
) -> pd.DataFrame:
    """Label each event by the first barrier its forward path touches.

    ``events`` are integer positions into ``data``. Returns a frame indexed by
    the event timestamps with columns: ``label`` (+1/-1/0), ``barrier``
    (profit/stop/vertical), ``entry_price``, ``exit_price``, ``gross_return``,
    ``net_return``, ``holding_bars``, ``touch_index`` (position of the exit bar).
    Events with a non-positive entry price are skipped.
    """
    close, high, low, index = _ohlc_arrays(data)
    n = len(close)
    upper_eff, lower_eff = effective_barriers(config)
    side = config.side
    rows: list[dict[str, object]] = []
    event_labels: list[object] = []

    for raw in events:
        i = int(raw)
        if i < 0 or i >= n:
            raise IndexError(f"event position {i} out of range for length {n}")
        entry = close[i]
        if entry <= 0:
            continue

        if side == 1:
            profit_price = entry * (1.0 + upper_eff)
            stop_price = entry * (1.0 - lower_eff)
        else:
            profit_price = entry * (1.0 - upper_eff)
            stop_price = entry * (1.0 + lower_eff)

        end = min(i + config.max_holding, n - 1)
        barrier: BarrierName = "vertical"
        touch_index = end
        exit_price = close[end]

        for j in range(i + 1, end + 1):
            if side == 1:
                hit_profit = high[j] >= profit_price
                hit_stop = low[j] <= stop_price
            else:
                hit_profit = low[j] <= profit_price
                hit_stop = high[j] >= stop_price
            if hit_profit and hit_stop:
                barrier = "profit" if config.tie_breaker == "profit" else "stop"
            elif hit_profit:
                barrier = "profit"
            elif hit_stop:
                barrier = "stop"
            else:
                continue
            touch_index = j
            exit_price = profit_price if barrier == "profit" else stop_price
            break

        gross_return = side * (exit_price / entry - 1.0)
        net_return = gross_return - config.cost_pct
        if barrier == "profit":
            label = 1
        elif barrier == "stop":
            label = -1
        else:
            label = 0 if config.vertical_zero else int(np.sign(net_return))

        rows.append(
            {
                "label": label,
                "barrier": barrier,
                "entry_price": round(float(entry), 6),
                "exit_price": round(float(exit_price), 6),
                "gross_return": round(float(gross_return), 6),
                "net_return": round(float(net_return), 6),
                "holding_bars": int(touch_index - i),
                "touch_index": int(touch_index),
            }
        )
        event_labels.append(index[i])

    columns = [
        "label",
        "barrier",
        "entry_price",
        "exit_price",
        "gross_return",
        "net_return",
        "holding_bars",
        "touch_index",
    ]
    return pd.DataFrame(rows, index=pd.Index(event_labels, name="event"), columns=columns)


def label_summary(labels: pd.DataFrame) -> dict[str, object]:
    """Counts and average net return per barrier outcome, for quick QA."""
    if labels.empty:
        return {"events": 0, "counts": {}, "avg_net_return": {}, "hit_rate": 0.0}
    counts = labels["barrier"].value_counts().to_dict()
    avg_net = labels.groupby("barrier")["net_return"].mean().round(6).to_dict()
    profits = int((labels["label"] == 1).sum())
    return {
        "events": int(len(labels)),
        "counts": {str(key): int(value) for key, value in counts.items()},
        "avg_net_return": {str(key): float(value) for key, value in avg_net.items()},
        "hit_rate": round(profits / len(labels), 4),
    }
