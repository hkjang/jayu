# Settings Reference

Generated from `jayu.settings.Settings`. Do not edit manually.

| Field | Type | Default | Constraints |
|---|---|---|---|
| `tickers` | `array` | `["SOXL", "TQQQ", "TSLA", "IONQ", "NVDL", "QBTS"]` | `{}` |
| `initial_capital` | `number` | `10000000` | `{"exclusiveMinimum": 0}` |
| `sim_runs` | `integer` | `500` | `{"maximum": 100000, "minimum": 1}` |
| `transaction_fee` | `number` | `0.0015` | `{"maximum": 0.02, "minimum": 0}` |
| `slippage` | `number` | `0.0005` | `{"maximum": 0.02, "minimum": 0}` |
| `random_seed` | `integer` | `42` | `{"maximum": 2147483647, "minimum": 0}` |
| `account_value_krw` | `number | null` | `null` | `{}` |
| `cash_balance_krw` | `number | null` | `null` | `{}` |
| `notification_message_limit` | `integer` | `900` | `{"maximum": 2000, "minimum": 100}` |
| `notification_retries` | `integer` | `3` | `{"maximum": 10, "minimum": 1}` |
| `run_retention_days` | `integer` | `30` | `{"maximum": 3650, "minimum": 1}` |
| `run_retention_count` | `integer` | `100` | `{"maximum": 10000, "minimum": 1}` |
| `data_provider` | `string` | `"yahoo"` | `{"enum": ["yahoo", "massive"]}` |
| `data_fallback_provider` | `string` | `"massive"` | `{"enum": ["none", "yahoo", "massive"]}` |
| `config_file` | `string | null` | `null` | `{}` |
| `state_dir` | `string | null` | `null` | `{}` |
| `signals_dir` | `string | null` | `null` | `{}` |
| `runs_dir` | `string | null` | `null` | `{}` |
| `cache_dir` | `string | null` | `null` | `{}` |
| `portfolio_file` | `string | null` | `null` | `{}` |
| `portfolio_mapping_file` | `string | null` | `null` | `{}` |
| `massive_api_key` | `string | null` | `null` | `{}` |
| `kakao_access_token` | `string | null` | `null` | `{}` |
| `kakao_refresh_token` | `string | null` | `null` | `{}` |
| `kakao_rest_api_key` | `string | null` | `null` | `{}` |
| `kakao_client_secret` | `string | null` | `null` | `{}` |
| `execution` | `ExecutionSettings` | `null` | `{}` |
| `execution.path_mode` | `string` | `"worst_case"` | `{"enum": ["worst_case", "best_case", "open_high_low_close", "intraday"]}` |
| `execution.max_participation_rate` | `number` | `0.0005` | `{"exclusiveMinimum": 0, "maximum": 0.05}` |
| `execution.broker` | `string` | `"generic"` | `{}` |
| `execution.slippage_model` | `string` | `"atr_participation"` | `{"enum": ["atr_participation", "fixed"]}` |
| `execution.max_slippage` | `number` | `0.01` | `{"maximum": 0.1, "minimum": 0}` |
| `execution.atr_slippage_weight` | `number` | `0.1` | `{"maximum": 2, "minimum": 0}` |
| `execution.participation_impact_weight` | `number` | `0.15` | `{"maximum": 2, "minimum": 0}` |
| `research` | `ResearchSettings` | `null` | `{}` |
| `research.train_months` | `integer` | `18` | `{"maximum": 120, "minimum": 6}` |
| `research.validation_months` | `integer` | `3` | `{"maximum": 24, "minimum": 1}` |
| `research.walk_forward_windows` | `integer` | `3` | `{"maximum": 12, "minimum": 2}` |
| `research.purge_days` | `integer` | `5` | `{"maximum": 60, "minimum": 1}` |
| `research.embargo_days` | `integer` | `1` | `{"maximum": 60, "minimum": 0}` |
| `research.min_oos_windows` | `integer` | `2` | `{"maximum": 12, "minimum": 1}` |
| `research.min_oos_pass_rate` | `number` | `0.67` | `{"maximum": 1, "minimum": 0}` |
| `research.min_oos_psr_observations` | `integer` | `3` | `{"maximum": 12, "minimum": 3}` |
| `research.min_oos_psr` | `number` | `0.5` | `{"maximum": 1, "minimum": 0}` |
| `research.selection_bias_enabled` | `boolean` | `true` | `{}` |
| `research.selection_min_candidates` | `integer` | `5` | `{"maximum": 100000, "minimum": 2}` |
| `research.selection_min_dsr` | `number` | `0.5` | `{"maximum": 1, "minimum": 0}` |
| `research.selection_max_pbo` | `number` | `0.5` | `{"maximum": 1, "minimum": 0}` |
| `research.selection_pbo_blocks` | `integer` | `2` | `{"maximum": 12, "minimum": 2}` |
| `research.final_lockbox_enabled` | `boolean` | `true` | `{}` |
| `research.final_lockbox_fraction` | `number` | `0.2` | `{"exclusiveMinimum": 0}` |
| `research.final_lockbox_min_rows` | `integer` | `40` | `{"maximum": 504, "minimum": 20}` |
| `research.final_lockbox_min_retention` | `number` | `0.5` | `{"maximum": 2, "minimum": 0}` |
| `research.final_lockbox_require_positive_return` | `boolean` | `true` | `{}` |
| `research.ga_min_runs` | `integer` | `100` | `{"maximum": 100000, "minimum": 1}` |
| `research.ga_early_stop_patience` | `integer` | `150` | `{"maximum": 100000, "minimum": 10}` |
| `research.fitness_version` | `string` | `"v2_daily_equity"` | `{}` |
| `universe` | `UniverseSettings` | `null` | `{}` |
| `universe.as_of` | `string | null` | `null` | `{}` |
| `universe.source` | `string` | `"manual_current_universe"` | `{}` |
| `universe.includes_delisted` | `boolean` | `false` | `{}` |
| `universe.policy` | `string` | `"warn"` | `{"enum": ["warn", "strict"]}` |
| `risk` | `RiskSettings` | `null` | `{}` |
| `risk.profile` | `string` | `"balanced"` | `{"enum": ["balanced", "conservative", "warning"]}` |
| `risk.max_underlying_exposure` | `number` | `0.3` | `{"maximum": 1, "minimum": 0}` |
| `risk.max_sector_exposure` | `number` | `0.5` | `{"maximum": 1, "minimum": 0}` |
| `risk.max_leveraged_etf_value` | `number` | `0.3` | `{"maximum": 1, "minimum": 0}` |
| `risk.max_adjusted_gross_exposure` | `number` | `1.75` | `{"maximum": 5, "minimum": 0}` |
| `risk.max_factor_exposure` | `number` | `0.6` | `{"maximum": 3, "minimum": 0}` |
| `risk.min_cash_pct` | `number` | `0.15` | `{"maximum": 1, "minimum": 0}` |
| `risk.max_invested_pct` | `number` | `0.85` | `{"maximum": 1, "minimum": 0}` |
| `risk.daily_loss_limit` | `number` | `0.03` | `{"maximum": 1, "minimum": 0}` |
| `risk.weekly_loss_limit` | `number` | `0.06` | `{"maximum": 1, "minimum": 0}` |
| `risk.monthly_mdd_limit` | `number` | `0.12` | `{"maximum": 1, "minimum": 0}` |
| `risk.enforcement` | `string` | `"block"` | `{"enum": ["block", "resize", "warn"]}` |
