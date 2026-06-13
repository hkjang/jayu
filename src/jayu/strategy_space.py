from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any


class StrategyMode(StrEnum):
    ENSEMBLE = "ensemble"
    CONNORS_RSI2 = "connors_rsi2"
    WILLIAMS_BREAKOUT = "williams_breakout"
    VOLUME_BREAKOUT = "volume_breakout"


STRATEGY_MODES = tuple(mode.value for mode in StrategyMode)

MODE_FLAG_MAP = {
    "connors_rsi2": "use_connors_rsi2",
    "williams_breakout": "use_williams_breakout",
    "volume_breakout": "use_volume_breakout",
}

CONDITIONAL_PARAMETERS = {
    "use_atr_stop": {"atr_mult_stop": True, "stop_pct": False},
    "use_atr_target": {"atr_mult_target": True, "target_pct": False},
    "trail_stop": {"trail_pct": True},
    "use_breakeven_stop": {"breakeven_trigger_pct": True},
    "use_volatility_sizing": {"max_risk_per_trade_pct": True},
}


def strategy_space_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "strategy_spaces"


def load_strategy_spaces(base_dir: Path | None = None) -> dict[str, dict[str, list[Any]]]:
    directory = base_dir or strategy_space_dir()
    names = ("common", *STRATEGY_MODES)
    spaces: dict[str, dict[str, list[Any]]] = {}
    for name in names:
        path = directory / f"{name}.json"
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a JSON object")
        spaces[name] = value
    return spaces


def infer_strategy_mode(params: dict[str, Any]) -> str:
    explicit = params.get("strategy_mode")
    if explicit in STRATEGY_MODES:
        return str(explicit)
    # Preserve the legacy backtest branch priority.
    if params.get("use_williams_breakout"):
        return "williams_breakout"
    if params.get("use_volume_breakout"):
        return "volume_breakout"
    if params.get("use_connors_rsi2"):
        return "connors_rsi2"
    return "ensemble"


def normalize_strategy_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    mode = infer_strategy_mode(normalized)
    normalized["strategy_mode"] = mode
    for mapped_mode, flag in MODE_FLAG_MAP.items():
        normalized[flag] = mode == mapped_mode
    return normalized


def active_parameter_space(
    params: dict[str, Any],
    spaces: dict[str, dict[str, list[Any]]] | None = None,
) -> dict[str, list[Any]]:
    loaded = spaces or load_strategy_spaces()
    normalized = normalize_strategy_params(params)
    active = {
        "strategy_mode": list(STRATEGY_MODES),
        **loaded["common"],
        **loaded[normalized["strategy_mode"]],
    }
    for switch, dependents in CONDITIONAL_PARAMETERS.items():
        switch_value = bool(normalized.get(switch, False))
        for parameter, required_value in dependents.items():
            if switch_value != required_value:
                active.pop(parameter, None)
    return active


def combined_parameter_space(
    spaces: dict[str, dict[str, list[Any]]] | None = None,
) -> dict[str, list[Any]]:
    loaded = spaces or load_strategy_spaces()
    combined: dict[str, list[Any]] = {"strategy_mode": list(STRATEGY_MODES)}
    for space in loaded.values():
        combined.update(space)
    return combined


def parameter_errors(params: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    mode = params.get("strategy_mode")
    if mode not in STRATEGY_MODES:
        errors.append(f"strategy_mode must be one of {', '.join(STRATEGY_MODES)}")

    enabled_legacy_modes = sum(bool(params.get(flag)) for flag in MODE_FLAG_MAP.values())
    expected_enabled = 0 if mode == "ensemble" else 1
    if enabled_legacy_modes != expected_enabled:
        errors.append("legacy strategy flags must match strategy_mode")
    elif mode != "ensemble" and not params.get(MODE_FLAG_MAP[str(mode)]):
        errors.append("the active legacy strategy flag must match strategy_mode")

    if params.get("rsi_lo", 0) >= params.get("rsi_hi", float("inf")):
        errors.append("rsi_lo must be smaller than rsi_hi")

    if params.get("use_atr_stop") and params.get("use_atr_target"):
        if params.get("atr_mult_target", 0) <= params.get("atr_mult_stop", 0):
            errors.append("atr_mult_target must be greater than atr_mult_stop")
    elif not params.get("use_atr_stop") and not params.get("use_atr_target"):
        if params.get("target_pct", 0) <= params.get("stop_pct", 0):
            errors.append("target_pct must be greater than stop_pct")

    for switch, dependents in CONDITIONAL_PARAMETERS.items():
        switch_value = bool(params.get(switch, False))
        for parameter, required_value in dependents.items():
            if switch_value == required_value and parameter not in params:
                errors.append(f"{parameter} is required when {switch}={required_value}")
    return errors


def validate_params(params: dict[str, Any]) -> None:
    errors = parameter_errors(params)
    if errors:
        raise ValueError("; ".join(errors))
