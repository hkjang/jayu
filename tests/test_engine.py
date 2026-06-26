from jayu.engine import _normalize_signal_regime, _strategy_regime_key


def test_signal_regime_helpers_handle_missing_values():
    assert _normalize_signal_regime(None) == "unknown"
    assert _normalize_signal_regime("") == "unknown"
    assert _normalize_signal_regime(" BULL ") == "bull"

    assert _strategy_regime_key(None) is None
    assert _strategy_regime_key("unknown") is None
    assert _strategy_regime_key("sideways") == "sideways"
