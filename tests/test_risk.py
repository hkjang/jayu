from jayu.risk import (
    apply_data_trust,
    apply_portfolio_risk,
    evaluate_signal_risk,
    risk_explanation,
)
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
    assert "SECTOR_EXPOSURE_EXCEEDED" in codes
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
    assert "DAILY_LOSS_LIMIT_BREACHED" in codes


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
    assert any(warning["code"] == "UNMAPPED_TICKER" for warning in decision.warnings)


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
    assert {"UNVERIFIED_PRICE_DATA", "REFERENCE_DATA_CONFLICT"} <= codes
    assert result["TEST"]["risk_notes"] == [{"code": "recent_news"}]


def test_provider_disagreement_blocks_even_when_verified_price_not_required():
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
        price_trust={"TEST": {"verified": True, "provider_disagreements": [{"x": 1}]}},
        reference_audits={},
        event_notes={},
        require_verified_price=False,
        reference_conflict_policy="warn",
    )

    assert result["TEST"]["eligible"] is False
    codes = {item["code"] for item in result["TEST"]["risk"]["violation_details"]}
    assert "DATA_DISAGREEMENT" in codes


def test_risk_explanation_does_not_count_hold_as_failed_review():
    report = risk_explanation(
        {
            "HOLD": {
                "signal": "wait",
                "action": "hold",
                "eligible": False,
                "risk": {"violation_details": [{"code": "NOT_A_BUY_SIGNAL", "message": "not buy"}]},
            },
            "BUY": {
                "signal": "entry",
                "action": "buy",
                "eligible": True,
                "risk": {"pass_details": [{"metric": "cash_pct"}]},
            },
        }
    )

    assert report["approved_count"] == 1
    assert report["blocked_count"] == 0
    assert report["hold_count"] == 1
