#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

cd "$PROJECT_ROOT"

if command -v jayu >/dev/null 2>&1; then
  exec jayu simulate --notify
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run jayu simulate --notify
fi

if [ -x ".venv/bin/jayu" ]; then
  exec .venv/bin/jayu simulate --notify
fi

echo "jayu executable not found. Install with 'uv sync --frozen' first." >&2
exit 127
