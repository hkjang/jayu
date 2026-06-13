from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

from .costs import breakeven_transaction_cost, cost_sensitivity


FITNESS_VERSION = "v2_daily_equity"


@dataclass(frozen=True)
class FitnessSpec:
    version: str = FITNESS_VERSION
    daily_sharpe_weight: float = 0.50
    daily_sortino_weight: float = 0.30
    calmar_weight: float = 0.20
    annualization_days: int = 252
    downside_mar: float = 0.0
    # Annualized turnover at which the (reported-only) turnover-adjusted fitness
    # is halved. Does NOT affect the canonical ``fitness`` used for selection.
    turnover_halflife: float = 252.0


def equity_curve_from_trades(
    trades: list[dict[str, Any]],
    capital_history: list[float],
) -> pd.DataFrame:
    if not capital_history:
        return pd.DataFrame(columns=["equity", "daily_return"])
    dated_capitals: dict[pd.Timestamp, float] = {}
    for index, trade in enumerate(trades):
        raw_date = trade.get("exit_date") or trade.get("date")
        if not raw_date:
            continue
        date = pd.Timestamp(raw_date).normalize()
        capital = trade.get("capital_after")
        if capital is None and index + 1 < len(capital_history):
            capital = capital_history[index + 1]
        if capital is not None:
            dated_capitals[date] = float(capital)
    if not dated_capitals:
        equity = pd.Series(
            [float(value) for value in capital_history],
            index=pd.RangeIndex(len(capital_history)),
            name="equity",
        )
    else:
        first_date = min(dated_capitals)
        last_date = max(dated_capitals)
        initial_date = first_date - pd.offsets.BDay(1)
        equity = pd.Series(
            {initial_date: float(capital_history[0]), **dated_capitals},
            name="equity",
        ).sort_index()
        daily_index = pd.bdate_range(initial_date, last_date).union(
            pd.DatetimeIndex(dated_capitals)
        )
        equity = equity.reindex(daily_index.sort_values(), method="ffill")
    curve = equity.to_frame()
    curve["daily_return"] = curve["equity"].pct_change().fillna(0.0)
    return curve


def _net_return_pct(trade: dict[str, Any]) -> float:
    """Return a single trade's net return in percent.

    ``ret`` and ``net_return_pct`` are both stored net of fees and slippage;
    prefer them. Fall back to the (after-slippage, before-fee) ``gross_return_pct``
    only when no net field exists.
    """
    for key in ("ret", "net_return_pct"):
        value = trade.get(key)
        if isinstance(value, (int, float)) and np.isfinite(value):
            return float(value)
    value = trade.get("gross_return_pct")
    if isinstance(value, (int, float)) and np.isfinite(value):
        return float(value)
    return 0.0


def cost_bridge(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Decompose aggregate gross (raw) return down to net return, step by step.

    When trades carry the exact additive cost fields emitted by the backtester
    (``raw_return_pct``, ``slippage_cost_pct``, ``fee_cost_pct``,
    ``net_return_pct``) the bridge is exact: gross − slippage − fee == net.
    When those fields are absent (e.g. externally supplied trade logs that only
    record ``ret``) the bridge degrades gracefully to net-only with cost
    components zeroed and ``has_cost_detail=False`` so callers can tell the
    difference between "no cost" and "cost unknown".
    """
    count = len(trades)
    if count == 0:
        return {
            "trades": 0,
            "has_cost_detail": False,
            "cost_detail_trade_count": 0,
            "partial_cost_detail": False,
            "returns_basis": "net",
            "avg_gross_return_pct": 0.0,
            "avg_slippage_cost_pct": 0.0,
            "avg_fee_cost_pct": 0.0,
            "avg_net_return_pct": 0.0,
            "total_gross_return_pct": 0.0,
            "total_slippage_cost_pct": 0.0,
            "total_fee_cost_pct": 0.0,
            "total_net_return_pct": 0.0,
            "cost_drag_pct_of_gross": 0.0,
        }

    net = np.array([_net_return_pct(trade) for trade in trades], dtype=float)
    gross_values: list[float] = []
    slippage_values: list[float] = []
    fee_values: list[float] = []
    detail_flags: list[bool] = []

    def finite_value(value: Any, default: float = 0.0) -> float:
        return float(value) if isinstance(value, (int, float)) and np.isfinite(value) else default

    for index, trade in enumerate(trades):
        raw = trade.get("raw_return_pct")
        pre_fee = trade.get("gross_return_pct")
        fee_cost = trade.get("fee_cost_pct")
        if isinstance(raw, (int, float)) and np.isfinite(raw):
            gross_values.append(float(raw))
            slippage_values.append(finite_value(trade.get("slippage_cost_pct")))
            fee_values.append(finite_value(fee_cost))
            detail_flags.append(True)
        elif isinstance(pre_fee, (int, float)) and np.isfinite(pre_fee):
            gross_values.append(float(pre_fee))
            slippage_values.append(0.0)
            fee_values.append(
                float(fee_cost)
                if isinstance(fee_cost, (int, float)) and np.isfinite(fee_cost)
                else float(pre_fee) - net[index]
            )
            detail_flags.append(True)
        else:
            gross_values.append(float(net[index]))
            slippage_values.append(0.0)
            fee_values.append(0.0)
            detail_flags.append(False)

    gross = np.array(gross_values, dtype=float)
    slippage = np.array(slippage_values, dtype=float)
    fee = np.array(fee_values, dtype=float)
    detail_count = sum(detail_flags)
    has_detail = detail_count == count

    total_gross = float(gross.sum())
    total_net = float(net.sum())
    cost_drag = round((total_gross - total_net) / abs(total_gross) * 100, 2) if total_gross else 0.0
    return {
        "trades": count,
        "has_cost_detail": has_detail,
        "cost_detail_trade_count": detail_count,
        "partial_cost_detail": 0 < detail_count < count,
        "returns_basis": "net",
        "avg_gross_return_pct": round(float(gross.mean()), 4),
        "avg_slippage_cost_pct": round(float(slippage.mean()), 4),
        "avg_fee_cost_pct": round(float(fee.mean()), 4),
        "avg_net_return_pct": round(float(net.mean()), 4),
        "total_gross_return_pct": round(total_gross, 4),
        "total_slippage_cost_pct": round(float(slippage.sum()), 4),
        "total_fee_cost_pct": round(float(fee.sum()), 4),
        "total_net_return_pct": round(total_net, 4),
        "cost_drag_pct_of_gross": cost_drag,
    }


def _clean_metric(value: float, limit: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(max(min(value, limit), -limit))


def _drawdown_details(equity: pd.Series) -> dict[str, Any]:
    if equity.empty:
        return {
            "max_drawdown": 0.0,
            "mdd_peak": None,
            "mdd_trough": None,
            "mdd_recovery": None,
            "mdd_duration_days": 0,
        }
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    trough = drawdown.idxmin()
    peak = equity.loc[:trough].idxmax()
    peak_value = float(equity.loc[peak])
    after_trough = equity.loc[trough:]
    recovered = after_trough[after_trough >= peak_value]
    recovery = recovered.index[0] if not recovered.empty else None

    def label(value: Any) -> str | int | None:
        if value is None:
            return None
        if isinstance(value, pd.Timestamp):
            return value.date().isoformat()
        return int(value)

    if isinstance(peak, pd.Timestamp) and isinstance(trough, pd.Timestamp):
        end = recovery if isinstance(recovery, pd.Timestamp) else equity.index[-1]
        duration = int((end - peak).days)
    else:
        end = recovery if recovery is not None else equity.index[-1]
        duration = int(end) - int(peak)
    return {
        "max_drawdown": round(abs(float(drawdown.min())) * 100, 2),
        "mdd_peak": label(peak),
        "mdd_trough": label(trough),
        "mdd_recovery": label(recovery),
        "mdd_duration_days": max(0, duration),
    }


def calc_metrics(
    trades: list[dict[str, Any]],
    final_capital: float,
    capital_history: list[float],
    min_trades: int = 5,
    *,
    fitness_version: str = FITNESS_VERSION,
) -> dict[str, Any] | None:
    if len(trades) < min_trades:
        return None
    if fitness_version != FITNESS_VERSION:
        raise ValueError(f"unsupported fitness version: {fitness_version}")
    spec = FitnessSpec()
    raw_returns = np.array(
        [float(trade.get("ret", 0.0)) if trade.get("ret") is not None else 0.0 for trade in trades]
    )
    invalid_return_data = not np.isfinite(raw_returns).all()
    returns_pct = np.nan_to_num(
        raw_returns,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    wins = returns_pct[returns_pct > 0]
    losses = returns_pct[returns_pct <= 0]
    win_rate = len(wins) / len(returns_pct) * 100 if len(returns_pct) else 0.0
    avg_win = float(np.mean(wins)) if len(wins) else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) else 0.0
    profit_factor = _clean_metric(
        float(wins.sum() / abs(losses.sum())) if losses.sum() else 9.99,
        9.99,
    )
    rr_ratio = _clean_metric(abs(avg_win / avg_loss) if avg_loss else 0.0, 9.99)
    maes = np.array([float(trade.get("mae", 0.0)) for trade in trades])
    avg_mae = float(np.mean(maes)) if len(maes) else 0.0
    worst_mae = float(np.min(maes)) if len(maes) else 0.0

    curve = equity_curve_from_trades(trades, capital_history)
    daily_returns = curve["daily_return"].to_numpy(dtype=float)
    daily_std = float(np.std(daily_returns))
    daily_sharpe = _clean_metric(
        float(np.mean(daily_returns) / daily_std * sqrt(spec.annualization_days))
        if daily_std > 0
        else 0.0,
        20.0,
    )
    downside = daily_returns[daily_returns < spec.downside_mar]
    downside_std = float(np.std(downside)) if len(downside) else 0.0
    daily_sortino = _clean_metric(
        float(
            (np.mean(daily_returns) - spec.downside_mar)
            / downside_std
            * sqrt(spec.annualization_days)
        )
        if downside_std > 0
        else 0.0,
        30.0,
    )
    trade_returns = returns_pct / 100
    trade_std = float(np.std(trade_returns))
    trade_sharpe = _clean_metric(
        float(np.mean(trade_returns) / trade_std * sqrt(len(trade_returns)))
        if trade_std > 0
        else 0.0,
        20.0,
    )
    if invalid_return_data:
        daily_sharpe = 0.0
        daily_sortino = 0.0
        trade_sharpe = 0.0

    initial_capital = float(capital_history[0]) if capital_history else final_capital
    total_return = (
        (float(final_capital) - initial_capital) / initial_capital * 100 if initial_capital else 0.0
    )
    drawdown = _drawdown_details(curve["equity"])
    elapsed_days = max(21, len(curve) - 1)
    annualized_return = (
        (float(final_capital) / initial_capital) ** (spec.annualization_days / elapsed_days) - 1.0
        if initial_capital > 0 and final_capital > 0
        else 0.0
    )
    max_drawdown_decimal = float(drawdown["max_drawdown"]) / 100
    calmar = _clean_metric(
        annualized_return / max_drawdown_decimal if max_drawdown_decimal > 0 else 0.0,
        50.0,
    )

    base_fitness = (
        max(daily_sharpe, 0.0) * spec.daily_sharpe_weight
        + max(daily_sortino, 0.0) * spec.daily_sortino_weight
        + max(calmar, 0.0) * spec.calmar_weight
    )
    mdd_penalty = max(0.1, 1.0 - float(drawdown["max_drawdown"]) / 10.0)
    mae_penalty = max(0.1, 1.0 - (abs(worst_mae) - 8.0) / 10.0) if worst_mae < -8.0 else 1.0
    fitness = round(base_fitness * mdd_penalty * mae_penalty, 3)

    # ── Turnover: reported metric + a turnover-adjusted fitness (NOT used for
    # selection, so the canonical fitness stays reproducible). More round trips
    # per year => more cost drag and execution/overfit risk => smaller penalty.
    annual_turnover = (
        float(len(returns_pct)) * spec.annualization_days / elapsed_days
        if elapsed_days > 0
        else 0.0
    )
    turnover_penalty = (
        spec.turnover_halflife / (spec.turnover_halflife + annual_turnover)
        if spec.turnover_halflife > 0
        else 1.0
    )
    fitness_turnover_adjusted = round(fitness * turnover_penalty, 3)

    breakeven = breakeven_transaction_cost(trades)
    sensitivity = cost_sensitivity(trades)
    return {
        "fitness_version": fitness_version,
        "returns_basis": "net",
        "cost_bridge": cost_bridge(trades),
        "breakeven_round_trip_bps": breakeven["breakeven_round_trip_bps"],
        "cost_sensitivity": sensitivity,
        "max_survivable_bps": sensitivity.get("max_survivable_bps"),
        "annual_turnover": round(annual_turnover, 1),
        "turnover_penalty": round(turnover_penalty, 3),
        "fitness_turnover_adjusted": fitness_turnover_adjusted,
        "trades": int(len(returns_pct)),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "rr_ratio": round(rr_ratio, 2),
        "sharpe": round(daily_sharpe, 2),
        "daily_sharpe": round(daily_sharpe, 2),
        "trade_sharpe": round(trade_sharpe, 2),
        "sortino": round(daily_sortino, 2),
        "sortino_basis": "daily returns below MAR=0, annualized with 252 sessions",
        "calmar": round(calmar, 2),
        "calmar_basis": "annualized return divided by maximum drawdown",
        "fitness": fitness,
        **drawdown,
        "total_return": round(total_return, 1),
        "annualized_return": round(annualized_return * 100, 2),
        "final_capital": round(float(final_capital), 0),
        "avg_mae": round(avg_mae, 2),
        "worst_mae": round(worst_mae, 2),
        "equity_curve_rows": len(curve),
    }


def equity_curve_records(
    trades: list[dict[str, Any]],
    capital_history: list[float],
) -> list[dict[str, Any]]:
    curve = equity_curve_from_trades(trades, capital_history).reset_index()
    curve.columns = ["date", "equity", "daily_return"]
    curve["date"] = curve["date"].map(
        lambda value: value.date().isoformat() if isinstance(value, pd.Timestamp) else int(value)
    )
    return curve.to_dict(orient="records")
