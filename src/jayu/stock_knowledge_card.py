from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class StockKnowledgeCardManager:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.cards_dir = self.state_dir / "knowledge_cards"
        self.cards_dir.mkdir(parents=True, exist_ok=True)

    def get_default_template(self, ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker.upper(),
            "investment_hypothesis": "투자 가설이 등록되지 않았습니다.",
            "reason_for_holding": "보유 이유가 등록되지 않았습니다.",
            "exit_conditions": "매도 조건이 등록되지 않았습니다.",
            "risk_factors": "주요 위험 요인이 등록되지 않았습니다.",
            "upcoming_events": [],
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def save_card(self, ticker: str, card_data: dict[str, Any]) -> dict[str, Any]:
        """Saves a stock knowledge card to state/knowledge_cards/{ticker}.json."""
        ticker = ticker.upper()
        card_file = self.cards_dir / f"{ticker}.json"
        
        # Merge with default template to ensure schema completeness
        template = self.get_default_template(ticker)
        merged_data = {**template, **card_data, "ticker": ticker, "updated_at": datetime.now(UTC).isoformat()}
        
        with open(card_file, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, indent=2, ensure_ascii=False)
            
        return merged_data

    def get_card(self, ticker: str) -> dict[str, Any]:
        """Retrieves a stock knowledge card. Returns a default template if not found."""
        ticker = ticker.upper()
        card_file = self.cards_dir / f"{ticker}.json"
        
        if not card_file.exists():
            return self.get_default_template(ticker)
            
        try:
            with open(card_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure structure is complete
                template = self.get_default_template(ticker)
                return {**template, **data, "ticker": ticker}
        except Exception:
            return self.get_default_template(ticker)

    def delete_card(self, ticker: str) -> bool:
        """Deletes a stock knowledge card file. Returns True if deleted, False otherwise."""
        ticker = ticker.upper()
        card_file = self.cards_dir / f"{ticker}.json"
        if card_file.exists():
            card_file.unlink()
            return True
        return False

    def list_cards(self) -> list[dict[str, Any]]:
        """Lists all saved stock knowledge cards."""
        cards = []
        for file_path in self.cards_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cards.append(data)
            except Exception:
                continue
        return sorted(cards, key=lambda c: c.get("ticker", ""))
