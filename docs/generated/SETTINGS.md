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
| `research` | `ResearchSettings` | `null` | `{}` |
| `universe` | `UniverseSettings` | `null` | `{}` |
| `risk` | `RiskSettings` | `null` | `{}` |
