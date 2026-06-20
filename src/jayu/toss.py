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


class TossApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: str | None = None,
        retryable: bool = False,
        action: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code
        self.retryable = retryable
        self.action = action


def _sanitize_error_message(message: str, secrets: list[str]) -> str:
    sanitized = message
    for sec in secrets:
        if sec and len(sec) > 3:
            sanitized = sanitized.replace(sec, "********")
    return sanitized


def _detect_status_code(error_msg: str) -> int | None:
    import re
    match = re.search(r"\b(400|401|403|404|429|5\d{2})\b", error_msg)
    if match:
        return int(match.group(1))
    match = re.search(r"HTTP\s+(\d{3})", error_msg)
    if match:
        return int(match.group(1))
    return None


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
        auth_style: Literal["auto", "basic", "body"] = "auto",
    ):
        if not api_key.strip() or not secret_key.strip():
            raise TossCredentialsError("Toss Open API requires api_key and secret_key")
        self.api_key = api_key
        self.secret_key = secret_key
        self.account = account.strip() if account and account.strip() else None
        self.base_url = (base_url or self.base_url).rstrip("/")
        self.policy = policy or ProviderPolicy(rate_limit_per_minute=120, cache_ttl_seconds=60)
        self.client = client or HttpJsonClient(self.policy)
        self.auth_style = auth_style
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._accounts_cache: list[dict[str, str]] | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _token(self) -> str:
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        import base64

        styles_to_try = []
        if self.auth_style == "basic":
            styles_to_try = ["basic"]
        elif self.auth_style == "body":
            styles_to_try = ["body"]
        else:
            styles_to_try = ["basic", "body"]

        last_exc = None
        for style in styles_to_try:
            try:
                headers = {"Accept": "application/json"}
                data = {"grant_type": "client_credentials"}

                if style == "basic":
                    auth_str = f"{self.api_key}:{self.secret_key}"
                    encoded = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
                    headers["Authorization"] = f"Basic {encoded}"
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                else:
                    data["client_id"] = self.api_key
                    data["client_secret"] = self.secret_key
                    headers["Content-Type"] = "application/x-www-form-urlencoded"

                payload = self.client.request_json(
                    "POST",
                    self._url(self.token_path),
                    data=data,
                    headers=headers,
                )

                if not isinstance(payload, Mapping) or not payload.get("access_token"):
                    raise TossCredentialsError("Toss token response did not include access_token")

                expires_in = _int_or_default(payload.get("expires_in"), 3600)
                self._access_token = str(payload["access_token"])
                self._token_expires_at = now + max(0, expires_in - 60)
                return self._access_token
            except Exception as exc:
                last_exc = exc
                continue

        err_msg = f"Toss token exchange failed: {last_exc}"
        sanitized = _sanitize_error_message(err_msg, [self.api_key, self.secret_key])
        raise TossApiError(
            sanitized,
            status_code=_detect_status_code(err_msg),
            retryable=True,
            action="Verify API keys and check auth style settings",
        )

    def _resolve_account_seq(self, account_val: str | None) -> str:
        try:
            if self._accounts_cache is None:
                accs_resp = self.accounts()
                rows = []
                if isinstance(accs_resp, dict):
                    for key in ("result", "accounts", "accountList", "account_list"):
                        val = accs_resp.get(key)
                        if isinstance(val, list):
                            rows = val
                            break
                    if not rows and "accounts" in accs_resp.get("result", {}):
                        rows = accs_resp["result"]["accounts"]
                elif isinstance(accs_resp, list):
                    rows = accs_resp

                cache = []
                for row in rows:
                    if isinstance(row, dict):
                        seq = str(row.get("accountSeq") or row.get("account_seq") or row.get("accountId") or row.get("account_id") or "").strip()
                        no = str(row.get("accountNo") or row.get("account_no") or row.get("accountNumber") or row.get("account_number") or "").strip()
                        if seq or no:
                            cache.append({"seq": seq, "no": no})
                self._accounts_cache = cache

            if account_val:
                acc_str = str(account_val).strip()
                for item in self._accounts_cache:
                    if item["seq"] == acc_str or item["no"] == acc_str:
                        if item["seq"]:
                            return item["seq"]
                return acc_str
            else:
                if self._accounts_cache:
                    return self._accounts_cache[0]["seq"] or self._accounts_cache[0]["no"]
        except Exception:
            pass
        return str(account_val or "")

    def _headers(self, *, account: str | None, requires_account: bool) -> dict[str, str]:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self._token()}"}
        resolved_account = account.strip() if account and account.strip() else self.account
        if requires_account:
            real_acc = self._resolve_account_seq(resolved_account)
            if not real_acc:
                raise TossCredentialsError(
                    "Toss account endpoint requires --account or TS_ACCOUNT/JAYU_TOSS_ACCOUNT"
                )
            headers["X-Tossinvest-Account"] = real_acc
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

        retries_limit = 3
        token_refreshed = False

        for attempt in range(retries_limit):
            try:
                headers = self._headers(account=account, requires_account=requires_account)
                return self.client.request_json(
                    "GET",
                    self._url(path),
                    params=clean_params,
                    headers=headers,
                )
            except TossCredentialsError:
                raise
            except Exception as exc:
                err_str = str(exc)
                status_code = _detect_status_code(err_str)

                if status_code == 401 and not token_refreshed:
                    self._access_token = None
                    token_refreshed = True
                    continue

                if status_code == 429:
                    time.sleep(1.0)
                    if attempt < retries_limit - 1:
                        continue
                    raise TossApiError(
                        "Toss API rate limit exceeded (429)",
                        status_code=429,
                        retryable=True,
                        action="Wait and retry after cooldown",
                    )

                if status_code and status_code >= 500:
                    if attempt < retries_limit - 1:
                        time.sleep(2**attempt)
                        continue
                    raise TossApiError(
                        f"Toss API server error ({status_code})",
                        status_code=status_code,
                        retryable=True,
                        action="Toss Securities API is experiencing issues. Try again later.",
                    )

                err_msg = f"Toss API request failed on {path}: {exc}"
                sanitized = _sanitize_error_message(
                    err_msg, [self.api_key, self.secret_key, self.account or ""]
                )
                raise TossApiError(
                    sanitized,
                    status_code=status_code,
                    retryable=False,
                    action="Check request parameters or endpoint status",
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


def doctor_diagnose(client: TossInvestClient, paths: RuntimePaths) -> dict[str, Any]:
    """Diagnose Toss credentials and connection status, save report, and return results."""
    import json
    import time

    api_key_set = bool(client.api_key.strip() and client.api_key != "your_toss_api_key")
    secret_key_set = bool(client.secret_key.strip() and client.secret_key != "your_toss_secret_key")
    account_set = bool(client.account)

    diagnosis = {
        "api_key_configured": api_key_set,
        "secret_key_configured": secret_key_set,
        "account_configured": account_set,
        "token_diagnosed": {"status": "skipped", "message": "skipped"},
        "accounts_endpoint_diagnosed": {"status": "skipped", "message": "skipped"},
        "prices_endpoint_diagnosed": {"status": "skipped", "message": "skipped"},
    }

    if not api_key_set or not secret_key_set:
        diagnosis["token_diagnosed"] = {
            "status": "failed",
            "message": "Missing credentials. Check TS_API_KEY and TS_SECRET_KEY in .env",
            "action": "Configure credentials in the project root .env file",
            "retryable": False,
        }
    else:
        try:
            token = client._token()
            diagnosis["token_diagnosed"] = {
                "status": "success",
                "message": "OAuth 2.0 token successfully issued",
                "token_preview": token[:10] + "..." if len(token) > 10 else token,
            }
        except Exception as exc:
            diagnosis["token_diagnosed"] = {
                "status": "failed",
                "message": f"Token request failed: {exc}",
                "action": "Ensure API key and Secret are correct and network is online",
                "retryable": True,
            }

    if diagnosis["token_diagnosed"]["status"] == "success":
        try:
            accs = client.accounts()
            num_accs = 'some'
            if isinstance(accs, dict):
                res = accs.get('result')
                if isinstance(res, list):
                    num_accs = len(res)
                elif isinstance(res, dict) and isinstance(res.get('accounts'), list):
                    num_accs = len(res.get('accounts'))
            elif isinstance(accs, list):
                num_accs = len(accs)

            diagnosis["accounts_endpoint_diagnosed"] = {
                "status": "success",
                "message": f"Accounts API check passed. Found {num_accs} accounts.",
            }
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            retryable = True
            action = "Check Toss Securities service status or retry later"
            if status_code == 401:
                retryable = False
                action = "Token unauthorized. Check API keys or permissions"
            elif status_code == 429:
                action = "Rate limit hit. Wait for cooldown"

            diagnosis["accounts_endpoint_diagnosed"] = {
                "status": "failed",
                "message": f"Accounts request failed: {exc}",
                "action": action,
                "retryable": retryable,
            }

        try:
            client.prices("SOXL")
            diagnosis["prices_endpoint_diagnosed"] = {
                "status": "success",
                "message": "Prices API check passed (SOXL fetch).",
            }
        except Exception as exc:
            diagnosis["prices_endpoint_diagnosed"] = {
                "status": "failed",
                "message": f"Prices request failed: {exc}",
                "action": "Check market session or retry later",
                "retryable": True,
            }

    overall_status = "success"
    failed_keys = []
    for key in ["token_diagnosed", "accounts_endpoint_diagnosed", "prices_endpoint_diagnosed"]:
        st = diagnosis[key]["status"]
        if st == "failed":
            overall_status = "failed"
            failed_keys.append(key)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": overall_status,
        "failed_steps": failed_keys,
        "diagnosis": diagnosis,
    }

    if paths.state_dir:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        report_file = paths.state_dir / "toss_doctor_report.json"
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    return report


def sync_endpoints(client: TossInvestClient, paths: RuntimePaths) -> dict[str, Any]:
    """Download official OpenAPI JSON, check schema drift with local TOSS_GET_ENDPOINTS, and save reports."""
    import json
    import time
    import requests

    url = "https://openapi.tossinvest.com/openapi-docs/latest/openapi.json"
    last_checked = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    spec_json = None
    fetch_error = None
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            spec_json = res.json()
        else:
            fetch_error = f"HTTP {res.status_code}"
    except Exception as exc:
        fetch_error = str(exc)

    if fetch_error:
        snapshot_file = paths.state_dir / "toss_openapi_snapshot.json" if paths.state_dir else None
        if snapshot_file and snapshot_file.exists():
            try:
                with open(snapshot_file, "r", encoding="utf-8") as f:
                    spec_json = json.load(f)
            except OSError:
                pass

        if not spec_json:
            return {
                "last_checked_at": last_checked,
                "status": "failed_to_fetch",
                "message": f"Could not retrieve Toss OpenAPI spec: {fetch_error}",
                "missing_endpoints": [],
                "extra_endpoints": [],
            }

    spec_get_paths = set()
    paths_dict = spec_json.get("paths", {})
    for path_key, path_val in paths_dict.items():
        if isinstance(path_val, Mapping) and "get" in path_val:
            spec_get_paths.add(path_key)

    local_get_paths = {endpoint.path for endpoint in TOSS_GET_ENDPOINTS}

    missing_endpoints = sorted(list(spec_get_paths - local_get_paths))
    extra_endpoints = sorted(list(local_get_paths - spec_get_paths))

    status = "drifted" if (missing_endpoints or extra_endpoints) else "synchronized"

    report = {
        "last_checked_at": last_checked,
        "status": status,
        "missing_endpoints": missing_endpoints,
        "extra_endpoints": extra_endpoints,
    }

    if paths.state_dir:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(paths.state_dir / "toss_api_drift.json", "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

        if not fetch_error and spec_json:
            try:
                with open(paths.state_dir / "toss_openapi_snapshot.json", "w", encoding="utf-8") as f:
                    json.dump(spec_json, f, ensure_ascii=False, indent=2)
            except OSError:
                pass

    return report


def create_snapshot(client: TossInvestClient, paths: RuntimePaths, redact: bool = True) -> dict[str, Any]:
    """Query accounts, holdings, cash levels, commission structure, exchange rates, and calendars."""
    import json
    import time
    import copy

    def _mask_account(value: str) -> str:
        digits = [char for char in value if char.isdigit()]
        if len(digits) < 5:
            return value
        visible = "".join(digits[-4:])
        return f"***-{visible}"

    snapshot = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "accounts": None,
        "holdings": None,
        "buying_power_krw": None,
        "buying_power_usd": None,
        "commissions": None,
        "exchange_rate": None,
        "market_calendar_kr": None,
        "market_calendar_us": None,
        "errors": {},
    }

    try:
        accs = client.accounts()
        if redact and isinstance(accs, dict) and "result" in accs and "accounts" in accs["result"]:
            masked_accs = copy.deepcopy(accs)
            for acc in masked_accs["result"]["accounts"]:
                for key in ["accountNo", "accountNumber", "account_no", "account_number", "maskedAccountNo"]:
                    if key in acc:
                        acc[key] = _mask_account(str(acc[key]))
            snapshot["accounts"] = masked_accs
        else:
            snapshot["accounts"] = accs
    except Exception as exc:
        snapshot["errors"]["accounts"] = str(exc)

    try:
        holdings = client.holdings()
        if redact and isinstance(holdings, dict) and "result" in holdings:
            res_dict = holdings["result"]
            holdings_key = "items" if "items" in res_dict else "holdings" if "holdings" in res_dict else None
            if holdings_key:
                masked_holdings = copy.deepcopy(holdings)
                for item in masked_holdings["result"][holdings_key]:
                    for key in ["accountNo", "accountNumber", "account_no", "account_number"]:
                        if key in item:
                            item[key] = _mask_account(str(item[key]))
                snapshot["holdings"] = masked_holdings
            else:
                snapshot["holdings"] = holdings
        else:
            snapshot["holdings"] = holdings
    except Exception as exc:
        snapshot["errors"]["holdings"] = str(exc)

    try:
        snapshot["buying_power_krw"] = client.buying_power(currency="KRW")
    except Exception as exc:
        snapshot["errors"]["buying_power_krw"] = str(exc)

    try:
        snapshot["buying_power_usd"] = client.buying_power(currency="USD")
    except Exception as exc:
        snapshot["errors"]["buying_power_usd"] = str(exc)

    try:
        snapshot["commissions"] = client.commissions()
    except Exception as exc:
        snapshot["errors"]["commissions"] = str(exc)

    try:
        snapshot["exchange_rate"] = client.exchange_rate(base_currency="USD", quote_currency="KRW")
    except Exception as exc:
        snapshot["errors"]["exchange_rate"] = str(exc)

    try:
        snapshot["market_calendar_kr"] = client.market_calendar_kr()
    except Exception as exc:
        snapshot["errors"]["market_calendar_kr"] = str(exc)

    try:
        snapshot["market_calendar_us"] = client.market_calendar_us()
    except Exception as exc:
        snapshot["errors"]["market_calendar_us"] = str(exc)

    if redact and "errors" in snapshot:
        if client.account:
            masked_val = _mask_account(client.account)
            for k, err_msg in list(snapshot["errors"].items()):
                snapshot["errors"][k] = err_msg.replace(client.account, masked_val)

    if paths.state_dir:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(paths.state_dir / "toss_account_snapshot.json", "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    return snapshot


def reconcile_portfolio_with_toss(
    client: TossInvestClient,
    paths: Any,
    *,
    account: str | None = None,
) -> dict[str, Any]:
    """Reconcile local portfolio.csv with Toss live holdings, identify discrepancies and unmapped tickers."""
    import time
    import json
    from .portfolio import load_portfolio, load_portfolio_mapping

    if not paths.portfolio_file.exists():
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "failed",
            "message": f"Local portfolio file not found: {paths.portfolio_file}",
            "differences": [],
            "unmapped_tickers": [],
        }

    try:
        holdings_res = client.holdings(account=account)
    except Exception as exc:
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "failed",
            "message": f"Failed to fetch live holdings from Toss: {exc}",
            "differences": [],
            "unmapped_tickers": [],
        }

    try:
        exch = client.exchange_rate(base_currency="USD", quote_currency="KRW")
        usd_krw = float(exch.get("rate") or exch.get("exchangeRate") or 1350.0)
    except Exception:
        usd_krw = 1350.0

    mapping = load_portfolio_mapping(paths.portfolio_mapping_file)
    fx_rates = {"USD": usd_krw, "KRW": 1.0}

    try:
        portfolio_positions = load_portfolio(
            paths.portfolio_file,
            usd_krw=usd_krw,
            mapping=mapping,
            fx_rates=fx_rates,
        )
    except Exception as exc:
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "failed",
            "message": f"Failed to load local portfolio: {exc}",
            "differences": [],
            "unmapped_tickers": [],
        }

    def normalize(sym: str) -> str:
        return sym.split(".")[0].upper().strip()

    local_qty_map = {}
    local_orig_map = {}
    for pos in portfolio_positions:
        norm = normalize(pos.ticker)
        local_qty_map[norm] = local_qty_map.get(norm, 0.0) + pos.quantity
        local_orig_map[norm] = pos.ticker

    toss_qty_map = {}
    holdings_res_dict = holdings_res.get("result", {}) if isinstance(holdings_res, dict) else {}
    holdings_list = holdings_res_dict.get("items") or holdings_res_dict.get("holdings") or []
    for h in holdings_list:
        sym = str(h.get("symbol") or h.get("ticker") or "").strip().upper()
        if not sym:
            continue
        norm = normalize(sym)
        toss_qty_map[norm] = toss_qty_map.get(norm, 0.0) + float(h.get("quantity") or h.get("qty") or 0.0)

    all_syms = set(local_qty_map.keys()) | set(toss_qty_map.keys())
    differences = []
    for sym in sorted(all_syms):
        local_qty = local_qty_map.get(sym, 0.0)
        toss_qty = toss_qty_map.get(sym, 0.0)
        diff = local_qty - toss_qty
        if abs(diff) > 1e-4:
            if local_qty > 0 and toss_qty == 0:
                diff_type = "missing_in_toss"
            elif toss_qty > 0 and local_qty == 0:
                diff_type = "missing_in_local"
            else:
                diff_type = "quantity_mismatch"
            differences.append({
                "ticker": local_orig_map.get(sym, sym),
                "local_quantity": local_qty,
                "toss_quantity": toss_qty,
                "difference": diff,
                "type": diff_type,
            })

    unmapped_tickers = []
    for h in holdings_list:
        sym = str(h.get("symbol") or h.get("ticker") or "").strip().upper()
        if not sym:
            continue
        matched_ticker = sym
        if sym.isdigit():
            for mapped_t in mapping.tickers:
                if mapped_t.split(".")[0] == sym:
                    matched_ticker = mapped_t
                    break
        lookup = mapping.lookup(matched_ticker)
        if not lookup.mapped:
            unmapped_tickers.append(sym)

    status = "diverged" if differences or unmapped_tickers else "synchronized"

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "differences": differences,
        "unmapped_tickers": sorted(list(set(unmapped_tickers))),
    }

    if paths.state_dir:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(paths.state_dir / "portfolio_reconciliation.json", "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    return report


def sync_portfolio_from_toss(
    client: TossInvestClient,
    paths: Any,
    *,
    account: str | None = None,
) -> dict[str, Any]:
    """Fetch live holdings from Toss OpenAPI and overwrite the local portfolio.csv file."""
    import csv
    import time

    try:
        resp = client.holdings(account=account)
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"Failed to fetch live holdings from Toss: {exc}"
        }

    holdings_res_dict = resp.get("result", {}) if isinstance(resp, dict) else {}
    holdings_list = holdings_res_dict.get("items") or holdings_res_dict.get("holdings") or []

    portfolio_file = paths.portfolio_file
    try:
        with open(portfolio_file, mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["종목명", "티커", "보유 수량", "현재가", "평가금", "통화"])

            for row in holdings_list:
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol") or row.get("stockCode") or ""
                name = row.get("name") or row.get("stockName") or symbol
                quantity = row.get("quantity") or "0"
                current_price = row.get("currentPrice") or row.get("lastPrice") or "0"

                mv = row.get("marketValue")
                if isinstance(mv, dict):
                    market_value = mv.get("amount") or mv.get("amountAfterCost") or "0"
                else:
                    market_value = mv or "0"

                currency = row.get("currency") or "USD"

                writer.writerow([name, symbol, quantity, current_price, market_value, currency])

        return {
            "status": "success",
            "message": f"Overwrote portfolio CSV with {len(holdings_list)} positions from Toss Securities API."
        }
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"Failed to write to portfolio file: {exc}"
        }


def attach_toss_readiness_to_signals(client: TossInvestClient, paths: Any) -> dict[str, Any]:
    """Fetch live data from Toss to attach real-time buying power, margins, warnings, and calendar session status to decisions."""
    import time
    import json
    from .failure_codes import FailureCode

    signal_file = paths.signal_file
    if not signal_file.exists():
        return {
            "status": "failed",
            "message": f"Signal file not found: {signal_file}",
        }

    try:
        with open(signal_file, "r", encoding="utf-8") as f:
            signals = json.load(f)
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"Failed to load signals: {exc}",
        }

    try:
        holdings_res = client.holdings()
        holdings_list = holdings_res.get("result", {}).get("holdings", []) or []
    except Exception:
        holdings_list = []

    live_tickers = {str(h.get("symbol") or h.get("ticker") or "").strip().upper() for h in holdings_list}

    try:
        bp_krw = client.buying_power(currency="KRW")
        cash_krw = float(bp_krw.get("amount") or bp_krw.get("buyingPower") or 0.0)
    except Exception:
        cash_krw = 0.0

    try:
        bp_usd = client.buying_power(currency="USD")
        cash_usd = float(bp_usd.get("amount") or bp_usd.get("buyingPower") or 0.0)
    except Exception:
        cash_usd = 0.0

    try:
        exch = client.exchange_rate(base_currency="USD", quote_currency="KRW")
        usd_krw = float(exch.get("rate") or exch.get("exchangeRate") or 1350.0)
    except Exception:
        usd_krw = 1350.0

    try:
        commissions = client.commissions()
    except Exception:
        commissions = {}

    try:
        cal_kr = client.market_calendar_kr()
        kr_open = cal_kr.get("open") or cal_kr.get("isOpen") or False
    except Exception:
        kr_open = False

    try:
        cal_us = client.market_calendar_us()
        us_open = cal_us.get("open") or cal_us.get("isOpen") or False
    except Exception:
        us_open = False

    market_session = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "KR": {"open": kr_open, "calendar": cal_kr},
        "US": {"open": us_open, "calendar": cal_us},
    }
    if paths.state_dir:
        try:
            with open(paths.state_dir / "market_session_status.json", "w", encoding="utf-8") as f:
                json.dump(market_session, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    warnings_gate = {}

    for ticker, signal_data in list(signals.items()):
        if not isinstance(signal_data, dict):
            continue

        is_us = not ticker.isdigit() and not ticker.endswith(".KS") and not ticker.endswith(".KQ")
        currency = "USD" if is_us else "KRW"
        buying_power_amount = cash_usd if is_us else cash_krw
        session_open = us_open if is_us else kr_open

        symbol_base = ticker.split(".")[0].upper()
        ticker_warnings = {}
        has_warning = False
        warning_msg = ""
        try:
            warn_res = client.stock_warnings(symbol_base)
            ticker_warnings = warn_res
            res = warn_res.get("result", {}) or {}
            suspended = res.get("suspended") or res.get("isSuspended") or res.get("tradeSuspended") or False
            warning_type = res.get("warningType") or res.get("warning") or ""

            if suspended:
                has_warning = True
                warning_msg = "Trading suspended on broker"
            elif warning_type and warning_type not in ("NONE", "NORMAL"):
                has_warning = True
                warning_msg = f"Broker warning flag: {warning_type}"
        except Exception:
            pass

        warnings_gate[ticker] = {
            "warnings": ticker_warnings,
            "has_warning": has_warning,
            "message": warning_msg,
        }

        is_held = symbol_base in live_tickers or ticker in live_tickers

        signal_data["broker_readiness"] = {
            "is_held": is_held,
            "buying_power": {
                "amount": buying_power_amount,
                "currency": currency,
            },
            "commission_structure": commissions,
            "market_session_open": session_open,
            "warnings": {
                "has_warning": has_warning,
                "message": warning_msg,
                "detail": ticker_warnings,
            }
        }

        if has_warning:
            signal_data["eligible"] = False
            risk = signal_data.setdefault("risk", {})
            if isinstance(risk, dict):
                violations = risk.setdefault("violations", [])
                violations.append(warning_msg)
                violation_details = risk.setdefault("violation_details", [])
                violation_details.append({
                    "code": FailureCode.LIQUIDITY_INSUFFICIENT.value,
                    "message": warning_msg,
                    "metric": "broker_warning",
                    "observed": True,
                    "limit": False,
                })

    if paths.state_dir:
        try:
            with open(paths.state_dir / "stock_warning_gate.json", "w", encoding="utf-8") as f:
                json.dump(warnings_gate, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    try:
        with open(signal_file, "w", encoding="utf-8") as f:
            json.dump(signals, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    order_plan_entries = []
    for ticker, signal_data in signals.items():
        if not isinstance(signal_data, dict):
            continue
        if signal_data.get("action") == "buy" and signal_data.get("eligible") is True:
            suggested_pct = float(signal_data.get("suggested_position_pct") or 0.10)
            approved_pct = float(signal_data.get("approved_position_pct") or suggested_pct)
            price = float(signal_data.get("price") or signal_data.get("close") or 0.0)

            is_us = not ticker.isdigit() and not ticker.endswith(".KS") and not ticker.endswith(".KQ")
            currency = "USD" if is_us else "KRW"
            buying_power_amount = cash_usd if is_us else cash_krw

            est_cash_to_use = buying_power_amount * approved_pct
            est_quantity = est_cash_to_use / price if price > 0 else 0.0

            order_plan_entries.append({
                "ticker": ticker,
                "action": "BUY",
                "suggested_pct": suggested_pct,
                "approved_pct": approved_pct,
                "price": price,
                "currency": currency,
                "estimated_cash": est_cash_to_use,
                "estimated_quantity": est_quantity,
            })

    order_plan = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "orders": order_plan_entries,
    }

    if paths.state_dir:
        try:
            with open(paths.state_dir / "order_plan.json", "w", encoding="utf-8") as f:
                json.dump(order_plan, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

        md_lines = [
            "# Manual Order Plan Report",
            f"Generated At: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            "",
            "The following buy signal candidates are eligible for manual execution based on the latest risk gate check and live broker evidence.",
            "",
            "| Ticker | Action | Approved Pct | Target Cash | Est Price | Est Qty |",
            "|---|---|---|---|---|---|",
        ]
        for entry in order_plan_entries:
            md_lines.append(
                f"| `{entry['ticker']}` | **{entry['action']}** | {entry['approved_pct']:.1%} | "
                f"{entry['estimated_cash']:,.2f} {entry['currency']} | {entry['price']:,.2f} | {entry['estimated_quantity']:.4f} |"
            )
        if not order_plan_entries:
            md_lines.append("| - | - | - | - | - | - |")
            md_lines.append("\n*No eligible buy orders for today.*")

        try:
            with open(paths.state_dir / "order_plan.md", "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines) + "\n")
        except OSError:
            pass

    return {
        "status": "success",
        "attached_count": len(signals),
        "eligible_orders_count": len(order_plan_entries),
    }


def load_live_toss_positions(snapshot: dict[str, Any], mapping: Any, usd_krw: float) -> list[Any]:
    """Parse live holdings and metadata from Toss Open API snapshot into Position structures."""
    from .portfolio import Position

    rates = {"KRW": 1.0, "USD": usd_krw}
    positions = []
    holdings_list = snapshot.get("holdings", {}).get("result", {}).get("holdings", []) or []

    for h in holdings_list:
        ticker = str(h.get("symbol") or h.get("ticker") or "").strip().upper()
        if not ticker:
            continue

        qty = float(h.get("quantity") or h.get("qty") or 0.0)
        price = float(h.get("price") or h.get("currentPrice") or h.get("current_price") or 0.0)
        market_val = float(h.get("marketValue") or h.get("market_value") or h.get("evaluationAmount") or h.get("evaluation_amount") or (qty * price))
        currency = str(h.get("currency") or ("KRW" if ticker.isdigit() else "USD")).strip().upper()

        matched_ticker = ticker
        if ticker.isdigit():
            for mapped_t in mapping.tickers:
                if mapped_t.split(".")[0] == ticker:
                    matched_ticker = mapped_t
                    break

        lookup = mapping.lookup(matched_ticker)
        mapped = lookup.mapping

        rate = rates.get(currency, usd_krw if currency == "USD" else 1.0)
        market_val_krw = market_val * rate

        positions.append(
            Position(
                name=str(h.get("symbolName") or h.get("name") or ticker),
                ticker=matched_ticker,
                quantity=qty,
                market_value=market_val,
                currency=currency,
                market_value_krw=market_val_krw,
                leverage_factor=mapped.leverage_factor,
                underlying_group=mapped.underlying_group or matched_ticker,
                sector=mapped.sector,
                factors=mapped.factors,
                mapping_status="mapped" if lookup.mapped else "unmapped",
            )
        )
    return positions

