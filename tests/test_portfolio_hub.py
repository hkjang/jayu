from datetime import date, timedelta

from jayu import portfolio_hub


def test_portfolio_hub_interprets_active_buy_sell_conflict(monkeypatch):
    def fake_fetch(ticker: str) -> dict:
        return {
            "ticker": ticker,
            "latest_price": 100.0,
            "change_pct": 12.0,
            "rsi2": 95.0,
            "rsi14": 32.0,
            "macd_hist": 0.5,
            "ema20": 90.0,
            "ema50": 80.0,
            "ema200": 70.0,
            "atr": 4.0,
            "volume_ratio": 2.0,
            "change_52w_pct": 20.0,
            "near_52w_high": False,
            "near_52w_low": False,
            "dividend_yield": None,
            "ex_dividend_date": None,
            "data_quality": "good",
        }

    monkeypatch.setattr(portfolio_hub, "fetch_ticker_data", fake_fetch)

    result = portfolio_hub.build_portfolio_hub(
        ["MIX"],
        portfolio_type_map={"MIX": ["short_term", "swing"]},
    )

    conflict = result["signal_conflicts"]["items"][0]
    assert conflict["ticker"] == "MIX"
    assert conflict["level"] == "high"
    assert conflict["conflict_type"] == "active_buy_sell_conflict"
    assert conflict["primary_action"] == "defer_order"
    assert conflict["active_type_labels"] == ["단타", "중타"]
    active = {item["portfolio_type"]: item["signal"] for item in conflict["active_signals"]}
    assert active["short_term"] == "sell_candidate"
    assert active["swing"] == "buy_candidate"
    assert result["signal_conflicts"]["summary"]["high_count"] == 1
    assert result["today_checklist"]["conflict_items"][0]["ticker"] == "MIX"


def test_portfolio_hub_builds_dividend_cashflow(monkeypatch):
    ex_date = (date.today() + timedelta(days=10)).isoformat()

    def fake_fetch(ticker: str) -> dict:
        base = {
            "ticker": ticker,
            "latest_price": 100.0,
            "change_pct": 1.0,
            "rsi2": 50.0,
            "rsi14": 50.0,
            "macd_hist": 0.1,
            "ema20": 95.0,
            "ema50": 90.0,
            "ema200": 80.0,
            "atr": 2.0,
            "volume_ratio": 1.1,
            "change_52w_pct": 8.0,
            "near_52w_high": False,
            "near_52w_low": False,
            "data_quality": "good",
        }
        if ticker == "DIV":
            return {**base, "dividend_yield": 4.0, "ex_dividend_date": ex_date}
        return {**base, "latest_price": 50.0, "dividend_yield": None, "ex_dividend_date": None}

    monkeypatch.setattr(portfolio_hub, "fetch_ticker_data", fake_fetch)

    result = portfolio_hub.build_portfolio_hub(
        ["DIV", "NOY"],
        portfolio_type_map={"DIV": ["dividend"], "NOY": ["dividend"]},
    )

    cashflow = result["dividend_cashflow"]
    assert cashflow["status"] == "warning"
    assert cashflow["summary"]["ticker_count"] == 2
    assert cashflow["summary"]["calculable_count"] == 1
    assert cashflow["summary"]["estimated_annual_income_per_share_total"] == 4.0
    assert cashflow["summary"]["average_yield_pct"] == 4.0
    assert cashflow["summary"]["upcoming_ex_dividend_count"] == 1
    assert cashflow["summary"]["missing_yield_count"] == 1
    assert cashflow["summary"]["unknown_ex_date_count"] == 1
    div_row = next(row for row in cashflow["rows"] if row["ticker"] == "DIV")
    assert div_row["annual_income_per_share"] == 4.0
    assert div_row["days_to_ex"] == 10
    assert "Yahoo Finance" in div_row["source"]
