"""Stable failure taxonomy shared across signals, reports, health, and registry."""

from __future__ import annotations

from enum import StrEnum
from typing import TypeAlias


class FailureCode(StrEnum):
    CONFIG_FAILURE = "CONFIG_FAILURE"
    DATA_FAILURE = "DATA_FAILURE"
    DATA_CONTRACT_FAILED = "DATA_CONTRACT_FAILED"
    DATA_DISAGREEMENT = "DATA_DISAGREEMENT"
    BACKTEST_FAILURE = "BACKTEST_FAILURE"
    NOTIFICATION_FAILURE = "NOTIFICATION_FAILURE"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"
    COST_FRAGILE = "COST_FRAGILE"
    COST_NOT_EVALUATED = "COST_NOT_EVALUATED"

    NOT_A_BUY_SIGNAL = "NOT_A_BUY_SIGNAL"
    PORTFOLIO_FILE_UNAVAILABLE = "PORTFOLIO_FILE_UNAVAILABLE"
    UNVERIFIED_PRICE_DATA = "UNVERIFIED_PRICE_DATA"
    REFERENCE_DATA_CONFLICT = "REFERENCE_DATA_CONFLICT"
    OPENFIGI_UNMAPPED = "OPENFIGI_UNMAPPED"
    EVENT_DATA_NOTE = "EVENT_DATA_NOTE"
    UNMAPPED_TICKER = "UNMAPPED_TICKER"

    UNDERLYING_EXPOSURE_EXCEEDED = "UNDERLYING_EXPOSURE_EXCEEDED"
    SECTOR_EXPOSURE_EXCEEDED = "SECTOR_EXPOSURE_EXCEEDED"
    LEVERAGED_ETF_VALUE_EXCEEDED = "LEVERAGED_ETF_VALUE_EXCEEDED"
    ADJUSTED_GROSS_EXPOSURE_EXCEEDED = "ADJUSTED_GROSS_EXPOSURE_EXCEEDED"
    FACTOR_EXPOSURE_EXCEEDED = "FACTOR_EXPOSURE_EXCEEDED"
    MIN_CASH_BREACHED = "MIN_CASH_BREACHED"
    MAX_INVESTED_EXCEEDED = "MAX_INVESTED_EXCEEDED"
    DAILY_LOSS_LIMIT_BREACHED = "DAILY_LOSS_LIMIT_BREACHED"
    WEEKLY_LOSS_LIMIT_BREACHED = "WEEKLY_LOSS_LIMIT_BREACHED"
    MONTHLY_DRAWDOWN_BREACHED = "MONTHLY_DRAWDOWN_BREACHED"


FailureCodeValue: TypeAlias = str


def normalize_failure_code(
    value: object, default: FailureCode = FailureCode.INTERNAL_FAILURE
) -> str:
    """Return a canonical failure code value for persisted artifacts."""
    if isinstance(value, FailureCode):
        return value.value
    if isinstance(value, str):
        normalized = value.strip().upper()
        try:
            return FailureCode(normalized).value
        except ValueError:
            return default.value
    return default.value
