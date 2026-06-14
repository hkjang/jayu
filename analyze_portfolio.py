"""Deprecated compatibility entry point for portfolio analysis."""

from __future__ import annotations

import sys
import warnings

from jayu.cli import app


def main() -> int:
    warnings.warn(
        "analyze_portfolio.py is deprecated; use `jayu portfolio analyze`. "
        "Removal date: 2026-09-30.",
        FutureWarning,
        stacklevel=1,
    )
    app(
        args=["portfolio", "analyze", *sys.argv[1:]],
        prog_name="jayu",
        standalone_mode=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
