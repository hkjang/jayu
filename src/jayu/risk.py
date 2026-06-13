from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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

    projected = {
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

    if not mapped:
        warnings.append(
            {
                "code": "unmapped_ticker",
                "message": (
                    f"{ticker} not found in portfolio mapping; using default "
                    f"leverage {leverage:g} and 'unmapped' factor"
                ),
            }
        )

    exposure_codes = {
        "underlying_exposure": "underlying_exposure_exceeded",
        "sector_exposure": "sector_exposure_exceeded",
        "leveraged_etf_value": "leveraged_etf_value_exceeded",
        "adjusted_gross_exposure": "adjusted_gross_exposure_exceeded",
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
    for factor in factors:
        key = f"factor:{factor}"
        if projected[key] > settings.max_factor_exposure:
            add_violation(
                "factor_exposure_exceeded",
                f"{key} {projected[key]:.1%} > {settings.max_factor_exposure:.1%}",
                observed=projected[key],
                limit=settings.max_factor_exposure,
                metric=key,
            )
    if cash_known and projected["cash_pct"] < settings.min_cash_pct:
        add_violation(
            "min_cash_breached",
            f"cash_pct {projected['cash_pct']:.1%} < {settings.min_cash_pct:.1%}",
            observed=projected["cash_pct"],
            limit=settings.min_cash_pct,
            metric="cash_pct",
        )
    if cash_known and projected["invested_pct"] > settings.max_invested_pct:
        add_violation(
            "max_invested_exceeded",
            f"invested_pct {projected['invested_pct']:.1%} > {settings.max_invested_pct:.1%}",
            observed=projected["invested_pct"],
            limit=settings.max_invested_pct,
            metric="invested_pct",
        )
    risk_status = portfolio.get("risk_status", {})
    loss_checks = (
        ("daily_return", settings.daily_loss_limit, "daily_loss_limit_breached"),
        ("weekly_return", settings.weekly_loss_limit, "weekly_loss_limit_breached"),
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
    monthly_drawdown = float(risk_status.get("monthly_drawdown", 0.0))
    if monthly_drawdown >= settings.monthly_mdd_limit:
        add_violation(
            "monthly_drawdown_breached",
            f"monthly_drawdown {monthly_drawdown:.1%} >= {settings.monthly_mdd_limit:.1%}",
            observed=monthly_drawdown,
            limit=settings.monthly_mdd_limit,
            metric="monthly_drawdown",
        )
    if not violations or settings.enforcement == "warn":
        approved = requested_position_pct
        eligible = True
    elif settings.enforcement == "resize":
        capacities = [
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
        if any("breached" in item or "monthly_drawdown" in item for item in violations):
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
            item["risk"] = {"reason": "not_a_buy_signal"}
        else:
            requested = float(item.get("suggested_position_pct", 0.10))
            decision = evaluate_signal_risk(
                ticker,
                requested,
                portfolio,
                settings,
                mapping=portfolio_mapping,
            )
            item["eligible"] = decision.eligible
            item["approved_position_pct"] = decision.approved_position_pct
            item["risk"] = decision.to_dict()
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
                    "code": "unverified_price_data",
                    "message": message,
                    "metric": "price_verified",
                    "observed": False,
                    "limit": True,
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
                        "code": "reference_data_conflict",
                        "message": message,
                        "metric": "reference_status",
                        "observed": "conflict",
                        "limit": "verified_or_warning",
                    }
                )
                item["eligible"] = False
                item["approved_position_pct"] = 0.0
            else:
                warnings.append({"code": "reference_data_conflict", "message": message})
        elif status == "unmapped":
            warnings.append(
                {
                    "code": "openfigi_unmapped",
                    "message": "OpenFIGI returned no mapping for ticker",
                }
            )
        notes = event_notes.get(ticker_key, [])
        if notes:
            item["risk_notes"] = notes
            warnings.append(
                {
                    "code": "event_data_note",
                    "message": f"{len(notes)} recent event or news notes attached",
                }
            )
        risk["data_trust"] = {
            "price": price,
            "reference": reference,
            "event_note_count": len(notes),
        }
    return signals
