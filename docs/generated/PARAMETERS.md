# Strategy Parameter Reference

Generated from `configs/strategy_spaces/*.json`. Do not edit manually.

A candidate has exactly one `strategy_mode`: `ensemble`, `connors_rsi2`, `williams_breakout`, or `volume_breakout`.

## common

| Parameter | Choices | Conditional |
|---|---|---|
| `hold_days` | `[1, 2, 3, 5]` | - |
| `vol_mult` | `[1.2, 1.5, 1.8, 2.0, 2.5, 3.0]` | - |
| `gap_min` | `[-0.01, -0.005, 0.0, 0.002, 0.005]` | - |
| `use_atr_stop` | `[true, false]` | - |
| `atr_mult_stop` | `[1.5, 2.0, 2.5, 3.0]` | `use_atr_stop=True` |
| `stop_pct` | `[0.02, 0.025, 0.03, 0.035, 0.04, 0.05]` | `use_atr_stop=False` |
| `use_atr_target` | `[true, false]` | - |
| `atr_mult_target` | `[1.5, 2.0, 2.5, 3.0, 4.0]` | `use_atr_target=True` |
| `target_pct` | `[0.04, 0.05, 0.06, 0.07, 0.08, 0.1, 0.12, 0.15]` | `use_atr_target=False` |
| `trail_stop` | `[true, false]` | - |
| `trail_pct` | `[0.02, 0.03, 0.04]` | `trail_stop=True` |
| `use_breakeven_stop` | `[true, false]` | - |
| `breakeven_trigger_pct` | `[0.3, 0.4, 0.5]` | `use_breakeven_stop=True` |
| `min_dollar_volume` | `[5000000, 10000000, 20000000]` | - |
| `use_volatility_sizing` | `[true, false]` | - |
| `max_risk_per_trade_pct` | `[0.01, 0.015, 0.02]` | `use_volatility_sizing=True` |
| `kelly_fraction` | `[0.25, 0.5, 1.0]` | - |

## ensemble

| Parameter | Choices | Conditional |
|---|---|---|
| `rsi_lo` | `[35, 40, 45, 50, 55]` | - |
| `rsi_hi` | `[60, 65, 70, 75, 80]` | - |
| `ema_span` | `[10, 20, 50]` | - |
| `require_macd` | `[true, false]` | - |
| `require_bb` | `[true, false]` | - |
| `regime_filter` | `[true, false]` | - |
| `ensemble_min` | `[1, 2, 3]` | - |
| `use_adx_filter` | `[true, false]` | - |
| `adx_threshold` | `[20, 25, 30]` | - |

## connors_rsi2

| Parameter | Choices | Conditional |
|---|---|---|
| `connors_rsi2_limit` | `[2, 5, 10, 15, 20]` | - |

## williams_breakout

| Parameter | Choices | Conditional |
|---|---|---|
| `williams_k_multiplier` | `[0.8, 1.0, 1.2]` | - |

## volume_breakout

| Parameter | Choices | Conditional |
|---|---|---|
| `volume_spike_mult` | `[1.8, 2.0, 2.5, 3.0]` | - |
| `volume_breakout_period` | `[5, 10, 15, 20]` | - |
