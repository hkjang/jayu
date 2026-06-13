from __future__ import annotations

from collections.abc import Iterable


def is_korean_ticker(ticker: str) -> bool:
    symbol = ticker.strip().upper()
    return symbol.endswith((".KS", ".KQ"))


def benchmark_for_ticker(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if symbol.endswith(".KS"):
        return "^KS11"
    if symbol.endswith(".KQ"):
        return "^KQ11"
    if symbol in {"SOXL", "SOXS", "NVDL", "NVDA"}:
        return "^SOX"
    return "^IXIC"


def benchmarks_for_tickers(tickers: Iterable[str]) -> list[str]:
    return sorted({benchmark_for_ticker(ticker) for ticker in tickers})


def vix_filter_applies(ticker: str) -> bool:
    return not is_korean_ticker(ticker)


def currency_for_ticker(ticker: str) -> str:
    return "KRW" if is_korean_ticker(ticker) else "USD"


def format_market_price(ticker: str, value: float | None) -> str:
    if value is None:
        return "N/A"
    if is_korean_ticker(ticker):
        return f"KRW {value:,.0f}"
    return f"USD {value:,.2f}"


def format_market_notional(ticker: str, value: float) -> str:
    if is_korean_ticker(ticker):
        return f"KRW {value:,.0f}"
    return f"USD {value / 1_000_000:.1f}M"
