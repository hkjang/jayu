from pathlib import Path

from scripts.generate_docs import generated_documents, settings_markdown
from typer.testing import CliRunner

from jayu.cli import app


def test_generated_docs_are_current():
    for path, expected in generated_documents().items():
        assert path.read_text(encoding="utf-8") == expected


def test_settings_reference_includes_nested_fields():
    content = settings_markdown()

    assert "`research.min_oos_psr`" in content
    assert "`risk.max_adjusted_gross_exposure`" in content


def test_sample_config_contains_every_non_secret_top_level_setting():
    import json

    from jayu.settings import Settings

    root = Path(__file__).resolve().parents[1]
    sample = json.loads((root / "configs" / "config.sample.json").read_text(encoding="utf-8"))
    allowed_omissions = {
        "config_file",
        "state_dir",
        "signals_dir",
        "runs_dir",
        "cache_dir",
        "portfolio_file",
        "massive_api_key",
        "kakao_access_token",
        "kakao_refresh_token",
        "kakao_rest_api_key",
        "kakao_client_secret",
    }
    assert set(Settings.model_fields) - allowed_omissions <= set(sample)


def test_documented_cli_commands_have_help():
    runner = CliRunner()
    for command in (
        ["simulate", "--help"],
        ["signal", "--help"],
        ["notify", "--help"],
        ["portfolio", "analyze", "--help"],
        ["validate-config", "--help"],
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output


def test_strategy_docs_match_strategy_space_choices():
    from jayu.strategy_space import load_strategy_spaces

    root = Path(__file__).resolve().parents[1]
    spaces = load_strategy_spaces()
    checks = {
        "STRATEGY_CONNORS_RSI2.md": (
            "connors_rsi2_limit",
            spaces["connors_rsi2"]["connors_rsi2_limit"],
        ),
        "STRATEGY_WILLIAMS_BREAKOUT.md": (
            "williams_k_multiplier",
            spaces["williams_breakout"]["williams_k_multiplier"],
        ),
        "STRATEGY_VOLUME_BREAKOUT.md": (
            "volume_spike_mult",
            spaces["volume_breakout"]["volume_spike_mult"],
        ),
    }
    for filename, (parameter, choices) in checks.items():
        content = (root / "docs" / filename).read_text(encoding="utf-8")
        expected = f"{parameter} ({', '.join(str(choice) for choice in choices)})"
        assert expected in content
