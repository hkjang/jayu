from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


ExitPathMode = Literal["worst_case", "best_case", "open_high_low_close", "intraday"]


@dataclass(frozen=True)
class ExitDecision:
    price: float
    reason: str
    trigger: str


class FeeModel:
    def round_trip_cost_rate(self, entry_price: float, exit_price: float) -> float:
        raise NotImplementedError


@dataclass(frozen=True)
class FixedRateFeeModel(FeeModel):
    rate_per_side: float

    def round_trip_cost_rate(self, entry_price: float, exit_price: float) -> float:
        return self.rate_per_side * 2


class SlippageModel:
    def rate(
        self,
        *,
        atr: float,
        close: float,
        order_notional: float,
        average_dollar_volume: float,
    ) -> float:
        raise NotImplementedError


@dataclass(frozen=True)
class FixedSlippageModel(SlippageModel):
    rate_value: float = 0.0005

    def rate(
        self,
        *,
        atr: float,
        close: float,
        order_notional: float,
        average_dollar_volume: float,
    ) -> float:
        return self.rate_value


@dataclass(frozen=True)
class AtrParticipationSlippageModel(SlippageModel):
    floor: float = 0.0005
    maximum: float = 0.01
    atr_weight: float = 0.10
    participation_weight: float = 0.15

    def rate(
        self,
        *,
        atr: float,
        close: float,
        order_notional: float,
        average_dollar_volume: float,
    ) -> float:
        atr_component = (atr / close) * self.atr_weight if close > 0 else 0.0
        impact = (
            self.participation_weight * (order_notional / average_dollar_volume)
            if average_dollar_volume > 0
            else self.maximum
        )
        return min(max(self.floor, atr_component) + impact, self.maximum)


@dataclass(frozen=True)
class ExecutionModel:
    path_mode: ExitPathMode = "worst_case"
    max_participation_rate: float = 0.0005
    fee_model: FeeModel = FixedRateFeeModel(0.0015)
    slippage_model: SlippageModel = AtrParticipationSlippageModel()

    def position_size_cap(
        self,
        *,
        capital: float,
        requested_fraction: float,
        average_dollar_volume: float,
    ) -> tuple[float, float]:
        requested_notional = max(0.0, capital * requested_fraction)
        available_notional = max(0.0, average_dollar_volume * self.max_participation_rate)
        filled_notional = min(requested_notional, available_notional)
        actual_fraction = filled_notional / capital if capital > 0 else 0.0
        fill_ratio = filled_notional / requested_notional if requested_notional > 0 else 0.0
        return actual_fraction, fill_ratio

    def slippage_rate(
        self,
        *,
        atr: float,
        close: float,
        order_notional: float,
        average_dollar_volume: float,
    ) -> float:
        return self.slippage_model.rate(
            atr=atr,
            close=close,
            order_notional=order_notional,
            average_dollar_volume=average_dollar_volume,
        )

    def resolve_daily_exit(
        self,
        *,
        open_price: float,
        high: float,
        low: float,
        close: float,
        stop_price: float,
        target_price: float,
    ) -> ExitDecision | None:
        if open_price <= stop_price:
            return ExitDecision(open_price, "stop", "gap_stop")
        if open_price >= target_price:
            return ExitDecision(open_price, "target", "gap_target")

        stop_hit = low <= stop_price
        target_hit = high >= target_price
        if not stop_hit and not target_hit:
            return None
        if stop_hit and not target_hit:
            return ExitDecision(stop_price, "stop", "oco_stop")
        if target_hit and not stop_hit:
            return ExitDecision(target_price, "target", "oco_target")

        if self.path_mode == "best_case":
            return ExitDecision(target_price, "target", "both_best_case")
        if self.path_mode == "open_high_low_close":
            return ExitDecision(target_price, "target", "both_ohlc_path")
        if self.path_mode == "intraday":
            raise ValueError("intraday path mode requires intraday bars")
        return ExitDecision(stop_price, "stop", "both_worst_case")

    def resolve_intraday_exit(
        self,
        bars: pd.DataFrame,
        *,
        stop_price: float,
        target_price: float,
    ) -> ExitDecision | None:
        for _, bar in bars.sort_index().iterrows():
            decision = self.resolve_daily_exit(
                open_price=float(bar["Open"]),
                high=float(bar["High"]),
                low=float(bar["Low"]),
                close=float(bar["Close"]),
                stop_price=stop_price,
                target_price=target_price,
            )
            if decision:
                return decision
        return None
