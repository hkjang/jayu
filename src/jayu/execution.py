from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


ExitPathMode = Literal["worst_case", "best_case", "open_high_low_close", "intraday"]

OrderSide = Literal["buy", "sell"]


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
    # Half of the quoted spread (fraction) crossed on each fill. 0 disables
    # quote-aware spread crossing, leaving fills driven by slippage alone.
    spread_half_rate: float = 0.0

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


# ── Quote-aware fill realism (roadmap #43–#46) ───────────────────────
# Daily OHLCV backtests implicitly assume you trade at the close/open with a
# flat slippage rate. In reality a marketable order crosses the spread (a buy
# pays the ask, a sell hits the bid), and a resting limit order only fills if
# price actually reaches it — and even then not always, depending on queue
# position. These models make those costs explicit without needing tick data.


@dataclass(frozen=True)
class QuotedSpreadModel:
    """Estimate the half-spread (as a fraction of price) for a marketable fill.

    Prefers an observed ``relative_spread`` when available; otherwise derives one
    from intraday volatility (ATR). The result is floored so a fill never assumes
    a zero spread.
    """

    floor_rate: float = 0.0001
    atr_weight: float = 0.05
    maximum_rate: float = 0.02

    def half_spread_rate(
        self,
        *,
        atr: float = 0.0,
        close: float = 0.0,
        relative_spread: float | None = None,
    ) -> float:
        if relative_spread is not None:
            estimate = relative_spread / 2.0
        else:
            estimate = (atr / close) * self.atr_weight if close > 0 else 0.0
        return min(max(self.floor_rate, estimate), self.maximum_rate)


def quote_aware_fill_price(
    side: OrderSide,
    reference_price: float,
    half_spread_rate: float,
) -> float:
    """Marketable fill price: a buy pays the ask, a sell hits the bid.

    ``reference_price`` is the midpoint; the order crosses half the spread.
    """
    if side == "buy":
        return reference_price * (1.0 + half_spread_rate)
    return reference_price * (1.0 - half_spread_rate)


@dataclass(frozen=True)
class LimitFillModel:
    """Whether — and with what probability — a resting limit order fills in a bar.

    A buy limit needs price to trade down to it (``low <= limit``); a sell limit
    needs price up to it (``high >= limit``). When price merely tags the level the
    fill is uncertain (you may be at the back of the queue); when price gaps
    through or penetrates deeply the fill is near-certain. ``fill_probability``
    turns the bar's penetration depth into that likelihood.
    """

    def fills(
        self,
        *,
        side: OrderSide,
        limit_price: float,
        bar_high: float,
        bar_low: float,
    ) -> bool:
        if side == "buy":
            return bar_low <= limit_price
        return bar_high >= limit_price

    def fill_probability(
        self,
        *,
        side: OrderSide,
        limit_price: float,
        bar_open: float,
        bar_high: float,
        bar_low: float,
    ) -> float:
        if not self.fills(side=side, limit_price=limit_price, bar_high=bar_high, bar_low=bar_low):
            return 0.0
        # A gap straight through the limit at the open fills with certainty.
        if side == "buy" and bar_open <= limit_price:
            return 1.0
        if side == "sell" and bar_open >= limit_price:
            return 1.0
        bar_range = bar_high - bar_low
        if bar_range <= 0:
            return 1.0
        if side == "buy":
            penetration = (limit_price - bar_low) / bar_range
        else:
            penetration = (bar_high - limit_price) / bar_range
        return float(min(max(penetration, 0.0), 1.0))
