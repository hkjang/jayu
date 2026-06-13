"""Compatibility alias for the packaged Jayu engine."""

import sys
import warnings

from jayu import engine as _engine

warnings.warn(
    "danta_simulation.py is deprecated; import from `jayu.engine` or use `jayu` CLI. "
    "This wrapper will be removed after 2026-09-30.",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    _engine.run()
else:
    sys.modules[__name__] = _engine
