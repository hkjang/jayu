from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jayu.meta_label import (
    MetaLabelModel,
    build_meta_targets,
    expected_value_threshold,
    meta_label_decisions,
    meta_label_report,
    return_attribution_weights,
)


def test_build_meta_targets_from_barrier_labels():
    labels = pd.DataFrame(
        {
            "label": [1, -1, 0, 1],
            "net_return": [0.02, -0.01, 0.005, 0.03],
        }
    )

    profit = build_meta_targets(labels, mode="profit")
    net_positive = build_meta_targets(labels, mode="net_positive")

    assert list(profit) == [1, 0, 0, 1]  # only profit-barrier hits
    assert list(net_positive) == [1, 0, 1, 1]  # vertical with +net counts
    with pytest.raises(ValueError):
        build_meta_targets(labels, mode="bogus")


def test_return_attribution_weights_normalise():
    weights = return_attribution_weights([0.0, 0.01, 0.03])
    assert weights.mean() == pytest.approx(1.0)
    assert weights[2] > weights[1] > weights[0]
    # All-zero -> uniform.
    assert list(return_attribution_weights([0.0, 0.0])) == [1.0, 1.0]


def test_logistic_model_learns_separable_signal():
    rng = np.random.default_rng(0)
    n = 400
    feature = rng.normal(0, 1, n)
    # Target is driven by the feature: high feature -> likely success.
    target = (feature + rng.normal(0, 0.3, n) > 0).astype(int)
    X = feature.reshape(-1, 1)

    model = MetaLabelModel(learning_rate=0.5, epochs=800).fit(X, target)

    # Positive weight: higher feature -> higher probability.
    assert model.weights_[0] > 0
    assert model.predict_proba([[2.0]])[0] > model.predict_proba([[-2.0]])[0]
    assert model.predict_proba([[2.0]])[0] > 0.8


def test_model_requires_fit_before_predict():
    with pytest.raises(RuntimeError):
        MetaLabelModel().predict_proba([[1.0]])


def test_sample_weight_shifts_decision_boundary():
    # Two clusters; weighting the positive cluster heavily raises its influence.
    X = np.array([[-1.0], [-1.0], [1.0], [1.0]])
    y = np.array([0, 0, 1, 1])
    base = MetaLabelModel(epochs=300).fit(X, y)
    weighted = MetaLabelModel(epochs=300).fit(X, y, sample_weight=[1, 1, 5, 5])

    assert weighted.predict_proba([[1.0]])[0] >= base.predict_proba([[1.0]])[0]


def test_meta_label_decisions_threshold():
    mask = meta_label_decisions([0.2, 0.6, 0.9], threshold=0.5)
    assert list(mask) == [False, True, True]


def test_expected_value_threshold_filters_losers():
    # Low-probability candidates carry the losing trades.
    proba = [0.1, 0.2, 0.8, 0.9]
    net = [-0.05, -0.03, 0.04, 0.06]

    best = expected_value_threshold(proba, net, thresholds=[0.0, 0.5, 0.85])

    # Skipping the two losers (raising the threshold) lifts total net PnL.
    assert best["threshold"] >= 0.5
    assert best["total_net"] == pytest.approx(0.10)
    assert best["coverage"] <= 0.5


def test_meta_label_report_precision_lift():
    # Perfect separation: proba>=0.5 exactly selects the winners.
    targets = [0, 0, 1, 1]
    proba = [0.1, 0.2, 0.8, 0.9]

    report = meta_label_report(targets, proba, threshold=0.5)

    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["coverage"] == 0.5
    assert report["base_rate"] == 0.5
    assert report["precision_lift"] == pytest.approx(0.5)
