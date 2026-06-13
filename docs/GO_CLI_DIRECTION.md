# Go CLI Direction

The Go entrypoint is intentionally a process supervisor and distribution shim
for now. It should not duplicate trading, risk, notification, or data-provider
business logic while the Python package is the system of record.

## Current Scope

- Locate the project root.
- Prefer `.venv` when available.
- Fall back to `uv run jayu`.
- Provide small operational helpers in `internal/notify`, `internal/portfolio`,
  and `internal/scheduler`.
- Preserve stdin, stdout, stderr, and exit codes.

## Not In Scope Yet

- Reimplementing strategy evaluation.
- Reimplementing portfolio risk decisions.
- Reimplementing Kakao token refresh.
- Maintaining a second configuration schema.

## Promotion Criteria

Go code can own a feature only when all of these are true:

1. The feature is operational rather than research/math heavy.
2. The Python behavior has a fixture-backed contract.
3. The Go package has unit tests for that contract.
4. The CLI help and release checklist mention the ownership boundary.

The first good candidates are scheduler health checks and long-running daemon
mode. The Rust core remains the preferred path for deterministic backtest
execution.
