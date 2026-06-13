from jayu.genetic import derive_seed, should_early_stop


def test_regime_seed_is_stable_and_scoped():
    assert derive_seed(42, "SOXL", "bull") == derive_seed(42, "SOXL", "bull")
    assert derive_seed(42, "SOXL", "bull") != derive_seed(42, "SOXL", "bear")


def test_early_stop_requires_minimum_runs_and_patience():
    assert not should_early_stop(
        evaluated_runs=99,
        no_improvement_runs=200,
        minimum_runs=100,
        patience=150,
    )
    assert should_early_stop(
        evaluated_runs=100,
        no_improvement_runs=150,
        minimum_runs=100,
        patience=150,
    )
