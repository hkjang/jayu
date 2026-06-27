from __future__ import annotations

import urllib.parse
from typing import Any


class NotificationDeeplink:
    """Generates precise, clickable deep links for the Jayu Dashboard."""

    def __init__(self, base_url: str = "http://127.0.0.1:9088") -> None:
        self.base_url = base_url.rstrip("/")

    def generate(self, tab: str, params: dict[str, str] | None = None) -> str:
        """Create a deep link for a specific dashboard tab and optional query parameters."""
        # Use Hash Routing as standard for SPA (Single Page Application)
        hash_route = f"/{tab}"
        if params:
            query_str = urllib.parse.urlencode(params)
            hash_route = f"{hash_route}?{query_str}"
        return f"{self.base_url}/#{hash_route}"

    def signal_link(self, ticker: str) -> str:
        """Generate a deep link for a specific ticker signal."""
        return self.generate("signals", {"ticker": ticker.upper()})

    def risk_link(self, rule_name: str, ticker: str | None = None) -> str:
        """Generate a deep link for a risk check block."""
        params = {"rule": rule_name}
        if ticker:
            params["ticker"] = ticker.upper()
        return self.generate("risk", params)

    def data_quality_link(self, field: str | None = None) -> str:
        """Generate a deep link for a data provider disagreement or quality issue."""
        params = {}
        if field:
            params["field"] = field
        return self.generate("data-quality", params)

    def overview_link(self) -> str:
        """Generate a deep link for the general overview dashboard."""
        return self.generate("overview")
