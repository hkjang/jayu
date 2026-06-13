"""Order-book microstructure features (roadmap module ``jayu.features.microstructure``).

Signal-engine items #3–#9: features that capture short-horizon directional
pressure and liquidity state from NBBO quotes (bid/ask price + size) and trades,
rather than from OHLCV alone. A daily-bar RSI cannot see that the book is 80%
bid-heavy or that the spread just blew out; these features can.

* **midpoint / quoted_spread / relative_spread** — basic quote geometry.
* **microprice** — size-weighted fair value; leans toward the side the book
  expects to trade through next.
* **queue_imbalance** — best-level depth skew in [-1, 1].
* **order_flow_imbalance (OFI)** — Cont–Kukanov–Stoikov signed flow from quote
  updates; the single best linear predictor of short-term price change.
* **signed_volume_imbalance** — rolling buy-minus-sell traded volume (tick rule).
* **spread_regime** — tight / normal / wide liquidity state by percentile.

All functions are pure and vectorised (numpy/pandas), no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Default NBBO column names (lower-case) used by :func:`add_microstructure_features`.
BID = "bid"
ASK = "ask"
BID_SIZE = "bid_size"
ASK_SIZE = "ask_size"


def _series(values: pd.Series | np.ndarray | list) -> pd.Series:
    return values if isinstance(values, pd.Series) else pd.Series(values)


def midpoint(bid: pd.Series, ask: pd.Series) -> pd.Series:
    return (_series(bid) + _series(ask)) / 2.0


def quoted_spread(bid: pd.Series, ask: pd.Series) -> pd.Series:
    return _series(ask) - _series(bid)


def relative_spread(bid: pd.Series, ask: pd.Series) -> pd.Series:
    """Quoted spread as a fraction of the midpoint (0.001 == 10 bps)."""
    mid = midpoint(bid, ask)
    spread = quoted_spread(bid, ask)
    return (spread / mid).where(mid > 0, 0.0)


def effective_spread(trade_price: pd.Series, mid: pd.Series, side: pd.Series) -> pd.Series:
    """Relative effective spread: ``2 * side * (price - mid) / mid``.

    ``side`` is +1 for a buy (trade at/above mid) and -1 for a sell. Positive
    values mean the trade paid the spread; it is the cost actually realised, vs
    the *quoted* spread that was merely advertised.
    """
    price = _series(trade_price)
    mid_s = _series(mid)
    side_s = _series(side)
    return (2.0 * side_s * (price - mid_s) / mid_s).where(mid_s > 0, 0.0)


def microprice(
    bid: pd.Series,
    ask: pd.Series,
    bid_size: pd.Series,
    ask_size: pd.Series,
) -> pd.Series:
    """Size-weighted fair value: ``ask*bid_size/total + bid*ask_size/total``.

    Heavy bid depth pulls the microprice toward the ask (buyers likely to lift
    it). Falls back to the midpoint when total size is zero.
    """
    bid_s, ask_s = _series(bid), _series(ask)
    bsz, asz = _series(bid_size), _series(ask_size)
    total = bsz + asz
    weighted = (ask_s * bsz + bid_s * asz) / total
    return weighted.where(total > 0, midpoint(bid_s, ask_s))


def queue_imbalance(bid_size: pd.Series, ask_size: pd.Series) -> pd.Series:
    """Best-level depth skew ``(bid - ask) / (bid + ask)`` in [-1, 1].

    Positive => more resting bid size => upward pressure.
    """
    bsz, asz = _series(bid_size), _series(ask_size)
    total = bsz + asz
    return ((bsz - asz) / total).where(total > 0, 0.0)


def order_flow_imbalance(
    bid: pd.Series,
    ask: pd.Series,
    bid_size: pd.Series,
    ask_size: pd.Series,
) -> pd.Series:
    """Per-update order-flow imbalance (Cont, Kukanov & Stoikov 2014).

    Combines best bid/ask price moves with size changes into a signed flow:
    positive = net buying pressure. The first row is 0 (no prior quote). Sum or
    average over a window to use as a feature.
    """
    pb, pa = _series(bid).to_numpy(float), _series(ask).to_numpy(float)
    qb, qa = _series(bid_size).to_numpy(float), _series(ask_size).to_numpy(float)
    n = len(pb)
    ofi = np.zeros(n)
    if n < 2:
        return pd.Series(ofi, index=_series(bid).index)

    pb_prev, pa_prev = pb[:-1], pa[:-1]
    qb_prev, qa_prev = qb[:-1], qa[:-1]
    pb_now, pa_now = pb[1:], pa[1:]
    qb_now, qa_now = qb[1:], qa[1:]

    bid_term = np.where(pb_now >= pb_prev, qb_now, 0.0) - np.where(pb_now <= pb_prev, qb_prev, 0.0)
    ask_term = np.where(pa_now >= pa_prev, qa_prev, 0.0) - np.where(pa_now <= pa_prev, qa_now, 0.0)
    ofi[1:] = bid_term + ask_term
    return pd.Series(ofi, index=_series(bid).index)


def tick_rule_sign(price: pd.Series) -> pd.Series:
    """Infer trade direction from price moves (+1 uptick, -1 downtick).

    A zero move inherits the previous sign (the standard tick rule); the first
    observation, with no prior, is 0.
    """
    prices = _series(price)
    direction = np.sign(prices.diff())
    direction = direction.replace(0.0, np.nan).ffill()
    return direction.fillna(0.0)


def signed_volume_imbalance(
    volume: pd.Series,
    sign: pd.Series,
    *,
    window: int = 20,
) -> pd.Series:
    """Rolling (buy − sell) / (buy + sell) traded volume in [-1, 1].

    ``sign`` is +1 for buyer-initiated, -1 for seller-initiated (e.g. from
    :func:`tick_rule_sign`). Windows with no volume yield 0.
    """
    vol = _series(volume)
    sgn = _series(sign)
    buy = vol.where(sgn > 0, 0.0)
    sell = vol.where(sgn < 0, 0.0)
    roll_buy = buy.rolling(window, min_periods=1).sum()
    roll_sell = sell.rolling(window, min_periods=1).sum()
    total = roll_buy + roll_sell
    return ((roll_buy - roll_sell) / total).where(total > 0, 0.0)


def classify_spread_regime(
    rel_spread: pd.Series,
    *,
    lower_q: float = 0.33,
    upper_q: float = 0.67,
) -> pd.Series:
    """Label each spread as ``tight`` / ``normal`` / ``wide`` by percentile.

    Thresholds come from the series' own quantiles, so the classification is
    relative to the instrument's typical spread. A degenerate (constant) series
    is all ``normal``.
    """
    spread = _series(rel_spread).astype(float)
    if spread.empty:
        return pd.Series([], index=spread.index, dtype=object)
    low = spread.quantile(lower_q)
    high = spread.quantile(upper_q)
    if not np.isfinite(low) or not np.isfinite(high) or low == high:
        return pd.Series(["normal"] * len(spread), index=spread.index, dtype=object)
    labels = np.where(spread <= low, "tight", np.where(spread >= high, "wide", "normal"))
    return pd.Series(labels, index=spread.index, dtype=object)


def add_microstructure_features(
    frame: pd.DataFrame,
    *,
    bid: str = BID,
    ask: str = ASK,
    bid_size: str = BID_SIZE,
    ask_size: str = ASK_SIZE,
    ofi_window: int = 20,
) -> pd.DataFrame:
    """Attach quote-derived microstructure columns to a copy of ``frame``.

    Requires ``bid``/``ask`` columns; size-dependent features are added only
    when the size columns are present. Adds: ``mid``, ``quoted_spread``,
    ``relative_spread``, ``spread_regime`` and, with sizes, ``microprice``,
    ``queue_imbalance``, ``ofi``, ``ofi_rolling``.
    """
    missing = [name for name in (bid, ask) if name not in frame.columns]
    if missing:
        raise ValueError(f"frame missing required quote columns: {missing}")
    result = frame.copy()
    result["mid"] = midpoint(result[bid], result[ask])
    result["quoted_spread"] = quoted_spread(result[bid], result[ask])
    result["relative_spread"] = relative_spread(result[bid], result[ask])
    result["spread_regime"] = classify_spread_regime(result["relative_spread"])
    if bid_size in frame.columns and ask_size in frame.columns:
        result["microprice"] = microprice(
            result[bid], result[ask], result[bid_size], result[ask_size]
        )
        result["queue_imbalance"] = queue_imbalance(result[bid_size], result[ask_size])
        ofi = order_flow_imbalance(result[bid], result[ask], result[bid_size], result[ask_size])
        result["ofi"] = ofi
        result["ofi_rolling"] = ofi.rolling(ofi_window, min_periods=1).sum()
    return result
