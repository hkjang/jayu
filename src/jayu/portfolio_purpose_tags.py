from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Allowed tags for portfolio classification
ALLOWED_TAGS = {"노후", "자녀", "단기자금", "배당", "실험", "현금대기"}

class PortfolioPurposeTags:
    """Manages purpose tags mapping for portfolios and tickers."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.tags_file = project_root / "state" / "portfolio_purpose_tags.json"

    def load_tags(self) -> dict[str, list[str]]:
        """Load ticker-to-tags mapping from JSON."""
        if not self.tags_file.exists():
            return {}
        try:
            with open(self.tags_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Filter and sanitize
                    return {k: [t for t in v if t in ALLOWED_TAGS] for k, v in data.items() if isinstance(v, list)}
                return {}
        except Exception:
            return {}

    def save_tags(self, tags_map: dict[str, list[str]]) -> None:
        """Save ticker-to-tags mapping to JSON."""
        self.tags_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.tags_file, "w", encoding="utf-8") as f:
            json.dump(tags_map, f, indent=2, ensure_ascii=False)

    def get_tags(self, ticker: str) -> list[str]:
        """Get tags list for a specific ticker."""
        tags_map = self.load_tags()
        return tags_map.get(ticker.upper(), [])

    def set_tags(self, ticker: str, tags: list[str]) -> list[str]:
        """Overwrite tags list for a specific ticker."""
        tags_map = self.load_tags()
        sanitized = sorted(list({t.strip() for t in tags if t.strip() in ALLOWED_TAGS}))
        tags_map[ticker.upper()] = sanitized
        self.save_tags(tags_map)
        return sanitized

    def add_tag(self, ticker: str, tag: str) -> list[str]:
        """Add a specific tag to a ticker if not present."""
        if tag not in ALLOWED_TAGS:
            raise ValueError(f"Invalid tag: {tag}. Allowed: {ALLOWED_TAGS}")
        tags = self.get_tags(ticker)
        if tag not in tags:
            tags.append(tag)
            return self.set_tags(ticker, tags)
        return tags

    def remove_tag(self, ticker: str, tag: str) -> list[str]:
        """Remove a specific tag from a ticker."""
        tags = self.get_tags(ticker)
        if tag in tags:
            tags.remove(tag)
            return self.set_tags(ticker, tags)
        return tags
