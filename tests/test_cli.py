from typer.testing import CliRunner

from jayu.cli import app


def test_validate_config_includes_strategy_space_audit():
    result = CliRunner().invoke(app, ["validate-config"])

    assert result.exit_code == 0, result.output
    assert '"strategy_space_audit"' in result.output
    assert '"valid": true' in result.output
    assert "configuration is valid" in result.output
