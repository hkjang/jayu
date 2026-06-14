# Legacy boundary: root scripts vs the `jayu` package

This project's logic lives in the `src/jayu` package (entry point: the `jayu`
CLI). A handful of scripts remain at the repository root for historical reasons.
This document classifies each so contributors know what is supported, what is a
thin compatibility shim, and what is a one-off utility that is **not** part of
the maintained surface or CI gates.

## Classification

| Script | Class | Status / guidance |
| --- | --- | --- |
| `danta_simulation.py` | **Compatibility shim** | Thin delegator to `jayu.engine`. Kept so older invocations keep working. Prefer `jayu simulate`. Linted; mypy-excluded. |
| `stock_kakao.py` | **Compatibility shim** | Thin delegator to `jayu.notifications`. Prefer `jayu notify`. Linted. |
| `analyze_portfolio.py` | **Compatibility shim** | Delegates to `jayu portfolio analyze` and emits a deprecation warning. |
| `build_portfolio.py` | **Compatibility shim** | Delegates to `jayu portfolio build` and emits a deprecation warning. |
| `fix_tickers.py`, `fix_remaining.py` | **One-off maintenance** | Ad-hoc CSV/ticker repair via `yfinance` (network). Not tested, not in the lint/CI scope. Run manually if ever needed. |
| `check_csv.py`, `debug_sim.py` | **One-off / debug** | Throwaway inspection helpers. Not maintained. |
| `test_simulation.py` | **Legacy test island** | `unittest`-style suite collected by pytest (`testpaths = ["tests", "."]`) but outside the `ruff`/`mypy` scope. New tests should live under `tests/`. |

## Supported surface

- **Logic**: `src/jayu/*` only.
- **CLI**: `jayu` (`simulate`, `signal`, `notify`, `portfolio`, `report`,
  `experiments`, `validate-config`).
- **CI-gated**: `src`, `tests`, `scripts`, and all four executable wrappers for lint.
- **Delegation**: executable wrappers use `jayu.legacy_cli.run_legacy_command`;
  wrapper-specific business logic is not permitted.

## Migration intent

- Compatibility shims stay until downstream callers are confirmed migrated to
  the `jayu` CLI.
- Superseded duplicates (`analyze_portfolio.py`, `build_portfolio.py`) should be
  removed once their package equivalents are confirmed feature-complete; do not
  add new features to them.
- One-off utilities may be moved under `scripts/legacy/` or deleted in a
  dedicated cleanup PR; they are intentionally left out of CI today.

> Note: moving `test_simulation.py` into `tests/` would pull its 866 lines into
> the `ruff` scope (a large reformat) and is therefore deferred to its own PR.
