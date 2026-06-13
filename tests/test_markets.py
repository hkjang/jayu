from jayu.markets import (
    benchmark_for_ticker,
    benchmarks_for_tickers,
    currency_for_ticker,
    format_market_notional,
    format_market_price,
    is_korean_ticker,
    vix_filter_applies,
)


def test_korean_tickers_use_domestic_benchmarks():
    assert benchmark_for_ticker("005930.KS") == "^KS11"
    assert benchmark_for_ticker("247540.KQ") == "^KQ11"
    assert is_korean_ticker("005930.ks") is True
    assert vix_filter_applies("005930.KS") is False
    assert currency_for_ticker("005930.KS") == "KRW"
    assert format_market_price("005930.KS", 72300) == "KRW 72,300"
    assert format_market_price("005930.KS", None) == "N/A"
    assert format_market_notional("005930.KS", 1_500_000_000) == "KRW 1,500,000,000"


def test_us_tickers_keep_us_benchmarks_and_vix_filter():
    assert benchmark_for_ticker("SOXL") == "^SOX"
    assert benchmark_for_ticker("TQQQ") == "^IXIC"
    assert vix_filter_applies("TQQQ") is True
    assert format_market_price("TQQQ", 55.5) == "USD 55.50"
    assert format_market_notional("TQQQ", 12_500_000) == "USD 12.5M"
    assert benchmarks_for_tickers(["SOXL", "TQQQ", "005930.KS"]) == [
        "^IXIC",
        "^KS11",
        "^SOX",
    ]
