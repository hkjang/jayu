from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .failure_codes import FailureCode
from .portfolio import PortfolioMapping, load_portfolio_mapping
from .settings import RiskSettings
from .signals import SignalAction, normalize_today_signal


@dataclass(frozen=True)
class RiskDecision:
    eligible: bool
    requested_position_pct: float
    approved_position_pct: float
    violations: list[str]
    projected: dict[str, float]
    # Structured, machine-readable view of the same violations (criterion #12).
    violation_details: list[dict[str, Any]] = field(default_factory=list)
    pass_details: list[dict[str, Any]] = field(default_factory=list)
    # Non-blocking notes (e.g. an unmapped ticker that fell back to defaults).
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # Whether the approved size was cut below the request by resize enforcement.
    resized: bool = False
    # Whether the ticker was found in the portfolio mapping.
    mapped: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_signal_risk(
    ticker: str,
    requested_position_pct: float,
    portfolio: dict[str, Any],
    settings: RiskSettings,
    *,
    mapping: PortfolioMapping | None = None,
    dollar_volume: float | None = None,
    minimum_dollar_volume: float | None = None,
) -> RiskDecision:
    ticker = ticker.upper()
    portfolio_mapping = mapping or load_portfolio_mapping()
    lookup = portfolio_mapping.lookup(ticker)
    ticker_mapping = lookup.mapping
    mapped = bool(lookup.mapped)
    leverage = ticker_mapping.leverage_factor
    underlying = ticker_mapping.underlying_group or ticker
    sector = ticker_mapping.sector

    current_underlying = portfolio.get("underlying_exposure_pct", {}).get(underlying, 0.0)
    current_sector = portfolio.get("sector_exposure_pct", {}).get(sector, 0.0)
    current_leveraged = float(portfolio.get("leveraged_etf_value_pct", 0.0))
    current_gross = float(portfolio.get("adjusted_gross_exposure", 0.0))
    current_invested = float(portfolio.get("invested_pct", 0.0))
    current_cash = float(portfolio.get("cash_pct", 0.0))
    cash_known = bool(portfolio.get("cash_known", False))
    factor_exposure = portfolio.get("factor_exposure_pct", {})
    factors = ticker_mapping.factors
    positions = [item for item in portfolio.get("positions", []) if isinstance(item, dict)]
    existing_tickers = {str(item.get("ticker", "")).upper() for item in positions}
    account_value = float(portfolio.get("account_value_krw", 0.0) or 0.0)
    current_ticker_value = sum(
        float(item.get("market_value_krw", 0.0) or 0.0)
        for item in positions
        if str(item.get("ticker", "")).upper() == ticker
    )
    current_ticker_pct = current_ticker_value / account_value if account_value > 0 else 0.0
    projected_position_count = len(existing_tickers) + int(ticker not in existing_tickers)

    projected = {
        "position_count": float(projected_position_count),
        "single_position_pct": current_ticker_pct + requested_position_pct,
        "underlying_exposure": current_underlying + requested_position_pct * leverage,
        "sector_exposure": current_sector + requested_position_pct * leverage,
        "leveraged_etf_value": current_leveraged
        + (requested_position_pct if leverage > 1 else 0.0),
        "adjusted_gross_exposure": current_gross + requested_position_pct * leverage,
        "invested_pct": current_invested + requested_position_pct,
        "cash_pct": max(0.0, current_cash - requested_position_pct),
    }
    for factor in factors:
        projected[f"factor:{factor}"] = float(factor_exposure.get(factor, 0.0)) + (
            requested_position_pct * leverage
        )
    limits = {
        "underlying_exposure": settings.max_underlying_exposure,
        "sector_exposure": settings.max_sector_exposure,
        "leveraged_etf_value": settings.max_leveraged_etf_value,
        "adjusted_gross_exposure": settings.max_adjusted_gross_exposure,
    }
    violations: list[str] = []
    violation_details: list[dict[str, Any]] = []
    pass_details: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def add_violation(
        code: str, message: str, *, observed: float, limit: float, metric: str
    ) -> None:
        violations.append(message)
        violation_details.append(
            {
                "code": code,
                "message": message,
                "metric": metric,
                "observed": round(observed, 6),
                "limit": round(limit, 6),
            }
        )

    def add_pass(*, metric: str, observed: float, limit: float, direction: str = "<=") -> None:
        pass_details.append(
            {
                "metric": metric,
                "observed": round(observed, 6),
                "limit": round(limit, 6),
                "direction": direction,
            }
        )

    if not mapped:
        message = (
            f"{ticker} not found in portfolio mapping; using default "
            f"leverage {leverage:g} and 'unmapped' factor"
        )
        warnings.append({"code": FailureCode.UNMAPPED_TICKER.value, "message": message})
        if settings.block_unmapped_tickers:
            add_violation(
                FailureCode.UNMAPPED_TICKER.value,
                message,
                observed=1,
                limit=0,
                metric="unmapped_ticker",
            )

    if projected_position_count > settings.max_positions:
        add_violation(
            FailureCode.MAX_POSITION_COUNT_EXCEEDED.value,
            f"position_count {projected_position_count} > {settings.max_positions}",
            observed=float(projected_position_count),
            limit=float(settings.max_positions),
            metric="position_count",
        )
    else:
        add_pass(
            metric="position_count",
            observed=float(projected_position_count),
            limit=float(settings.max_positions),
        )
    if projected["single_position_pct"] > settings.max_single_position_pct:
        add_violation(
            FailureCode.SINGLE_POSITION_EXCEEDED.value,
            "single_position_pct "
            f"{projected['single_position_pct']:.1%} > {settings.max_single_position_pct:.1%}",
            observed=projected["single_position_pct"],
            limit=settings.max_single_position_pct,
            metric="single_position_pct",
        )
    else:
        add_pass(
            metric="single_position_pct",
            observed=projected["single_position_pct"],
            limit=settings.max_single_position_pct,
        )
    liquidity_limit = max(
        settings.min_dollar_volume,
        float(minimum_dollar_volume or 0.0),
    )
    if dollar_volume is not None and dollar_volume < liquidity_limit:
        add_violation(
            FailureCode.LIQUIDITY_INSUFFICIENT.value,
            f"dollar_volume {dollar_volume:.0f} < {liquidity_limit:.0f}",
            observed=dollar_volume,
            limit=liquidity_limit,
            metric="dollar_volume_ma20",
        )
    elif dollar_volume is not None:
        add_pass(
            metric="dollar_volume_ma20",
            observed=dollar_volume,
            limit=liquidity_limit,
            direction=">=",
        )

    exposure_codes = {
        "underlying_exposure": FailureCode.UNDERLYING_EXPOSURE_EXCEEDED.value,
        "sector_exposure": FailureCode.SECTOR_EXPOSURE_EXCEEDED.value,
        "leveraged_etf_value": FailureCode.LEVERAGED_ETF_VALUE_EXCEEDED.value,
        "adjusted_gross_exposure": FailureCode.ADJUSTED_GROSS_EXPOSURE_EXCEEDED.value,
    }
    for name, limit in limits.items():
        if projected[name] > limit:
            add_violation(
                exposure_codes[name],
                f"{name} {projected[name]:.1%} > {limit:.1%}",
                observed=projected[name],
                limit=limit,
                metric=name,
            )
        else:
            add_pass(metric=name, observed=projected[name], limit=limit)
    for factor in factors:
        key = f"factor:{factor}"
        if projected[key] > settings.max_factor_exposure:
            add_violation(
                FailureCode.FACTOR_EXPOSURE_EXCEEDED.value,
                f"{key} {projected[key]:.1%} > {settings.max_factor_exposure:.1%}",
                observed=projected[key],
                limit=settings.max_factor_exposure,
                metric=key,
            )
        else:
            add_pass(
                metric=key,
                observed=projected[key],
                limit=settings.max_factor_exposure,
            )
    if cash_known and projected["cash_pct"] < settings.min_cash_pct:
        add_violation(
            FailureCode.MIN_CASH_BREACHED.value,
            f"cash_pct {projected['cash_pct']:.1%} < {settings.min_cash_pct:.1%}",
            observed=projected["cash_pct"],
            limit=settings.min_cash_pct,
            metric="cash_pct",
        )
    elif cash_known:
        add_pass(
            metric="cash_pct",
            observed=projected["cash_pct"],
            limit=settings.min_cash_pct,
            direction=">=",
        )
    if cash_known and projected["invested_pct"] > settings.max_invested_pct:
        add_violation(
            FailureCode.MAX_INVESTED_EXCEEDED.value,
            f"invested_pct {projected['invested_pct']:.1%} > {settings.max_invested_pct:.1%}",
            observed=projected["invested_pct"],
            limit=settings.max_invested_pct,
            metric="invested_pct",
        )
    elif cash_known:
        add_pass(
            metric="invested_pct",
            observed=projected["invested_pct"],
            limit=settings.max_invested_pct,
        )
    risk_status = portfolio.get("risk_status", {})
    loss_checks = (
        ("daily_return", settings.daily_loss_limit, FailureCode.DAILY_LOSS_LIMIT_BREACHED.value),
        ("weekly_return", settings.weekly_loss_limit, FailureCode.WEEKLY_LOSS_LIMIT_BREACHED.value),
    )
    for key, limit, code in loss_checks:
        value = float(risk_status.get(key, 0.0))
        if value <= -limit:
            add_violation(
                code,
                f"{key} {value:.1%} breached -{limit:.1%}",
                observed=value,
                limit=-limit,
                metric=key,
            )
        else:
            add_pass(metric=key, observed=value, limit=-limit, direction=">")
    monthly_drawdown = float(risk_status.get("monthly_drawdown", 0.0))
    if monthly_drawdown >= settings.monthly_mdd_limit:
        add_violation(
            FailureCode.MONTHLY_DRAWDOWN_BREACHED.value,
            f"monthly_drawdown {monthly_drawdown:.1%} >= {settings.monthly_mdd_limit:.1%}",
            observed=monthly_drawdown,
            limit=settings.monthly_mdd_limit,
            metric="monthly_drawdown",
        )
    else:
        add_pass(
            metric="monthly_drawdown",
            observed=monthly_drawdown,
            limit=settings.monthly_mdd_limit,
            direction="<",
        )
    if not violations or settings.enforcement == "warn":
        approved = requested_position_pct
        eligible = True
    elif settings.enforcement == "resize":
        capacities = [
            max(0.0, settings.max_single_position_pct - current_ticker_pct),
            max(0.0, (limits["underlying_exposure"] - current_underlying) / leverage),
            max(0.0, (limits["sector_exposure"] - current_sector) / leverage),
            max(
                0.0,
                limits["leveraged_etf_value"] - current_leveraged,
            )
            if leverage > 1
            else requested_position_pct,
            max(0.0, (limits["adjusted_gross_exposure"] - current_gross) / leverage),
        ]
        capacities.extend(
            max(
                0.0,
                (settings.max_factor_exposure - float(factor_exposure.get(factor, 0.0))) / leverage,
            )
            for factor in factors
        )
        if cash_known:
            capacities.extend(
                [
                    max(0.0, current_cash - settings.min_cash_pct),
                    max(0.0, settings.max_invested_pct - current_invested),
                ]
            )
        hard_block_codes = {
            FailureCode.MAX_POSITION_COUNT_EXCEEDED.value,
            FailureCode.UNMAPPED_TICKER.value,
            FailureCode.LIQUIDITY_INSUFFICIENT.value,
            FailureCode.DAILY_LOSS_LIMIT_BREACHED.value,
            FailureCode.WEEKLY_LOSS_LIMIT_BREACHED.value,
            FailureCode.MONTHLY_DRAWDOWN_BREACHED.value,
        }
        if any(item.get("code") in hard_block_codes for item in violation_details):
            capacities.append(0.0)
        approved = min(requested_position_pct, *capacities)
        eligible = approved >= 0.01
    else:
        approved = 0.0
        eligible = False
    resized = eligible and approved < requested_position_pct
    return RiskDecision(
        eligible=eligible,
        requested_position_pct=requested_position_pct,
        approved_position_pct=approved,
        violations=violations,
        projected=projected,
        violation_details=violation_details,
        pass_details=pass_details,
        warnings=warnings,
        resized=resized,
        mapped=mapped,
    )


def apply_portfolio_risk(
    signals: dict[str, dict[str, Any]],
    portfolio: dict[str, Any],
    settings: RiskSettings,
    *,
    mapping: PortfolioMapping | None = None,
) -> dict[str, dict[str, Any]]:
    evaluated: dict[str, dict[str, Any]] = {}
    portfolio_mapping = mapping or load_portfolio_mapping()
    for ticker, signal in signals.items():
        item = normalize_today_signal(dict(signal))
        is_buy = item.get("action") == SignalAction.BUY.value
        if not is_buy:
            item["eligible"] = False
            cost_survival = item.get("cost_survival")
            code = FailureCode.NOT_A_BUY_SIGNAL.value
            message = "signal action is not buy"
            if isinstance(cost_survival, dict) and cost_survival.get("survives") is False:
                if cost_survival.get("checked") is True:
                    code = FailureCode.COST_FRAGILE.value
                    message = "strategy does not survive configured trading costs"
                else:
                    code = FailureCode.COST_NOT_EVALUATED.value
                    message = "strategy trading-cost survival was not evaluated"
            item["risk"] = {
                "violations": [message],
                "violation_details": [
                    {
                        "code": code,
                        "message": message,
                        "metric": "action",
                        "observed": item.get("action"),
                        "limit": SignalAction.BUY.value,
                    }
                ],
            }
        else:
            requested = float(item.get("suggested_position_pct", 0.10))
            decision = evaluate_signal_risk(
                ticker,
                requested,
                portfolio,
                settings,
                mapping=portfolio_mapping,
                dollar_volume=_optional_float(item.get("dollar_volume_ma20")),
                minimum_dollar_volume=_optional_float(item.get("minimum_dollar_volume")),
            )
            item["eligible"] = decision.eligible
            item["approved_position_pct"] = decision.approved_position_pct
            item["risk"] = decision.to_dict()
        _set_signal_status(item)
        evaluated[ticker] = item
    return evaluated


def apply_data_trust(
    signals: dict[str, dict[str, Any]],
    *,
    price_trust: dict[str, dict[str, Any]],
    reference_audits: dict[str, dict[str, Any]],
    event_notes: dict[str, list[dict[str, Any]]],
    require_verified_price: bool,
    reference_conflict_policy: str,
) -> dict[str, dict[str, Any]]:
    for ticker, item in signals.items():
        ticker_key = ticker.upper()
        risk = item.setdefault("risk", {})
        if not isinstance(risk, dict):
            risk = {"portfolio_risk": risk}
            item["risk"] = risk
        violations = risk.setdefault("violations", [])
        details = risk.setdefault("violation_details", [])
        warnings = risk.setdefault("warnings", [])
        price = price_trust.get(ticker_key, {})
        if (
            item.get("action") == SignalAction.BUY.value
            and require_verified_price
            and price.get("verified") is not True
        ):
            message = "price data was not verified by the configured quality policy"
            violations.append(message)
            details.append(
                {
                    "code": FailureCode.UNVERIFIED_PRICE_DATA.value,
                    "message": message,
                    "metric": "price_verified",
                    "observed": False,
                    "limit": True,
                }
            )
            item["eligible"] = False
            item["approved_position_pct"] = 0.0
        disagreements = price.get("provider_disagreements")
        if item.get("action") == SignalAction.BUY.value and disagreements:
            message = "provider price disagreement exceeded configured tolerance"
            violations.append(message)
            details.append(
                {
                    "code": FailureCode.DATA_DISAGREEMENT.value,
                    "message": message,
                    "metric": "provider_disagreements",
                    "observed": len(disagreements) if isinstance(disagreements, list) else True,
                    "limit": 0,
                }
            )
            item["eligible"] = False
            item["approved_position_pct"] = 0.0
        reference = reference_audits.get(ticker_key, {})
        status = reference.get("status")
        if status == "conflict":
            message = "reference data conflict detected for ticker"
            if reference_conflict_policy == "block":
                violations.append(message)
                details.append(
                    {
                        "code": FailureCode.REFERENCE_DATA_CONFLICT.value,
                        "message": message,
                        "metric": "reference_status",
                        "observed": "conflict",
                        "limit": "verified_or_warning",
                    }
                )
                item["eligible"] = False
                item["approved_position_pct"] = 0.0
            else:
                warnings.append(
                    {"code": FailureCode.REFERENCE_DATA_CONFLICT.value, "message": message}
                )
        elif status == "unmapped":
            warnings.append(
                {
                    "code": FailureCode.OPENFIGI_UNMAPPED.value,
                    "message": "OpenFIGI returned no mapping for ticker",
                }
            )
        notes = event_notes.get(ticker_key, [])
        if notes:
            item["risk_notes"] = notes
            warnings.append(
                {
                    "code": FailureCode.EVENT_DATA_NOTE.value,
                    "message": f"{len(notes)} recent event or news notes attached",
                }
            )
        risk["data_trust"] = {
            "price": price,
            "reference": reference,
            "event_note_count": len(notes),
        }
        _set_signal_status(item)
    return signals


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _set_signal_status(item: dict[str, Any]) -> None:
    risk = item.get("risk")
    details = risk.get("violation_details", []) if isinstance(risk, dict) else []
    reason_codes = sorted(
        {
            str(detail.get("code"))
            for detail in details
            if isinstance(detail, dict) and detail.get("code")
        }
    )
    if isinstance(risk, dict):
        risk["reason_codes"] = reason_codes
    is_buy = item.get("action") == SignalAction.BUY.value
    blocked = bool(is_buy and not item.get("eligible"))
    item["blocked"] = blocked
    item["status"] = "blocked" if blocked else "eligible" if is_buy else "hold"
    item["reason_codes"] = reason_codes


def risk_explanation(signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for ticker, signal in signals.items():
        risk = signal.get("risk") if isinstance(signal, dict) else None
        risk = risk if isinstance(risk, dict) else {}
        failed = risk.get("violation_details")
        passed = risk.get("pass_details")
        failed_items = (
            [dict(item) for item in failed if isinstance(item, dict)]
            if isinstance(failed, list)
            else []
        )
        passed_items = (
            [dict(item) for item in passed if isinstance(item, dict)]
            if isinstance(passed, list)
            else []
        )
        failure_codes = {str(item.get("code")) for item in failed_items if item.get("code")}
        reviewed = (
            signal.get("action") == SignalAction.BUY.value
            or FailureCode.COST_FRAGILE.value in failure_codes
            or FailureCode.COST_NOT_EVALUATED.value in failure_codes
        )
        rows.append(
            {
                "ticker": ticker,
                "action": signal.get("action") if isinstance(signal, dict) else None,
                "reviewed": reviewed,
                "eligible": bool(signal.get("eligible")) if isinstance(signal, dict) else False,
                "approved_position_pct": signal.get("approved_position_pct")
                if isinstance(signal, dict)
                else None,
                "passed": passed_items,
                "failed": [
                    {
                        **item,
                        "excess": _excess(item),
                    }
                    for item in failed_items
                ],
                "warnings": risk.get("warnings", []),
            }
        )
    reviewed = [row for row in rows if row["reviewed"]]
    blocked = [row for row in reviewed if not row["eligible"]]
    return {
        "signals": rows,
        "approved_count": len(reviewed) - len(blocked),
        "blocked_count": len(blocked),
        "hold_count": len(rows) - len(reviewed),
        "top_block_reasons": _top_codes(rows),
    }


def _excess(item: dict[str, Any]) -> float | None:
    observed = item.get("observed")
    limit = item.get("limit")
    if isinstance(observed, (int, float)) and isinstance(limit, (int, float)):
        return round(float(observed) - float(limit), 6)
    return None


def _top_codes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        if not row.get("reviewed"):
            continue
        for item in row.get("failed", []):
            code = str(item.get("code") or "")
            if code:
                counts[code] = counts.get(code, 0) + 1
    return [
        {"code": code, "count": count}
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
