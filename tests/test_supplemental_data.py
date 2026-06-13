from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from jayu.portfolio import PortfolioMapping
from jayu.provider_core import ProviderPolicy
from jayu.supplemental_data import (
    AlphaVantageNewsProvider,
    FinnhubEventProvider,
    FredMacroProvider,
    OpenFigiProvider,
    SecEdgarProvider,
    assess_macro_regime_gate,
)


class FakeJsonClient:
    def __init__(self, payloads: dict[str, Any]):
        self.payloads = payloads

    def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        for marker, payload in self.payloads.items():
            if marker in url:
                return payload
        raise AssertionError(f"unexpected request: {method} {url} {kwargs}")


def test_sec_companyfacts_are_filtered_by_accepted_time(tmp_path: Path):
    client = FakeJsonClient(
        {
            "company_tickers.json": {
                "0": {"ticker": "TEST", "cik_str": 1234, "title": "Test Corp"}
            },
            "/submissions/": {
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000001234-25-000001"],
                        "form": ["10-Q"],
                        "filingDate": ["2025-05-01"],
                        "acceptanceDateTime": ["2025-05-01T16:30:00Z"],
                    }
                }
            },
            "/companyfacts/": {
                "facts": {
                    "us-gaap": {
                        "Revenue": {
                            "units": {
                                "USD": [
                                    {
                                        "accn": "0000001234-25-000001",
                                        "filed": "2025-05-01",
                                        "val": 100,
                                    }
                                ]
                            }
                        }
                    }
                }
            },
        }
    )
    provider = SecEdgarProvider(
        tmp_path,
        "Jayu research contact@example.com",
        policy=ProviderPolicy(cache_ttl_seconds=0),
        client=client,  # type: ignore[arg-type]
    )

    before = provider.point_in_time_facts(
        "TEST",
        datetime(2025, 5, 1, 16, 29, tzinfo=UTC),
    )
    after = provider.point_in_time_facts(
        "TEST",
        datetime(2025, 5, 1, 16, 31, tzinfo=UTC),
    )

    assert before == []
    assert after[0]["val"] == 100
    assert after[0]["filing_date"] == "2025-05-01"
    assert after[0]["accepted_at"] == "2025-05-01T16:30:00Z"


def test_fred_forward_fill_starts_at_initial_release_date(tmp_path: Path):
    provider = FredMacroProvider(
        tmp_path,
        "test-key",
        client=FakeJsonClient({}),  # type: ignore[arg-type]
    )
    trading_days = pd.to_datetime(["2025-01-09", "2025-01-10", "2025-01-13"])
    observations = [
        {
            "series_id": "CPIAUCSL",
            "observation_date": "2024-12-01",
            "available_at": "2025-01-10",
            "value": 320.0,
        }
    ]

    aligned = provider.align_to_trading_days(observations, trading_days)

    assert pd.isna(aligned.loc["2025-01-09"])
    assert aligned.loc["2025-01-10"] == pytest.approx(320.0)
    assert aligned.loc["2025-01-13"] == pytest.approx(320.0)


def test_macro_regime_requires_separate_oos_gate():
    approved = assess_macro_regime_gate(
        [0.10, 0.05, 0.03],
        [0.10, 0.05, 0.025],
    )
    rejected = assess_macro_regime_gate(
        [0.10, 0.05, 0.03],
        [0.01, -0.02, -0.01],
    )

    assert approved["approved"] is True
    assert rejected["approved"] is False
    assert "macro_gate_return_retention_below_threshold" in rejected["reasons"]


def test_fred_feature_frame_generates_point_in_time_regime(tmp_path: Path, monkeypatch):
    provider = FredMacroProvider(
        tmp_path,
        "test-key",
        client=FakeJsonClient({}),  # type: ignore[arg-type]
    )
    values = {
        "DGS10": 4.0,
        "DGS2": 5.0,
        "VIXCLS": 30.0,
    }

    def observations(series_id, **kwargs):
        return [
            {
                "series_id": series_id,
                "observation_date": "2025-01-01",
                "available_at": "2025-01-02",
                "value": values[series_id],
            }
        ]

    monkeypatch.setattr(provider, "observations", observations)
    frame = provider.feature_frame(
        pd.to_datetime(["2025-01-02", "2025-01-03"]),
        series_ids=("DGS10", "DGS2", "VIXCLS"),
        as_of=datetime(2025, 1, 3, tzinfo=UTC),
    )

    assert frame.loc["2025-01-03", "yield_curve_10y_2y"] == pytest.approx(-1.0)
    assert frame.loc["2025-01-03", "macro_regime"] == "risk_off"


def test_openfigi_conflict_blocks_reference_audit(tmp_path: Path):
    client = FakeJsonClient(
        {
            "/v3/mapping": [
                {
                    "data": [
                        {
                            "ticker": "TEST",
                            "figi": "FIGI1",
                            "compositeFIGI": "COMP1",
                            "exchCode": "US",
                            "securityType2": "Common Stock",
                            "marketSector": "Equity",
                        },
                        {
                            "ticker": "TEST",
                            "figi": "FIGI2",
                            "compositeFIGI": "COMP2",
                            "exchCode": "LN",
                            "securityType2": "Common Stock",
                            "marketSector": "Equity",
                        },
                    ]
                }
            ]
        }
    )
    provider = OpenFigiProvider(tmp_path, client=client)  # type: ignore[arg-type]

    audit = provider.audit_ticker("TEST", PortfolioMapping.empty())

    assert audit.status == "conflict"
    assert audit.blocks_signal is True
    assert "multiple_openfigi_instruments" in audit.issues


def test_news_is_ordered_and_filtered_by_published_at(tmp_path: Path):
    client = FakeJsonClient(
        {
            "alphavantage.co": {
                "feed": [
                    {
                        "time_published": "20250602T120000",
                        "title": "future",
                        "ticker_sentiment": [{"ticker": "TEST", "ticker_sentiment_score": "0.2"}],
                    },
                    {
                        "time_published": "20250601T120000",
                        "title": "visible",
                        "ticker_sentiment": [{"ticker": "TEST", "ticker_sentiment_score": "-0.1"}],
                    },
                ]
            }
        }
    )
    provider = AlphaVantageNewsProvider(
        tmp_path,
        "test-key",
        policy=ProviderPolicy(cache_ttl_seconds=0),
        client=client,  # type: ignore[arg-type]
    )

    visible = provider.visible_news(
        "TEST",
        datetime(2025, 6, 1, 18, 0, tzinfo=UTC),
    )

    assert [row["title"] for row in visible] == ["visible"]
    assert visible[0]["sentiment_score"] == pytest.approx(-0.1)


def test_finnhub_snapshot_keeps_news_insider_and_earnings_as_notes(tmp_path: Path):
    published = int(datetime(2025, 6, 1, 12, 0, tzinfo=UTC).timestamp())
    client = FakeJsonClient(
        {
            "company-news": [{"datetime": published, "headline": "filing update"}],
            "insider-sentiment": {"data": [{"year": 2025, "month": 5, "mspr": 12.5, "change": 4}]},
            "calendar/earnings": {
                "earningsCalendar": [{"date": "2025-06-05", "hour": "amc", "epsEstimate": 1.2}]
            },
        }
    )
    provider = FinnhubEventProvider(
        tmp_path,
        "test-key",
        policy=ProviderPolicy(cache_ttl_seconds=0),
        client=client,  # type: ignore[arg-type]
    )

    rows = provider.event_snapshot(
        "TEST",
        as_of=datetime(2025, 6, 2, 12, 0, tzinfo=UTC),
    )

    assert {row["event_type"] for row in rows} == {
        "news",
        "insider_sentiment",
        "earnings_calendar",
    }
    assert all(row["known_at"] <= "2025-06-02T12:00:00+00:00" for row in rows)
