from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import exchange_calendars as xcals
import pandas as pd
import requests
import yfinance as yf

from .artifacts import RunContext
from .io import atomic_write_json, file_sha256, stable_hash
from .yahoo import get_yahoo_session


REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


@dataclass
class DataRequest:
    ticker: str
    start: str | None = None
    end: str | None = None
    period: str | None = "2y"
    interval: str = "1d"
    adjusted: bool = True

    @property
    def cache_key(self) -> str:
        readable = "_".join(
            str(value or "none")
            for value in (self.ticker, self.start, self.end, self.period, self.interval)
        )
        digest = stable_hash(asdict(self))[:12]
        safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in readable)
        return f"{safe}_{digest}"


@dataclass
class DataQualityReport:
    ticker: str
    rows: int
    first_date: str | None
    last_date: str | None
    missing_columns: list[str]
    null_counts: dict[str, int]
    duplicate_index_count: int
    non_monotonic_index: bool
    invalid_price_rows: int
    invalid_ohlc_rows: int
    missing_sessions: int | None
    adjusted: bool
    valid: bool
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MarketDataProvider(Protocol):
    name: str

    def fetch(self, request: DataRequest) -> pd.DataFrame: ...


class YahooProvider:
    name = "yahoo"

    def fetch(self, request: DataRequest) -> pd.DataFrame:
        kwargs = {
            "interval": request.interval,
            "auto_adjust": request.adjusted,
            "progress": False,
        }
        if request.start or request.end:
            kwargs.update(start=request.start, end=request.end)
        else:
            kwargs["period"] = request.period or "2y"
        frame = yf.download(
            request.ticker,
            session=get_yahoo_session(),
            **kwargs,
        )
        return normalize_ohlcv(frame)


class MassiveProvider:
    name = "massive"

    def __init__(self, api_key: str, timeout: float = 20):
        self.api_key = api_key
        self.timeout = timeout

    def fetch(self, request: DataRequest) -> pd.DataFrame:
        if request.interval != "1d":
            raise ValueError("MassiveProvider currently supports daily data only")
        end = request.end or date.today().isoformat()
        start = request.start
        if not start:
            period = request.period or "2y"
            quantity = int(period[:-1])
            unit = period[-1]
            days = quantity * 366 if unit == "y" else quantity * 31 if unit == "m" else quantity
            start = (datetime.now().date() - timedelta(days=days)).isoformat()
        url = f"https://api.massive.com/v2/aggs/ticker/{request.ticker}/range/1/day/{start}/{end}"
        params: dict[str, str | int] = {
            "adjusted": str(request.adjusted).lower(),
            "sort": "asc",
            "limit": 50_000,
            "apiKey": self.api_key,
        }
        response = requests.get(
            url,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = response.json().get("results", [])
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)
        frame.index = pd.to_datetime(frame["t"], unit="ms", utc=True).tz_convert(None)
        return frame.rename(
            columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"}
        )[REQUIRED_COLUMNS]


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)
    missing = [column for column in REQUIRED_COLUMNS if column not in result.columns]
    if missing:
        return result
    result = result[REQUIRED_COLUMNS]
    result.index = pd.to_datetime(result.index).tz_localize(None)
    return result


def dataframe_sha256(frame: pd.DataFrame) -> str:
    normalized = normalize_ohlcv(frame).sort_index()
    row_hashes = pd.util.hash_pandas_object(normalized, index=True).values
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()


def build_quality_report(
    request: DataRequest,
    frame: pd.DataFrame,
    *,
    calendar_name: str | None = None,
) -> DataQualityReport:
    calendar_name = calendar_name or ("XKRX" if request.ticker.endswith((".KS", ".KQ")) else "XNYS")
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    usable = frame if not missing_columns else pd.DataFrame(columns=REQUIRED_COLUMNS)
    null_counts = {column: int(usable[column].isna().sum()) for column in REQUIRED_COLUMNS}
    invalid_price_rows = 0
    invalid_ohlc_rows = 0
    if not usable.empty:
        prices = usable[["Open", "High", "Low", "Close"]]
        invalid_price_rows = int((prices <= 0).any(axis=1).sum())
        invalid_ohlc_rows = int(
            (
                (usable["High"] < usable[["Open", "Close", "Low"]].max(axis=1))
                | (usable["Low"] > usable[["Open", "Close", "High"]].min(axis=1))
            ).sum()
        )
    missing_sessions: int | None = None
    warnings: list[str] = []
    if not usable.empty and request.interval == "1d":
        try:
            calendar = xcals.get_calendar(calendar_name)
            expected = calendar.sessions_in_range(usable.index.min(), usable.index.max())
            actual_dates = set(pd.DatetimeIndex(usable.index).normalize())
            missing_sessions = sum(
                pd.Timestamp(session).tz_localize(None).normalize() not in actual_dates
                for session in expected
            )
            if missing_sessions:
                warnings.append(f"{missing_sessions} expected exchange sessions are absent")
        except Exception as exc:
            warnings.append(f"calendar validation unavailable: {exc}")
    if usable.empty:
        warnings.append("provider returned no rows")
    if any(null_counts.values()):
        warnings.append("null OHLCV values found")
    valid = (
        not usable.empty
        and not missing_columns
        and invalid_price_rows == 0
        and invalid_ohlc_rows == 0
        and not any(null_counts.values())
    )
    return DataQualityReport(
        ticker=request.ticker,
        rows=len(usable),
        first_date=str(usable.index.min()) if not usable.empty else None,
        last_date=str(usable.index.max()) if not usable.empty else None,
        missing_columns=missing_columns,
        null_counts=null_counts,
        duplicate_index_count=int(usable.index.duplicated().sum()),
        non_monotonic_index=not usable.index.is_monotonic_increasing,
        invalid_price_rows=invalid_price_rows,
        invalid_ohlc_rows=invalid_ohlc_rows,
        missing_sessions=missing_sessions,
        adjusted=request.adjusted,
        valid=valid,
        warnings=warnings,
    )


class CachedMarketDataService:
    def __init__(
        self,
        cache_dir: Path,
        providers: list[MarketDataProvider],
        *,
        run_context: RunContext | None = None,
        retries: int = 3,
        refresh_all: bool = False,
    ):
        self.cache_dir = cache_dir
        self.providers = providers
        self.run_context = run_context
        self.retries = retries
        self.refresh_all = refresh_all
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, request: DataRequest, *, refresh: bool = False) -> pd.DataFrame:
        parquet_path = self.cache_dir / f"{request.cache_key}.parquet"
        metadata_path = self.cache_dir / f"{request.cache_key}.json"
        historical_request = bool(request.end and request.end < date.today().isoformat())
        cache_age_seconds = (
            time.time() - parquet_path.stat().st_mtime if parquet_path.exists() else float("inf")
        )
        cache_is_fresh = historical_request or cache_age_seconds < 4 * 60 * 60
        if parquet_path.exists() and cache_is_fresh and not (refresh or self.refresh_all):
            frame = pd.read_parquet(parquet_path)
            self._record(request, frame, parquet_path, source="cache")
            return frame

        failures: list[str] = []
        for provider in self.providers:
            for attempt in range(1, self.retries + 1):
                try:
                    frame = normalize_ohlcv(provider.fetch(request))
                    report = build_quality_report(request, frame)
                    if not report.valid:
                        raise ValueError("; ".join(report.warnings) or "invalid market data")
                    frame.to_parquet(parquet_path)
                    atomic_write_json(
                        metadata_path,
                        {
                            "request": asdict(request),
                            "provider": provider.name,
                            "rows": len(frame),
                            "ohlcv_hash": dataframe_sha256(frame),
                            "parquet_hash": file_sha256(parquet_path),
                        },
                    )
                    self._record(request, frame, parquet_path, source=provider.name)
                    return frame
                except Exception as exc:
                    failures.append(f"{provider.name} attempt {attempt}: {exc}")
                    if attempt < self.retries:
                        time.sleep(attempt)
        raise RuntimeError(f"all providers failed for {request.ticker}: {' | '.join(failures)}")

    def _record(
        self,
        request: DataRequest,
        frame: pd.DataFrame,
        parquet_path: Path,
        *,
        source: str,
    ) -> None:
        if not self.run_context:
            return
        report = build_quality_report(request, frame).to_dict()
        report["source"] = source
        report["parquet_hash"] = file_sha256(parquet_path)
        self.run_context.record_data(
            request.cache_key,
            data_hash=dataframe_sha256(frame),
            quality_report=report,
        )
