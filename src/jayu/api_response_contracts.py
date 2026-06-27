from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .failure_codes import FailureCode
from .order_history_utils import order_rows


VALID_ORDER_STATUS = {
    "OPEN",
    "FILLED",
    "PARTIAL_FILLED",
    "CANCELED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "CLOSED",
}


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TossExecutionContract(_ContractModel):
    filledQuantity: Decimal | None = None
    averageFilledPrice: Decimal | None = None
    filledAmount: Decimal | None = None
    commission: Decimal | None = Decimal("0")
    tax: Decimal | None = Decimal("0")
    filledAt: datetime | None = None
    settlementDate: str | None = None

    @field_validator("filledQuantity", "averageFilledPrice", "filledAmount", "commission", "tax")
    @classmethod
    def non_negative_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("must be non-negative")
        return value


class TossOrderContract(_ContractModel):
    orderId: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    status: str = Field(min_length=1)
    currency: Literal["KRW", "USD"]
    orderedAt: datetime
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    orderAmount: Decimal | None = Field(default=None, ge=0)
    execution: TossExecutionContract | None = None

    @field_validator("status")
    @classmethod
    def known_status(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in VALID_ORDER_STATUS:
            raise ValueError(f"unknown order status: {value}")
        return normalized


class TossAccountContract(_ContractModel):
    account_seq: str = Field(min_length=1)


class TossHoldingContract(_ContractModel):
    symbol: str = Field(min_length=1)
    quantity: Decimal = Field(ge=0)
    currency: Literal["KRW", "USD"] = "KRW"
    market_value_krw: Decimal | None = Field(default=None, ge=0)
    average_price: Decimal | None = Field(default=None, ge=0)


class TossPriceContract(_ContractModel):
    symbol: str = Field(min_length=1)
    price: Decimal = Field(gt=0)
    currency: Literal["KRW", "USD"] = "KRW"


class TossExchangeRateContract(_ContractModel):
    base_currency: str = Field(min_length=3)
    quote_currency: str = Field(min_length=3)
    rate: Decimal = Field(gt=0)


class TossCommissionContract(_ContractModel):
    market: str | None = None
    currency: Literal["KRW", "USD"] | None = None
    commission_rate: Decimal | None = Field(default=None, ge=0)
    minimum_commission: Decimal | None = Field(default=None, ge=0)


def validate_api_response_contract(
    endpoint: str,
    payload: Any,
    *,
    provider: str = "toss",
    source: str | None = None,
) -> dict[str, Any]:
    normalized_endpoint = endpoint.lower().replace("-", "_")
    rows = _rows_for_endpoint(normalized_endpoint, payload)
    model = _model_for_endpoint(normalized_endpoint)
    violations: list[dict[str, Any]] = []

    if model is None:
        violations.append(_violation(normalized_endpoint, "endpoint", "unsupported endpoint contract"))
    elif not rows and normalized_endpoint in {"orders", "holdings", "commissions"}:
        pass
    elif not rows:
        violations.append(_violation(normalized_endpoint, "rows", "response contains no rows"))
    else:
        for index, row in enumerate(rows):
            normalized = _normalize_row(normalized_endpoint, row)
            try:
                model.model_validate(normalized)
            except ValidationError as exc:
                for error in exc.errors():
                    field = ".".join(str(part) for part in error.get("loc", ())) or "row"
                    violations.append(
                        _violation(
                            normalized_endpoint,
                            field,
                            str(error.get("msg") or "validation failed"),
                            index=index,
                            ref=_row_ref(row),
                        )
                    )

    failed_count = len(violations)
    status = "not_evaluated" if not rows and not violations else "success" if failed_count == 0 else "failed"
    return {
        "status": status,
        "provider": provider,
        "endpoint": normalized_endpoint,
        "contract": f"{provider}.{normalized_endpoint}",
        "summary": {
            "row_count": len(rows),
            "violation_count": failed_count,
            "validated": failed_count == 0,
        },
        "violations": violations[:100],
        "failure_code": FailureCode.DATA_CONTRACT_FAILED.value if violations else None,
        "source": source or f"{provider} {normalized_endpoint} response",
    }


def validate_many_api_contracts(
    payloads: Mapping[str, Any],
    *,
    provider: str = "toss",
) -> dict[str, Any]:
    reports = [
        validate_api_response_contract(endpoint, payload, provider=provider)
        for endpoint, payload in payloads.items()
    ]
    failed = [report for report in reports if report["status"] != "success"]
    return {
        "status": "failed" if failed else "success",
        "summary": {
            "contract_count": len(reports),
            "failed_contract_count": len(failed),
            "violation_count": sum(report["summary"]["violation_count"] for report in reports),
        },
        "reports": reports,
        "source": "api_response_contracts.py",
    }


def _model_for_endpoint(endpoint: str) -> type[BaseModel] | None:
    return {
        "orders": TossOrderContract,
        "order": TossOrderContract,
        "accounts": TossAccountContract,
        "holdings": TossHoldingContract,
        "prices": TossPriceContract,
        "price": TossPriceContract,
        "exchange_rate": TossExchangeRateContract,
        "exchange-rate": TossExchangeRateContract,
        "commissions": TossCommissionContract,
    }.get(endpoint)


def _rows_for_endpoint(endpoint: str, payload: Any) -> list[dict[str, Any]]:
    if endpoint in {"orders", "order"}:
        return order_rows(payload)
    return _generic_rows(payload)


def _generic_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("items", "data", "result", "accounts", "holdings", "prices", "commissions"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return [dict(item) for item in value if isinstance(item, Mapping)]
            if isinstance(value, Mapping):
                nested = _generic_rows(value)
                if nested:
                    return nested
        return [dict(payload)]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _normalize_row(endpoint: str, row: Mapping[str, Any]) -> dict[str, Any]:
    if endpoint in {"accounts"}:
        return {"account_seq": _first(row, "account_seq", "accountSeq", "id"), **dict(row)}
    if endpoint in {"holdings"}:
        return {
            "symbol": _first(row, "symbol", "ticker", "stockCode", "stock_code"),
            "quantity": _first(row, "quantity", "qty", "holdingQuantity", "holding_quantity"),
            "currency": _first(row, "currency", default="KRW"),
            "market_value_krw": _first(row, "market_value_krw", "marketValueKrw", "marketValue"),
            "average_price": _first(row, "average_price", "averagePrice", "avg_price", "avg_cost"),
            **dict(row),
        }
    if endpoint in {"prices", "price"}:
        return {
            "symbol": _first(row, "symbol", "ticker", "stockCode", "stock_code"),
            "price": _first(row, "price", "close", "currentPrice", "lastPrice"),
            "currency": _first(row, "currency", default="KRW"),
            **dict(row),
        }
    if endpoint in {"exchange_rate", "exchange-rate"}:
        return {
            "base_currency": _first(row, "base_currency", "baseCurrency", default="USD"),
            "quote_currency": _first(row, "quote_currency", "quoteCurrency", default="KRW"),
            "rate": _first(row, "rate", "exchangeRate", "basePrice", "price"),
            **dict(row),
        }
    if endpoint == "commissions":
        return {
            "market": _first(row, "market", "exchange"),
            "currency": _first(row, "currency"),
            "commission_rate": _first(row, "commission_rate", "commissionRate", "rate"),
            "minimum_commission": _first(row, "minimum_commission", "minimumCommission", "minimum"),
            **dict(row),
        }
    return dict(row)


def _first(row: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return default


def _row_ref(row: Mapping[str, Any]) -> str:
    return str(_first(row, "orderId", "order_id", "symbol", "ticker", "stockCode", "account_seq", default="-"))


def _violation(
    contract: str,
    field: str,
    message: str,
    *,
    index: int | None = None,
    ref: str = "-",
) -> dict[str, Any]:
    return {
        "code": FailureCode.DATA_CONTRACT_FAILED.value,
        "contract": contract,
        "field": field,
        "message": message,
        "index": index,
        "ref": ref,
        "severity": "failed",
    }
