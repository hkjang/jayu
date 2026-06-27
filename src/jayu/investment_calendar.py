from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


class InvestmentCalendar:
    """Consolidates key investment dates, salary/savings schedules, and economic milestones."""

    def __init__(self) -> None:
        # Standard default calendar events for reference
        self.preset_events = [
            {"date": "2026-06-15", "category": "macro", "title": "CPI 소비자물가지수 발표", "description": "인플레이션 추이 확인"},
            {"date": "2026-06-18", "category": "macro", "title": "FOMC 기준금리 결정", "description": "연준 금리 로드맵 시그널"},
            {"date": "2026-06-25", "category": "personal", "title": "월 정기 급여일 & 자금 유입", "description": "월급 추가 투자금 가용 예산 편성일"},
            {"date": "2026-06-26", "category": "rebalance", "title": "분기 포트폴리오 정기 리밸런싱", "description": "전략 비중에 맞춘 포지션 재조정"},
            {"date": "2026-06-30", "category": "dividend", "title": "SCHD 배당락일 (Ex-Dividend Date)", "description": "분기 배당 권리 획득 마감일"},
        ]

    def get_events(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        """Returns consolidated events sorted chronologically."""
        events = list(self.preset_events)
        
        # Format filters if dates are provided
        if start_date:
            events = [e for e in events if e["date"] >= start_date]
        if end_date:
            events = [e for e in events if e["date"] <= end_date]

        return sorted(events, key=lambda x: x["date"])

    def add_custom_event(self, event_date: str, category: str, title: str, description: str = "") -> None:
        """Dynamically appends custom milestones (e.g., specific earnings calls or deposits)."""
        self.preset_events.append({
            "date": event_date,
            "category": category,
            "title": title,
            "description": description
        })
