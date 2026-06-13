"""Real-time trading kill switch / risk guard (roadmap module ``jayu.risk.kill_switch`` #70).

A live trading loop needs a circuit breaker that halts new entries the moment
risk or execution quality degrades — before a bad day becomes a blown account.
This guard accumulates trade and order outcomes and trips (latches off) when any
limit is breached:

* **daily loss** (#84) — cumulative day PnL beyond ``max_daily_loss_pct``.
* **drawdown** (#92) — equity peak-to-trough beyond ``max_drawdown_pct``.
* **consecutive losses** (#87) — a losing streak at/above the cap.
* **slippage** — realised slippage (bps) averaging above budget.
* **reject rate** — too many orders bounced (once enough orders seen).
* **latency** — a quote/exec latency spike beyond ``max_latency_ms``.

Once tripped it stays tripped (latched) until an explicit :meth:`reset`, so a
brief recovery cannot silently re-arm trading. Pure, deterministic, testable —
no clock or network; callers feed it events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KillSwitchConfig:
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    max_consecutive_losses: int = 5
    max_slippage_bps: float = 50.0
    max_reject_rate: float = 0.20
    max_latency_ms: float = 2000.0
    min_orders_for_rates: int = 5

    def __post_init__(self) -> None:
        if self.max_daily_loss_pct <= 0 or self.max_drawdown_pct <= 0:
            raise ValueError("loss/drawdown limits must be positive fractions")
        if self.min_orders_for_rates < 1:
            raise ValueError("min_orders_for_rates must be >= 1")


class KillSwitch:
    """Latching circuit breaker fed by trade and order events."""

    equity: float
    peak_equity: float
    daily_pnl: float
    consecutive_losses: int
    orders: int
    rejects: int
    last_latency_ms: float
    max_latency_ms: float
    _slippage_sum: float
    _slippage_count: int

    def __init__(self, config: KillSwitchConfig, *, starting_equity: float):
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self.config = config
        self.starting_equity = float(starting_equity)
        self._tripped = False
        self._reasons: list[str] = []
        self.reset(starting_equity)

    # ── event intake ────────────────────────────────────────────────
    def record_trade(
        self,
        *,
        pnl: float,
        equity: float,
        slippage_bps: float | None = None,
    ) -> "KillSwitchState":
        self.daily_pnl += float(pnl)
        self.equity = float(equity)
        self.peak_equity = max(self.peak_equity, self.equity)
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        if slippage_bps is not None:
            self._slippage_sum += float(slippage_bps)
            self._slippage_count += 1
        return self.evaluate()

    def record_order(
        self,
        *,
        accepted: bool,
        latency_ms: float | None = None,
    ) -> "KillSwitchState":
        self.orders += 1
        if not accepted:
            self.rejects += 1
        if latency_ms is not None:
            self.last_latency_ms = float(latency_ms)
            self.max_latency_ms = max(self.max_latency_ms, float(latency_ms))
        return self.evaluate()

    # ── evaluation ──────────────────────────────────────────────────
    @property
    def average_slippage_bps(self) -> float:
        return self._slippage_sum / self._slippage_count if self._slippage_count else 0.0

    @property
    def reject_rate(self) -> float:
        return self.rejects / self.orders if self.orders else 0.0

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return self.equity / self.peak_equity - 1.0

    @property
    def daily_loss_pct(self) -> float:
        return self.daily_pnl / self.starting_equity

    def _current_breaches(self) -> list[str]:
        config = self.config
        reasons: list[str] = []
        if self.daily_loss_pct <= -config.max_daily_loss_pct:
            reasons.append("daily_loss_limit")
        if self.drawdown <= -config.max_drawdown_pct:
            reasons.append("max_drawdown")
        if self.consecutive_losses >= config.max_consecutive_losses:
            reasons.append("consecutive_losses")
        if self._slippage_count and self.average_slippage_bps > config.max_slippage_bps:
            reasons.append("slippage_budget")
        if self.orders >= config.min_orders_for_rates and self.reject_rate > config.max_reject_rate:
            reasons.append("reject_rate")
        if self.last_latency_ms > config.max_latency_ms:
            reasons.append("latency_spike")
        return reasons

    def evaluate(self) -> "KillSwitchState":
        breaches = self._current_breaches()
        if breaches:
            self._tripped = True
            for reason in breaches:
                if reason not in self._reasons:
                    self._reasons.append(reason)
        return self.state

    def manual_trip(self, reason: str = "manual") -> "KillSwitchState":
        """Operator-initiated halt (e.g. broker outage, news event)."""
        self._tripped = True
        if reason not in self._reasons:
            self._reasons.append(reason)
        return self.state

    @property
    def tripped(self) -> bool:
        return self._tripped

    def allow_trading(self) -> bool:
        """True only while the switch is armed (not tripped)."""
        return not self._tripped

    @property
    def state(self) -> "KillSwitchState":
        return KillSwitchState(
            tripped=self._tripped,
            reasons=list(self._reasons),
            daily_loss_pct=round(self.daily_loss_pct, 6),
            drawdown=round(self.drawdown, 6),
            consecutive_losses=self.consecutive_losses,
            average_slippage_bps=round(self.average_slippage_bps, 4),
            reject_rate=round(self.reject_rate, 4),
            last_latency_ms=self.last_latency_ms,
        )

    # ── lifecycle ───────────────────────────────────────────────────
    def reset(self, equity: float | None = None) -> None:
        """Re-arm the switch and clear all accumulated state."""
        baseline = float(equity) if equity is not None else self.starting_equity
        self.equity = baseline
        self.peak_equity = baseline
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.orders = 0
        self.rejects = 0
        self._slippage_sum = 0.0
        self._slippage_count = 0
        self.last_latency_ms = 0.0
        self.max_latency_ms = 0.0
        self._tripped = False
        self._reasons = []

    def reset_day(self) -> None:
        """Start a new session: clear the daily PnL while keeping run-level state.

        Drawdown (vs the run peak), reject/slippage stats and the streak persist;
        only the daily loss budget resets. Does not re-arm a tripped switch.
        """
        self.daily_pnl = 0.0


@dataclass(frozen=True)
class KillSwitchState:
    tripped: bool
    reasons: list[str] = field(default_factory=list)
    daily_loss_pct: float = 0.0
    drawdown: float = 0.0
    consecutive_losses: int = 0
    average_slippage_bps: float = 0.0
    reject_rate: float = 0.0
    last_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tripped": self.tripped,
            "reasons": list(self.reasons),
            "daily_loss_pct": self.daily_loss_pct,
            "drawdown": self.drawdown,
            "consecutive_losses": self.consecutive_losses,
            "average_slippage_bps": self.average_slippage_bps,
            "reject_rate": self.reject_rate,
            "last_latency_ms": self.last_latency_ms,
        }
