import re
from pathlib import Path


def test_runtime_package_contains_no_broker_order_submission_api():
    forbidden_patterns = {
        r"\b(?:submit|place|create)_order\s*\(": "broker order method",
        r"\btrading_?client\s*\(": "broker trading client",
        r"\balpaca\.trading\b": "Alpaca trading SDK",
        r"/v2/orders\b": "broker order endpoint",
    }
    violations = []
    for path in Path("src/jayu").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        for pattern, label in forbidden_patterns.items():
            if re.search(pattern, content, flags=re.IGNORECASE):
                violations.append(f"{path}:{label}")

    assert violations == []
