"""Small internal data contract validators.

The validators intentionally do not repair data. A failed contract should be
visible in artifacts and health instead of being quietly smoothed over.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .failure_codes import FailureCode


class DataContractError(ValueError):
    def __init__(self, contract: str, violations: Sequence[Mapping[str, Any]]):
        self.contract = contract
        self.violations = [dict(violation) for violation in violations]
        detail = "; ".join(str(violation.get("message", violation)) for violation in violations)
        super().__init__(f"{FailureCode.DATA_CONTRACT_FAILED.value}: {contract}: {detail}")


@dataclass(frozen=True)
class ContractViolation:
    contract: str
    field: str
    message: str
    code: str = FailureCode.DATA_CONTRACT_FAILED.value

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _violation(contract: str, field: str, message: str) -> ContractViolation:
    return ContractViolation(contract=contract, field=field, message=message)


def validate_ohlcv_contract(
    frame: pd.DataFrame, *, contract: str = "ohlcv"
) -> list[dict[str, str]]:
    required = ["Open", "High", "Low", "Close", "Volume"]
    violations: list[ContractViolation] = []
    missing = [column for column in required if column not in frame.columns]
    if missing:
        violations.append(_violation(contract, "columns", f"missing columns: {', '.join(missing)}"))
        return [item.to_dict() for item in violations]
    if frame.empty:
        violations.append(_violation(contract, "rows", "frame is empty"))
    if frame.index.has_duplicates:
        violations.append(_violation(contract, "index", "index contains duplicate timestamps"))
    if not frame.index.is_monotonic_increasing:
        violations.append(_violation(contract, "index", "index is not monotonic increasing"))
    if frame[required].isna().any().any():
        violations.append(_violation(contract, "values", "OHLCV contains null values"))
    prices = frame[["Open", "High", "Low", "Close"]]
    if not frame.empty and (prices <= 0).any().any():
        violations.append(_violation(contract, "price", "OHLC prices must be positive"))
    if not frame.empty and (frame["Volume"] < 0).any():
        violations.append(_violation(contract, "volume", "volume must be non-negative"))
    if not frame.empty:
        high_ok = frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1)
        low_ok = frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1)
        if not bool((high_ok & low_ok).all()):
            violations.append(_violation(contract, "ohlc", "high/low bounds are inconsistent"))
    return [item.to_dict() for item in violations]


def validate_trade_log_contract(
    trades: Sequence[Mapping[str, Any]],
    *,
    contract: str = "trade_log",
) -> list[dict[str, str]]:
    violations: list[ContractViolation] = []
    if not isinstance(trades, Sequence):
        return [_violation(contract, "rows", "trade log must be a sequence").to_dict()]
    required_any = ("ret", "net_return_pct", "gross_return_pct")
    for index, trade in enumerate(trades):
        if not isinstance(trade, Mapping):
            violations.append(_violation(contract, f"trade[{index}]", "trade must be an object"))
            continue
        if not any(isinstance(trade.get(key), (int, float)) for key in required_any):
            violations.append(
                _violation(
                    contract,
                    f"trade[{index}]",
                    "trade must contain ret, net_return_pct, or gross_return_pct",
                )
            )
    return [item.to_dict() for item in violations]


def validate_signal_contract(
    signals: Mapping[str, Mapping[str, Any]],
    *,
    contract: str = "signal_dataframe",
) -> list[dict[str, str]]:
    violations: list[ContractViolation] = []
    if not isinstance(signals, Mapping):
        return [_violation(contract, "signals", "signals must be an object").to_dict()]
    for ticker, signal in signals.items():
        if not isinstance(signal, Mapping):
            violations.append(_violation(contract, str(ticker), "signal must be an object"))
            continue
        if not str(ticker).strip():
            violations.append(_violation(contract, "ticker", "ticker must not be empty"))
        if not isinstance(signal.get("signal"), str) or not signal.get("signal"):
            violations.append(_violation(contract, str(ticker), "signal text must be present"))
        if signal.get("action") not in {"buy", "hold", "sell"}:
            violations.append(
                _violation(contract, str(ticker), "action must be buy, hold, or sell")
            )
        if not isinstance(signal.get("eligible", False), bool):
            violations.append(_violation(contract, str(ticker), "eligible must be boolean"))
    return [item.to_dict() for item in violations]


def validate_portfolio_snapshot_contract(
    snapshot: Mapping[str, Any],
    *,
    contract: str = "portfolio_snapshot",
) -> list[dict[str, str]]:
    violations: list[ContractViolation] = []
    for field in ("account_value_krw", "cash_balance_krw"):
        value = snapshot.get(field)
        if not isinstance(value, (int, float)) or value < 0:
            violations.append(_violation(contract, field, f"{field} must be a non-negative number"))
    return [item.to_dict() for item in violations]


def ensure_contract(contract: str, violations: Sequence[Mapping[str, Any]]) -> None:
    if violations:
        raise DataContractError(contract, violations)
