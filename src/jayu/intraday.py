"""Intraday (1m/5m/…) bar collection with session separation and tz-aware cache.

Roadmap module ``jayu.data.intraday``. Kept as a sibling of :mod:`jayu.data`
(which is a module, not a package) to avoid an invasive package restructure.

Daily :func:`jayu.data.normalize_ohlcv` drops the timezone (``tz_localize(None)``),
which is fine for daily bars but destroys the information needed to tell a
pre-market print from a regular-session one. Intraday bars therefore use
:func:`normalize_intraday`, which *preserves* a UTC tz-aware index, and
:func:`add_session_column`, which tags every bar ``premarket`` / ``regular`` /
``afterhours`` / ``closed`` from its local time-of-day.

Network access lives in an injectable ``provider`` callable so the pure
logic (interval/lookback validation, normalisation, session classification,
resampling) is fully unit-testable offline.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Literal

import pandas as pd

from .data import REQUIRED_COLUMNS

Session = Literal["premarket", "regular", "afterhours", "closed"]

# Yahoo only serves these intraday granularities.
INTRADAY_INTERVALS: frozenset[str] = frozenset({"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"})

# Conservative per-interval lookback ceilings (calendar days) accepted by Yahoo.
# 1m is the tightest (~7 days per request); hourly bars stretch furthest.
_MAX_LOOKBACK_DAYS: dict[str, int] = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "90m": 60,
    "1h": 730,
}

_OHLCV_AGG: dict[str, str] = {
    "Open": "first",
    "High": "max",
    "Low": "min",
    "Close": "last",
    "Volume": "sum",
}

# Provider contract: (ticker, interval, lookback_days, prepost) -> raw OHLCV frame.
IntradayProvider = Callable[[str, str, int, bool], pd.DataFrame]


@dataclass(frozen=True)
class SessionWindows:
    """Local-time boundaries used to label intraday bars.

    Defaults match US equity hours (US/Eastern): pre-market 04:00–09:30,
    regular 09:30–16:00, after-hours 16:00–20:00. Early-close days are not
    special-cased; override ``regular_close`` for a half-day study if needed.
    """

    tz: str = "America/New_York"
    premarket_open: time = time(4, 0)
    regular_open: time = time(9, 30)
    regular_close: time = time(16, 0)
    afterhours_close: time = time(20, 0)


def is_intraday_interval(interval: str) -> bool:
    return interval in INTRADAY_INTERVALS


def validate_intraday_interval(interval: str) -> None:
    if interval not in INTRADAY_INTERVALS:
        allowed = ", ".join(sorted(INTRADAY_INTERVALS))
        raise ValueError(f"unsupported intraday interval {interval!r}; expected one of {allowed}")


def max_lookback_days(interval: str) -> int:
    validate_intraday_interval(interval)
    return _MAX_LOOKBACK_DAYS[interval]


def clamp_lookback_days(interval: str, lookback_days: int) -> int:
    """Cap a requested lookback at the interval's Yahoo ceiling (min 1 day)."""
    ceiling = max_lookback_days(interval)
    return max(1, min(int(lookback_days), ceiling))


def normalize_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    """Return OHLCV columns with a sorted, UTC tz-aware index (tz preserved).

    A naive index is assumed to already be UTC. Unlike the daily normaliser the
    timezone is kept so sessions can be classified downstream.
    """
    if frame.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)
    missing = [column for column in REQUIRED_COLUMNS if column not in result.columns]
    if missing:
        return result
    result = result[REQUIRED_COLUMNS]
    index = pd.DatetimeIndex(result.index)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    result.index = index
    return result.sort_index()


def classify_sessions(
    index: Iterable[pd.Timestamp],
    windows: SessionWindows = SessionWindows(),
) -> pd.Series:
    """Label each timestamp by trading session from its local time-of-day.

    Weekends are always ``closed``. Times outside the pre-market→after-hours
    span are ``closed`` too.
    """
    idx = pd.DatetimeIndex(index)
    if len(idx) == 0:
        return pd.Series([], index=idx, dtype=object)
    utc = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    local = utc.tz_convert(windows.tz)
    labels: list[str] = []
    for stamp in local:
        if stamp.weekday() >= 5:
            labels.append("closed")
            continue
        tod = stamp.time()
        if windows.premarket_open <= tod < windows.regular_open:
            labels.append("premarket")
        elif windows.regular_open <= tod < windows.regular_close:
            labels.append("regular")
        elif windows.regular_close <= tod < windows.afterhours_close:
            labels.append("afterhours")
        else:
            labels.append("closed")
    return pd.Series(labels, index=idx, dtype=object)


def add_session_column(
    frame: pd.DataFrame,
    windows: SessionWindows = SessionWindows(),
) -> pd.DataFrame:
    """Return a copy of ``frame`` with a ``session`` column attached."""
    if frame.empty:
        result = frame.copy()
        result["session"] = pd.Series(dtype=object)
        return result
    result = frame.copy()
    result["session"] = classify_sessions(result.index, windows).to_numpy()
    return result


def split_sessions(
    frame: pd.DataFrame,
    windows: SessionWindows = SessionWindows(),
) -> dict[str, pd.DataFrame]:
    """Group bars by session label into separate frames (no ``session`` column)."""
    tagged = add_session_column(frame, windows)
    if tagged.empty:
        return {}
    columns = [column for column in tagged.columns if column != "session"]
    return {str(label): group[columns] for label, group in tagged.groupby("session", sort=False)}


def regular_session_only(
    frame: pd.DataFrame,
    windows: SessionWindows = SessionWindows(),
) -> pd.DataFrame:
    """Keep only regular-trading-hours bars (drops the ``session`` column)."""
    tagged = add_session_column(frame, windows)
    if tagged.empty:
        return tagged.drop(columns=["session"], errors="ignore")
    return tagged[tagged["session"] == "regular"].drop(columns=["session"])


def resample_ohlcv(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate finer bars to a coarser ``rule`` (e.g. ``"5min"``) the OHLCV way."""
    if frame.empty:
        return frame
    columns = [column for column in REQUIRED_COLUMNS if column in frame.columns]
    aggregated = (
        frame[columns].resample(rule).agg({column: _OHLCV_AGG[column] for column in columns})
    )
    return aggregated.dropna(how="all")


def _default_intraday_provider(
    ticker: str,
    interval: str,
    lookback_days: int,
    prepost: bool,
) -> pd.DataFrame:  # pragma: no cover - network path
    import yfinance as yf

    from .yahoo import get_yahoo_session

    return yf.download(
        ticker,
        interval=interval,
        period=f"{lookback_days}d",
        prepost=prepost,
        auto_adjust=False,
        progress=False,
        session=get_yahoo_session(),
    )


def fetch_intraday(
    ticker: str,
    *,
    interval: str = "5m",
    lookback_days: int = 60,
    prepost: bool = True,
    sessions: Sequence[Session] | None = None,
    windows: SessionWindows = SessionWindows(),
    provider: IntradayProvider | None = None,
    cache_dir: str | Path | None = None,
    refresh: bool = False,
    cache_ttl_seconds: float = 3600.0,
) -> pd.DataFrame:
    """Fetch intraday bars, tag sessions, optionally filter, and cache to parquet.

    The returned frame has a UTC tz-aware index, the standard OHLCV columns, and
    a ``session`` column. ``sessions`` (e.g. ``("regular",)``) restricts the
    output. Caching is keyed by ``ticker_interval_Nd`` with a short default TTL
    because intraday data is only valid for a recent window.
    """
    validate_intraday_interval(interval)
    days = clamp_lookback_days(interval, lookback_days)

    cache_path: Path | None = None
    if cache_dir is not None:
        cache_root = Path(cache_dir)
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = cache_root / f"{ticker}_{interval}_{days}d.parquet"
        if cache_path.exists() and not refresh:
            age = _time.time() - cache_path.stat().st_mtime
            if age < cache_ttl_seconds:
                cached = pd.read_parquet(cache_path)
                return _apply_session_filter(cached, sessions)

    provider = provider or _default_intraday_provider
    frame = normalize_intraday(provider(ticker, interval, days, prepost))
    frame = add_session_column(frame, windows)

    if cache_path is not None and not frame.empty:
        frame.to_parquet(cache_path)

    return _apply_session_filter(frame, sessions)


def _apply_session_filter(
    frame: pd.DataFrame,
    sessions: Sequence[Session] | None,
) -> pd.DataFrame:
    if not sessions or frame.empty or "session" not in frame.columns:
        return frame
    return frame[frame["session"].isin(set(sessions))]
