from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

import exchange_calendars as xcals
import pandas as pd
import requests
import yfinance as yf

from .artifacts import RunContext
from .io import atomic_write_json, file_sha256, read_json, stable_hash
from .provider_core import ProviderCategory
from .yahoo import get_yahoo_session


REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def exchange_calendar_for_ticker(ticker: str) -> str:
    return "XKRX" if ticker.upper().endswith((".KS", ".KQ")) else "XNYS"


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
    invalid_volume_rows: int
    missing_sessions: int | None
    adjusted: bool
    valid: bool
    warnings: list[str]
    provider_disagreements: list[dict[str, Any]] = field(default_factory=list)
    provider_sources: list[dict[str, Any]] = field(default_factory=list)
    price_verified: bool = False
    price_usable: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MarketDataProvider(Protocol):
    name: str
    category: ProviderCategory

    def fetch(self, request: DataRequest) -> pd.DataFrame: ...


class YahooProvider:
    name = "yahoo"
    category = ProviderCategory.PRICE

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
    category = ProviderCategory.PRICE

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


class TiingoProvider:
    name = "tiingo"
    category = ProviderCategory.PRICE
    base_url = "https://api.tiingo.com/tiingo/daily"

    def __init__(self, api_key: str, timeout: float = 20):
        self.api_key = api_key
        self.timeout = timeout

    def fetch(self, request: DataRequest) -> pd.DataFrame:
        if request.interval != "1d":
            raise ValueError("TiingoProvider currently supports daily data only")
        start, end = _request_date_range(request)
        response = requests.get(
            f"{self.base_url}/{request.ticker}/prices",
            params={
                "startDate": start,
                "endDate": end,
                "resampleFreq": "daily",
                "token": self.api_key,
            },
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)
        frame = pd.DataFrame(rows)
        prefix = "adj" if request.adjusted else ""
        column_map = {
            f"{prefix}Open" if prefix else "open": "Open",
            f"{prefix}High" if prefix else "high": "High",
            f"{prefix}Low" if prefix else "low": "Low",
            f"{prefix}Close" if prefix else "close": "Close",
            f"{prefix}Volume" if prefix else "volume": "Volume",
        }
        missing = [column for column in column_map if column not in frame.columns]
        if missing:
            raise ValueError(f"Tiingo response missing columns: {', '.join(missing)}")
        frame.index = pd.to_datetime(frame["date"], utc=True).dt.tz_convert(None)
        return frame.rename(columns=column_map)[REQUIRED_COLUMNS]


def _request_date_range(request: DataRequest) -> tuple[str, str]:
    end = request.end or date.today().isoformat()
    if request.start:
        return request.start, end
    period = request.period or "2y"
    try:
        quantity = int(period[:-1])
        unit = period[-1]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported period: {period}") from exc
    days = quantity * 366 if unit == "y" else quantity * 31 if unit == "m" else quantity
    return (datetime.now().date() - timedelta(days=days)).isoformat(), end


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
    calendar_name = calendar_name or exchange_calendar_for_ticker(request.ticker)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    usable = frame if not missing_columns else pd.DataFrame(columns=REQUIRED_COLUMNS)
    null_counts = {column: int(usable[column].isna().sum()) for column in REQUIRED_COLUMNS}
    invalid_price_rows = 0
    invalid_ohlc_rows = 0
    invalid_volume_rows = 0
    if not usable.empty:
        prices = usable[["Open", "High", "Low", "Close"]]
        invalid_price_rows = int((prices <= 0).any(axis=1).sum())
        invalid_volume_rows = int((usable["Volume"] < 0).sum())
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
    duplicate_index_count = int(usable.index.duplicated().sum())
    non_monotonic_index = not usable.index.is_monotonic_increasing
    if duplicate_index_count:
        warnings.append(f"{duplicate_index_count} duplicate timestamps found")
    if non_monotonic_index:
        warnings.append("OHLCV index is not monotonic increasing")
    if invalid_volume_rows:
        warnings.append(f"{invalid_volume_rows} rows have negative volume")
    valid = (
        not usable.empty
        and not missing_columns
        and invalid_price_rows == 0
        and invalid_ohlc_rows == 0
        and invalid_volume_rows == 0
        and duplicate_index_count == 0
        and not non_monotonic_index
        and not any(null_counts.values())
    )
    return DataQualityReport(
        ticker=request.ticker,
        rows=len(usable),
        first_date=str(usable.index.min()) if not usable.empty else None,
        last_date=str(usable.index.max()) if not usable.empty else None,
        missing_columns=missing_columns,
        null_counts=null_counts,
        duplicate_index_count=duplicate_index_count,
        non_monotonic_index=non_monotonic_index,
        invalid_price_rows=invalid_price_rows,
        invalid_ohlc_rows=invalid_ohlc_rows,
        invalid_volume_rows=invalid_volume_rows,
        missing_sessions=missing_sessions,
        adjusted=request.adjusted,
        valid=valid,
        warnings=warnings,
    )


def compare_ohlcv_sources(
    frames: dict[str, pd.DataFrame],
    *,
    max_row_count_delta: int = 2,
    max_index_mismatches: int = 2,
    max_relative_price_delta: float = 0.005,
) -> dict[str, Any]:
    names = list(frames)
    sources = [
        {
            "provider": name,
            "rows": len(frame),
            "first_date": str(frame.index.min()) if not frame.empty else None,
            "last_date": str(frame.index.max()) if not frame.empty else None,
            "ohlcv_hash": dataframe_sha256(frame),
        }
        for name, frame in frames.items()
    ]
    comparisons: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    if len(names) < 2:
        return {
            "sources": sources,
            "comparisons": comparisons,
            "disagreements": disagreements,
            "agreed": True,
        }
    baseline_name = names[0]
    baseline = normalize_ohlcv(frames[baseline_name]).sort_index()
    for candidate_name in names[1:]:
        candidate = normalize_ohlcv(frames[candidate_name]).sort_index()
        index_mismatches = len(baseline.index.symmetric_difference(candidate.index))
        row_count_delta = abs(len(baseline) - len(candidate))
        common = baseline.index.intersection(candidate.index)
        max_relative_delta = 0.0
        if len(common):
            left = baseline.loc[common, ["Open", "High", "Low", "Close"]].astype(float)
            right = candidate.loc[common, ["Open", "High", "Low", "Close"]].astype(float)
            denominator = left.abs().clip(lower=1e-12)
            max_relative_delta = float(((left - right).abs() / denominator).max().max())
        hash_equal = dataframe_sha256(baseline) == dataframe_sha256(candidate)
        agreed = (
            row_count_delta <= max_row_count_delta
            and index_mismatches <= max_index_mismatches
            and max_relative_delta <= max_relative_price_delta
        )
        comparison = {
            "baseline": baseline_name,
            "candidate": candidate_name,
            "row_count_delta": row_count_delta,
            "index_mismatches": index_mismatches,
            "common_rows": len(common),
            "max_relative_price_delta": max_relative_delta,
            "hash_equal": hash_equal,
            "agreed": agreed,
        }
        comparisons.append(comparison)
        if not agreed:
            disagreements.append(comparison)
    return {
        "sources": sources,
        "comparisons": comparisons,
        "disagreements": disagreements,
        "agreed": not disagreements,
    }


class CachedMarketDataService:
    def __init__(
        self,
        cache_dir: Path,
        providers: list[MarketDataProvider],
        *,
        run_context: RunContext | None = None,
        retries: int = 3,
        refresh_all: bool = False,
        cross_validate: bool = False,
        minimum_valid_sources: int = 1,
        disagreement_policy: Literal["warn", "block"] = "block",
        max_row_count_delta: int = 2,
        max_index_mismatches: int = 2,
        max_relative_price_delta: float = 0.005,
        cache_ttl_seconds: int = 14_400,
        provider_retries: dict[str, int] | None = None,
        provider_rate_limits_per_minute: dict[str, int] | None = None,
    ):
        self.cache_dir = cache_dir
        self.providers = providers
        self.run_context = run_context
        self.retries = retries
        self.refresh_all = refresh_all
        self.cross_validate = cross_validate
        self.minimum_valid_sources = minimum_valid_sources
        self.disagreement_policy = disagreement_policy
        self.max_row_count_delta = max_row_count_delta
        self.max_index_mismatches = max_index_mismatches
        self.max_relative_price_delta = max_relative_price_delta
        self.cache_ttl_seconds = cache_ttl_seconds
        self.provider_retries = provider_retries or {}
        self.provider_rate_limits_per_minute = provider_rate_limits_per_minute or {}
        self._provider_last_request_at: dict[str, float] = {}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, request: DataRequest, *, refresh: bool = False) -> pd.DataFrame:
        parquet_path = self.cache_dir / f"{request.cache_key}.parquet"
        metadata_path = self.cache_dir / f"{request.cache_key}.json"
        verification_signature = self._verification_signature()
        cached_metadata = read_json(metadata_path, default={})
        metadata_matches = (
            isinstance(cached_metadata, dict)
            and cached_metadata.get("verification_signature") == verification_signature
        )
        historical_request = bool(request.end and request.end < date.today().isoformat())
        cache_age_seconds = (
            time.time() - parquet_path.stat().st_mtime if parquet_path.exists() else float("inf")
        )
        cache_is_fresh = historical_request or cache_age_seconds < self.cache_ttl_seconds
        if self.cross_validate and not metadata_matches:
            cache_is_fresh = False
        if parquet_path.exists() and cache_is_fresh and not (refresh or self.refresh_all):
            frame = pd.read_parquet(parquet_path)
            self._record(
                request,
                frame,
                parquet_path,
                source="cache",
                metadata=cached_metadata if isinstance(cached_metadata, dict) else {},
            )
            return frame

        failures: list[str] = []
        valid_frames: dict[str, pd.DataFrame] = {}
        source_records: list[dict[str, Any]] = []
        for provider in self.providers:
            provider_failure = ""
            retries = self.provider_retries.get(provider.name, self.retries)
            for attempt in range(1, retries + 1):
                try:
                    self._throttle_provider(provider.name)
                    frame = normalize_ohlcv(provider.fetch(request))
                    self._provider_last_request_at[provider.name] = time.monotonic()
                    report = build_quality_report(request, frame)
                    if not report.valid:
                        raise ValueError("; ".join(report.warnings) or "invalid market data")
                    valid_frames[provider.name] = frame
                    source_records.append(
                        _source_record(provider.name, request, frame, status="success")
                    )
                    break
                except Exception as exc:
                    provider_failure = f"{provider.name} attempt {attempt}: {exc}"
                    failures.append(provider_failure)
                    if attempt < retries:
                        time.sleep(attempt)
            if provider.name not in valid_frames:
                source_records.append(
                    {
                        "provider": provider.name,
                        "category": ProviderCategory.PRICE.value,
                        "ticker": request.ticker,
                        "status": "failed",
                        "error": provider_failure or "provider failed",
                    }
                )
            if valid_frames and not self.cross_validate:
                break
        if not valid_frames:
            self._record_source_records(source_records)
            raise RuntimeError(f"all providers failed for {request.ticker}: {' | '.join(failures)}")

        comparison = compare_ohlcv_sources(
            valid_frames,
            max_row_count_delta=self.max_row_count_delta,
            max_index_mismatches=self.max_index_mismatches,
            max_relative_price_delta=self.max_relative_price_delta,
        )
        enough_sources = len(valid_frames) >= self.minimum_valid_sources
        price_verified = enough_sources and comparison["agreed"]
        price_usable = enough_sources and (
            comparison["agreed"] or self.disagreement_policy == "warn"
        )
        metadata = {
            "request": asdict(request),
            "provider": next(iter(valid_frames)),
            "sources": source_records,
            "provider_comparison": comparison,
            "price_verified": price_verified,
            "price_usable": price_usable,
            "verification_signature": verification_signature,
        }
        self._record_source_records(source_records)
        self._record_disagreement(request, comparison)
        if not price_usable:
            raise RuntimeError(
                f"price verification failed for {request.ticker}: "
                f"{len(valid_frames)} valid sources, "
                f"{len(comparison['disagreements'])} disagreements"
            )
        selected_name, selected = next(iter(valid_frames.items()))
        selected.to_parquet(parquet_path)
        metadata.update(
            {
                "provider": selected_name,
                "rows": len(selected),
                "ohlcv_hash": dataframe_sha256(selected),
                "parquet_hash": file_sha256(parquet_path),
            }
        )
        atomic_write_json(metadata_path, metadata)
        self._record(
            request,
            selected,
            parquet_path,
            source=selected_name,
            metadata=metadata,
        )
        return selected

    def _record(
        self,
        request: DataRequest,
        frame: pd.DataFrame,
        parquet_path: Path,
        *,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.run_context:
            return
        report = build_quality_report(request, frame).to_dict()
        report["source"] = source
        report["parquet_hash"] = file_sha256(parquet_path)
        metadata = metadata or {}
        comparison = metadata.get("provider_comparison", {})
        report["provider_disagreements"] = (
            comparison.get("disagreements", []) if isinstance(comparison, dict) else []
        )
        report["provider_sources"] = metadata.get("sources", [])
        report["price_verified"] = bool(metadata.get("price_verified", True))
        report["price_usable"] = bool(
            metadata.get("price_usable", metadata.get("price_verified", True))
        )
        self.run_context.record_data(
            request.cache_key,
            data_hash=dataframe_sha256(frame),
            quality_report=report,
        )
        self.run_context.record_price_trust(
            request.ticker,
            {
                "verified": report["price_verified"],
                "usable": report["price_usable"],
                "source": source,
                "provider_disagreements": report["provider_disagreements"],
            },
        )

    def _record_source_records(self, records: list[dict[str, Any]]) -> None:
        if not self.run_context:
            return
        for record in records:
            self.run_context.record_data_source(record)

    def _record_disagreement(self, request: DataRequest, comparison: dict[str, Any]) -> None:
        if self.run_context and comparison.get("disagreements"):
            self.run_context.record_provider_disagreement(
                {
                    "ticker": request.ticker,
                    "request": asdict(request),
                    **comparison,
                }
            )

    def _verification_signature(self) -> str:
        return stable_hash(
            {
                "providers": [provider.name for provider in self.providers],
                "cross_validate": self.cross_validate,
                "minimum_valid_sources": self.minimum_valid_sources,
                "disagreement_policy": self.disagreement_policy,
                "max_row_count_delta": self.max_row_count_delta,
                "max_index_mismatches": self.max_index_mismatches,
                "max_relative_price_delta": self.max_relative_price_delta,
            }
        )

    def _throttle_provider(self, provider_name: str) -> None:
        limit = self.provider_rate_limits_per_minute.get(provider_name)
        last_request = self._provider_last_request_at.get(provider_name)
        if not limit or last_request is None:
            return
        wait_seconds = 60.0 / limit - (time.monotonic() - last_request)
        if wait_seconds > 0:
            time.sleep(wait_seconds)


def _source_record(
    provider: str,
    request: DataRequest,
    frame: pd.DataFrame,
    *,
    status: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "category": ProviderCategory.PRICE.value,
        "ticker": request.ticker,
        "status": status,
        "rows": len(frame),
        "first_date": str(frame.index.min()) if not frame.empty else None,
        "last_date": str(frame.index.max()) if not frame.empty else None,
        "hash": dataframe_sha256(frame) if not frame.empty else None,
    }
