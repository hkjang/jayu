from __future__ import annotations

from dataclasses import asdict, dataclass
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
    ticker_mapping = portfolio_mapping.lookup(ticker).mapping
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
    violations = [
        f"{name} {projected[name]:.1%} > {limit:.1%}"
        for name, limit in limits.items()
        if projected[name] > limit
    ]
    for factor in factors:
        key = f"factor:{factor}"
        if projected[key] > settings.max_factor_exposure:
            violations.append(f"{key} {projected[key]:.1%} > {settings.max_factor_exposure:.1%}")
    if cash_known and projected["cash_pct"] < settings.min_cash_pct:
        violations.append(f"cash_pct {projected['cash_pct']:.1%} < {settings.min_cash_pct:.1%}")
    if cash_known and projected["invested_pct"] > settings.max_invested_pct:
        violations.append(
            f"invested_pct {projected['invested_pct']:.1%} > {settings.max_invested_pct:.1%}"
        )
    risk_status = portfolio.get("risk_status", {})
    loss_checks = (
        ("daily_return", settings.daily_loss_limit),
        ("weekly_return", settings.weekly_loss_limit),
    )
    for key, limit in loss_checks:
        value = float(risk_status.get(key, 0.0))
        if value <= -limit:
            violations.append(f"{key} {value:.1%} breached -{limit:.1%}")
    monthly_drawdown = float(risk_status.get("monthly_drawdown", 0.0))
    if monthly_drawdown >= settings.monthly_mdd_limit:
        violations.append(
            f"monthly_drawdown {monthly_drawdown:.1%} >= {settings.monthly_mdd_limit:.1%}"
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
    return RiskDecision(
        eligible=eligible,
        requested_position_pct=requested_position_pct,
        approved_position_pct=approved,
        violations=violations,
        projected=projected,
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
