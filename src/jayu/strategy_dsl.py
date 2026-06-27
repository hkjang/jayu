from __future__ import annotations

import yaml
from typing import Any, Mapping, Sequence

class StrategyDSLError(ValueError):
    """Raised when Strategy DSL validation or parsing fails."""


def validate_strategy_dsl(dsl_dict: dict[str, Any]) -> dict[str, Any]:
    """Validate Strategy DSL dictionary and return a validation report.
    
    Raises StrategyDSLError if validation fails.
    """
    required_fields = ["name", "universe", "portfolio_type", "entry_rules", "exit_rules"]
    for field in required_fields:
        if field not in dsl_dict:
            raise StrategyDSLError(f"Missing required DSL field: '{field}'")

    if not isinstance(dsl_dict["name"], str) or not dsl_dict["name"].strip():
        raise StrategyDSLError("Field 'name' must be a non-empty string.")

    if not isinstance(dsl_dict["universe"], list):
        raise StrategyDSLError("Field 'universe' must be a list of tickers.")
    for ticker in dsl_dict["universe"]:
        if not isinstance(ticker, str) or not ticker.strip():
            raise StrategyDSLError("All items in 'universe' must be non-empty strings.")

    valid_portfolio_types = ["momentum", "balanced", "dividend", "short_term"]
    if dsl_dict["portfolio_type"] not in valid_portfolio_types:
        raise StrategyDSLError(
            f"Field 'portfolio_type' must be one of {valid_portfolio_types}."
        )

    if not isinstance(dsl_dict["entry_rules"], list):
        raise StrategyDSLError("Field 'entry_rules' must be a list of condition strings.")
    if not isinstance(dsl_dict["exit_rules"], list):
        raise StrategyDSLError("Field 'exit_rules' must be a list of condition strings.")

    # Optional fields validation
    for key in ["stop_loss_pct", "take_profit_pct"]:
        if key in dsl_dict and dsl_dict[key] is not None:
            try:
                float(dsl_dict[key])
            except (ValueError, TypeError):
                raise StrategyDSLError(f"Field '{key}' must be a float.")

    if "risk_filters" in dsl_dict and not isinstance(dsl_dict["risk_filters"], dict):
        raise StrategyDSLError("Field 'risk_filters' must be a dictionary.")

    return {
        "status": "valid",
        "name": dsl_dict["name"],
        "universe_count": len(dsl_dict["universe"]),
        "portfolio_type": dsl_dict["portfolio_type"],
    }


def parse_condition_token(val_str: str, row: Mapping[str, Any]) -> float:
    """Parse a token in a condition to a float value, looking it up in the row or converting to float."""
    # Check exact match in row
    if val_str in row:
        return float(row[val_str])
    
    # Common case insensitivity for standard indicators
    for k, v in row.items():
        if k.lower() == val_str.lower():
            return float(v)
            
    # Try converting to float constant
    try:
        return float(val_str)
    except ValueError:
        # If it cannot be parsed and is not in row, return 0.0 as fallback
        return 0.0


def evaluate_single_condition(row: Mapping[str, Any], condition: str) -> bool:
    """Evaluate a single condition string (e.g. 'rsi < 30') against a data row."""
    tokens = condition.split()
    if len(tokens) != 3:
        raise StrategyDSLError(f"Invalid condition format: '{condition}'. Must be 'LHS OP RHS'.")
    
    lhs_str, op, rhs_str = tokens
    lhs_val = parse_condition_token(lhs_str, row)
    rhs_val = parse_condition_token(rhs_str, row)

    if op == "<":
        return lhs_val < rhs_val
    elif op == ">":
        return lhs_val > rhs_val
    elif op == "<=":
        return lhs_val <= rhs_val
    elif op == ">=":
        return lhs_val >= rhs_val
    elif op == "==":
        return lhs_val == rhs_val
    elif op == "!=":
        return lhs_val != rhs_val
    else:
        raise StrategyDSLError(f"Unsupported operator '{op}' in condition: '{condition}'")


def evaluate_dsl_rules(row: Mapping[str, Any], rules: Sequence[str]) -> bool:
    """Evaluate if all rules in the sequence are met for the given row."""
    if not rules:
        return False
    try:
        for rule in rules:
            if not evaluate_single_condition(row, rule):
                return False
        return True
    except Exception as e:
        # Gracefully handle evaluation exceptions during runtime
        return False


def compile_dsl_to_params(dsl_dict: dict[str, Any]) -> dict[str, Any]:
    """Compile DSL dictionary into standard parameters compatible with backtest_core."""
    # We map the DSL parameters into the ensemble parameter dict
    params = {
        "strategy_name": dsl_dict["name"],
        "portfolio_type": dsl_dict["portfolio_type"],
        "stop_loss_pct": float(dsl_dict.get("stop_loss_pct", 0.05)),
        "take_profit_pct": float(dsl_dict.get("take_profit_pct", 0.15)),
        "holding_days_limit": int(dsl_dict.get("holding_days_limit", 15)),
        "entry_rules": dsl_dict["entry_rules"],
        "exit_rules": dsl_dict["exit_rules"],
        "risk_filters": dsl_dict.get("risk_filters", {}),
        "is_dsl": True,
    }
    return params


def load_strategy_dsl_yaml(file_path: str) -> dict[str, Any]:
    """Load, validate, and return a compiled Strategy DSL from a YAML file."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
    if not isinstance(content, dict):
        raise StrategyDSLError("YAML root must be a dictionary.")
    validate_strategy_dsl(content)
    return content
