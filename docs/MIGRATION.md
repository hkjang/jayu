# Migration Guide

Legacy root scripts remain as compatibility wrappers during the package
migration. New automation should use the `jayu` CLI or `src/jayu` modules.

## Deprecation Schedule

Target removal date: 2026-09-30

| Legacy entrypoint | Replacement |
|---|---|
| `python danta_simulation.py` | `jayu simulate` or `jayu signal --date today` |
| `python stock_kakao.py` | `jayu notify --channel kakao` |
| `python build_portfolio.py` | `jayu portfolio build` |
| imports from `danta_simulation` | imports from `jayu.engine` or smaller `jayu.*` modules |

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
