"""Deprecated compatibility alias for the packaged Jayu engine."""

import sys
import warnings

if __name__ == "__main__":
    from jayu.legacy_cli import run_legacy_command

    raise SystemExit(
        run_legacy_command(
            ("simulate",),
            sys.argv[1:],
            script_name="danta_simulation.py",
            replacement="jayu simulate",
        )
    )
else:
    from jayu import engine as _engine

    warnings.warn(
        "imports from danta_simulation are deprecated; import from jayu.engine. "
        "Removal date: 2026-09-30.",
        DeprecationWarning,
        stacklevel=2,
    )
    sys.modules[__name__] = _engine
