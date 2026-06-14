"""Deprecated compatibility entry point for portfolio CSV refresh."""

from __future__ import annotations

import sys

from jayu.legacy_cli import run_legacy_command


def main() -> int:
    return run_legacy_command(
        ("portfolio", "build"),
        sys.argv[1:],
        script_name="build_portfolio.py",
        replacement="jayu portfolio build",
    )


if __name__ == "__main__":
    raise SystemExit(main())
