"""Deprecated compatibility alias for the packaged Jayu engine."""

import sys
import warnings

if __name__ == "__main__":
    from jayu.cli import app

    warnings.warn(
        "danta_simulation.py is deprecated; use `jayu simulate`. Removal date: 2026-09-30.",
        FutureWarning,
        stacklevel=1,
    )
    app(args=["simulate", *sys.argv[1:]], prog_name="jayu")
else:
    from jayu import engine as _engine

    warnings.warn(
        "imports from danta_simulation are deprecated; import from jayu.engine. "
        "Removal date: 2026-09-30.",
        DeprecationWarning,
        stacklevel=2,
    )
    sys.modules[__name__] = _engine
