"""Trade exit resolution (extracted from ``backtest_core`` for testability).

Separates the *exit logic* responsibility (project task #3) from the backtest
loop: walk the bars after entry and decide where the position closes, honouring
(in priority order) the OCO stop/target via the execution model's path mode,
break-even and trailing stops, a strategy-specific exit (Connors), a stagnation
timeout, and an RSI-overbought/MACD reversal. If none trigger within the hold
window, close at the time-barrier close.

Behaviour-preserving — identical to the previous inline loop — and pinned by
``tests/test_golden_backtest.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .execution import ExecutionModel


@dataclass(frozen=True)
class ExitOutcome:
    exit_price: float
    exit_reason: str
    exit_trigger: str
    exit_idx: int
    worst_lo: float


def resolve_trade_exit(
    df: pd.DataFrame,
    *,
    signal_index: int,
    entry: float,
    stop_price: float,
    target_price: float,
    target_dist: float,
    params: Mapping[str, Any],
    execution_model: ExecutionModel,
    strategy_mode: str,
    transaction_fee: float,
) -> ExitOutcome:
    """Resolve where a trade entered at ``signal_index + 1`` exits."""
    i = signal_index
    trail_floor = stop_price  # 트레일링 시작점

    exit_price: float | None = None
    exit_reason = "time"
    exit_trigger = "time_limit"
    exit_idx = -1
    peak = entry
    worst_lo = entry
    breakeven_activated = False

    for j in range(1, params["hold_days"] + 2):
        idx = i + 1 + j
        if idx >= len(df):
            break
        fut = df.iloc[idx]
        opn = float(fut["Open"])
        hi = float(fut["High"])
        lo = float(fut["Low"])

        worst_lo = min(worst_lo, lo)

        # 본전 손절(Break-Even Stop) 작동 여부 감시
        if params.get("use_breakeven_stop", False) and not breakeven_activated:
            trigger_price = entry + (target_dist * params.get("breakeven_trigger_pct", 0.5))
            if hi >= trigger_price:
                breakeven_activated = True
                # 손절선을 수수료를 감안한 보전선으로 상향
                stop_price = max(stop_price, entry * (1.0 + transaction_fee * 2))

        # 트레일링 스톱 업데이트
        if params["trail_stop"] and hi > peak:
            peak = hi
            trail_floor = max(trail_floor, peak * (1 - params["trail_pct"]))

        effective_stop = max(stop_price, trail_floor) if params["trail_stop"] else stop_price

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
        if j >= max(2, params["hold_days"] // 2):
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
        # No trigger fired within the hold window: close at the time barrier.
        fidx = min(i + 1 + params["hold_days"], len(df) - 1)
        exit_price = float(df.iloc[fidx]["Close"])
        exit_idx = fidx

    return ExitOutcome(
        exit_price=float(exit_price),
        exit_reason=exit_reason,
        exit_trigger=exit_trigger,
        exit_idx=exit_idx,
        worst_lo=worst_lo,
    )
