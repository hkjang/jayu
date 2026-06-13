from jayu.risk import apply_portfolio_risk, evaluate_signal_risk
from jayu.settings import RiskSettings


def test_balanced_profile_blocks_leveraged_signal_over_limit():
    portfolio = {
        "adjusted_gross_exposure": 1.50,
        "leveraged_etf_value_pct": 0.25,
        "underlying_exposure_pct": {"semiconductors": 0.20},
        "sector_exposure_pct": {"semiconductors": 0.35},
    }

    decision = evaluate_signal_risk(
        "SOXL",
        0.10,
        portfolio,
        RiskSettings(),
    )

    assert not decision.eligible
    assert decision.approved_position_pct == 0
    assert decision.violations


def test_non_buy_signal_is_never_marked_eligible():
    signals = {"SOXL": {"signal": "대기", "action": "hold"}}

    result = apply_portfolio_risk(
        signals,
        {
            "adjusted_gross_exposure": 0,
            "leveraged_etf_value_pct": 0,
            "underlying_exposure_pct": {},
            "sector_exposure_pct": {},
        },
        RiskSettings(),
    )

    assert result["SOXL"]["eligible"] is False


def test_account_loss_limit_blocks_new_buy():
    portfolio = {
        "adjusted_gross_exposure": 0.2,
        "leveraged_etf_value_pct": 0,
        "underlying_exposure_pct": {},
        "sector_exposure_pct": {},
        "factor_exposure_pct": {},
        "risk_status": {"daily_return": -0.04},
    }

    decision = evaluate_signal_risk("TSLA", 0.05, portfolio, RiskSettings())

    assert decision.eligible is False
    assert any("daily_return" in item for item in decision.violations)
