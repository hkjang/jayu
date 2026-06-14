"""Shared compatibility wrapper for deprecated root entry points."""

from __future__ import annotations

import warnings
from collections.abc import Sequence

from .cli import app

REMOVAL_DATE = "2026-09-30"


def run_legacy_command(
    command: Sequence[str],
    argv: Sequence[str],
    *,
    script_name: str,
    replacement: str,
) -> int:
    warnings.warn(
        f"{script_name} is deprecated; use `{replacement}`. Removal date: {REMOVAL_DATE}.",
        FutureWarning,
        stacklevel=2,
    )
    app(
        args=[*command, *argv],
        prog_name="jayu",
        standalone_mode=False,
    )
    return 0
