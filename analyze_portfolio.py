"""Deprecated compatibility entry point for portfolio analysis."""

from __future__ import annotations

import sys

from jayu.legacy_cli import run_legacy_command


def main() -> int:
    return run_legacy_command(
        ("portfolio", "analyze"),
        sys.argv[1:],
        script_name="analyze_portfolio.py",
        replacement="jayu portfolio analyze",
    )


if __name__ == "__main__":
    raise SystemExit(main())
