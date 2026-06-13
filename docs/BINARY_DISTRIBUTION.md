# Binary Distribution

Jayu currently ships as a Python package with a thin Go entrypoint. The target
deployment shape is a single `jayu` executable per platform, while runtime
state remains outside the binary.

## Layout

Tracked:

- `cmd/jayu`: Go entrypoint and process supervisor
- `internal/notify`: notification command wiring
- `internal/portfolio`: portfolio command wiring
- `internal/scheduler`: schedule calculation helpers
- `rust/jayu-core`: typed backtest core under migration
- `src/jayu`: Python orchestration, data, reports, and integrations

External runtime directories:

- `state/`
- `signals/`
- `runs/`
- `data/cache/`

## Build Targets

Short term:

1. Build `bin/jayu.exe` or `bin/jayu` from `cmd/jayu`.
2. Install Python dependencies with `uv sync --frozen`.
3. Let the Go binary locate `.venv` or fall back to `uv run jayu`.

Medium term:

1. Compile `rust/jayu-core` as the deterministic backtest engine.
2. Keep Python as the orchestration layer for providers, notifications, and
   reporting.
3. Add golden tests between Python and Rust outputs before moving each strategy
   path.

Long term:

1. Bundle the Python environment with the Go executable or a platform archive.
2. Keep secrets, portfolio CSVs, and run outputs outside the archive.
3. Publish checksums and a manifest containing Git revision, dependency lock
   hash, and Rust core version.

## Release Checklist

1. `uv run pytest -q`
2. `uv run ruff format --check src tests scripts`
3. `uv run ruff check src tests scripts danta_simulation.py stock_kakao.py`
4. `uv run mypy src/jayu`
5. `go test ./...`
6. `cargo test --manifest-path rust/jayu-core/Cargo.toml`
7. `scripts/build_release.ps1`
