from jayu.risk import apply_data_trust, apply_portfolio_risk, evaluate_signal_risk
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


def test_violation_details_carry_codes_and_numbers():
    portfolio = {
        "adjusted_gross_exposure": 1.50,
        "leveraged_etf_value_pct": 0.25,
        "underlying_exposure_pct": {"semiconductors": 0.20},
        "sector_exposure_pct": {"semiconductors": 0.35},
    }

    decision = evaluate_signal_risk("SOXL", 0.10, portfolio, RiskSettings())

    # Same number of structured details as legacy strings, with stable codes.
    assert len(decision.violation_details) == len(decision.violations)
    codes = {detail["code"] for detail in decision.violation_details}
    assert "sector_exposure_exceeded" in codes
    for detail in decision.violation_details:
        assert {"code", "message", "metric", "observed", "limit"} <= detail.keys()


def test_daily_loss_emits_structured_code():
    portfolio = {
        "adjusted_gross_exposure": 0.2,
        "leveraged_etf_value_pct": 0,
        "underlying_exposure_pct": {},
        "sector_exposure_pct": {},
        "factor_exposure_pct": {},
        "risk_status": {"daily_return": -0.04},
    }

    decision = evaluate_signal_risk("TSLA", 0.05, portfolio, RiskSettings())

    codes = {detail["code"] for detail in decision.violation_details}
    assert "daily_loss_limit_breached" in codes


def test_resize_enforcement_sets_resized_flag():
    portfolio = {
        "adjusted_gross_exposure": 0.0,
        "leveraged_etf_value_pct": 0.0,
        "underlying_exposure_pct": {"semiconductors": 0.26},
        "sector_exposure_pct": {},
        "factor_exposure_pct": {},
    }

    decision = evaluate_signal_risk("SOXL", 0.10, portfolio, RiskSettings(enforcement="resize"))

    assert decision.eligible is True
    assert decision.resized is True
    assert 0.0 < decision.approved_position_pct < 0.10


def test_unmapped_ticker_is_flagged_as_warning():
    portfolio = {
        "adjusted_gross_exposure": 0.0,
        "leveraged_etf_value_pct": 0.0,
        "underlying_exposure_pct": {},
        "sector_exposure_pct": {},
        "factor_exposure_pct": {},
    }

    decision = evaluate_signal_risk("ZZZZ", 0.05, portfolio, RiskSettings())

    assert decision.mapped is False
    assert any(warning["code"] == "unmapped_ticker" for warning in decision.warnings)


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


def test_unverified_price_and_reference_conflict_block_eligible_signal():
    signals = {
        "TEST": {
            "signal": "entry",
            "action": "buy",
            "eligible": True,
            "approved_position_pct": 0.1,
            "risk": {},
        }
    }

    result = apply_data_trust(
        signals,
        price_trust={"TEST": {"verified": False}},
        reference_audits={"TEST": {"status": "conflict"}},
        event_notes={"TEST": [{"code": "recent_news"}]},
        require_verified_price=True,
        reference_conflict_policy="block",
    )

    assert result["TEST"]["eligible"] is False
    assert result["TEST"]["approved_position_pct"] == 0
    codes = {item["code"] for item in result["TEST"]["risk"]["violation_details"]}
    assert {"unverified_price_data", "reference_data_conflict"} <= codes
    assert result["TEST"]["risk_notes"] == [{"code": "recent_news"}]
