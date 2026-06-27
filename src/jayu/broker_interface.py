from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from .toss import TossInvestClient

@runtime_checkable
class BaseBrokerAdapter(Protocol):
    """Standard multi-broker interface definition for Jayu."""

    def get_account_summary(self, account_seq: str | None = None) -> dict[str, Any]:
        """Retrieve account balance, assets, and metadata."""
        ...

    def get_holdings(self, account_seq: str | None = None) -> list[dict[str, Any]]:
        """Retrieve currently held security positions."""
        ...

    def get_buying_power(self, currency: str = "KRW", account_seq: str | None = None) -> dict[str, Any]:
        """Retrieve available purchasing power for trading."""
        ...

    def get_sellable_quantity(self, ticker: str, account_seq: str | None = None) -> dict[str, Any]:
        """Retrieve the quantity of a specific security that is available to sell."""
        ...

    def get_commissions_rate(self, account_seq: str | None = None) -> dict[str, Any]:
        """Retrieve commission rates and fees information."""
        ...

    def execute_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float | None = None,
        account_seq: str | None = None,
    ) -> dict[str, Any]:
        """Execute a new order. Raises NotImplementedError if the broker is read-only."""
        ...

    def cancel_order(self, order_id: str, account_seq: str | None = None) -> dict[str, Any]:
        """Cancel an existing open order. Raises NotImplementedError if the broker is read-only."""
        ...


class TossBrokerAdapter(BaseBrokerAdapter):
    """Read-only adapter for Toss Securities Open API.
    
    Strictly prevents any order submission or execution actions.
    """

    def __init__(self, client: TossInvestClient) -> None:
        self.client = client

    def get_account_summary(self, account_seq: str | None = None) -> dict[str, Any]:
        # TossInvestClient handles the default account internally if None is passed.
        # But we pass it if provided.
        resp = self.client.accounts()
        return {"broker": "toss", "status": "success", "data": resp}

    def get_holdings(self, account_seq: str | None = None) -> list[dict[str, Any]]:
        resp = self.client.holdings(account=account_seq)
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict) and "holdings" in resp:
            return resp["holdings"]
        return [resp] if resp else []

    def get_buying_power(self, currency: str = "KRW", account_seq: str | None = None) -> dict[str, Any]:
        resp = self.client.buying_power(currency=currency, account=account_seq)
        return {"broker": "toss", "currency": currency, "data": resp}

    def get_sellable_quantity(self, ticker: str, account_seq: str | None = None) -> dict[str, Any]:
        resp = self.client.sellable_quantity(symbol=ticker, account=account_seq)
        return {"broker": "toss", "ticker": ticker, "data": resp}

    def get_commissions_rate(self, account_seq: str | None = None) -> dict[str, Any]:
        resp = self.client.commissions(account=account_seq)
        return {"broker": "toss", "data": resp}

    def execute_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price: float | None = None,
        account_seq: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "Toss API integration is strictly read-only; order execution is disabled."
        )

    def cancel_order(self, order_id: str, account_seq: str | None = None) -> dict[str, Any]:
        raise NotImplementedError(
            "Toss API integration is strictly read-only; order cancellation is disabled."
        )
