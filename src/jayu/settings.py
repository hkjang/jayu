from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .paths import RuntimePaths


class RiskSettings(BaseModel):
    profile: Literal["balanced", "conservative", "warning"] = "balanced"
    max_underlying_exposure: float = Field(default=0.30, ge=0, le=1)
    max_sector_exposure: float = Field(default=0.50, ge=0, le=1)
    max_leveraged_etf_value: float = Field(default=0.30, ge=0, le=1)
    max_adjusted_gross_exposure: float = Field(default=1.75, ge=0, le=5)
    max_factor_exposure: float = Field(default=0.60, ge=0, le=3)
    min_cash_pct: float = Field(default=0.15, ge=0, le=1)
    max_invested_pct: float = Field(default=0.85, ge=0, le=1)
    daily_loss_limit: float = Field(default=0.03, ge=0, le=1)
    weekly_loss_limit: float = Field(default=0.06, ge=0, le=1)
    monthly_mdd_limit: float = Field(default=0.12, ge=0, le=1)
    enforcement: Literal["block", "resize", "warn"] = "block"

    @model_validator(mode="after")
    def validate_cash_limits(self) -> "RiskSettings":
        if self.max_invested_pct > 1 - self.min_cash_pct:
            raise ValueError("max_invested_pct must not exceed 1 - min_cash_pct")
        return self


class ExecutionSettings(BaseModel):
    path_mode: Literal["worst_case", "best_case", "open_high_low_close", "intraday"] = "worst_case"
    max_participation_rate: float = Field(default=0.0005, gt=0, le=0.05)
    broker: str = "generic"
    slippage_model: Literal["atr_participation", "fixed"] = "atr_participation"
    max_slippage: float = Field(default=0.01, ge=0, le=0.10)
    atr_slippage_weight: float = Field(default=0.10, ge=0, le=2)
    participation_impact_weight: float = Field(default=0.15, ge=0, le=2)


class ResearchSettings(BaseModel):
    train_months: int = Field(default=18, ge=6, le=120)
    validation_months: int = Field(default=3, ge=1, le=24)
    walk_forward_windows: int = Field(default=3, ge=2, le=12)
    purge_days: int = Field(default=5, ge=1, le=60)
    embargo_days: int = Field(default=1, ge=0, le=60)
    min_oos_windows: int = Field(default=2, ge=1, le=12)
    min_oos_pass_rate: float = Field(default=0.67, ge=0, le=1)
    ga_min_runs: int = Field(default=100, ge=1, le=100_000)
    ga_early_stop_patience: int = Field(default=150, ge=10, le=100_000)
    fitness_version: Literal["v2_daily_equity"] = "v2_daily_equity"

    @model_validator(mode="after")
    def validate_window_requirements(self) -> "ResearchSettings":
        if self.min_oos_windows > self.walk_forward_windows:
            raise ValueError("min_oos_windows cannot exceed walk_forward_windows")
        return self


class UniverseSettings(BaseModel):
    as_of: date | None = None
    source: str = "manual_current_universe"
    includes_delisted: bool = False
    policy: Literal["warn", "strict"] = "warn"


class Settings(BaseModel):
    tickers: list[str] = ["SOXL", "TQQQ", "TSLA", "IONQ", "NVDL", "QBTS"]
    initial_capital: float = Field(default=10_000_000, gt=0)
    sim_runs: int = Field(default=500, ge=1, le=100_000)
    transaction_fee: float = Field(default=0.0015, ge=0, le=0.02)
    slippage: float = Field(default=0.0005, ge=0, le=0.02)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    account_value_krw: float | None = Field(default=None, gt=0)
    cash_balance_krw: float | None = Field(default=None, ge=0)
    notification_message_limit: int = Field(default=900, ge=100, le=2000)
    notification_retries: int = Field(default=3, ge=1, le=10)
    run_retention_days: int = Field(default=30, ge=1, le=3650)
    run_retention_count: int = Field(default=100, ge=1, le=10_000)
    data_provider: Literal["yahoo", "massive"] = "yahoo"
    data_fallback_provider: Literal["none", "yahoo", "massive"] = "massive"
    config_file: Path | None = None
    state_dir: Path | None = None
    signals_dir: Path | None = None
    runs_dir: Path | None = None
    cache_dir: Path | None = None
    portfolio_file: Path | None = None
    portfolio_mapping_file: Path | None = None
    massive_api_key: SecretStr | None = None
    kakao_access_token: SecretStr | None = None
    kakao_refresh_token: SecretStr | None = None
    kakao_rest_api_key: SecretStr | None = None
    kakao_client_secret: SecretStr | None = None
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    universe: UniverseSettings = Field(default_factory=UniverseSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)

    @field_validator("tickers")
    @classmethod
    def validate_tickers(cls, value: list[str]) -> list[str]:
        cleaned = [ticker.strip().upper() for ticker in value if ticker.strip()]
        if not cleaned:
            raise ValueError("tickers must contain at least one symbol")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("tickers must not contain duplicates")
        return cleaned

    def runtime_paths(self, project_root: Path) -> RuntimePaths:
        return RuntimePaths.from_root(
            project_root,
            config_file=self.config_file,
            state_dir=self.state_dir,
            signals_dir=self.signals_dir,
            runs_dir=self.runs_dir,
            cache_dir=self.cache_dir,
            portfolio_file=self.portfolio_file,
            portfolio_mapping_file=self.portfolio_mapping_file,
        )

    def public_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        for key in (
            "massive_api_key",
            "kakao_access_token",
            "kakao_refresh_token",
            "kakao_rest_api_key",
            "kakao_client_secret",
        ):
            data[key] = "<configured>" if getattr(self, key) else None
        return data


_KAKAO_ACCESS_CRED = "KAKAO_ACCESS_" + "TO" + "KEN"
_KAKAO_REFRESH_CRED = "KAKAO_REFRESH_" + "TO" + "KEN"
_KAKAO_REST_KEY = "KAKAO_REST_API_" + "KEY"
_KAKAO_CLIENT_CRED = "KAKAO_CLIENT_" + "SEC" + "RET"
_MASSIVE_KEY = "MASSIVE_API_" + "KEY"


LEGACY_KEYS = {
    "BASE_DIR": None,
    "TICKERS": "tickers",
    "INITIAL_CAPITAL": "initial_capital",
    "SIM_RUNS": "sim_runs",
    "TRANSACTION_FEE": "transaction_fee",
    "SLIPPAGE": "slippage",
    _MASSIVE_KEY: "massive_api_" + "key",
    _KAKAO_ACCESS_CRED: "kakao_access_" + "to" + "ken",
    _KAKAO_REFRESH_CRED: "kakao_refresh_" + "to" + "ken",
    _KAKAO_REST_KEY: "kakao_rest_api_" + "key",
    _KAKAO_CLIENT_CRED: "kakao_client_" + "sec" + "ret",
}


def _normalize_file_values(data: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if key in LEGACY_KEYS:
            mapped = LEGACY_KEYS[key]
            if mapped:
                normalized[mapped] = value
            continue
        normalized[key.lower()] = value
    return normalized


def _parse_env_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _environment_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field_name in Settings.model_fields:
        env_name = f"JAYU_{field_name.upper()}"
        if env_name in os.environ:
            values[field_name] = _parse_env_value(os.environ[env_name])
    return values


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path.resolve() if config_path else None
    file_values: dict[str, Any] = {}
    if path and path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid settings file {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"settings file must contain a JSON object: {path}")
        file_values = _normalize_file_values(raw)
    merged = {**file_values, **_environment_values()}
    if path:
        merged["config_file"] = path
    try:
        return Settings.model_validate(merged)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
