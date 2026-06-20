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
