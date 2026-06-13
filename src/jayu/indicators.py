from __future__ import annotations


INDICATOR_WARMUP_ROWS = {
    "rsi": 14,
    "rsi2": 2,
    "sma5": 5,
    "sma200": 200,
    "ema10": 10,
    "ema20": 20,
    "ema50": 50,
    "ema200": 200,
    "volume_ratio": 20,
    "atr": 14,
    "dollar_volume_ma20": 20,
    "macd": 35,
    "bollinger_bands": 20,
    "stoch_rsi": 31,
    "obv_trend": 30,
    "adx": 28,
    "williams_noise_ratio": 20,
    "donchian_breakout": 20,
}


def indicator_warmup_report() -> dict[str, int]:
    return dict(INDICATOR_WARMUP_ROWS)
