import pytest

from jayu.signal_generation import strategy_is_approved
from jayu.signals import SignalAction, normalize_signal_map, normalize_today_signal


def test_today_signal_action_is_enum_backed():
    signal = normalize_today_signal(
        {
            "signal": "entry",
            "action": "buy",
            "eligible": True,
            "suggested_position_pct": 0.1,
        }
    )

    assert signal["action"] == SignalAction.BUY.value


def test_today_signal_rejects_unknown_action():
    with pytest.raises(ValueError):
        normalize_today_signal({"signal": "entry", "action": "maybe"})


def test_signal_map_defaults_to_hold():
    signals = normalize_signal_map({"SOXL": {"signal": "no data"}})

    assert signals["SOXL"]["action"] == SignalAction.HOLD.value
    assert signals["SOXL"]["eligible"] is False


def test_approved_signal_requires_final_lockbox_when_enabled():
    strategy = {"validation_status": "approved"}

    assert (
        strategy_is_approved(
            strategy,
            require_final_lockbox=False,
            require_selection_bias=False,
        )
        is True
    )
    assert (
        strategy_is_approved(
            strategy,
            require_final_lockbox=True,
            require_selection_bias=False,
        )
        is False
    )

    strategy["final_lockbox"] = {"approved": True}
    assert (
        strategy_is_approved(
            strategy,
            require_final_lockbox=True,
            require_selection_bias=False,
        )
        is True
    )


def test_approved_signal_requires_selection_bias_evidence_when_enabled():
    strategy = {
        "validation_status": "approved",
        "final_lockbox": {"approved": True},
    }

    assert strategy_is_approved(strategy, require_final_lockbox=True) is False

    strategy["selection_bias"] = {"approved": False}
    assert strategy_is_approved(strategy, require_final_lockbox=True) is False

    strategy["selection_bias"] = {"approved": True}
    assert strategy_is_approved(strategy, require_final_lockbox=True) is True
