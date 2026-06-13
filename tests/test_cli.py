from typer.testing import CliRunner

from jayu.artifacts import RunContext
from jayu.cli import _failed_market_tickers, app
from jayu.settings import Settings


def test_validate_config_includes_strategy_space_audit():
    result = CliRunner().invoke(app, ["validate-config"])

    assert result.exit_code == 0, result.output
    assert '"strategy_space_audit"' in result.output
    assert '"valid": true' in result.output
    assert "configuration is valid" in result.output


def test_missing_verified_price_is_reported_as_market_data_failure():
    context = object.__new__(RunContext)
    context.data_reports = {
        "SOXL": {
            "ticker": "SOXL",
            "valid": True,
            "price_verified": True,
            "price_usable": True,
        },
        "TQQQ": {
            "ticker": "TQQQ",
            "valid": True,
            "price_verified": False,
            "price_usable": False,
        },
    }

    failed = _failed_market_tickers(Settings(tickers=["SOXL", "TQQQ"]), context)

    assert failed == ["TQQQ"]
