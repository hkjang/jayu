from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


class NotificationPolicyEngine:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.inbox_path = self.state_dir / "notifications_inbox.jsonl"

    def classify(self, event_type: str, severity: str) -> str:
        """Classifies notifications into categories: urgent, daily, weekly, or silent."""
        if severity == "critical" or event_type in {"risk_blocked", "user_approval_required"}:
            return "urgent"
        elif event_type in {"signal_created", "routine_completed", "recovery_action_needed"}:
            if severity == "warning":
                return "urgent"
            return "daily"
        elif event_type in {"weekly_rebalance", "sla_violation_summary", "performance_summary"}:
            return "weekly"
        else:
            return "silent"

    def add_to_inbox(
        self,
        *,
        event_type: str,
        message: str,
        ticker: Optional[str] = None,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Adds a new notification to the local JSONL inbox."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        category = self.classify(event_type, severity)
        now_str = datetime.now(UTC).isoformat()
        
        notification = {
            "id": f"notif_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{ticker or 'sys'}",
            "timestamp": now_str,
            "event_type": event_type,
            "ticker": ticker,
            "severity": severity,
            "category": category,
            "message": message,
            "payload": payload or {},
            "sent": False,
            "sent_at": None,
        }

        with open(self.inbox_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(notification, ensure_ascii=False) + "\n")
            
        return notification

    def get_inbox(self) -> list[dict[str, Any]]:
        """Retrieves all notifications from the inbox."""
        if not self.inbox_path.exists():
            return []
            
        notifications = []
        with open(self.inbox_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    notifications.append(json.loads(line))
                except Exception:
                    continue
        return sorted(notifications, key=lambda n: n["timestamp"], reverse=True)

    def mark_as_sent(self, notification_ids: list[str]) -> None:
        """Marks specific notifications as sent in the inbox."""
        if not self.inbox_path.exists():
            return
            
        notifications = self.get_inbox()
        # Reverse chronological is returned, reverse it back for update
        notifications.reverse()
        
        updated = False
        for n in notifications:
            if n["id"] in notification_ids and not n["sent"]:
                n["sent"] = True
                n["sent_at"] = datetime.now(UTC).isoformat()
                updated = True

        if updated:
            with open(self.inbox_path, "w", encoding="utf-8") as f:
                for n in notifications:
                    f.write(json.dumps(n, ensure_ascii=False) + "\n")

    def process_and_batch_unsent(self, window_hours: int = 1) -> list[dict[str, Any]]:
        """Batches unsent notifications for the same ticker within the window to prevent alert fatigue.
        Returns a list of batched notification payloads suitable for sending.
        """
        notifications = self.get_inbox()
        unsent = [n for n in notifications if not n["sent"]]
        if not unsent:
            return []

        # Group by ticker
        grouped_by_ticker: dict[str, list[dict[str, Any]]] = {}
        system_notifications = []

        for n in unsent:
            ticker = n.get("ticker")
            if ticker:
                grouped_by_ticker.setdefault(ticker, []).append(n)
            else:
                system_notifications.append(n)

        batched_results = []

        # Process ticker batches
        for ticker, items in grouped_by_ticker.items():
            # Sort by timestamp (oldest first)
            items.sort(key=lambda x: x["timestamp"])
            
            # If multiple notifications exist, batch them
            if len(items) > 1:
                messages = [f"[{datetime.fromisoformat(item['timestamp']).strftime('%H:%M')}] {item['message']}" for item in items]
                highest_severity = "info"
                for item in items:
                    if item["severity"] == "critical":
                        highest_severity = "critical"
                    elif item["severity"] == "warning" and highest_severity != "critical":
                        highest_severity = "warning"

                combined_message = f"종목 {ticker}에 대한 알림 {len(items)}건 묶음 발송:\n" + "\n".join(messages)
                
                batched_results.append({
                    "ids": [item["id"] for item in items],
                    "ticker": ticker,
                    "event_type": "batched_ticker_notification",
                    "severity": highest_severity,
                    "category": "urgent" if highest_severity in {"critical", "warning"} else "daily",
                    "message": combined_message,
                    "items_count": len(items),
                })
            else:
                # Single notification, no batching needed
                item = items[0]
                batched_results.append({
                    "ids": [item["id"]],
                    "ticker": ticker,
                    "event_type": item["event_type"],
                    "severity": item["severity"],
                    "category": item["category"],
                    "message": item["message"],
                    "items_count": 1,
                })

        # Process system notifications individually
        for n in system_notifications:
            batched_results.append({
                "ids": [n["id"]],
                "ticker": None,
                "event_type": n["event_type"],
                "severity": n["severity"],
                "category": n["category"],
                "message": n["message"],
                "items_count": 1,
            })

        return batched_results
