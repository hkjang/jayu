"""Paper-trading / shadow execution loop (roadmap module ``jayu.ops.paper`` #15, #141, #142).

Before risking capital, signals should run through a loop that behaves like the
live path but books no real orders. This session ties together three otherwise
standalone pieces into one working flow:

* :mod:`jayu.execution` — quote-aware fills (cross the spread; optional partial
  fill) instead of assuming a clean mid-price execution,
* :mod:`jayu.post_trade` — implementation-shortfall analytics on every fill,
* :mod:`jayu.kill_switch` — a circuit breaker consulted *before* each order and
  fed *after* it, so a bad run halts further entries.

It is deterministic and offline: the caller supplies each order's lifecycle
prices (decision / arrival mid / final), as a historical replay or a paper feed
would. The session report exposes execution quality, realised PnL, and the final
kill-switch state — the inputs a live-vs-backtest decay study needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution import OrderSide, QuotedSpreadModel, quote_aware_fill_price
from .kill_switch import KillSwitch
from .post_trade import aggregate_execution_quality, implementation_shortfall


@dataclass(frozen=True)
class OrderIntent:
    ticker: str
    side: OrderSide
    quantity: float
    decision_price: float
    arrival_mid: float
    final_price: float
    atr: float = 0.0
    relative_spread: float | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class OrderApproval:
    status: str = "not_requested"
    approved_by: str | None = None
    approved_at: str | None = None
    live_order_enabled: bool = False
    reason: str = "Paper trading only; live orders are disabled."


@dataclass(frozen=True)
class OrderPlan:
    intents: tuple[OrderIntent, ...]
    generated_at: str | None = None
    mode: str = "paper"
    source: str = "order_plan.json"
    approval: OrderApproval = field(default_factory=OrderApproval)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": "OrderPlan",
            "mode": self.mode,
            "generated_at": self.generated_at,
            "source": self.source,
            "intents": [
                {
                    "model": "OrderIntent",
                    "ticker": intent.ticker,
                    "side": intent.side,
                    "quantity": intent.quantity,
                    "decision_price": intent.decision_price,
                    "arrival_mid": intent.arrival_mid,
                    "final_price": intent.final_price,
                    "atr": intent.atr,
                    "relative_spread": intent.relative_spread,
                    "latency_ms": intent.latency_ms,
                }
                for intent in self.intents
            ],
            "approval": {
                "model": "OrderApproval",
                "status": self.approval.status,
                "approved_by": self.approval.approved_by,
                "approved_at": self.approval.approved_at,
                "live_order_enabled": self.approval.live_order_enabled,
                "reason": self.approval.reason,
            },
        }


@dataclass(frozen=True)
class PaperBroker:
    """Deterministic paper fill engine: cross the spread, optionally partial-fill."""

    spread_model: QuotedSpreadModel = field(default_factory=QuotedSpreadModel)
    fill_ratio: float = 1.0

    def fill(self, intent: OrderIntent) -> tuple[float, float]:
        """Return ``(filled_quantity, fill_price)`` for an order intent."""
        half_spread = self.spread_model.half_spread_rate(
            atr=intent.atr,
            close=intent.arrival_mid,
            relative_spread=intent.relative_spread,
        )
        fill_price = quote_aware_fill_price(intent.side, intent.arrival_mid, half_spread)
        filled = intent.quantity * min(max(self.fill_ratio, 0.0), 1.0)
        return filled, fill_price


def run_paper_session(
    intents: list[OrderIntent],
    *,
    starting_equity: float,
    kill_switch: KillSwitch,
    broker: PaperBroker | None = None,
) -> dict[str, Any]:
    """Run order intents through the kill-switch-gated paper loop.

    Each intent is gated by :meth:`KillSwitch.allow_trading` first; filled via the
    paper broker; marked to ``final_price`` for PnL; then fed back to the kill
    switch (which may trip and block the remainder). Returns a session report.
    """
    broker = broker or PaperBroker()
    records: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    equity = float(starting_equity)
    realized_pnl = 0.0
    blocked = 0

    for intent in intents:
        if not kill_switch.allow_trading():
            blocked += 1
            fills.append(
                {
                    "ticker": intent.ticker,
                    "status": "blocked",
                    "reasons": list(kill_switch.state.reasons),
                }
            )
            continue

        filled_quantity, fill_price = broker.fill(intent)
        accepted = filled_quantity > 0
        kill_switch.record_order(accepted=accepted, latency_ms=intent.latency_ms)
        if not accepted:
            fills.append({"ticker": intent.ticker, "status": "rejected"})
            continue

        sign = 1.0 if intent.side == "buy" else -1.0
        pnl = sign * (intent.final_price - fill_price) * filled_quantity
        equity += pnl
        realized_pnl += pnl
        slippage_bps = (
            abs(fill_price - intent.arrival_mid) / intent.arrival_mid * 10_000.0
            if intent.arrival_mid > 0
            else 0.0
        )
        kill_switch.record_trade(pnl=pnl, equity=equity, slippage_bps=slippage_bps)

        shortfall = implementation_shortfall(
            side=intent.side,
            decision_price=intent.decision_price,
            arrival_price=intent.arrival_mid,
            fill_price=fill_price,
            final_price=intent.final_price,
            target_quantity=intent.quantity,
            filled_quantity=filled_quantity,
        )
        records.append(shortfall)
        fills.append(
            {
                "ticker": intent.ticker,
                "status": "filled",
                "side": intent.side,
                "filled_quantity": round(filled_quantity, 6),
                "fill_price": round(fill_price, 6),
                "pnl": round(pnl, 4),
                "implementation_shortfall_bps": shortfall["implementation_shortfall_bps"],
            }
        )

    return {
        "starting_equity": round(float(starting_equity), 2),
        "ending_equity": round(equity, 2),
        "realized_pnl": round(realized_pnl, 4),
        "orders_submitted": len(intents),
        "orders_filled": len(records),
        "orders_blocked": blocked,
        "execution_quality": aggregate_execution_quality(records),
        "kill_switch": kill_switch.state.to_dict(),
        "fills": fills,
    }
