from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yfinance as yf

from .io import read_json
from .yahoo import get_yahoo_session


DEFAULT_MAPPING_FILE = Path(__file__).resolve().parents[2] / "configs" / "portfolio_mapping.json"

HEADER_ALIASES = {
    "name": ("\uc885\ubaa9\uba85", "name", "security_name"),
    "ticker": ("\ud2f0\ucee4", "ticker", "symbol"),
    "quantity": ("\ubcf4\uc720 \uc218\ub7c9", "quantity", "qty", "shares"),
    "market_value": ("\ud3c9\uac00\uae08", "market_value", "value"),
    "currency": ("\ud1b5\ud654", "currency", "ccy"),
}


@dataclass(frozen=True)
class TickerMapping:
    ticker: str
    leverage_factor: float = 1.0
    underlying_group: str | None = None
    sector: str = "other"
    factors: tuple[str, ...] = ("unmapped",)
    portfolio_types: tuple[str, ...] = ()
    currency: str | None = None

    @classmethod
    def from_raw(cls, ticker: str, raw: Mapping[str, Any]) -> "TickerMapping":
        factors = raw.get("factors", ("unmapped",))
        if isinstance(factors, str):
            factors = (factors,)
        portfolio_types = raw.get("portfolio_types", raw.get("investment_types", ()))
        if isinstance(portfolio_types, str):
            portfolio_types = (portfolio_types,)
        elif not isinstance(portfolio_types, Sequence):
            portfolio_types = ()
        return cls(
            ticker=ticker.upper(),
            leverage_factor=float(raw.get("leverage_factor", 1.0)),
            underlying_group=str(raw.get("underlying_group") or ticker.upper()),
            sector=str(raw.get("sector", "other")),
            factors=tuple(str(factor) for factor in factors),
            portfolio_types=tuple(str(item) for item in portfolio_types if str(item).strip()),
            currency=str(raw["currency"]).upper() if raw.get("currency") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MappingLookup:
    mapping: TickerMapping
    mapped: bool


@dataclass(frozen=True)
class PortfolioMapping:
    version: int
    source: str
    tickers: dict[str, TickerMapping]
    leveraged_name_keywords: tuple[str, ...] = ("\ub808\ubc84\ub9ac\uc9c0",)

    @classmethod
    def empty(cls) -> "PortfolioMapping":
        return cls(version=1, source="empty", tickers={})

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], *, source: str) -> "PortfolioMapping":
        tickers_raw = raw.get("tickers", {})
        if not isinstance(tickers_raw, Mapping):
            raise ValueError("portfolio mapping must contain a tickers object")
        keywords = raw.get("leveraged_name_keywords", ["\ub808\ubc84\ub9ac\uc9c0"])
        if not isinstance(keywords, Sequence) or isinstance(keywords, str):
            raise ValueError("leveraged_name_keywords must be a list")
        return cls(
            version=int(raw.get("version", 1)),
            source=source,
            tickers={
                ticker.upper(): TickerMapping.from_raw(ticker, value)
                for ticker, value in tickers_raw.items()
                if isinstance(value, Mapping)
            },
            leveraged_name_keywords=tuple(str(keyword) for keyword in keywords),
        )

    def lookup(self, ticker: str, *, name: str = "") -> MappingLookup:
        symbol = ticker.upper()
        mapping = self.tickers.get(symbol)
        if mapping:
            return MappingLookup(mapping=mapping, mapped=True)
        leverage = 2.0 if any(keyword in name for keyword in self.leveraged_name_keywords) else 1.0
        return MappingLookup(
            mapping=TickerMapping(
                ticker=symbol,
                leverage_factor=leverage,
                underlying_group=symbol,
                sector="other",
                factors=("unmapped",),
            ),
            mapped=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source": self.source,
            "leveraged_name_keywords": list(self.leveraged_name_keywords),
            "tickers": {
                ticker: mapping.to_dict() for ticker, mapping in sorted(self.tickers.items())
            },
        }


def load_portfolio_mapping(path: Path | None = None) -> PortfolioMapping:
    mapping_path = path or DEFAULT_MAPPING_FILE
    raw = read_json(mapping_path, default=None)
    if raw is None:
        return PortfolioMapping.empty()
    if not isinstance(raw, Mapping):
        raise ValueError(f"portfolio mapping must be a JSON object: {mapping_path}")
    return PortfolioMapping.from_raw(raw, source=str(mapping_path))


@dataclass
class Position:
    name: str
    ticker: str
    quantity: float
    market_value: float
    currency: str
    market_value_krw: float
    leverage_factor: float
    underlying_group: str
    sector: str
    factors: tuple[str, ...]
    mapping_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _resolve_headers(fieldnames: Sequence[str] | None) -> dict[str, str]:
    available = set(fieldnames or [])
    resolved: dict[str, str] = {}
    missing = []
    for canonical, aliases in HEADER_ALIASES.items():
        match = next((alias for alias in aliases if alias in available), None)
        if match:
            resolved[canonical] = match
        else:
            missing.append("/".join(aliases))
    if missing:
        raise ValueError(f"portfolio CSV is missing required columns: {', '.join(missing)}")
    return resolved


def _coerce_mapping(mapping: PortfolioMapping | Path | None) -> PortfolioMapping:
    if isinstance(mapping, PortfolioMapping):
        return mapping
    return load_portfolio_mapping(mapping)


def load_portfolio(
    path: Path,
    usd_krw: float,
    *,
    mapping: PortfolioMapping | Path | None = None,
    fx_rates: Mapping[str, float] | None = None,
) -> list[Position]:
    portfolio_mapping = _coerce_mapping(mapping)
    rates = {
        "KRW": 1.0,
        "USD": usd_krw,
        **{k.upper(): float(v) for k, v in (fx_rates or {}).items()},
    }
    positions: list[Position] = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = _resolve_headers(reader.fieldnames)
        for line_number, row in enumerate(reader, start=2):
            value_raw = (row.get(headers["market_value"]) or "").strip()
            if not value_raw:
                continue
            ticker = (row.get(headers["ticker"]) or "").strip().upper()
            if not ticker:
                raise ValueError(f"portfolio CSV row {line_number} has an empty ticker")
            try:
                value = float(value_raw.replace(",", ""))
                quantity = float((row.get(headers["quantity"]) or "0").replace(",", ""))
            except ValueError as exc:
                raise ValueError(
                    f"portfolio CSV row {line_number} has a non-numeric value"
                ) from exc
            currency = (row.get(headers["currency"]) or "USD").strip().upper()
            if currency not in rates:
                raise ValueError(
                    f"portfolio CSV row {line_number} has unsupported currency {currency}; "
                    "provide an fx_rates entry"
                )
            value_krw = value * rates[currency]
            name = (row.get(headers["name"]) or ticker).strip()
            lookup = portfolio_mapping.lookup(ticker, name=name)
            mapped = lookup.mapping
            positions.append(
                Position(
                    name=name,
                    ticker=ticker,
                    quantity=quantity,
                    market_value=value,
                    currency=currency,
                    market_value_krw=value_krw,
                    leverage_factor=mapped.leverage_factor,
                    underlying_group=mapped.underlying_group or ticker,
                    sector=mapped.sector,
                    factors=mapped.factors,
                    mapping_status="mapped" if lookup.mapped else "unmapped",
                )
            )
    return positions


def get_usd_krw(default: float = 1380.0) -> float:
    try:
        frame = yf.download(
            "USDKRW=X",
            period="5d",
            auto_adjust=True,
            progress=False,
            session=get_yahoo_session(),
        )
        close = frame["Close"].dropna()
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        return float(close.iloc[-1]) if not close.empty else default
    except Exception:
        return default


def get_fx_rates(
    currencies: Iterable[str],
    *,
    defaults: Mapping[str, float] | None = None,
) -> dict[str, float]:
    rates = {"KRW": 1.0, **{key.upper(): float(value) for key, value in (defaults or {}).items()}}
    for currency in {item.upper() for item in currencies}:
        if currency in rates:
            continue
        ticker = f"{currency}KRW=X"
        fallback = 1380.0 if currency == "USD" else 1.0
        try:
            frame = yf.download(
                ticker,
                period="5d",
                auto_adjust=True,
                progress=False,
                session=get_yahoo_session(),
            )
            close = frame["Close"].dropna()
            if hasattr(close, "columns"):
                close = close.iloc[:, 0]
            rates[currency] = float(close.iloc[-1]) if not close.empty else fallback
        except Exception:
            rates[currency] = fallback
    return rates


def portfolio_summary(
    positions: Iterable[Position],
    *,
    account_value_krw: float | None = None,
    cash_balance_krw: float | None = None,
    risk_status: dict[str, float] | None = None,
) -> dict[str, Any]:
    rows = list(positions)
    invested = sum(position.market_value_krw for position in rows)
    if account_value_krw is not None and account_value_krw < invested:
        raise ValueError("account_value_krw cannot be smaller than invested value")
    cash_known = account_value_krw is not None or cash_balance_krw is not None
    cash = (
        cash_balance_krw
        if cash_balance_krw is not None
        else max(0.0, (account_value_krw or invested) - invested)
    )
    account_value = account_value_krw or (invested + cash)
    adjusted_total = sum(position.market_value_krw * position.leverage_factor for position in rows)
    leveraged_value = sum(
        position.market_value_krw for position in rows if position.leverage_factor > 1
    )
    underlying: dict[str, float] = {}
    sectors: dict[str, float] = {}
    factors: dict[str, float] = {}
    currency_exposure: dict[str, float] = {}
    for position in rows:
        adjusted = position.market_value_krw * position.leverage_factor
        underlying[position.underlying_group] = (
            underlying.get(position.underlying_group, 0) + adjusted
        )
        sectors[position.sector] = sectors.get(position.sector, 0) + adjusted
        currency_exposure[position.currency] = (
            currency_exposure.get(position.currency, 0) + position.market_value_krw
        )
        for factor in position.factors:
            factors[factor] = factors.get(factor, 0) + adjusted
    denominator = account_value or 1
    return {
        "total_value_krw": invested,
        "account_value_krw": account_value,
        "cash_balance_krw": cash,
        "cash_known": cash_known,
        "cash_pct": cash / denominator,
        "invested_pct": invested / denominator,
        "adjusted_gross_exposure": adjusted_total / denominator,
        "leveraged_etf_value_pct": leveraged_value / denominator,
        "underlying_exposure_pct": {
            key: value / denominator for key, value in sorted(underlying.items())
        },
        "sector_exposure_pct": {key: value / denominator for key, value in sorted(sectors.items())},
        "factor_exposure_pct": {key: value / denominator for key, value in sorted(factors.items())},
        "currency_exposure_pct": {
            key: value / denominator for key, value in sorted(currency_exposure.items())
        },
        "unmapped_tickers": sorted(
            position.ticker for position in rows if position.mapping_status == "unmapped"
        ),
        "risk_status": risk_status or {},
        "positions": [position.to_dict() for position in rows],
    }


def unmapped_ticker_report(summary: Mapping[str, Any]) -> dict[str, Any]:
    tickers = [str(ticker) for ticker in summary.get("unmapped_tickers", [])]
    positions = [
        position
        for position in summary.get("positions", [])
        if isinstance(position, Mapping) and position.get("ticker") in tickers
    ]
    return {
        "unmapped_count": len(tickers),
        "unmapped_tickers": sorted(tickers),
        "positions": positions,
        "recommendation": (
            "Add these symbols to configs/portfolio_mapping.json before relying on "
            "sector, factor, or leverage limits."
        )
        if tickers
        else "All portfolio tickers are mapped.",
    }
