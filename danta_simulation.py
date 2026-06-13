"""Compatibility alias for the packaged Jayu engine."""

import sys

from jayu import engine as _engine


if __name__ == "__main__":
    _engine.run()
else:
    sys.modules[__name__] = _engine
