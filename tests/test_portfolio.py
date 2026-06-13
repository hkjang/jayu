from __future__ import annotations

from pathlib import Path

import pytest

from jayu.portfolio import (
    load_portfolio,
    load_portfolio_mapping,
    portfolio_summary,
    unmapped_ticker_report,
)


def _mapping_file(path: Path) -> Path:
    mapping = path / "portfolio_mapping.json"
    mapping.write_text(
        """
{
  "version": 1,
  "tickers": {
    "SOXL": {
      "leverage_factor": 3,
      "underlying_group": "semiconductors",
      "sector": "semiconductors",
      "factors": ["semiconductors", "technology", "leveraged"]
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    return mapping


def test_portfolio_csv_and_factor_exposure_use_external_mapping(tmp_path: Path):
    path = tmp_path / "portfolio.csv"
    path.write_text(
        "name,ticker,quantity,market_value,currency\nSOXL,SOXL,1,100,USD\nUnknown,ZZZZ,1,50,USD\n",
        encoding="utf-8",
    )
    mapping = load_portfolio_mapping(_mapping_file(tmp_path))

    summary = portfolio_summary(
        load_portfolio(path, usd_krw=1000, mapping=mapping),
        account_value_krw=200_000,
        cash_balance_krw=50_000,
    )

    assert summary["adjusted_gross_exposure"] == pytest.approx(1.75)
    assert summary["factor_exposure_pct"]["semiconductors"] == pytest.approx(1.5)
    assert summary["currency_exposure_pct"]["USD"] == pytest.approx(0.75)
    assert summary["cash_pct"] == pytest.approx(0.25)
    assert summary["unmapped_tickers"] == ["ZZZZ"]


def test_unmapped_ticker_report_lists_missing_symbols(tmp_path: Path):
    path = tmp_path / "portfolio.csv"
    path.write_text(
        "name,ticker,quantity,market_value,currency\nUnknown,ZZZZ,1,50,USD\n",
        encoding="utf-8",
    )

    summary = portfolio_summary(load_portfolio(path, usd_krw=1000, mapping=_mapping_file(tmp_path)))
    report = unmapped_ticker_report(summary)

    assert report["unmapped_count"] == 1
    assert report["unmapped_tickers"] == ["ZZZZ"]
    assert report["positions"][0]["ticker"] == "ZZZZ"


def test_default_mapping_supports_samsung_korean_equity():
    mapping = load_portfolio_mapping(Path("configs/portfolio_mapping.json"))

    lookup = mapping.lookup("005930.KS")

    assert lookup.mapped is True
    assert lookup.mapping.currency == "KRW"
    assert lookup.mapping.sector == "semiconductors"
    assert lookup.mapping.leverage_factor == 1.0


def test_portfolio_rejects_missing_columns(tmp_path: Path):
    path = tmp_path / "portfolio.csv"
    path.write_text("ticker,market_value\nSOXL,100\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        load_portfolio(path, usd_krw=1000, mapping=_mapping_file(tmp_path))


def test_portfolio_supports_injected_fx_rates(tmp_path: Path):
    path = tmp_path / "portfolio.csv"
    path.write_text(
        "name,ticker,quantity,market_value,currency\nJPY Fund,JPYX,1,100,JPY\n",
        encoding="utf-8",
    )

    positions = load_portfolio(
        path,
        usd_krw=1000,
        mapping=_mapping_file(tmp_path),
        fx_rates={"JPY": 9.0},
    )

    assert positions[0].market_value_krw == 900


def test_portfolio_rejects_unknown_currency_without_rate(tmp_path: Path):
    path = tmp_path / "portfolio.csv"
    path.write_text(
        "name,ticker,quantity,market_value,currency\nJPY Fund,JPYX,1,100,JPY\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="provide an fx_rates entry"):
        load_portfolio(path, usd_krw=1000, mapping=_mapping_file(tmp_path))
