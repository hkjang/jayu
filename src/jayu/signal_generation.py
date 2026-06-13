from __future__ import annotations

from typing import Any

from .legacy_adapter import migrate_json_structure
from .optimizer import fill_missing_params
from .settings import Settings
from .signals import TodaySignal, normalize_signal_map
from .strategy_space import infer_strategy_mode

TICKERS: list[str] = list(Settings().tickers)


def configure(*, tickers: list[str]) -> None:
    global TICKERS
    TICKERS = list(tickers)


def _signal_payload(**kwargs: Any) -> dict[str, Any]:
    return TodaySignal(**kwargs).model_dump(mode="json")


def check_today_signals(
    df,
    best_all,
    vix_val=0.0,
    market_trends=None,
    require_approved=False,
):
    """현재 데이터 기준 진입 조건 충족 여부 (VIX, 시장 지수, 거래대금 필터 포함)"""
    best_all = migrate_json_structure(best_all)
    today_sigs = {}
    for ticker in TICKERS:
        row = df[ticker].iloc[-1] if ticker in df else None
        if row is None:
            today_sigs[ticker] = {"signal": "데이터없음"}
            continue

        # 오늘 국면 판정
        today_regime = row["regime"]  # 'bull', 'bear', 'sideways'

        # 최적 파라미터 로드
        ticker_data = best_all.get(ticker, {})
        data = ticker_data.get(today_regime)
        if require_approved and data and data.get("validation_status") != "approved":
            data = None

        # 폴백 처리 (오늘 국면 설정이 없으면 다른 국면이라도 사용)
        if not data or "params" not in data:
            for r in ["bull", "bear", "sideways"]:
                if (
                    r in ticker_data
                    and "params" in ticker_data[r]
                    and (
                        not require_approved
                        or ticker_data[r].get("validation_status") == "approved"
                    )
                ):
                    data = ticker_data[r]
                    break

        if not data or "params" not in data:
            today_sigs[ticker] = {
                "signal": "재검증필요" if require_approved else "설정없음",
                "action": "hold",
                "eligible": False,
            }
            continue

        p = fill_missing_params(data["params"])

        # 시장 모멘텀 필터 검사
        market_ok = True
        idx_name = "^SOX" if ticker == "SOXL" else "^IXIC"
        if market_trends and idx_name in market_trends:
            last_date = df[ticker].index[-1]
            market_ok = market_trends[idx_name].get(last_date, True)

        # ── 거래대금 유동성 가드 검사 ──────────────────────────
        min_vol = p.get("min_dollar_volume", 10_000_000)
        dollar_vol_ok = True
        if "dollar_volume_ma20" in row:
            dollar_vol_ok = float(row["dollar_volume_ma20"]) >= min_vol

        ema = float(row[f"ema{p['ema_span']}"])

        # 앙상블 조건 판정
        conds = {
            "rsi": p["rsi_lo"] <= float(row["rsi"]) <= p["rsi_hi"],
            "ema": float(row["Close"]) > ema,
            "volume": float(row["vol_ratio"]) >= p["vol_mult"],
            "gap": float(row["gap"]) >= p["gap_min"],
            "macd": bool(row["macd_cross"]) if p["require_macd"] else True,
            "bb": float(row["bb_pct"]) < 0.4 if p["require_bb"] else True,
            "regime": row["regime"] != "bear" if p["regime_filter"] else True,
            "obv": bool(row["obv_trend"]),
            "stoch": float(row["stoch_rsi"]) < 0.8,
        }

        strategy_mode = infer_strategy_mode(p)
        use_connors = strategy_mode == "connors_rsi2"
        use_williams = strategy_mode == "williams_breakout"
        use_volume = strategy_mode == "volume_breakout"
        mandatory = conds["volume"] and conds["gap"] and market_ok

        if use_williams:
            williams_target = float(row["Open"]) + float(row["prev_range"]) * float(
                row["k_dynamic"]
            ) * p.get("williams_k_multiplier", 1.0)
            williams_ok = (float(row["Close"]) > williams_target) and (
                float(row["Close"]) > float(row["sma200"])
            )
            all_ok = mandatory and williams_ok and dollar_vol_ok
        elif use_volume:
            vol_mult = p.get("volume_spike_mult", 2.0)
            vol_period = p.get("volume_breakout_period", 10)
            high_col = f"high_max_{vol_period}"
            volume_spike = float(row["Volume"]) > float(row["volume_ma20"]) * vol_mult
            price_break = float(row["Close"]) > float(row[high_col]) if high_col in row else False
            trend_ok = float(row["Close"]) > float(row["sma200"])
            volume_ok = volume_spike and price_break and trend_ok
            all_ok = mandatory and volume_ok and dollar_vol_ok
        elif use_connors:
            connors_ok = (float(row["Close"]) > float(row["sma200"])) and (
                float(row["rsi2"]) < p.get("connors_rsi2_limit", 10)
            )
            all_ok = mandatory and connors_ok and dollar_vol_ok
        else:
            # ADX 필터 및 스위칭 로직
            use_adx = p.get("use_adx_filter", False)
            adx_val = float(row["adx"]) if "adx" in row else 0.0

            if use_adx and adx_val > p.get("adx_threshold", 25):
                mandatory = mandatory and conds["ema"]
                if p["require_macd"]:
                    mandatory = mandatory and conds["macd"]
                optionals = [
                    conds["rsi"],
                    conds["macd"] if not p["require_macd"] else True,
                    conds["bb"],
                    conds["regime"],
                    conds["obv"],
                    conds["stoch"],
                ]
            elif use_adx and adx_val < 20:
                mandatory = mandatory and conds["rsi"]
                if p["require_bb"]:
                    mandatory = mandatory and conds["bb"]
                optionals = [
                    conds["ema"],
                    conds["macd"],
                    conds["bb"] if not p["require_bb"] else True,
                    conds["regime"],
                    conds["obv"],
                    conds["stoch"],
                ]
            else:
                mandatory = mandatory and conds["rsi"] and conds["ema"]
                optionals = [
                    conds["macd"],
                    conds["bb"],
                    conds["regime"],
                    conds["obv"],
                    conds["stoch"],
                ]

            optional_met = sum([bool(cond) for cond in optionals])
            all_ok = mandatory and (optional_met >= p["ensemble_min"]) and dollar_vol_ok

        # 상세 조건 현황 문자열화
        conds_str = {
            "RSI": f"{float(row['rsi']):.0f} ({'✅' if conds['rsi'] else '❌'})",
            "EMA": f"{'✅' if conds['ema'] else '❌'} ({float(row['Close']):.2f} vs {ema:.2f})",
            "Volume": f"{'✅' if conds['volume'] else '❌'} ({float(row['vol_ratio']):.1f}x)",
            "MACD": f"{'✅' if row['macd_hist'] > 0 else '❌'}",
            "BB": f"{'✅' if float(row['bb_pct']) < 0.4 else '❌'} ({float(row['bb_pct']):.2f})",
            "Regime": f"{today_regime} (필터:{'ON' if p['regime_filter'] else 'OFF'})",
            "Market": f"{'✅' if market_ok else '❌'} ({idx_name} 상방)",
            "Dollar_Volume": f"{'✅' if dollar_vol_ok else '❌'} (${float(row['dollar_volume_ma20']) / 1_000_000:.1f}M vs ${min_vol / 1_000_000:.0f}M)",
        }
        if use_williams:
            williams_target = float(row["Open"]) + float(row["prev_range"]) * float(
                row["k_dynamic"]
            ) * p.get("williams_k_multiplier", 1.0)
            conds_str["Williams_Breakout"] = (
                f"{'✅' if float(row['Close']) > williams_target else '❌'} (종가 {float(row['Close']):.2f} vs 타겟 {williams_target:.2f})"
            )
            conds_str["SMA200"] = (
                f"{'✅' if float(row['Close']) > float(row['sma200']) else '❌'} (종가 {float(row['Close']):.2f} vs SMA200 {float(row['sma200']):.2f})"
            )
            conds_str["Williams_Mode"] = "ACTIVE"
        elif use_volume:
            vol_mult = p.get("volume_spike_mult", 2.0)
            vol_period = p.get("volume_breakout_period", 10)
            high_col = f"high_max_{vol_period}"
            volume_spike = float(row["Volume"]) > float(row["volume_ma20"]) * vol_mult
            price_break = float(row["Close"]) > float(row[high_col]) if high_col in row else False
            conds_str["Volume_Spike"] = (
                f"{'✅' if volume_spike else '❌'} ({float(row['Volume']) / 1_000_000:.1f}M vs {float(row['volume_ma20']) / 1_000_000 * vol_mult:.1f}M)"
            )
            conds_str["Price_Break"] = (
                f"{'✅' if price_break else '❌'} (종가 {float(row['Close']):.2f} vs {vol_period}일고가 {float(row[high_col]) if high_col in row else 0.0:.2f})"
            )
            conds_str["SMA200"] = (
                f"{'✅' if float(row['Close']) > float(row['sma200']) else '❌'} (종가 {float(row['Close']):.2f} vs SMA200 {float(row['sma200']):.2f})"
            )
            conds_str["Volume_Mode"] = "ACTIVE"
        elif use_connors:
            conds_str["RSI2"] = (
                f"{float(row['rsi2']):.1f} ({'✅' if float(row['rsi2']) < p.get('connors_rsi2_limit', 10) else '❌'}, limit:{p.get('connors_rsi2_limit', 10)})"
            )
            conds_str["SMA200"] = (
                f"{'✅' if float(row['Close']) > float(row['sma200']) else '❌'} (종가 {float(row['Close']):.2f} vs SMA200 {float(row['sma200']):.2f})"
            )
            conds_str["Connors_Mode"] = "ACTIVE"
        else:
            conds_str["ADX"] = (
                f"{adx_val:.1f} (필터:{'ON' if use_adx else 'OFF'}, 임계치:{p.get('adx_threshold', 25)})"
            )

        if vix_val >= 22.0:
            signal_desc = f"🔴 대기 (VIX 위험: {vix_val:.1f})"
        elif not market_ok:
            signal_desc = f"🔴 대기 ({idx_name} 하락세)"
        elif not dollar_vol_ok:
            signal_desc = (
                f"🔴 대기 (거래대금 부족: ${float(row['dollar_volume_ma20']) / 1_000_000:.1f}M)"
            )
        else:
            signal_desc = "🟢 진입 검토" if all_ok else "🔴 대기"

        today_sigs[ticker] = {
            "signal": signal_desc,
            "action": "buy"
            if all_ok and vix_val < 22.0 and market_ok and dollar_vol_ok
            else "hold",
            "conditions": conds_str,
            "price": round(float(row["Close"]), 2),
            "regime": today_regime,
            "suggested_position_pct": float(p.get("pos_size", 0.10)),
        }
    return normalize_signal_map(today_sigs)
