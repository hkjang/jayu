import pandas as pd
import pytest

from jayu.data import (
    CachedMarketDataService,
    DataRequest,
    ProviderCategory,
    TiingoProvider,
    YahooProvider,
    build_quality_report,
    compare_ohlcv_sources,
    dataframe_sha256,
    exchange_calendar_for_ticker,
)


def test_quality_report_rejects_invalid_ohlc():
    frame = pd.DataFrame(
        {
            "Open": [100],
            "High": [99],
            "Low": [98],
            "Close": [100],
            "Volume": [1000],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )

    report = build_quality_report(DataRequest("TEST"), frame)

    assert not report.valid
    assert report.invalid_ohlc_rows == 1


def test_ohlcv_hash_depends_on_content_not_row_order():
    frame = pd.DataFrame(
        {
            "Open": [100, 101],
            "High": [102, 103],
            "Low": [99, 100],
            "Close": [101, 102],
            "Volume": [1000, 1100],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )

    assert dataframe_sha256(frame) == dataframe_sha256(frame.iloc[::-1])


def test_exchange_calendar_matches_us_and_korean_tickers():
    assert exchange_calendar_for_ticker("SOXL") == "XNYS"
    assert exchange_calendar_for_ticker("005930.KS") == "XKRX"
    assert exchange_calendar_for_ticker("247540.KQ") == "XKRX"


def test_quality_report_rejects_duplicate_unsorted_and_negative_volume():
    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102],
            "High": [102, 103, 104],
            "Low": [99, 100, 101],
            "Close": [101, 102, 103],
            "Volume": [1000, -1, 1200],
        },
        index=pd.to_datetime(["2026-01-05", "2026-01-02", "2026-01-02"]),
    )

    report = build_quality_report(DataRequest("TEST"), frame)

    assert report.valid is False
    assert report.duplicate_index_count == 1
    assert report.non_monotonic_index is True
    assert report.invalid_volume_rows == 1


def _price_frame(close_offset: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0 + close_offset, 102.0 + close_offset],
            "Volume": [1000.0, 1100.0],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )


def test_compare_ohlcv_sources_records_hash_and_price_disagreement():
    report = compare_ohlcv_sources(
        {
            "yahoo": _price_frame(),
            "massive": _price_frame(),
            "tiingo": _price_frame(close_offset=0.8),
        }
    )

    assert len(report["sources"]) == 3
    assert report["sources"][0]["ohlcv_hash"] == report["sources"][1]["ohlcv_hash"]
    assert report["agreed"] is False
    assert report["disagreements"][0]["candidate"] == "tiingo"
    assert report["disagreements"][0]["failure_code"] == "DATA_DISAGREEMENT"


def test_compare_ohlcv_sources_records_volume_disagreement():
    baseline = _price_frame()
    high_volume = _price_frame()
    high_volume["Volume"] = [5000.0, 5500.0]

    report = compare_ohlcv_sources(
        {"yahoo": baseline, "tiingo": high_volume},
        max_relative_price_delta=0.01,
        max_relative_volume_delta=0.10,
    )

    assert report["agreed"] is False
    assert report["disagreements"][0]["max_relative_volume_delta"] > 0.10


def test_tiingo_provider_normalizes_adjusted_daily_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "date": "2026-01-02T00:00:00.000Z",
                    "adjOpen": 100,
                    "adjHigh": 102,
                    "adjLow": 99,
                    "adjClose": 101,
                    "adjVolume": 1000,
                }
            ]

    monkeypatch.setattr("jayu.data.requests.get", lambda *args, **kwargs: Response())

    frame = TiingoProvider("secret").fetch(
        DataRequest("TEST", start="2026-01-01", end="2026-01-03")
    )

    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert frame.iloc[0]["Close"] == 101
    assert frame.index.tz is None


def test_yahoo_provider_treats_request_end_as_inclusive(monkeypatch):
    captured = {}

    def fake_download(*args, **kwargs):
        captured.update(kwargs)
        return _price_frame()

    monkeypatch.setattr("jayu.data.yf.download", fake_download)

    YahooProvider().fetch(DataRequest("TEST", period="1y", end="2026-01-05"))

    assert captured["end"] == "2026-01-06"


def test_cached_service_blocks_provider_disagreement(tmp_path):
    class Provider:
        category = ProviderCategory.PRICE

        def __init__(self, name, frame):
            self.name = name
            self.frame = frame

        def fetch(self, request):
            return self.frame

    service = CachedMarketDataService(
        tmp_path,
        [
            Provider("yahoo", _price_frame()),
            Provider("tiingo", _price_frame(close_offset=0.8)),
        ],
        retries=1,
        cross_validate=True,
        minimum_valid_sources=2,
        disagreement_policy="block",
    )

    with pytest.raises(RuntimeError, match="price verification failed"):
        service.fetch(DataRequest("TEST", start="2026-01-01", end="2026-01-06"))

    assert not list(tmp_path.glob("*.parquet"))


def test_provider_disagreement_is_recorded_in_quality_report(tmp_path):
    class Provider:
        category = ProviderCategory.PRICE

        def __init__(self, name, frame):
            self.name = name
            self.frame = frame

        def fetch(self, request):
            return self.frame

    class Context:
        def __init__(self):
            self.data_reports = {}
            self.sources = []
            self.disagreements = []
            self.price_trust = {}

        def record_data(self, key, *, data_hash, quality_report):
            self.data_reports[key] = quality_report

        def record_data_source(self, record):
            self.sources.append(record)

        def record_provider_disagreement(self, report):
            self.disagreements.append(report)

        def record_price_trust(self, ticker, report):
            self.price_trust[ticker] = report

    context = Context()
    service = CachedMarketDataService(
        tmp_path,
        [
            Provider("yahoo", _price_frame()),
            Provider("tiingo", _price_frame(close_offset=0.8)),
        ],
        run_context=context,  # type: ignore[arg-type]
        retries=1,
        cross_validate=True,
        minimum_valid_sources=2,
        disagreement_policy="warn",
    )

    service.fetch(DataRequest("TEST", start="2026-01-01", end="2026-01-06"))

    report = next(iter(context.data_reports.values()))
    assert report["price_usable"] is True
    assert report["price_verified"] is False
    assert report["provider_disagreements"]
    assert context.disagreements[0]["ticker"] == "TEST"
    assert {source["provider"] for source in context.sources} == {"yahoo", "tiingo"}
    assert context.price_trust["TEST"]["verified"] is False
