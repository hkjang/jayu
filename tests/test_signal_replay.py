from jayu.signal_replay import compute_signal_hash


def test_signal_hash_is_stable_for_identical_inputs():
    signals = {"SOXL": {"signal": "entry", "action": "buy", "eligible": True}}

    left = compute_signal_hash(
        signals,
        config_hash="config-a",
        data_hashes={"SOXL": "data-a"},
        seed=42,
        signal_date="2026-01-02",
    )
    right = compute_signal_hash(
        {"SOXL": {"eligible": True, "action": "buy", "signal": "entry"}},
        config_hash="config-a",
        data_hashes={"SOXL": "data-a"},
        seed=42,
        signal_date="2026-01-02",
    )

    assert left == right


def test_signal_hash_changes_when_data_or_config_changes():
    signals = {"SOXL": {"signal": "entry", "action": "buy", "eligible": True}}
    base = compute_signal_hash(
        signals,
        config_hash="config-a",
        data_hashes={"SOXL": "data-a"},
        seed=42,
        signal_date="2026-01-02",
    )
    data_changed = compute_signal_hash(
        signals,
        config_hash="config-a",
        data_hashes={"SOXL": "data-b"},
        seed=42,
        signal_date="2026-01-02",
    )
    config_changed = compute_signal_hash(
        signals,
        config_hash="config-b",
        data_hashes={"SOXL": "data-a"},
        seed=42,
        signal_date="2026-01-02",
    )

    assert base != data_changed
    assert base != config_changed
