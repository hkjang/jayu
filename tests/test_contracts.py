import pandas as pd
import pytest

from jayu.contracts import (
    DataContractError,
    ensure_contract,
    validate_ohlcv_contract,
    validate_portfolio_snapshot_contract,
    validate_signal_contract,
    validate_trade_log_contract,
)


def test_ohlcv_contract_flags_invalid_rows():
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [99.0],
            "Low": [98.0],
            "Close": [101.0],
            "Volume": [1000.0],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )

    violations = validate_ohlcv_contract(frame)

    assert violations
    assert {item["code"] for item in violations} == {"DATA_CONTRACT_FAILED"}


def test_contract_failure_raises_standard_code():
    violations = validate_signal_contract({"SOXL": {"signal": "", "action": "maybe"}})

    with pytest.raises(DataContractError, match="DATA_CONTRACT_FAILED"):
        ensure_contract("signal_dataframe", violations)


def test_trade_and_portfolio_contracts_accept_minimal_valid_payloads():
    assert validate_trade_log_contract([{"ret": 0.01}]) == []
    assert (
        validate_portfolio_snapshot_contract(
            {"account_value_krw": 1_000_000.0, "cash_balance_krw": 100_000.0}
        )
        == []
    )
