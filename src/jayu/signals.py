from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalAction(StrEnum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class TodaySignal(BaseModel):
    model_config = ConfigDict(extra="allow")

    signal: str
    action: SignalAction = SignalAction.HOLD
    eligible: bool = False
    conditions: dict[str, str] = Field(default_factory=dict)
    price: float | None = None
    regime: str | None = None
    suggested_position_pct: float | None = Field(default=None, ge=0, le=1)

    @field_validator("signal")
    @classmethod
    def validate_signal_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("signal text must not be empty")
        return text


def normalize_today_signal(payload: dict[str, Any]) -> dict[str, Any]:
    return TodaySignal.model_validate(payload).model_dump(mode="json")


def normalize_signal_map(signals: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {ticker: normalize_today_signal(signal) for ticker, signal in signals.items()}
