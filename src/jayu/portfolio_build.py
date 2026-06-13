from __future__ import annotations

import csv
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yfinance as yf

from .io import read_json
from .portfolio import HEADER_ALIASES, load_portfolio_mapping
from .yahoo import get_yahoo_session

PRICE_HEADER = "\ud604\uc7ac\uac00"
LOGGER = logging.getLogger(__name__)
DEFAULT_FIELDNAMES = [
    "\uc885\ubaa9\uba85",
    "\ud2f0\ucee4",
    "\ubcf4\uc720 \uc218\ub7c9",
    PRICE_HEADER,
    "\ud3c9\uac00\uae08",
    "\ud1b5\ud654",
]


@dataclass(frozen=True)
class PortfolioBuildReport:
    path: str
    row_count: int
    valid_ticker_count: int
    price_success_count: int
    failed_tickers: list[str]
    unmapped_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_optional_headers(fieldnames: Sequence[str] | None) -> dict[str, str | None]:
    available = set(fieldnames or [])
    resolved: dict[str, str | None] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        resolved[canonical] = next((alias for alias in aliases if alias in available), None)
    resolved["price"] = PRICE_HEADER if PRICE_HEADER in available else None
    return resolved


def _load_ticker_map(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    raw = read_json(path, default={})
    if not isinstance(raw, Mapping):
        raise ValueError(f"portfolio ticker map must be a JSON object: {path}")
    return {str(key).strip(): str(value).strip().upper() for key, value in raw.items()}


def _infer_ticker(name: str, ticker: str, ticker_map: Mapping[str, str]) -> str:
    symbol = ticker.strip().upper()
    if symbol and symbol not in {"?", "N/A"}:
        return symbol
    mapped = ticker_map.get(name.strip())
    if mapped:
        return mapped
    candidate = name.strip().upper()
    if candidate and all(ch.isascii() and (ch.isalnum() or ch in ".-") for ch in candidate):
        return candidate
    return "?"


def _currency_for(ticker: str, configured_currency: str | None = None) -> str:
    if configured_currency:
        return configured_currency.upper()
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return "KRW"
    return "USD"


def fetch_latest_prices(tickers: list[str]) -> dict[str, float]:
    valid = [ticker for ticker in tickers if ticker not in {"?", "N/A"}]
    if not valid:
        return {}
    raw = yf.download(
        sorted(set(valid)),
        period="5d",
        auto_adjust=True,
        progress=False,
        session=get_yahoo_session(),
    )
    prices: dict[str, float] = {}
    if hasattr(raw.columns, "levels"):
        for ticker in valid:
            try:
                series = raw["Close"][ticker].dropna()
                if not series.empty:
                    prices[ticker] = round(float(series.iloc[-1]), 4)
            except Exception as exc:
                LOGGER.debug("price fetch failed for %s: %s", ticker, exc)
    else:
        try:
            series = raw["Close"].dropna()
            if not series.empty:
                prices[valid[0]] = round(float(series.iloc[-1]), 4)
        except Exception as exc:
            LOGGER.debug("single ticker price fetch failed: %s", exc)
    return prices


def build_portfolio_csv(
    path: Path,
    *,
    ticker_map_file: Path | None = None,
    mapping_file: Path | None = None,
    price_provider: Callable[[list[str]], dict[str, float]] = fetch_latest_prices,
) -> PortfolioBuildReport:
    ticker_map = _load_ticker_map(ticker_map_file)
    portfolio_mapping = (
        load_portfolio_mapping(mapping_file) if mapping_file else load_portfolio_mapping()
    )

    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = _resolve_optional_headers(reader.fieldnames)
        rows = [dict(row) for row in reader]

    updated_rows = []
    tickers = []
    unmapped_names = []
    for row in rows:
        name_key = headers.get("name")
        ticker_key = headers.get("ticker")
        quantity_key = headers.get("quantity")
        name = (row.get(name_key or "") or "").strip()
        current_ticker = (row.get(ticker_key or "") or "").strip()
        ticker = _infer_ticker(name, current_ticker, ticker_map)
        if ticker == "?":
            unmapped_names.append(name or current_ticker)
        if ticker not in {"?", "N/A"}:
            tickers.append(ticker)
        quantity_raw = (row.get(quantity_key or "") or "0").replace(",", "")
        try:
            quantity = float(quantity_raw)
        except ValueError:
            quantity = 0.0
        lookup = portfolio_mapping.lookup(ticker)
        currency = _currency_for(ticker, lookup.mapping.currency)
        updated_rows.append((row, name, ticker, quantity, currency))

    prices = price_provider(tickers)
    output_rows = []
    for row, name, ticker, quantity, currency in updated_rows:
        price = prices.get(ticker)
        output_rows.append(
            {
                "\uc885\ubaa9\uba85": name or ticker,
                "\ud2f0\ucee4": ticker,
                "\ubcf4\uc720 \uc218\ub7c9": quantity,
                PRICE_HEADER: "" if price is None else price,
                "\ud3c9\uac00\uae08": "" if price is None else round(price * quantity, 2),
                "\ud1b5\ud654": currency,
            }
        )

    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=DEFAULT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(output_rows)

    failed = sorted(set(ticker for ticker in tickers if ticker not in prices))
    return PortfolioBuildReport(
        path=str(path),
        row_count=len(rows),
        valid_ticker_count=len(set(tickers)),
        price_success_count=len(prices),
        failed_tickers=failed,
        unmapped_names=sorted(set(item for item in unmapped_names if item)),
    )
