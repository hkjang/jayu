"""Registry for managing schema versions and structural rules of state files."""

from __future__ import annotations

from typing import Any

# Define the expected schema version for each state file type
CURRENT_VERSIONS = {
    "toss_account_snapshot": "1.1",
    "dividend_cache": "1.1",
    "dashboard_cache": "1.1",
    "feature_inventory": "1.1",
    "order_history_cache": "1.1"
}

# Define required keys for validating structural integrity
SCHEMA_RULES = {
    "toss_account_snapshot": {
        "required_keys": ["symbol", "holdingQuantity", "currentPrice", "avgPrice", "currency"],
        "is_list": True
    },
    "dividend_cache": {
        "required_keys": ["ticker", "fetched_at", "dividends", "splits"],
        "is_list": False
    },
    "dashboard_cache": {
        "required_keys": ["generated_at", "holdings", "annual_dividend_krw", "data_quality_summary"],
        "is_list": False
    },
    "feature_inventory": {
        "required_keys": ["generated_at", "summary", "features"],
        "is_list": False
    },
    "order_history_cache": {
        "required_keys": ["fetched_at", "orders"],
        "is_list": False
    }
}


def validate_state_structure(file_type: str, data: Any) -> tuple[bool, str | None]:
    """Validates if the loaded state dictionary complies with the schema registry rules."""
    rule = SCHEMA_RULES.get(file_type)
    if not rule:
        return True, None

    # Check list/dict type requirement
    if rule["is_list"]:
        if not isinstance(data, list):
            return False, f"Expected list type for {file_type}, got {type(data).__name__}"
        if len(data) > 0:
            sample = data[0]
            if not isinstance(sample, dict):
                return False, f"Expected list of dicts for {file_type}"
            missing = [k for k in rule["required_keys"] if k not in sample]
            if missing:
                return False, f"Missing required keys in list items of {file_type}: {missing}"
    else:
        if not isinstance(data, dict):
            return False, f"Expected dict type for {file_type}, got {type(data).__name__}"
        missing = [k for k in rule["required_keys"] if k not in data]
        if missing:
            return False, f"Missing required keys in {file_type}: {missing}"

    return True, None
