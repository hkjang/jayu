"""Single-flight lock for operational signal runs."""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .failure_codes import FailureCode
from .io import read_json


class OperationalRunConflict(RuntimeError):
    code = FailureCode.OPERATIONAL_RUN_ACTIVE

    def __init__(self, lock_details: dict[str, Any]):
        self.lock_details = lock_details
        owner = lock_details.get("owner_id", "unknown")
        acquired_at = lock_details.get("acquired_at", "unknown")
        super().__init__(
            f"operational run already active: owner={owner}, acquired_at={acquired_at}"
        )


@dataclass
class OperationalRunLock:
    path: Path
    command: str
    mode: str
    timeout_minutes: int
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    owner_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    acquired: bool = False

    def acquire(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            acquired_at = self.now()
            payload = {
                "owner_id": self.owner_id,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "command": self.command,
                "mode": self.mode,
                "acquired_at": acquired_at.isoformat(),
                "expires_at": (acquired_at + timedelta(minutes=self.timeout_minutes)).isoformat(),
            }
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                existing = self._existing_lock()
                if self._is_stale(existing):
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                raise OperationalRunConflict(existing) from None
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
            self.acquired = True
            return payload
        raise OperationalRunConflict(self._existing_lock())

    def release(self) -> None:
        if not self.acquired:
            return
        existing = self._existing_lock()
        if existing.get("owner_id") == self.owner_id:
            self.path.unlink(missing_ok=True)
        self.acquired = False

    def _existing_lock(self) -> dict[str, Any]:
        value = read_json(self.path, default={})
        return value if isinstance(value, dict) else {}

    def _is_stale(self, payload: dict[str, Any]) -> bool:
        acquired_at = _parse_timestamp(payload.get("acquired_at"))
        if acquired_at is not None:
            return self.now() - acquired_at > timedelta(minutes=self.timeout_minutes)
        try:
            modified_at = datetime.fromtimestamp(self.path.stat().st_mtime, tz=UTC)
        except FileNotFoundError:
            return True
        return self.now() - modified_at > timedelta(minutes=self.timeout_minutes)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
