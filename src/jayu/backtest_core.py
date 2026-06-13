from __future__ import annotations

import numpy as np
import pandas as pd

from .execution import (
    AtrParticipationSlippageModel,
    ExecutionModel,
    FixedRateFeeModel,
)
from .markets import benchmark_for_ticker
from .optimizer import fill_missing_params
from .performance import calc_metrics
from .settings import ResearchSettings, Settings
from .stat_tests import candidate_selection_bias, probabilistic_sharpe_ratio
from .strategy_space import infer_strategy_mode
from .validation import assert_purged_splits, purged_walk_forward_splits

_DEFAULT_SETTINGS = Settings()
INITIAL_CAPITAL = _DEFAULT_SETTINGS.initial_capital
TRANSACTION_FEE = _DEFAULT_SETTINGS.transaction_fee
MAX_POS = 0.30
MIN_TRADES = 5
_ACTIVE_EXECUTION_MODEL = ExecutionModel(
    path_mode="worst_case",
    max_participation_rate=1.0,
    fee_model=FixedRateFeeModel(TRANSACTION_FEE),
    slippage_model=AtrParticipationSlippageModel(floor=_DEFAULT_SETTINGS.slippage),
)
_ACTIVE_RESEARCH: ResearchSettings = _DEFAULT_SETTINGS.research


def configure(
    *,
    initial_capital: float,
    transaction_fee: float,
    max_pos: float,
    min_trades: int,
    execution_model: ExecutionModel,
    research: ResearchSettings,
) -> None:
    global INITIAL_CAPITAL, TRANSACTION_FEE, MAX_POS, MIN_TRADES
    global _ACTIVE_EXECUTION_MODEL, _ACTIVE_RESEARCH
    INITIAL_CAPITAL = initial_capital
    TRANSACTION_FEE = transaction_fee
    MAX_POS = max_pos
    MIN_TRADES = min_trades
    _ACTIVE_EXECUTION_MODEL = execution_model
    _ACTIVE_RESEARCH = research


def kelly_size(win_rate_pct, avg_win_pct, avg_loss_pct, max_size=MAX_POS):
    # 분모 0 방지 및 비정상 거래 통계 처리
    if win_rate_pct <= 0 or win_rate_pct > 100:
        return 0.10

    # 평균 손실이 양수이거나 0에 극도로 수렴하는 경우 방어
    if avg_loss_pct >= -0.01:
        # 손실이 거의 없는 훌륭한 전략이지만, 과투자 방지를 위해 승률 비례 기본값 할당
        return round(min(0.10 + (win_rate_pct / 1000), max_size), 2)

    p = win_rate_pct / 100
    q = 1 - p

    # 안전한 나눗셈 처리
    denominator = abs(avg_loss_pct)
    b = abs(avg_win_pct) / denominator  # 배당비율

    if b <= 0:
        return 0.10

    k = (p * b - q) / b  # Kelly %

    # Half Kelly 기법 적용
    half_k = k * 0.5

    # 극단적인 비중 제약 방어 (10% ~ max_size 범위)
    constrained_k = max(min(half_k, max_size), 0.10)
    return round(constrained_k, 2)


# ── 백테스트 v3 ──────────────────────────────────────────────────
def backtest(
    df,
    p,
    market_trend_dict=None,
    target_regime=None,
    execution_model=None,
    *,
    initial_skip=220,
):
    execution_model = execution_model or _ACTIVE_EXECUTION_MODEL
    p = fill_missing_params(p)
    ema_col = f"ema{p['ema_span']}"
    capital = float(INITIAL_CAPITAL)
    trades, capitals = [], [capital]
    # Internal research folds pass initial_skip=0 because add_indicators()
    # already removed the complete indicator warmup. The default preserves
    # compatibility for callers that relied on the legacy API.
    i = initial_skip

    while i < len(df) - p["hold_days"] - 2:
        row = df.iloc[i]
        close = float(row["Close"])
        ema = float(row[ema_col])
        atr = float(row["atr"]) if row["atr"] > 0 else close * 0.02

        # ── 유동성 가드 검사 ──────────────────────────────────────
        min_vol = p.get("min_dollar_volume", 10_000_000)
        if "dollar_volume_ma20" in row and float(row["dollar_volume_ma20"]) < min_vol:
            i += 1
            continue

        # 시장 지수 모멘텀 필터 적용
        market_ok = True
        if market_trend_dict:
            date_key = df.index[i]
            idx_name = benchmark_for_ticker(str(p.get("ticker", "")))
            if idx_name in market_trend_dict:
                market_ok = market_trend_dict[idx_name].get(date_key, True)

        # ── 앙상블 진입 조건 ──────────────────────────────────────
        conds = {
            "rsi": p["rsi_lo"] <= float(row["rsi"]) <= p["rsi_hi"],
            "ema": close > ema,
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
            williams_ok = (close > williams_target) and (close > float(row["sma200"]))
            if not (mandatory and williams_ok):
                i += 1
                continue
            optionals = []
            optional_met = 0
        elif use_volume:
            vol_mult = p.get("volume_spike_mult", 2.0)
            vol_period = p.get("volume_breakout_period", 10)
            high_col = f"high_max_{vol_period}"
            volume_spike = float(row["Volume"]) > float(row["volume_ma20"]) * vol_mult
            price_break = close > float(row[high_col]) if high_col in row else False
            trend_ok = close > float(row["sma200"])
            volume_ok = volume_spike and price_break and trend_ok
            if not (mandatory and volume_ok):
                i += 1
                continue
            optionals = []
            optional_met = 0
        elif use_connors:
            connors_ok = (close > float(row["sma200"])) and (
                float(row["rsi2"]) < p.get("connors_rsi2_limit", 10)
            )
            if not (mandatory and connors_ok):
                i += 1
                continue
            optionals = []
            optional_met = 0
        else:
            # ADX 필터 작동시 진입성격 스위칭
            use_adx = p.get("use_adx_filter", False)
            adx_val = float(row["adx"]) if "adx" in row else 0.0

            # ADX 국면에 따른 필수 조건 분기
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
                # 기본 모드
                mandatory = mandatory and conds["rsi"] and conds["ema"]
                optionals = [
                    conds["macd"],
                    conds["bb"],
                    conds["regime"],
                    conds["obv"],
                    conds["stoch"],
                ]

            optional_met = sum([bool(cond) for cond in optionals])

            if not mandatory or optional_met < p["ensemble_min"]:
                i += 1
                continue

        entry_raw = float(df.iloc[i + 1]["Open"])
        if entry_raw <= 0:
            i += 1
            continue
        entry_idx = i + 1

        # ── 포지션 비중 결정 (Kelly + Volatility Sizing) ──────────
        confidence_score = optional_met / len(optionals) if optionals else 0.6
        confidence_score = max(0.2, min(confidence_score, 1.0))
        base_pos_size = p["pos_size"] * confidence_score * p.get("kelly_fraction", 0.50)

        if p.get("use_volatility_sizing", False):
            atr_pct = (
                float(row["atr_pct"]) if "atr_pct" in row and row["atr_pct"] > 0 else (atr / close)
            )
            atr_mult_stop = (
                p.get("atr_mult_stop", 2.0)
                if p["use_atr_stop"]
                else (p["stop_pct"] / (atr / close))
            )
            max_risk = p.get("max_risk_per_trade_pct", 0.015)
            risk_adjusted_size = max_risk / (atr_mult_stop * atr_pct)
            actual_pos_size = min(base_pos_size, risk_adjusted_size)
        else:
            actual_pos_size = base_pos_size

        actual_pos_size = max(min(actual_pos_size, MAX_POS), 0.05)

        # ── 변동성 및 시장 충격 슬리피지 적용 ─────────────────────
        dollar_vol_20 = (
            float(row["dollar_volume_ma20"]) if "dollar_volume_ma20" in row else 100_000_000
        )
        actual_pos_size, fill_ratio = execution_model.position_size_cap(
            capital=capital,
            requested_fraction=actual_pos_size,
            average_dollar_volume=dollar_vol_20,
        )
        if actual_pos_size <= 0:
            i += 1
            continue
        dynamic_slippage = execution_model.slippage_rate(
            atr=atr,
            close=close,
            order_notional=capital * actual_pos_size,
            average_dollar_volume=dollar_vol_20,
        )
        # Quote-aware fill: cross half the quoted spread on each side (opt-in;
        # spread_half_rate defaults to 0, so default runs are unchanged). Folded
        # into the effective slippage so the gross→net cost bridge stays additive.
        spread_half = getattr(execution_model, "spread_half_rate", 0.0)
        effective_slippage = dynamic_slippage + spread_half

        entry = entry_raw * (1.0 + effective_slippage)

        # ── 손절/목표 결정 ────────────────────────────────────────
        stop_dist = (atr * p["atr_mult_stop"]) if p["use_atr_stop"] else (entry * p["stop_pct"])
        stop_price = entry - stop_dist

        use_atr_tgt = p.get("use_atr_target", False)
        target_dist = (
            (atr * p.get("atr_mult_target", 2.0)) if use_atr_tgt else (entry * p["target_pct"])
        )
        target_price = entry + target_dist
        trail_floor = stop_price  # 트레일링 시작점

        exit_price, exit_reason = None, "time"
        exit_trigger = "time_limit"
        exit_idx = None
        peak = entry
        worst_lo = entry
        breakeven_activated = False

        for j in range(1, p["hold_days"] + 2):
            idx = i + 1 + j
            if idx >= len(df):
                break
            fut = df.iloc[idx]
            opn = float(fut["Open"])
            hi = float(fut["High"])
            lo = float(fut["Low"])

            worst_lo = min(worst_lo, lo)

            # 본전 손절(Break-Even Stop) 작동 여부 감시
            if p.get("use_breakeven_stop", False) and not breakeven_activated:
                trigger_price = entry + (target_dist * p.get("breakeven_trigger_pct", 0.5))
                if hi >= trigger_price:
                    breakeven_activated = True
                    # 손절선을 수수료를 감안한 보전선으로 상향
                    stop_price = max(stop_price, entry * (1.0 + TRANSACTION_FEE * 2))

            # 트레일링 스톱 업데이트
            if p["trail_stop"] and hi > peak:
                peak = hi
                trail_floor = max(trail_floor, peak * (1 - p["trail_pct"]))

            effective_stop = max(stop_price, trail_floor) if p["trail_stop"] else stop_price

            # OCO 청산 판정: 일봉 내 경로 모드와 갭 체결을 함께 적용
            decision = execution_model.resolve_daily_exit(
                open_price=opn,
                high=hi,
                low=lo,
                close=float(fut["Close"]),
                stop_price=effective_stop,
                target_price=target_price,
            )
            if decision:
                exit_price = decision.price
                exit_trigger = decision.trigger
                exit_idx = idx
                exit_reason = (
                    "breakeven"
                    if breakeven_activated and decision.reason == "stop"
                    else decision.reason
                )
                break

            # 래리 코너스 청산 조건: Close > sma5
            if strategy_mode == "connors_rsi2" and float(fut["Close"]) > float(fut["sma5"]):
                exit_price, exit_reason = float(fut["Close"]), "connors_exit"
                exit_trigger, exit_idx = "strategy_exit", idx
                break

            # 정체 청산 (Timeout Exit): 보유 기간 절반 이상 지났을 때 수익률이 미미하면 조기 탈출
            if j >= max(2, p["hold_days"] // 2):
                current_ret = (float(fut["Close"]) - entry) / entry
                if abs(current_ret) < 0.005:  # ±0.5% 이내 횡보 시
                    exit_price, exit_reason = float(fut["Close"]), "timeout"
                    exit_trigger, exit_idx = "stagnation_timeout", idx
                    break

            # 조기 청산: RSI 과매수 + MACD 하향교차
            if j >= 2:
                fut_rsi = float(fut["rsi"]) if not pd.isna(fut["rsi"]) else 50
                fut_macd = float(fut["macd_hist"]) if not pd.isna(fut["macd_hist"]) else 0
                prev_macd = (
                    float(df.iloc[idx - 1]["macd_hist"])
                    if not pd.isna(df.iloc[idx - 1]["macd_hist"])
                    else 0
                )
                if fut_rsi > 80 and fut_macd < prev_macd:
                    exit_price, exit_reason = float(fut["Close"]), "overbought"
                    exit_trigger, exit_idx = "indicator_exit", idx
                    break

        if exit_price is None:
            fidx = min(i + 1 + p["hold_days"], len(df) - 1)
            exit_price = float(df.iloc[fidx]["Close"])
            exit_idx = fidx

        exit_settled = exit_price * (1.0 - effective_slippage)
        fee_rate = execution_model.fee_model.round_trip_cost_rate(entry, exit_settled)
        gross_ret = (exit_settled - entry) / entry
        ret = gross_ret - fee_rate

        # ── Gross→Net 비용 분해 (정확히 가산됨) ───────────────────
        # raw_ret 은 비용 0 가정의 진짜 시세 수익(체결가 전·후 슬리피지 미반영),
        # 아래 두 비용을 차감하면 net(ret)과 정확히 일치한다.
        #   raw_return_pct - slippage_cost_pct - fee_cost_pct == net_return_pct
        raw_ret = (exit_price - entry_raw) / entry_raw if entry_raw > 0 else 0.0
        slippage_cost = raw_ret - gross_ret
        fee_cost = fee_rate

        capital_before = capital
        pnl = capital * actual_pos_size * ret
        capital += pnl
        capitals.append(capital)

        trade_mae_pct = ((worst_lo - entry) / entry) * 100
        trades.append(
            {
                "trade_id": len(trades) + 1,
                "signal_date": str(df.index[i].date()),
                "entry_date": str(df.index[entry_idx].date()),
                "exit_date": str(df.index[exit_idx].date()),
                "entry_price": round(entry, 6),
                "exit_price": round(exit_settled, 6),
                "gross_return_pct": round(gross_ret * 100, 4),
                "net_return_pct": round(ret * 100, 4),
                "ret": round(ret * 100, 3),
                "raw_return_pct": round(raw_ret * 100, 4),
                "slippage_cost_pct": round(slippage_cost * 100, 4),
                "fee_cost_pct": round(fee_cost * 100, 4),
                "fee_rate_pct": round(fee_rate * 100, 4),
                "slippage_rate_pct": round(dynamic_slippage * 100, 4),
                "spread_half_rate_pct": round(spread_half * 100, 4),
                "position_pct": round(actual_pos_size * 100, 4),
                "capital_before": round(capital_before, 2),
                "capital_after": round(capital, 2),
                "pnl": round(pnl, 2),
                "reason": exit_reason,
                "trigger": exit_trigger,
                "date": str(df.index[i].date()),
                "holding_days": max(1, exit_idx - entry_idx),
                "mae": round(trade_mae_pct, 3),
                "fill_ratio": round(fill_ratio, 4),
            }
        )
        i += p["hold_days"] + 1

    return trades, capital, capitals


# ── 성과 지표 v3 ─────────────────────────────────────────────────
# ── 멀티 윈도우 Walk-Forward 검증 ────────────────────────────────
def oos_statistical_evidence(
    fold_metrics: list[dict],
    *,
    minimum_observations: int | None = None,
) -> dict:
    required = minimum_observations or _ACTIVE_RESEARCH.min_oos_psr_observations
    returns = [
        float(metrics["total_return"]) / 100.0
        for metrics in fold_metrics
        if isinstance(metrics.get("total_return"), (int, float))
    ]
    psr = probabilistic_sharpe_ratio(returns, 0.0) if len(returns) >= required else None
    return {
        "return_observations": len(returns),
        "minimum_observations": required,
        "psr_vs_zero": round(psr, 6) if psr is not None else None,
        "mean_oos_return_pct": round(float(np.mean(returns)) * 100.0, 4) if returns else None,
    }


def oos_fold_returns(validation_metrics: dict) -> list[float]:
    returns: list[float] = []
    for fold in validation_metrics.get("folds", []):
        if not isinstance(fold, dict):
            continue
        metrics = fold.get("validation")
        value = metrics.get("total_return") if isinstance(metrics, dict) else None
        if isinstance(value, (int, float)) and np.isfinite(value):
            returns.append(float(value) / 100.0)
    return returns


def assess_candidate_selection(
    candidate_fold_returns: list[list[float]],
    selected_fold_returns: list[float],
    *,
    evaluated_trials: int,
) -> dict:
    research = _ACTIVE_RESEARCH
    if not research.selection_bias_enabled:
        return {
            "approved": True,
            "reasons": [],
            "evidence": {"enabled": False},
        }
    evidence = candidate_selection_bias(
        candidate_fold_returns,
        selected_fold_returns,
        trials=evaluated_trials,
        minimum_candidates=research.selection_min_candidates,
        pbo_blocks=research.selection_pbo_blocks,
    )
    reasons: list[str] = []
    if not evidence["sufficient_candidates"]:
        reasons.append("insufficient_candidates_for_selection_bias_test")
    if evidence["dsr"] < research.selection_min_dsr:
        reasons.append("deflated_sharpe_ratio_below_threshold")
    if evidence["pbo"] is None:
        reasons.append("missing_probability_of_backtest_overfitting")
    elif evidence["pbo"] > research.selection_max_pbo:
        reasons.append("probability_of_backtest_overfitting_above_threshold")
    return {
        "approved": not reasons,
        "reasons": reasons,
        "thresholds": {
            "min_dsr": research.selection_min_dsr,
            "max_pbo": research.selection_max_pbo,
        },
        "evidence": evidence,
    }


def multi_window_validate(df, p, market_trend_dict=None, target_regime=None):
    """Evaluate non-overlapping OOS folds with purge and embargo gaps."""
    research = _ACTIVE_RESEARCH
    splits = purged_walk_forward_splits(
        len(df),
        train_rows=research.train_months * 21,
        validation_rows=research.validation_months * 21,
        windows=research.walk_forward_windows,
        purge_rows=research.purge_days,
        embargo_rows=research.embargo_days,
    )
    assert_purged_splits(splits)
    if len(splits) < research.min_oos_psr_observations:
        return None, None
    windows = []
    for split in splits:
        df_train = df.iloc[split.train_start : split.train_end]
        df_valid = df.iloc[split.validation_start : split.validation_end]
        tr_t, tr_cap, tr_ch = backtest(
            df_train,
            p,
            market_trend_dict,
            target_regime,
            initial_skip=0,
        )
        tr_m = calc_metrics(
            tr_t,
            tr_cap,
            tr_ch,
            min_trades=2 if target_regime else MIN_TRADES,
            fitness_version=research.fitness_version,
        )
        if tr_m is None:
            continue
        min_wr = 44 if target_regime else 48
        min_pf = 1.0 if target_regime else 1.2
        if tr_m["win_rate"] < min_wr or tr_m["profit_factor"] < min_pf:
            continue
        vl_t, vl_cap, vl_ch = backtest(
            df_valid,
            p,
            market_trend_dict,
            target_regime,
            initial_skip=0,
        )
        vl_m = calc_metrics(
            vl_t,
            vl_cap,
            vl_ch,
            min_trades=1 if target_regime else MIN_TRADES,
            fitness_version=research.fitness_version,
        )
        windows.append((split, tr_m, vl_m))

    completed = [(split, tr, vl) for split, tr, vl in windows if vl]
    if len(completed) != len(splits):
        return None, None
    if len(completed) < research.min_oos_windows:
        return None, None
    positive = [item for item in completed if item[2]["total_return"] > 0]
    pass_rate = len(positive) / len(completed)
    if pass_rate < research.min_oos_pass_rate:
        return None, None

    best_tr = max(completed, key=lambda item: item[1]["fitness"])[1]
    metrics = [item[2] for item in completed]
    statistical_evidence = oos_statistical_evidence(metrics)
    psr = statistical_evidence["psr_vs_zero"]
    if psr is None or psr < research.min_oos_psr:
        return None, None
    average_sharpe = float(np.mean([item["daily_sharpe"] for item in metrics]))
    avg_val = {
        "fitness_version": research.fitness_version,
        "fitness": round(float(np.mean([item["fitness"] for item in metrics])), 3),
        "total_return": round(float(np.mean([item["total_return"] for item in metrics])), 1),
        "annualized_return": round(
            float(np.mean([item["annualized_return"] for item in metrics])),
            2,
        ),
        "win_rate": round(float(np.mean([item["win_rate"] for item in metrics])), 1),
        "daily_sharpe": round(average_sharpe, 2),
        "sharpe": round(average_sharpe, 2),
        "max_drawdown": round(float(max(item["max_drawdown"] for item in metrics)), 2),
        "windows": len(completed),
        "positive_windows": len(positive),
        "pass_rate": round(pass_rate, 3),
        "statistical_evidence": statistical_evidence,
        "purge_days": research.purge_days,
        "embargo_days": research.embargo_days,
        "folds": [
            {**split.to_dict(), "train": train, "validation": validation}
            for split, train, validation in completed
        ],
    }
    return best_tr, avg_val


# ── 메타 학습 가중 샘플링 ────────────────────────────────────────


def assess_validation(train_metrics, validation_metrics):
    reasons = []
    statistical_evidence = None
    if not validation_metrics:
        reasons.append("missing_out_of_sample_metrics")
    else:
        if validation_metrics.get("total_return", 0) <= 0:
            reasons.append("non_positive_out_of_sample_return")
        if validation_metrics.get("windows", 0) < _ACTIVE_RESEARCH.min_oos_windows:
            reasons.append("insufficient_out_of_sample_windows")
        if validation_metrics.get("pass_rate", 0) < _ACTIVE_RESEARCH.min_oos_pass_rate:
            reasons.append("out_of_sample_pass_rate_below_threshold")
        if not validation_metrics.get("folds"):
            reasons.append("missing_purged_fold_metadata")
        fold_metrics = [
            fold["validation"]
            for fold in validation_metrics.get("folds", [])
            if isinstance(fold, dict) and isinstance(fold.get("validation"), dict)
        ]
        statistical_evidence = validation_metrics.get("statistical_evidence")
        if not isinstance(statistical_evidence, dict):
            statistical_evidence = oos_statistical_evidence(fold_metrics)
        if (
            statistical_evidence.get("return_observations", 0)
            < _ACTIVE_RESEARCH.min_oos_psr_observations
        ):
            reasons.append("insufficient_out_of_sample_observations_for_psr")
        elif (
            statistical_evidence.get("psr_vs_zero") is None
            or statistical_evidence["psr_vs_zero"] < _ACTIVE_RESEARCH.min_oos_psr
        ):
            reasons.append("out_of_sample_psr_below_threshold")
        train_return = abs(float(train_metrics.get("total_return", 0)))
        valid_return = abs(float(validation_metrics.get("total_return", 0)))
        if train_return / max(valid_return, 0.1) > 5:
            reasons.append("train_validation_return_ratio_above_5")
    return {
        "approved": not reasons,
        "reasons": reasons,
        "statistical_evidence": statistical_evidence,
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
    }
