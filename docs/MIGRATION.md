# Migration Guide

Legacy root scripts remain as compatibility wrappers during the package
migration. New automation should use the `jayu` CLI or `src/jayu` modules.

## Deprecation Schedule

Target removal date: 2026-09-30

| Legacy entrypoint | Replacement | Example | Removal date |
|---|---|---|---|
| `python danta_simulation.py` | `jayu simulate` | `uv run jayu simulate --mode research --runs 500` | 2026-09-30 |
| `python stock_kakao.py` | `jayu notify --channel kakao` | `uv run jayu notify --channel kakao` | 2026-09-30 |
| `python build_portfolio.py` | `jayu portfolio build` | `uv run jayu portfolio build` | 2026-09-30 |
| `python analyze_portfolio.py` | `jayu portfolio analyze` | `uv run jayu portfolio analyze --details` | 2026-09-30 |
| imports from `danta_simulation` | `jayu.engine` or smaller `jayu.*` modules | `from jayu import engine` | 2026-09-30 |

All four executable wrappers delegate to the packaged CLI and emit a visible
`FutureWarning` when run directly. No new behavior should be added to them.
The shared delegation path is `jayu.legacy_cli.run_legacy_command`; direct
broker, provider, portfolio, or strategy logic in a root wrapper is unsupported.

## Strategy State Migration

Legacy flags such as `use_connors_rsi2`, `use_williams_breakout`, and
`use_volume_breakout` are still accepted only for old state-file migration.
New state should use the single `strategy_mode` field.

Before removing the flags:

1. Run `jayu validate-config`.
2. Run one `jayu simulate --runs <N>` cycle to rewrite state under `state/`.
3. Confirm `state/best_strategy.json` and `state/gene_pool.json` contain
   `strategy_mode`.
4. Keep only sample JSON files in Git.

## Portfolio Build Migration

`jayu portfolio build` now calls `jayu.portfolio_build.build_portfolio_csv`
directly. Put private ticker-name mappings in
`configs/portfolio_ticker_map.json`; keep that file local if it contains
broker-specific names.
