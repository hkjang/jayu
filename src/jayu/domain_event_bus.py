from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    event_type: str
    ticker: Optional[str] = None
    severity: str = "info"  # "info", "warning", "critical"
    source_module: str
    payload_hash: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    payload: dict[str, Any] = Field(default_factory=dict)


class DomainEventBus:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.events_dir = self.state_dir / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        *,
        run_id: str,
        event_type: str,
        source_module: str,
        ticker: Optional[str] = None,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> DomainEvent:
        payload_data = payload or {}
        
        # Calculate payload hash
        payload_str = json.dumps(payload_data, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        event = DomainEvent(
            run_id=run_id,
            event_type=event_type,
            ticker=ticker,
            severity=severity,
            source_module=source_module,
            payload_hash=payload_hash,
            payload=payload_data,
        )

        self._write_event(event)
        return event

    def _write_event(self, event: DomainEvent) -> None:
        today_str = datetime.now(UTC).strftime("%Y%m%d")
        event_file = self.events_dir / f"{today_str}.jsonl"
        
        # Append to JSONL file
        with open(event_file, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def get_events(self, date_str: str | None = None) -> list[DomainEvent]:
        """Retrieve events for a specific date (format: YYYYMMDD).
        If date_str is None, retrieves today's events.
        """
        if not date_str:
            date_str = datetime.now(UTC).strftime("%Y%m%d")
            
        event_file = self.events_dir / f"{date_str}.jsonl"
        if not event_file.exists():
            return []

        events = []
        with open(event_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(DomainEvent.model_validate_json(line))
                except Exception:
                    # Skip malformed lines
                    continue
        return events
