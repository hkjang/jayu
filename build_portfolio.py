"""Deprecated compatibility entry point for portfolio CSV refresh."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from jayu.portfolio_build import build_portfolio_csv


def main() -> int:
    warnings.warn(
        "build_portfolio.py is deprecated; use `jayu portfolio build` instead. "
        "This wrapper will be removed after 2026-09-30.",
        DeprecationWarning,
        stacklevel=2,
    )
    root = Path(__file__).resolve().parent
    report = build_portfolio_csv(
        root / "toss_portfolio.csv",
        ticker_map_file=root / "configs" / "portfolio_ticker_map.json",
        mapping_file=root / "configs" / "portfolio_mapping.json",
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
