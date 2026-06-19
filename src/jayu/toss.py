from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .provider_core import HttpJsonClient, ProviderPolicy


class JsonRequester(Protocol):
    def request_json(self, method: str, url: str, **kwargs: Any) -> Any: ...


class TossCredentialsError(ValueError):
    """Raised when Toss Open API credentials or account headers are missing."""


@dataclass(frozen=True)
class TossGetEndpoint:
    operation_id: str
    path: str
    requires_account: bool = False


TOSS_GET_ENDPOINTS: tuple[TossGetEndpoint, ...] = (
    TossGetEndpoint("getOrderbook", "/api/v1/orderbook"),
    TossGetEndpoint("getPrices", "/api/v1/prices"),
    TossGetEndpoint("getTrades", "/api/v1/trades"),
    TossGetEndpoint("getPriceLimit", "/api/v1/price-limits"),
    TossGetEndpoint("getCandles", "/api/v1/candles"),
    TossGetEndpoint("getStocks", "/api/v1/stocks"),
    TossGetEndpoint("getStockWarnings", "/api/v1/stocks/{symbol}/warnings"),
    TossGetEndpoint("getExchangeRate", "/api/v1/exchange-rate"),
    TossGetEndpoint("getKrMarketCalendar", "/api/v1/market-calendar/KR"),
    TossGetEndpoint("getUsMarketCalendar", "/api/v1/market-calendar/US"),
    TossGetEndpoint("getAccounts", "/api/v1/accounts"),
    TossGetEndpoint("getHoldings", "/api/v1/holdings", requires_account=True),
    TossGetEndpoint("getOrders", "/api/v1/orders", requires_account=True),
    TossGetEndpoint("getOrder", "/api/v1/orders/{orderId}", requires_account=True),
    TossGetEndpoint("getBuyingPower", "/api/v1/buying-power", requires_account=True),
    TossGetEndpoint("getSellableQuantity", "/api/v1/sellable-quantity", requires_account=True),
    TossGetEndpoint("getCommissions", "/api/v1/commissions", requires_account=True),
)


class TossInvestClient:
    """Read-only Toss Securities Open API client.

    The client intentionally implements only GET market/account endpoints plus
    the OAuth token exchange required to authenticate those reads. Order
    submission, modification, and cancellation endpoints are out of scope.
    """

    base_url = "https://openapi.tossinvest.com"
    token_path = "/oauth2/token"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        account: str | None = None,
        base_url: str | None = None,
        policy: ProviderPolicy | None = None,
        client: JsonRequester | None = None,
    ):
        if not api_key.strip() or not secret_key.strip():
            raise TossCredentialsError("Toss Open API requires api_key and secret_key")
        self.api_key = api_key
        self.secret_key = secret_key
        self.account = account.strip() if account and account.strip() else None
        self.base_url = (base_url or self.base_url).rstrip("/")
        self.policy = policy or ProviderPolicy(rate_limit_per_minute=120, cache_ttl_seconds=60)
        self.client = client or HttpJsonClient(self.policy)
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _token(self) -> str:
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token
        payload = self.client.request_json(
            "POST",
            self._url(self.token_path),
            data={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if not isinstance(payload, Mapping) or not payload.get("access_token"):
            raise TossCredentialsError("Toss token response did not include access_token")
        expires_in = _int_or_default(payload.get("expires_in"), 3600)
        self._access_token = str(payload["access_token"])
        self._token_expires_at = now + max(0, expires_in - 60)
        return self._access_token

    def _headers(self, *, account: str | None, requires_account: bool) -> dict[str, str]:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self._token()}"}
        resolved_account = account.strip() if account and account.strip() else self.account
        if requires_account:
            if not resolved_account:
                raise TossCredentialsError(
                    "Toss account endpoint requires --account or TS_ACCOUNT/JAYU_TOSS_ACCOUNT"
                )
            headers["X-Tossinvest-Account"] = resolved_account
        return headers

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        account: str | None = None,
        requires_account: bool = False,
    ) -> Any:
        clean_params = {
            key: _param_value(value)
            for key, value in (params or {}).items()
            if value is not None
        }
        return self.client.request_json(
            "GET",
            self._url(path),
            params=clean_params,
            headers=self._headers(account=account, requires_account=requires_account),
        )

    def orderbook(self, symbol: str) -> Any:
        return self._get("/api/v1/orderbook", params={"symbol": _symbol(symbol)})

    def prices(self, symbols: str | Sequence[str]) -> Any:
        return self._get("/api/v1/prices", params={"symbols": _symbols(symbols)})

    def trades(self, symbol: str, *, count: int = 50) -> Any:
        _ensure_range("count", count, minimum=1, maximum=50)
        return self._get("/api/v1/trades", params={"symbol": _symbol(symbol), "count": count})

    def price_limits(self, symbol: str) -> Any:
        return self._get("/api/v1/price-limits", params={"symbol": _symbol(symbol)})

    def candles(
        self,
        symbol: str,
        *,
        interval: Literal["1m", "1d"],
        count: int = 100,
        before: str | None = None,
        adjusted: bool = True,
    ) -> Any:
        if interval not in {"1m", "1d"}:
            raise ValueError("interval must be one of: 1m, 1d")
        _ensure_range("count", count, minimum=1, maximum=200)
        return self._get(
            "/api/v1/candles",
            params={
                "symbol": _symbol(symbol),
                "interval": interval,
                "count": count,
                "before": before,
                "adjusted": adjusted,
            },
        )

    def stocks(self, symbols: str | Sequence[str]) -> Any:
        return self._get("/api/v1/stocks", params={"symbols": _symbols(symbols)})

    def stock_warnings(self, symbol: str) -> Any:
        return self._get(f"/api/v1/stocks/{_symbol(symbol)}/warnings")

    def exchange_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        date_time: str | None = None,
    ) -> Any:
        return self._get(
            "/api/v1/exchange-rate",
            params={
                "dateTime": date_time,
                "baseCurrency": base_currency.strip().upper(),
                "quoteCurrency": quote_currency.strip().upper(),
            },
        )

    def market_calendar_kr(self, *, date: str | None = None) -> Any:
        return self._get("/api/v1/market-calendar/KR", params={"date": date})

    def market_calendar_us(self, *, date: str | None = None) -> Any:
        return self._get("/api/v1/market-calendar/US", params={"date": date})

    def accounts(self) -> Any:
        return self._get("/api/v1/accounts")

    def holdings(self, *, account: str | None = None, symbol: str | None = None) -> Any:
        return self._get(
            "/api/v1/holdings",
            params={"symbol": _symbol(symbol) if symbol else None},
            account=account,
            requires_account=True,
        )

    def orders(
        self,
        *,
        status: Literal["OPEN", "CLOSED"],
        account: str | None = None,
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> Any:
        if status not in {"OPEN", "CLOSED"}:
            raise ValueError("status must be one of: OPEN, CLOSED")
        _ensure_range("limit", limit, minimum=1, maximum=100)
        return self._get(
            "/api/v1/orders",
            params={
                "status": status,
                "symbol": _symbol(symbol) if symbol else None,
                "from": from_date,
                "to": to_date,
                "cursor": cursor,
                "limit": limit,
            },
            account=account,
            requires_account=True,
        )

    def order(self, order_id: str, *, account: str | None = None) -> Any:
        if not order_id.strip():
            raise ValueError("order_id must not be empty")
        return self._get(
            f"/api/v1/orders/{order_id.strip()}",
            account=account,
            requires_account=True,
        )

    def buying_power(self, *, currency: str, account: str | None = None) -> Any:
        return self._get(
            "/api/v1/buying-power",
            params={"currency": currency.strip().upper()},
            account=account,
            requires_account=True,
        )

    def sellable_quantity(self, symbol: str, *, account: str | None = None) -> Any:
        return self._get(
            "/api/v1/sellable-quantity",
            params={"symbol": _symbol(symbol)},
            account=account,
            requires_account=True,
        )

    def commissions(self, *, account: str | None = None) -> Any:
        return self._get("/api/v1/commissions", account=account, requires_account=True)


def _symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")
    return symbol


def _symbols(values: str | Sequence[str]) -> str:
    if isinstance(values, str):
        raw = values.split(",")
    else:
        raw = list(values)
    symbols = [_symbol(symbol) for symbol in raw if str(symbol).strip()]
    if not symbols:
        raise ValueError("symbols must contain at least one symbol")
    if len(symbols) > 200:
        raise ValueError("symbols supports at most 200 symbols")
    return ",".join(symbols)


def _param_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ensure_range(name: str, value: int, *, minimum: int, maximum: int) -> None:
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
