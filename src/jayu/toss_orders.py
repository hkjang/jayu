from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .paths import RuntimePaths
from .settings import load_settings
from .toss import TossInvestClient


class TossOrdersManager:
    """Manages order history from Toss Securities OpenAPI, caching it in state/toss_orders.json."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.state_dir = project_root / "state"
        self.orders_file = self.state_dir / "toss_orders.json"
        self.order_details_file = self.state_dir / "toss_order_details.json"

    def fetch_and_save(
        self,
        paths: RuntimePaths,
        *,
        account: str | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Fetch the official Order History getOrders surface for the last year.

        Toss OpenAPI exposes Order History as ``GET /api/v1/orders``. CLOSED
        orders use ``limit``/``cursor`` paging; OPEN ignores paging and returns
        all open orders in one call.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        config = paths.config_file if paths.config_file.exists() else None
        settings = load_settings(config)
        api_key = settings.toss_api_key.get_secret_value() if settings.toss_api_key else None
        secret_key = settings.toss_secret_key.get_secret_value() if settings.toss_secret_key else None
        default_account = settings.toss_account.get_secret_value() if settings.toss_account else None
        selected_account = account or default_account

        if not api_key or not secret_key:
            existing = self.load_orders()
            return {
                "status": "missing_credentials",
                "message": "Toss API credentials missing. Loaded cached order history.",
                "count": len(existing),
                "source": "state/toss_orders.json · Toss Order History getOrders cache",
            }

        try:
            client = TossInvestClient(
                api_key=api_key,
                secret_key=secret_key,
                account=selected_account,
                auth_style=settings.toss_oauth_auth_style,
            )
            reference = today or datetime.now(UTC).astimezone().date()
            from_date = (reference - timedelta(days=365)).isoformat()
            to_date = reference.isoformat()
            closed_orders, closed_pages = self._fetch_closed_orders(
                client,
                account=selected_account,
                from_date=from_date,
                to_date=to_date,
            )
            open_orders = self._extract_orders(
                client.orders(
                    status="OPEN",
                    account=selected_account,
                    from_date=from_date,
                    to_date=to_date,
                    limit=100,
                )
            )
            all_orders = [*_normalize_rows(closed_orders, "CLOSED"), *_normalize_rows(open_orders, "OPEN")]

            deduped = {}
            for order in all_orders:
                oid = order.get("orderId")
                if oid:
                    deduped[oid] = order
            sorted_orders = sorted(deduped.values(), key=lambda x: x.get("orderedAt", ""), reverse=True)
            self._save_orders(sorted_orders)
            return {
                "status": "success",
                "message": "Fetched Toss Order History getOrders for the last year.",
                "count": len(sorted_orders),
                "closed_count": len(closed_orders),
                "open_count": len(open_orders),
                "closed_pages": closed_pages,
                "from": from_date,
                "to": to_date,
                "source": "Toss Order History getOrders · GET /api/v1/orders",
            }

        except Exception as e:
            existing = self.load_orders()
            return {
                "status": "fallback",
                "message": f"Toss Order History API error: {str(e)}. Loaded cached order history.",
                "count": len(existing),
                "source": "state/toss_orders.json · Toss Order History getOrders cache",
            }

    def fetch_order_detail(
        self,
        paths: RuntimePaths,
        order_id: str,
        *,
        account: str | None = None,
    ) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        order_id = order_id.strip()
        if not order_id:
            raise ValueError("order_id must not be empty")
        config = paths.config_file if paths.config_file.exists() else None
        settings = load_settings(config)
        api_key = settings.toss_api_key.get_secret_value() if settings.toss_api_key else None
        secret_key = settings.toss_secret_key.get_secret_value() if settings.toss_secret_key else None
        default_account = settings.toss_account.get_secret_value() if settings.toss_account else None
        selected_account = account or default_account
        if not api_key or not secret_key:
            detail = self.load_order_detail(order_id)
            return {
                "status": "missing_credentials",
                "order": detail,
                "source": "state/toss_order_details.json · cached Toss getOrder detail",
            }
        client = TossInvestClient(
            api_key=api_key,
            secret_key=secret_key,
            account=selected_account,
            auth_style=settings.toss_oauth_auth_style,
        )
        payload = client.order(order_id, account=selected_account)
        order = _extract_order(payload)
        self._save_order_detail(order_id, order)
        return {
            "status": "success",
            "order": order,
            "source": "Toss Order History getOrder · GET /api/v1/orders/{orderId}",
        }

    def load_orders(self) -> list[dict[str, Any]]:
        if not self.orders_file.exists():
            return []
        try:
            with open(self.orders_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except Exception:
            return []

    def load_order_detail(self, order_id: str) -> dict[str, Any] | None:
        details = self._load_order_details()
        detail = details.get(order_id)
        return detail if isinstance(detail, dict) else None

    def _save_orders(self, orders: list[dict[str, Any]]) -> None:
        self.orders_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.orders_file, "w", encoding="utf-8") as f:
            json.dump(orders, f, indent=2, ensure_ascii=False)

    def _save_order_detail(self, order_id: str, order: dict[str, Any]) -> None:
        details = self._load_order_details()
        details[order_id] = order
        self.order_details_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.order_details_file, "w", encoding="utf-8") as f:
            json.dump(details, f, indent=2, ensure_ascii=False)

    def _load_order_details(self) -> dict[str, Any]:
        if not self.order_details_file.exists():
            return {}
        try:
            with open(self.order_details_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _fetch_closed_orders(
        self,
        client: TossInvestClient,
        *,
        account: str | None,
        from_date: str,
        to_date: str,
    ) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        cursor = None
        pages = 0
        while True:
            payload = client.orders(
                status="CLOSED",
                account=account,
                from_date=from_date,
                to_date=to_date,
                cursor=cursor,
                limit=100,
            )
            pages += 1
            result = _result(payload)
            rows.extend(self._extract_orders(payload))
            has_next = bool(result.get("hasNext") or result.get("has_next"))
            cursor = result.get("nextCursor") or result.get("next_cursor")
            if not has_next or not cursor:
                return rows, pages

    def _extract_orders(self, payload: Any) -> list[dict[str, Any]]:
        return _extract_orders(payload)

    def _generate_mock_orders(self) -> list[dict[str, Any]]:
        """Generate realistic mock order history over the last 6 years (2020-2026)."""
        import random
        
        tickers = [
            ("AAPL", "USD", 120.0, 185.0),
            ("005930", "KRW", 55000.0, 78000.0),
            ("TSLA", "USD", 150.0, 260.0),
            ("SCHD", "USD", 65.0, 80.0),
            ("O", "USD", 50.0, 68.0),
            ("MSFT", "USD", 220.0, 420.0),
            ("TQQQ", "USD", 25.0, 62.0),
            ("SOXL", "USD", 12.0, 45.0),
        ]
        
        orders = []
        now = datetime.now()
        
        # We generate around 80 orders over 6 years
        for i in range(80):
            # pick random date in past 6 years
            days_ago = random.randint(5, 6 * 365)
            order_time = now - timedelta(days=days_ago, hours=random.randint(0, 23), minutes=random.randint(0, 59))
            
            ticker, currency, min_price, max_price = random.choice(tickers)
            side = random.choice(["BUY", "SELL"])
            
            # Trend price based on age (older = cheaper usually)
            age_factor = (6 * 365 - days_ago) / (6 * 365) # 0 to 1
            price_val = min_price + (max_price - min_price) * age_factor * random.uniform(0.8, 1.2)
            price_val = round(price_val, 2) if currency == "USD" else round(price_val, -2)
            
            qty = random.randint(2, 20) if currency == "USD" else random.randint(5, 100)
            status = random.choice(["FILLED", "FILLED", "FILLED", "CANCELED", "PARTIAL_FILLED"])
            
            # Executed details
            filled_qty = qty if status == "FILLED" else (0 if status == "CANCELED" else random.randint(1, qty - 1))
            avg_price = price_val if filled_qty > 0 else None
            filled_amt = round(filled_qty * avg_price, 2) if avg_price else None
            
            if currency == "KRW":
                commission = round(filled_amt * 0.0015, -1) if filled_amt else None
                tax = round(filled_amt * 0.002, -1) if (filled_amt and side == "SELL") else 0
            else:
                commission = round(filled_amt * 0.0025, 2) if filled_amt else None
                tax = round(filled_amt * 0.00002, 2) if (filled_amt and side == "SELL") else 0

            order_id = f"mock_oid_{order_time.strftime('%Y%m%d%H%M')}_{i:03d}"
            
            orders.append({
                "orderId": order_id,
                "symbol": ticker,
                "side": side,
                "orderType": "LIMIT",
                "timeInForce": "DAY",
                "status": status,
                "price": str(price_val),
                "quantity": str(qty),
                "orderAmount": None,
                "currency": currency,
                "orderedAt": order_time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
                "canceledAt": (order_time + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S+09:00") if status == "CANCELED" else None,
                "execution": {
                    "filledQuantity": str(filled_qty),
                    "averageFilledPrice": str(avg_price) if avg_price else None,
                    "filledAmount": str(filled_amt) if filled_amt else None,
                    "commission": str(commission) if commission else None,
                    "tax": str(tax) if tax else None,
                    "filledAt": (order_time + timedelta(seconds=random.randint(1, 30))).strftime("%Y-%m-%dT%H:%M:%S+09:00") if filled_qty > 0 else None,
                    "settlementDate": None
                }
            })

        # Sort by date descending
        orders.sort(key=lambda x: x["orderedAt"], reverse=True)
        return orders


def _result(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        return payload
    return {}


def _extract_orders(payload: Any) -> list[dict[str, Any]]:
    result = _result(payload)
    for key in ("orders", "items", "result"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    return []


def _extract_order(payload: Any) -> dict[str, Any]:
    result = _result(payload)
    if result and not any(isinstance(result.get(key), list) for key in ("orders", "items")):
        return dict(result)
    if isinstance(payload, dict) and payload.get("orderId"):
        return dict(payload)
    return {}


def _normalize_rows(rows: list[dict[str, Any]], history_status: str) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        item = dict(row)
        item.setdefault("historyStatus", history_status)
        item.setdefault("source", "Toss Order History getOrders · GET /api/v1/orders")
        normalized.append(item)
    return normalized
