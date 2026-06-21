from __future__ import annotations

from typing import Any

from .entries import evaluate_entry
from .legacy_adapter import migrate_json_structure
from .markets import benchmark_for_ticker, format_market_notional, vix_filter_applies
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


def round_trip_cost_bps(settings: Settings | None = None) -> float:
    """Actual round-trip trading cost in basis points (both sides, fee + slippage)."""
    settings = settings or Settings()
    return (settings.transaction_fee + settings.slippage) * 2.0 * 10_000.0


def cost_survival_gate(
    data: dict[str, Any] | None,
    round_trip_bps: float,
    *,
    buffer_bps: float = 10.0,
) -> dict[str, Any]:
    """Does the strategy's backtested edge survive the real round-trip cost?

    Reads ``max_survivable_bps`` from the strategy's stored metrics (the
    cost-sensitivity sweep added to :func:`jayu.performance.calc_metrics`). When
    A missing metric is not sufficient evidence for operational approval.
    """
    metrics = data.get("metrics") if isinstance(data, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    max_survivable = metrics.get("max_survivable_bps")
    breakeven = metrics.get("breakeven_round_trip_bps")
    breakeven_value = float(breakeven) if isinstance(breakeven, (int, float)) else None
    required_bps = round_trip_bps + buffer_bps
    if not isinstance(max_survivable, (int, float)):
        return {
            "checked": False,
            "round_trip_bps": round(round_trip_bps, 2),
            "buffer_bps": round(buffer_bps, 2),
            "required_round_trip_bps": round(required_bps, 2),
            "max_survivable_bps": None,
            "breakeven_round_trip_bps": breakeven_value,
            "survives": False,
            "status": "not_evaluated",
        }
    return {
        "checked": True,
        "round_trip_bps": round(round_trip_bps, 2),
        "buffer_bps": round(buffer_bps, 2),
        "required_round_trip_bps": round(required_bps, 2),
        "max_survivable_bps": float(max_survivable),
        "breakeven_round_trip_bps": breakeven_value,
        "survives": float(max_survivable) >= required_bps,
        "status": "approved" if float(max_survivable) >= required_bps else "rejected",
    }


def strategy_is_approved(
    data: dict[str, Any] | None,
    *,
    require_final_lockbox: bool,
    require_selection_bias: bool = True,
) -> bool:
    if not data or data.get("validation_status") != "approved":
        return False
    if require_selection_bias:
        selection_bias = data.get("selection_bias")
        if not isinstance(selection_bias, dict) or selection_bias.get("approved") is not True:
            return False
    if not require_final_lockbox:
        return True
    lockbox = data.get("final_lockbox")
    return isinstance(lockbox, dict) and lockbox.get("approved") is True


def check_today_signals(
    df,
    best_all,
    vix_val=0.0,
    market_trends=None,
    require_approved=False,
    require_final_lockbox=True,
    require_selection_bias=True,
    require_cost_survival=False,
    round_trip_cost_bps_value=None,
    cost_survival_buffer_bps=10.0,
):
    """현재 데이터 기준 진입 조건 충족 여부 (VIX, 시장 지수, 거래대금 필터 포함)"""
    best_all = migrate_json_structure(best_all)
    cost_bps = (
        round_trip_cost_bps_value
        if round_trip_cost_bps_value is not None
        else round_trip_cost_bps()
    )
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
        if require_approved and not strategy_is_approved(
            data,
            require_final_lockbox=require_final_lockbox,
            require_selection_bias=require_selection_bias,
        ):
            data = None

        # 폴백 처리 (오늘 국면 설정이 없으면 다른 국면이라도 사용)
        if not data or "params" not in data:
            for r in ["bull", "bear", "sideways"]:
                if (
                    r in ticker_data
                    and "params" in ticker_data[r]
                    and (
                        not require_approved
                        or strategy_is_approved(
                            ticker_data[r],
                            require_final_lockbox=require_final_lockbox,
                            require_selection_bias=require_selection_bias,
                        )
                    )
                ):
                    data = ticker_data[r]
                    break

        if not data or "params" not in data:
            latest_index = df[ticker].index[-1]
            signal_date = (
                latest_index.date().isoformat() if hasattr(latest_index, "date") else str(latest_index)
            )
            today_sigs[ticker] = {
                "signal": "재검증필요" if require_approved else "설정없음",
                "signal_date": signal_date,
                "action": "hold",
                "eligible": False,
                "regime": today_regime,
                "price": round(float(row["Close"]), 2) if "Close" in row else None,
            }
            continue

        p = fill_missing_params(data["params"])

        # ── 비용 생존 게이트: 백테스트 엣지가 실제 왕복비용을 견디는가 ──
        cost_survival = cost_survival_gate(
            data,
            cost_bps,
            buffer_bps=cost_survival_buffer_bps,
        )
        cost_blocked = require_cost_survival and not cost_survival["survives"]

        # 시장 모멘텀 필터 검사
        market_ok = True
        idx_name = benchmark_for_ticker(ticker)
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
        # ADX state kept only for the condition-status display below.
        use_adx = p.get("use_adx_filter", False)
        adx_val = float(row["adx"]) if "adx" in row else 0.0

        # Entry decision shares jayu.entries.evaluate_entry with the backtester,
        # so the live signal and backtest can no longer drift apart. The
        # liquidity (dollar-volume) guard remains signal-specific.
        entry_decision = evaluate_entry(
            row,
            p,
            close=float(row["Close"]),
            ema=ema,
            strategy_mode=strategy_mode,
            market_ok=market_ok,
        )
        all_ok = entry_decision.entered and dollar_vol_ok

        # 상세 조건 현황 문자열화
        conds_str = {
            "RSI": f"{float(row['rsi']):.0f} ({'✅' if conds['rsi'] else '❌'})",
            "EMA": f"{'✅' if conds['ema'] else '❌'} ({float(row['Close']):.2f} vs {ema:.2f})",
            "Volume": f"{'✅' if conds['volume'] else '❌'} ({float(row['vol_ratio']):.1f}x)",
            "MACD": f"{'✅' if row['macd_hist'] > 0 else '❌'}",
            "BB": f"{'✅' if float(row['bb_pct']) < 0.4 else '❌'} ({float(row['bb_pct']):.2f})",
            "Regime": f"{today_regime} (필터:{'ON' if p['regime_filter'] else 'OFF'})",
            "Market": f"{'✅' if market_ok else '❌'} ({idx_name} 상방)",
            "Notional_Volume": (
                f"{'✅' if dollar_vol_ok else '❌'} "
                f"({format_market_notional(ticker, float(row['dollar_volume_ma20']))} vs "
                f"{format_market_notional(ticker, float(min_vol))})"
            ),
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

        vix_blocked = vix_filter_applies(ticker) and vix_val >= 22.0
        if vix_blocked:
            signal_desc = f"🔴 대기 (VIX 위험: {vix_val:.1f})"
        elif not market_ok:
            signal_desc = f"🔴 대기 ({idx_name} 하락세)"
        elif not dollar_vol_ok:
            signal_desc = (
                "🔴 대기 (거래대금 부족: "
                f"{format_market_notional(ticker, float(row['dollar_volume_ma20']))})"
            )
        elif cost_blocked:
            max_survivable = cost_survival["max_survivable_bps"]
            signal_desc = (
                "🔴 대기 (비용 검증 없음)"
                if max_survivable is None
                else (
                    f"🔴 대기 (비용 미생존: 견딤 {max_survivable:.0f}bp "
                    f"< 승인 {cost_survival['required_round_trip_bps']:.0f}bp)"
                )
            )
        else:
            signal_desc = "🟢 진입 검토" if all_ok else "🔴 대기"

        latest_index = df[ticker].index[-1]
        signal_date = (
            latest_index.date().isoformat() if hasattr(latest_index, "date") else str(latest_index)
        )
        today_sigs[ticker] = {
            "signal": signal_desc,
            "signal_date": signal_date,
            "action": "buy"
            if all_ok and not vix_blocked and market_ok and dollar_vol_ok and not cost_blocked
            else "hold",
            "conditions": conds_str,
            "price": round(float(row["Close"]), 2),
            "dollar_volume_ma20": float(row["dollar_volume_ma20"])
            if "dollar_volume_ma20" in row
            else None,
            "minimum_dollar_volume": float(min_vol),
            "regime": today_regime,
            "suggested_position_pct": float(p.get("pos_size", 0.10)),
            "cost_survival": cost_survival,
        }
    return normalize_signal_map(today_sigs)
