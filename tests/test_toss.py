from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from jayu.cli import app
from jayu.settings import load_settings
from jayu.toss import TOSS_GET_ENDPOINTS, TossCredentialsError, TossInvestClient


class FakeJsonRequester:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, **kwargs})
        if method == "POST":
            return {"access_token": "access-token", "token_type": "Bearer", "expires_in": 86400}
        return {
            "ok": True,
            "method": method,
            "url": url,
            "params": kwargs.get("params"),
            "headers": kwargs.get("headers"),
        }


def test_toss_get_endpoint_catalog_matches_openapi_get_surface() -> None:
    assert len(TOSS_GET_ENDPOINTS) == 17
    assert {endpoint.operation_id for endpoint in TOSS_GET_ENDPOINTS} == {
        "getOrderbook",
        "getPrices",
        "getTrades",
        "getPriceLimit",
        "getCandles",
        "getStocks",
        "getStockWarnings",
        "getExchangeRate",
        "getKrMarketCalendar",
        "getUsMarketCalendar",
        "getAccounts",
        "getHoldings",
        "getOrders",
        "getOrder",
        "getBuyingPower",
        "getSellableQuantity",
        "getCommissions",
    }


def test_toss_client_maps_all_read_endpoints_to_get_requests() -> None:
    fake = FakeJsonRequester()
    client = TossInvestClient(
        "client-id",
        "client-secret",
        account="account-seq",
        base_url="https://example.test",
        client=fake,
    )

    cases = [
        (lambda: client.orderbook("aapl"), "/api/v1/orderbook", {"symbol": "AAPL"}, False),
        (lambda: client.prices(["aapl", "msft"]), "/api/v1/prices", {"symbols": "AAPL,MSFT"}, False),
        (lambda: client.trades("aapl", count=3), "/api/v1/trades", {"symbol": "AAPL", "count": 3}, False),
        (lambda: client.price_limits("005930"), "/api/v1/price-limits", {"symbol": "005930"}, False),
        (
            lambda: client.candles("aapl", interval="1d", count=10, adjusted=False),
            "/api/v1/candles",
            {"symbol": "AAPL", "interval": "1d", "count": 10, "adjusted": "false"},
            False,
        ),
        (lambda: client.stocks("aapl,msft"), "/api/v1/stocks", {"symbols": "AAPL,MSFT"}, False),
        (lambda: client.stock_warnings("aapl"), "/api/v1/stocks/AAPL/warnings", {}, False),
        (
            lambda: client.exchange_rate(base_currency="usd", quote_currency="krw"),
            "/api/v1/exchange-rate",
            {"baseCurrency": "USD", "quoteCurrency": "KRW"},
            False,
        ),
        (
            lambda: client.market_calendar_kr(date="2026-06-19"),
            "/api/v1/market-calendar/KR",
            {"date": "2026-06-19"},
            False,
        ),
        (
            lambda: client.market_calendar_us(date="2026-06-19"),
            "/api/v1/market-calendar/US",
            {"date": "2026-06-19"},
            False,
        ),
        (lambda: client.accounts(), "/api/v1/accounts", {}, False),
        (lambda: client.holdings(symbol="aapl"), "/api/v1/holdings", {"symbol": "AAPL"}, True),
        (
            lambda: client.orders(status="OPEN", symbol="aapl", limit=5),
            "/api/v1/orders",
            {"status": "OPEN", "symbol": "AAPL", "limit": 5},
            True,
        ),
        (lambda: client.order("order-1"), "/api/v1/orders/order-1", {}, True),
        (
            lambda: client.buying_power(currency="usd"),
            "/api/v1/buying-power",
            {"currency": "USD"},
            True,
        ),
        (
            lambda: client.sellable_quantity("aapl"),
            "/api/v1/sellable-quantity",
            {"symbol": "AAPL"},
            True,
        ),
        (lambda: client.commissions(), "/api/v1/commissions", {}, True),
    ]

    for invoke, path, expected_params, requires_account in cases:
        payload = invoke()
        assert payload["method"] == "GET"
        assert payload["url"] == f"https://example.test{path}"
        assert payload["params"] == expected_params
        assert payload["headers"]["Authorization"] == "Bearer access-token"
        if requires_account:
            assert payload["headers"]["X-Tossinvest-Account"] == "account-seq"

    token_calls = [call for call in fake.calls if call["method"] == "POST"]
    get_calls = [call for call in fake.calls if call["method"] == "GET"]
    assert len(token_calls) == 1
    assert len(get_calls) == len(cases)
    assert token_calls[0]["data"]["grant_type"] == "client_credentials"
    assert token_calls[0]["data"]["client_id"] == "client-id"
    assert token_calls[0]["data"]["client_secret"] == "client-secret"


def test_toss_account_header_is_required_for_account_reads() -> None:
    client = TossInvestClient(
        "client-id",
        "client-secret",
        base_url="https://example.test",
        client=FakeJsonRequester(),
    )

    try:
        client.holdings()
    except TossCredentialsError as exc:
        assert "account" in str(exc)
    else:
        raise AssertionError("account read should require account header")


def test_toss_settings_load_ts_env_aliases_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "TS_API_KEY=client-id",
                "TS_SECRET_KEY=client-secret",
                "TS_ACCOUNT=account-seq",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(None)

    assert settings.toss_api_key is not None
    assert settings.toss_api_key.get_secret_value() == "client-id"
    assert settings.toss_secret_key is not None
    assert settings.toss_secret_key.get_secret_value() == "client-secret"
    assert settings.toss_account is not None
    assert settings.toss_account.get_secret_value() == "account-seq"
    assert settings.public_dict()["toss_api_key"] == "<configured>"
    assert settings.public_dict()["toss_secret_key"] == "<configured>"
    assert settings.public_dict()["toss_account"] == "<configured>"


def test_toss_endpoints_cli_lists_read_only_catalog() -> None:
    result = CliRunner().invoke(app, ["toss", "endpoints"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 17
    assert {item["method"] for item in payload} == {"GET"}
    assert any(item["path"] == "/api/v1/orders" for item in payload)
