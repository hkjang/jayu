from __future__ import annotations

import json
from pathlib import Path
from typing import Any

class DividendSupplementalSource:
    """Supplemental data source for dividends (DART, SEIBro, FMP, Polygon, Nasdaq, etc.)"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.supplements_path = self.project_root / "state" / "dividend_supplements.json"

    def load_manual_supplements(self) -> dict[str, list[dict[str, Any]]]:
        if not self.supplements_path.exists():
            return {}
        try:
            with open(self.supplements_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_manual_supplement(self, symbol: str, event: dict[str, Any]) -> None:
        supplements = self.load_manual_supplements()
        symbol = symbol.upper()
        
        if symbol not in supplements:
            supplements[symbol] = []
            
        # Update or append event
        # Match by ex_date
        ex_date = event.get("ex_date")
        if not ex_date:
            return
            
        updated = False
        for i, e in enumerate(supplements[symbol]):
            if e.get("ex_date") == ex_date:
                supplements[symbol][i] = event
                updated = True
                break
        if not updated:
            supplements[symbol].append(event)

        try:
            with open(self.supplements_path, "w", encoding="utf-8") as f:
                json.dump(supplements, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def fetch_fmp(self, symbol: str, api_key: str | None = None) -> list[dict[str, Any]]:
        """
        Placeholder for Financial Modeling Prep API.
        Can be integrated if the API key is provided.
        """
        if not api_key:
            return []
        # Return empty for now, can be implemented with requests
        return []

    def fetch_polygon(self, symbol: str, api_key: str | None = None) -> list[dict[str, Any]]:
        """
        Placeholder for Polygon.io Dividend API.
        """
        if not api_key:
            return []
        return []

    def get_supplemental_events(self, symbol: str) -> list[dict[str, Any]]:
        """
        Returns all cached or manually supplied events for a symbol.
        """
        supplements = self.load_manual_supplements()
        return supplements.get(symbol.upper(), [])
