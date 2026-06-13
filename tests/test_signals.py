import pytest

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
