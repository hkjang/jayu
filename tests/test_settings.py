import json
from pathlib import Path

import pytest

from jayu.settings import ResearchSettings, load_settings


def test_environment_overrides_legacy_json(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"SIM_RUNS": 100, "TRANSACTION_FEE": 0.001}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JAYU_SIM_RUNS", "250")

    settings = load_settings(config)

    assert settings.sim_runs == 250
    assert settings.transaction_fee == 0.001


def test_provider_secret_loads_from_environment_and_is_masked(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("JAYU_TIINGO_API_" + "KEY", "placeholder")

    settings = load_settings(config)

    assert settings.tiingo_api_key is not None
    assert settings.tiingo_api_key.get_secret_value() == "placeholder"
    assert settings.public_dict()["tiingo_api_key"] == "<configured>"


def test_invalid_fee_is_rejected(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"transaction_fee": -0.1}), encoding="utf-8")

    with pytest.raises(ValueError, match="transaction_fee"):
        load_settings(config)


def test_sample_config_is_valid():
    settings = load_settings(Path("configs/config.sample.json"))

    assert settings.execution.path_mode == "worst_case"
    assert settings.portfolio_mapping_file == Path("configs/portfolio_mapping.json")
    assert settings.risk.enforcement == "block"
    assert settings.data.api_key_env_names["tiingo"] == "JAYU_TIINGO_API_KEY"


def test_inconsistent_cash_limits_are_rejected(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"risk": {"min_cash_pct": 0.2, "max_invested_pct": 0.9}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_invested_pct"):
        load_settings(config)


def test_psr_observation_requirement_must_fit_walk_forward_windows():
    with pytest.raises(ValueError, match="min_oos_psr_observations"):
        ResearchSettings(walk_forward_windows=2, min_oos_psr_observations=3)


def test_selection_pbo_blocks_must_be_even_and_fit_windows():
    with pytest.raises(ValueError, match="must be even"):
        ResearchSettings(walk_forward_windows=4, selection_pbo_blocks=3)
    with pytest.raises(ValueError, match="cannot exceed"):
        ResearchSettings(walk_forward_windows=3, selection_pbo_blocks=4)


def test_cross_validation_provider_requires_enough_available_sources(tmp_path):
    from jayu.provider_factory import (
        build_provider_registry,
        provider_configuration_audit,
    )
    from jayu.settings import Settings

    settings = Settings.model_validate(
        {
            "data": {
                "cross_validation_providers": ["tiingo"],
                "minimum_valid_price_sources": 2,
            }
        }
    )
    registry = build_provider_registry(settings, tmp_path)

    audit = provider_configuration_audit(settings, registry)

    assert audit["valid"] is False
    assert "tiingo" in audit["warnings"][0]
    assert "minimum_valid_price_sources" in audit["errors"][0]
