from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .io import atomic_write_json
from .portfolio import PortfolioMapping
from .provider_core import (
    HttpJsonClient,
    JsonCache,
    ProviderCategory,
    ProviderPolicy,
)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def point_in_time_rows(
    rows: Sequence[Mapping[str, Any]],
    as_of: datetime,
    *,
    timestamp_key: str,
) -> list[dict[str, Any]]:
    cutoff = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    visible: list[dict[str, Any]] = []
    for row in rows:
        known_at = _parse_datetime(row.get(timestamp_key))
        if known_at is not None and known_at <= cutoff:
            visible.append(dict(row))
    return visible


def _filing_date_fallback(value: Any) -> str | None:
    if not value:
        return None
    return f"{value}T23:59:59Z"


class SecEdgarProvider:
    name = "sec_edgar"
    category = ProviderCategory.FUNDAMENTALS
    base_url = "https://data.sec.gov"
    ticker_url = "https://www.sec.gov/files/company_tickers.json"

    def __init__(
        self,
        cache_dir: Path,
        user_agent: str,
        *,
        policy: ProviderPolicy | None = None,
        client: HttpJsonClient | None = None,
    ):
        if not user_agent.strip():
            raise ValueError("SEC EDGAR requires a descriptive user agent")
        self.policy = policy or ProviderPolicy(rate_limit_per_minute=600, cache_ttl_seconds=86_400)
        self.client = client or HttpJsonClient(self.policy)
        self.cache = JsonCache(cache_dir)
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

    def ticker_mapping(self) -> dict[str, dict[str, Any]]:
        key = "company_tickers"
        cached = self.cache.read("reference", key, ttl_seconds=self.policy.cache_ttl_seconds)
        if isinstance(cached, dict):
            return cached
        payload = self.client.request_json("GET", self.ticker_url, headers=self.headers)
        mapping = {
            str(row["ticker"]).upper(): {
                "ticker": str(row["ticker"]).upper(),
                "cik": str(row["cik_str"]).zfill(10),
                "title": row.get("title"),
            }
            for row in payload.values()
            if isinstance(row, Mapping) and row.get("ticker") and row.get("cik_str") is not None
        }
        self.cache.write("reference", key, mapping)
        return mapping

    def cik_for_ticker(self, ticker: str) -> str:
        record = self.ticker_mapping().get(ticker.upper())
        if not record:
            raise KeyError(f"SEC CIK not found for ticker {ticker}")
        return str(record["cik"])

    def _get(self, namespace: str, url: str, key: Mapping[str, Any]) -> dict[str, Any]:
        cached = self.cache.read(namespace, key, ttl_seconds=self.policy.cache_ttl_seconds)
        if isinstance(cached, dict):
            return cached
        payload = self.client.request_json("GET", url, headers=self.headers)
        if not isinstance(payload, dict):
            raise ValueError(f"SEC {namespace} response must be an object")
        self.cache.write(namespace, key, payload)
        return payload

    def submissions(self, ticker: str) -> dict[str, Any]:
        cik = self.cik_for_ticker(ticker)
        return self._get(
            "submissions",
            f"{self.base_url}/submissions/CIK{cik}.json",
            {"ticker": ticker.upper(), "cik": cik},
        )

    def companyfacts(self, ticker: str) -> dict[str, Any]:
        cik = self.cik_for_ticker(ticker)
        return self._get(
            "companyfacts",
            f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json",
            {"ticker": ticker.upper(), "cik": cik},
        )

    def companyconcept(
        self,
        ticker: str,
        concept: str,
        *,
        taxonomy: str = "us-gaap",
    ) -> dict[str, Any]:
        cik = self.cik_for_ticker(ticker)
        return self._get(
            "companyconcept",
            f"{self.base_url}/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json",
            {
                "ticker": ticker.upper(),
                "cik": cik,
                "taxonomy": taxonomy,
                "concept": concept,
            },
        )

    def filing_timeline(self, ticker: str) -> list[dict[str, Any]]:
        recent = self.submissions(ticker).get("filings", {}).get("recent", {})
        if not isinstance(recent, Mapping):
            return []
        accessions = recent.get("accessionNumber", [])
        rows: list[dict[str, Any]] = []
        for index, accession in enumerate(accessions):
            accepted_values = recent.get("acceptanceDateTime", [])
            filed_values = recent.get("filingDate", [])
            rows.append(
                {
                    "accession": accession,
                    "form": _value_at(recent.get("form", []), index),
                    "filing_date": _value_at(filed_values, index),
                    "accepted_at": _value_at(accepted_values, index)
                    or _filing_date_fallback(_value_at(filed_values, index)),
                }
            )
        return rows

    def point_in_time_facts(
        self,
        ticker: str,
        as_of: datetime,
        *,
        concept: str | None = None,
        taxonomy: str = "us-gaap",
    ) -> list[dict[str, Any]]:
        payload = (
            self.companyconcept(ticker, concept, taxonomy=taxonomy)
            if concept
            else self.companyfacts(ticker)
        )
        accession_timeline = {str(row["accession"]): row for row in self.filing_timeline(ticker)}
        facts_root: Mapping[str, Any]
        if concept:
            facts_root = {taxonomy: {concept: payload}}
        else:
            raw_facts = payload.get("facts", {})
            facts_root = raw_facts if isinstance(raw_facts, Mapping) else {}
        rows: list[dict[str, Any]] = []
        for tax_name, concepts in facts_root.items():
            if not isinstance(concepts, Mapping):
                continue
            for concept_name, fact in concepts.items():
                if not isinstance(fact, Mapping):
                    continue
                units = fact.get("units", {})
                if not isinstance(units, Mapping):
                    continue
                for unit, values in units.items():
                    if not isinstance(values, list):
                        continue
                    for value in values:
                        if not isinstance(value, Mapping):
                            continue
                        accession = str(value.get("accn") or "")
                        timeline = accession_timeline.get(accession, {})
                        filing_date = value.get("filed") or timeline.get("filing_date")
                        accepted_at = timeline.get("accepted_at") or _filing_date_fallback(
                            filing_date
                        )
                        rows.append(
                            {
                                **dict(value),
                                "taxonomy": tax_name,
                                "concept": concept_name,
                                "unit": unit,
                                "filing_date": filing_date,
                                "accepted_at": accepted_at,
                            }
                        )
        self.cache.write(
            "normalized_facts",
            {
                "ticker": ticker.upper(),
                "taxonomy": taxonomy,
                "concept": concept,
            },
            rows,
        )
        return point_in_time_rows(rows, as_of, timestamp_key="accepted_at")


def _value_at(values: Any, index: int) -> Any:
    return values[index] if isinstance(values, list) and index < len(values) else None


FRED_BASE_SERIES = ("FEDFUNDS", "DGS10", "DGS2", "CPIAUCSL", "UNRATE", "VIXCLS")


class FredMacroProvider:
    name = "fred"
    category = ProviderCategory.MACRO
    base_url = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(
        self,
        cache_dir: Path,
        api_key: str,
        *,
        policy: ProviderPolicy | None = None,
        client: HttpJsonClient | None = None,
    ):
        self.api_key = api_key
        self.policy = policy or ProviderPolicy(rate_limit_per_minute=120, cache_ttl_seconds=86_400)
        self.client = client or HttpJsonClient(self.policy)
        self.cache = JsonCache(cache_dir)

    def observations(
        self,
        series_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        key = {"series_id": series_id, "start": start, "end": end, "output_type": 4}
        cached = self.cache.read("series", key, ttl_seconds=self.policy.cache_ttl_seconds)
        if isinstance(cached, list):
            return cached
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "output_type": 4,
            "observation_start": start or "1776-07-04",
            "observation_end": end or "9999-12-31",
        }
        payload = self.client.request_json("GET", self.base_url, params=params)
        raw = payload.get("observations", []) if isinstance(payload, Mapping) else []
        rows = [
            {
                "series_id": series_id,
                "observation_date": row.get("date"),
                "available_at": row.get("realtime_start"),
                "value": None if row.get("value") == "." else float(row["value"]),
            }
            for row in raw
            if isinstance(row, Mapping) and row.get("date") and row.get("realtime_start")
        ]
        self.cache.write("series", key, rows)
        return rows

    def align_to_trading_days(
        self,
        observations: Sequence[Mapping[str, Any]],
        trading_days: pd.DatetimeIndex,
        *,
        as_of: datetime | None = None,
    ) -> pd.Series:
        cutoff = as_of or datetime.max.replace(tzinfo=UTC)
        visible = point_in_time_rows(observations, cutoff, timestamp_key="available_at")
        if not visible:
            return pd.Series(index=trading_days, dtype=float)
        frame = pd.DataFrame(visible)
        frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True).dt.tz_localize(None)
        frame = frame.sort_values("available_at").drop_duplicates("available_at", keep="last")
        values = pd.Series(
            frame["value"].to_numpy(),
            index=pd.DatetimeIndex(frame["available_at"]),
            dtype=float,
        )
        return (
            values.reindex(trading_days.union(values.index))
            .sort_index()
            .ffill()
            .reindex(trading_days)
        )

    def feature_frame(
        self,
        trading_days: pd.DatetimeIndex,
        *,
        series_ids: Sequence[str] = FRED_BASE_SERIES,
        as_of: datetime | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        frame = pd.DataFrame(index=trading_days)
        for series_id in series_ids:
            frame[series_id] = self.align_to_trading_days(
                self.observations(series_id, start=start, end=end),
                trading_days,
                as_of=as_of,
            )
        if {"DGS10", "DGS2"} <= set(frame):
            frame["yield_curve_10y_2y"] = frame["DGS10"] - frame["DGS2"]
        if "CPIAUCSL" in frame:
            frame["inflation_yoy"] = frame["CPIAUCSL"].pct_change(252, fill_method=None)
        if "FEDFUNDS" in frame:
            frame["policy_rate_change_63d"] = frame["FEDFUNDS"].diff(63)
        if "UNRATE" in frame:
            frame["unemployment_change_63d"] = frame["UNRATE"].diff(63)
        frame["macro_regime"] = _macro_regime(frame)
        return frame


def _macro_regime(frame: pd.DataFrame) -> pd.Series:
    regimes = pd.Series("neutral", index=frame.index, dtype="object")
    risk_off = pd.Series(False, index=frame.index)
    if "VIXCLS" in frame:
        risk_off |= frame["VIXCLS"] >= 25
    if "yield_curve_10y_2y" in frame:
        risk_off |= frame["yield_curve_10y_2y"] < 0
    regimes.loc[risk_off] = "risk_off"
    if "inflation_yoy" in frame:
        regimes.loc[(~risk_off) & (frame["inflation_yoy"] > 0.03)] = "inflationary"
    if "unemployment_change_63d" in frame:
        regimes.loc[
            (~risk_off) & (frame["unemployment_change_63d"] <= 0) & (regimes == "neutral")
        ] = "expansion"
    return regimes


def assess_macro_regime_gate(
    baseline_fold_returns: Sequence[float],
    gated_fold_returns: Sequence[float],
    *,
    minimum_return_retention: float = 0.90,
    minimum_positive_fold_ratio: float = 0.50,
) -> dict[str, Any]:
    if not baseline_fold_returns or len(baseline_fold_returns) != len(gated_fold_returns):
        return {"approved": False, "reasons": ["incomplete_macro_gate_oos_folds"]}
    baseline = sum(baseline_fold_returns)
    gated = sum(gated_fold_returns)
    retention = gated / baseline if baseline > 0 else None
    positive_ratio = sum(value > 0 for value in gated_fold_returns) / len(gated_fold_returns)
    reasons: list[str] = []
    if retention is None or retention < minimum_return_retention:
        reasons.append("macro_gate_return_retention_below_threshold")
    if positive_ratio < minimum_positive_fold_ratio:
        reasons.append("macro_gate_positive_fold_ratio_below_threshold")
    return {
        "approved": not reasons,
        "reasons": reasons,
        "return_retention": retention,
        "positive_fold_ratio": positive_ratio,
        "thresholds": {
            "minimum_return_retention": minimum_return_retention,
            "minimum_positive_fold_ratio": minimum_positive_fold_ratio,
        },
    }


@dataclass(frozen=True)
class ReferenceAudit:
    ticker: str
    status: str
    candidates: list[dict[str, Any]]
    issues: list[str]

    @property
    def blocks_signal(self) -> bool:
        return self.status == "conflict"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "status": self.status,
            "candidates": self.candidates,
            "issues": self.issues,
            "blocks_signal": self.blocks_signal,
        }


class OpenFigiProvider:
    name = "openfigi"
    category = ProviderCategory.REFERENCE
    url = "https://api.openfigi.com/v3/mapping"

    def __init__(
        self,
        cache_dir: Path,
        api_key: str | None = None,
        *,
        policy: ProviderPolicy | None = None,
        client: HttpJsonClient | None = None,
    ):
        self.api_key = api_key
        self.policy = policy or ProviderPolicy(rate_limit_per_minute=25, cache_ttl_seconds=604_800)
        self.client = client or HttpJsonClient(self.policy)
        self.cache = JsonCache(cache_dir)

    def map_ticker(self, ticker: str, *, exchange_code: str | None = None) -> list[dict[str, Any]]:
        key = {"ticker": ticker.upper(), "exchange_code": exchange_code}
        cached = self.cache.read("mapping", key, ttl_seconds=self.policy.cache_ttl_seconds)
        if isinstance(cached, list):
            return cached
        query_ticker = ticker.upper().removesuffix(".KS").removesuffix(".KQ")
        job: dict[str, Any] = {"idType": "TICKER", "idValue": query_ticker}
        if exchange_code:
            job["exchCode"] = exchange_code
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        payload = self.client.request_json("POST", self.url, headers=headers, json=[job])
        first = payload[0] if isinstance(payload, list) and payload else {}
        raw = first.get("data", []) if isinstance(first, Mapping) else []
        rows = [
            {
                "ticker": item.get("ticker"),
                "exchange": item.get("exchCode"),
                "figi": item.get("figi"),
                "composite_figi": item.get("compositeFIGI"),
                "security_type": item.get("securityType2") or item.get("securityType"),
                "market_sector": item.get("marketSector"),
                "name": item.get("name"),
            }
            for item in raw
            if isinstance(item, Mapping)
        ]
        self.cache.write("mapping", key, rows)
        return rows

    def audit_ticker(
        self,
        ticker: str,
        portfolio_mapping: PortfolioMapping,
        *,
        exchange_code: str | None = None,
    ) -> ReferenceAudit:
        candidates = self.map_ticker(ticker, exchange_code=exchange_code)
        issues: list[str] = []
        if not candidates:
            return ReferenceAudit(ticker, "unmapped", [], ["openfigi_no_match"])
        distinct_figis = {row.get("composite_figi") or row.get("figi") for row in candidates}
        distinct_figis.discard(None)
        if len(distinct_figis) > 1:
            issues.append("multiple_openfigi_instruments")
        expected_ticker = ticker.upper().removesuffix(".KS").removesuffix(".KQ")
        if any(str(row.get("ticker") or "").upper() != expected_ticker for row in candidates):
            issues.append("openfigi_ticker_mismatch")
        mapped = portfolio_mapping.lookup(ticker).mapped
        if not mapped:
            issues.append("portfolio_mapping_missing")
        status = (
            "conflict"
            if any(issue != "portfolio_mapping_missing" for issue in issues)
            else ("warning" if issues else "verified")
        )
        return ReferenceAudit(ticker, status, candidates, issues)


class AlphaVantageNewsProvider:
    name = "alpha_vantage_news"
    category = ProviderCategory.NEWS
    url = "https://www.alphavantage.co/query"

    def __init__(
        self,
        cache_dir: Path,
        api_key: str,
        *,
        policy: ProviderPolicy | None = None,
        client: HttpJsonClient | None = None,
    ):
        self.api_key = api_key
        self.policy = policy or ProviderPolicy(rate_limit_per_minute=5, cache_ttl_seconds=900)
        self.client = client or HttpJsonClient(self.policy)
        self.cache = JsonCache(cache_dir)

    def fetch(
        self,
        ticker: str,
        *,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        key = {
            "ticker": ticker.upper(),
            "time_from": time_from.isoformat() if time_from else None,
            "time_to": time_to.isoformat() if time_to else None,
            "limit": limit,
        }
        cached = self.cache.read("news", key, ttl_seconds=self.policy.cache_ttl_seconds)
        if isinstance(cached, list):
            return cached
        params: dict[str, Any] = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker.upper(),
            "limit": limit,
            "sort": "LATEST",
            "apikey": self.api_key,
        }
        if time_from:
            params["time_from"] = time_from.strftime("%Y%m%dT%H%M")
        if time_to:
            params["time_to"] = time_to.strftime("%Y%m%dT%H%M")
        payload = self.client.request_json("GET", self.url, params=params)
        feed = payload.get("feed", []) if isinstance(payload, Mapping) else []
        rows = []
        for item in feed:
            if not isinstance(item, Mapping):
                continue
            ticker_scores = item.get("ticker_sentiment", [])
            score = next(
                (
                    entry.get("ticker_sentiment_score")
                    for entry in ticker_scores
                    if isinstance(entry, Mapping)
                    and str(entry.get("ticker", "")).upper() == ticker.upper()
                ),
                None,
            )
            published = str(item.get("time_published") or "")
            try:
                published_at = datetime.strptime(published, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
            except ValueError:
                continue
            rows.append(
                {
                    "ticker": ticker.upper(),
                    "published_at": published_at.isoformat(),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "source": item.get("source"),
                    "sentiment_score": float(score) if score is not None else None,
                    "overall_sentiment_score": item.get("overall_sentiment_score"),
                }
            )
        rows.sort(key=lambda row: str(row["published_at"]))
        self.cache.write("news", key, rows)
        return rows

    def visible_news(self, ticker: str, as_of: datetime) -> list[dict[str, Any]]:
        return point_in_time_rows(
            self.fetch(ticker, time_to=as_of), as_of, timestamp_key="published_at"
        )


class FinnhubEventProvider:
    name = "finnhub_events"
    category = ProviderCategory.NEWS
    base_url = "https://finnhub.io/api/v1"

    def __init__(
        self,
        cache_dir: Path,
        api_key: str,
        *,
        policy: ProviderPolicy | None = None,
        client: HttpJsonClient | None = None,
    ):
        self.api_key = api_key
        self.policy = policy or ProviderPolicy(rate_limit_per_minute=30, cache_ttl_seconds=900)
        self.client = client or HttpJsonClient(self.policy)
        self.cache = JsonCache(cache_dir)

    def _get(
        self,
        namespace: str,
        endpoint: str,
        params: dict[str, Any],
    ) -> Any:
        key = {"endpoint": endpoint, **params}
        cached = self.cache.read(namespace, key, ttl_seconds=self.policy.cache_ttl_seconds)
        if cached is not None:
            return cached
        payload = self.client.request_json(
            "GET",
            f"{self.base_url}/{endpoint}",
            params={**params, "token": self.api_key},
        )
        self.cache.write(namespace, key, payload)
        return payload

    def company_news(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        payload = self._get(
            "company_news",
            "company-news",
            {"symbol": ticker.upper(), "from": start.isoformat(), "to": end.isoformat()},
        )
        rows = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, Mapping) or not item.get("datetime"):
                continue
            published_at = datetime.fromtimestamp(float(item["datetime"]), tz=UTC)
            rows.append(
                {
                    "event_type": "news",
                    "ticker": ticker.upper(),
                    "published_at": published_at.isoformat(),
                    "known_at": published_at.isoformat(),
                    "headline": item.get("headline"),
                    "source": item.get("source"),
                    "url": item.get("url"),
                }
            )
        return sorted(rows, key=lambda row: str(row["known_at"]))

    def insider_sentiment(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
        collected_at: datetime,
    ) -> list[dict[str, Any]]:
        payload = self._get(
            "insider_sentiment",
            "stock/insider-sentiment",
            {"symbol": ticker.upper(), "from": start.isoformat(), "to": end.isoformat()},
        )
        raw = payload.get("data", []) if isinstance(payload, Mapping) else []
        return [
            {
                "event_type": "insider_sentiment",
                "ticker": ticker.upper(),
                "year": item.get("year"),
                "month": item.get("month"),
                "mspr": item.get("mspr"),
                "change": item.get("change"),
                # Finnhub does not expose a publication timestamp here. The
                # collection time is the earliest defensible known-at value.
                "known_at": collected_at.isoformat(),
            }
            for item in raw
            if isinstance(item, Mapping)
        ]

    def earnings_calendar(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
        collected_at: datetime,
    ) -> list[dict[str, Any]]:
        payload = self._get(
            "earnings_calendar",
            "calendar/earnings",
            {"symbol": ticker.upper(), "from": start.isoformat(), "to": end.isoformat()},
        )
        raw = payload.get("earningsCalendar", []) if isinstance(payload, Mapping) else []
        return [
            {
                "event_type": "earnings_calendar",
                "ticker": ticker.upper(),
                "event_date": item.get("date"),
                "hour": item.get("hour"),
                "eps_estimate": item.get("epsEstimate"),
                "revenue_estimate": item.get("revenueEstimate"),
                "known_at": collected_at.isoformat(),
            }
            for item in raw
            if isinstance(item, Mapping)
        ]

    def event_snapshot(
        self,
        ticker: str,
        *,
        as_of: datetime,
        lookback_days: int = 30,
        lookahead_days: int = 14,
    ) -> list[dict[str, Any]]:
        start = (as_of - pd.Timedelta(days=lookback_days)).date()
        end = (as_of + pd.Timedelta(days=lookahead_days)).date()
        rows = [
            *self.company_news(ticker, start=start, end=as_of.date()),
            *self.insider_sentiment(
                ticker,
                start=start,
                end=as_of.date(),
                collected_at=as_of,
            ),
            *self.earnings_calendar(
                ticker,
                start=as_of.date(),
                end=end,
                collected_at=as_of,
            ),
        ]
        return point_in_time_rows(rows, as_of, timestamp_key="known_at")


def write_supplemental_snapshot(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_json(path, {"generated_at": datetime.now(UTC).isoformat(), **dict(payload)})
