from pathlib import Path

from jayu.portfolio_build import build_portfolio_csv


def test_build_portfolio_csv_updates_prices_without_subprocess(tmp_path: Path):
    portfolio = tmp_path / "portfolio.csv"
    portfolio.write_text(
        "name,ticker,quantity,market_value,currency\nSOXL,SOXL,2,0,USD\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        '{"version": 1, "tickers": {"SOXL": {"currency": "USD"}}}',
        encoding="utf-8",
    )

    report = build_portfolio_csv(
        portfolio,
        mapping_file=mapping,
        price_provider=lambda tickers: {"SOXL": 10.0},
    )

    content = portfolio.read_text(encoding="utf-8-sig")
    assert report.price_success_count == 1
    assert "SOXL" in content
    assert "20.0" in content


def test_build_portfolio_csv_reports_unmapped_names(tmp_path: Path):
    portfolio = tmp_path / "portfolio.csv"
    portfolio.write_text(
        "name,ticker,quantity,market_value,currency\n한글종목,?,1,0,USD\n",
        encoding="utf-8",
    )

    report = build_portfolio_csv(portfolio, price_provider=lambda tickers: {})

    assert report.unmapped_names == ["한글종목"]
