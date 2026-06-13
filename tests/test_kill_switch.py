from __future__ import annotations

import pytest

from jayu.kill_switch import KillSwitch, KillSwitchConfig


def _switch(**overrides):
    config = KillSwitchConfig(**overrides)
    return KillSwitch(config, starting_equity=1_000_000.0)


def test_starts_armed_and_allows_trading():
    switch = _switch()
    assert switch.allow_trading()
    assert not switch.tripped


def test_config_and_equity_validation():
    with pytest.raises(ValueError):
        KillSwitchConfig(max_daily_loss_pct=0.0)
    with pytest.raises(ValueError):
        KillSwitch(KillSwitchConfig(), starting_equity=0.0)


def test_daily_loss_trips():
    switch = _switch(max_daily_loss_pct=0.03)
    # Lose 4% of starting equity in a day.
    state = switch.record_trade(pnl=-40_000.0, equity=960_000.0)
    assert state.tripped
    assert "daily_loss_limit" in state.reasons
    assert not switch.allow_trading()


def test_drawdown_trips_from_peak():
    switch = _switch(max_drawdown_pct=0.10, max_daily_loss_pct=0.50)
    switch.record_trade(pnl=100_000.0, equity=1_100_000.0)  # new peak
    state = switch.record_trade(pnl=-150_000.0, equity=950_000.0)  # -13.6% from peak
    assert state.tripped
    assert "max_drawdown" in state.reasons


def test_consecutive_losses_trip_and_reset_on_win():
    switch = _switch(max_consecutive_losses=3, max_daily_loss_pct=0.9)
    switch.record_trade(pnl=-1.0, equity=999_999.0)
    switch.record_trade(pnl=5.0, equity=1_000_004.0)  # win resets streak
    assert switch.consecutive_losses == 0
    switch.record_trade(pnl=-1.0, equity=1_000_003.0)
    switch.record_trade(pnl=-1.0, equity=1_000_002.0)
    state = switch.record_trade(pnl=-1.0, equity=1_000_001.0)
    assert state.tripped
    assert "consecutive_losses" in state.reasons


def test_reject_rate_waits_for_minimum_orders():
    switch = _switch(max_reject_rate=0.2, min_orders_for_rates=5)
    # 1 reject out of 1 order = 100% but below the minimum-orders gate.
    switch.record_order(accepted=False)
    assert not switch.tripped
    for _ in range(4):
        switch.record_order(accepted=True)
    # 1/5 = 20% (not strictly above 0.2) -> still armed.
    assert not switch.tripped
    state = switch.record_order(accepted=False)  # 2/6 = 33%
    assert state.tripped
    assert "reject_rate" in state.reasons


def test_slippage_budget_trips_on_average():
    switch = _switch(max_slippage_bps=50.0, max_daily_loss_pct=0.9)
    switch.record_trade(pnl=1.0, equity=1_000_001.0, slippage_bps=40.0)
    state = switch.record_trade(pnl=1.0, equity=1_000_002.0, slippage_bps=80.0)  # avg 60
    assert state.tripped
    assert "slippage_budget" in state.reasons


def test_latency_spike_trips():
    switch = _switch(max_latency_ms=1000.0)
    assert not switch.record_order(accepted=True, latency_ms=500.0).tripped
    state = switch.record_order(accepted=True, latency_ms=1500.0)
    assert state.tripped
    assert "latency_spike" in state.reasons


def test_latch_stays_tripped_until_reset():
    switch = _switch(max_daily_loss_pct=0.03)
    switch.record_trade(pnl=-40_000.0, equity=960_000.0)
    assert switch.tripped
    # Recovering equity does NOT re-arm.
    switch.record_trade(pnl=50_000.0, equity=1_010_000.0)
    assert switch.tripped
    # Explicit reset re-arms.
    switch.reset(equity=1_010_000.0)
    assert switch.allow_trading()
    assert switch.state.reasons == []


def test_manual_trip():
    switch = _switch()
    state = switch.manual_trip("broker_outage")
    assert state.tripped
    assert "broker_outage" in state.reasons


def test_reset_day_clears_daily_loss_only():
    switch = _switch(max_daily_loss_pct=0.50, max_drawdown_pct=0.50)
    switch.record_trade(pnl=-100_000.0, equity=900_000.0)
    assert switch.daily_loss_pct == pytest.approx(-0.1)
    switch.reset_day()
    assert switch.daily_loss_pct == pytest.approx(0.0)
    # Run-level equity/peak retained -> drawdown still reflects the dip.
    assert switch.drawdown < 0.0
