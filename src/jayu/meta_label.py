"""Meta-labelling: a second model that filters a primary strategy's entries.

Roadmap module ``jayu.models.meta_label`` (#23). The primary strategy decides
*when/which side* to trade (it generates entry candidates). The meta-model
decides *whether to act* — it learns, from features observed at entry time,
which candidates actually went on to clear the cost-aware profit barrier. Acting
only on high-probability candidates raises precision and trims the false
positives that bleed money after costs.

The training target comes straight from :mod:`jayu.labels` triple-barrier
output: a +1 (profit barrier) is a meta-positive, everything else a
meta-negative. The classifier is a dependency-free numpy logistic regression
(standardised features, full-batch gradient descent, deterministic zero init),
so results are reproducible and unit-testable without scikit-learn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


def build_meta_targets(labels: pd.DataFrame, *, mode: str = "profit") -> pd.Series:
    """Binary meta-target from triple-barrier labels.

    ``mode="profit"`` (default): 1 when the profit barrier was hit (label == 1).
    ``mode="net_positive"``: 1 when the net return was positive — useful when the
    vertical (time) barrier should still count as a win if it ended in profit.
    """
    if mode == "profit":
        target = (labels["label"] == 1).astype(int)
    elif mode == "net_positive":
        target = (labels["net_return"] > 0).astype(int)
    else:
        raise ValueError(f"unknown mode {mode!r}; expected 'profit' or 'net_positive'")
    return target.rename("meta_target")


def return_attribution_weights(net_returns: Sequence[float]) -> np.ndarray:
    """Sample weights proportional to |net return| (normalised to mean 1).

    Trades that mattered more to PnL get more say in the fit, per López de Prado's
    return-attribution weighting. An all-zero input yields uniform weights.
    """
    magnitude = np.abs(np.asarray(net_returns, dtype=float))
    total = magnitude.sum()
    if total <= 0:
        return np.ones(len(magnitude))
    return magnitude / total * len(magnitude)


@dataclass
class MetaLabelModel:
    """Dependency-free logistic-regression meta-classifier.

    Standardises features, then runs full-batch gradient descent from a zero
    init (deterministic). Supports per-sample weights for return attribution.
    """

    learning_rate: float = 0.1
    epochs: int = 500
    l2: float = 0.0
    mean_: np.ndarray | None = field(default=None, repr=False)
    std_: np.ndarray | None = field(default=None, repr=False)
    weights_: np.ndarray | None = field(default=None, repr=False)
    bias_: float = field(default=0.0, repr=False)

    def _standardise(self, features: np.ndarray) -> np.ndarray:
        return (features - self.mean_) / self.std_

    def fit(
        self,
        features: np.ndarray | pd.DataFrame,
        targets: Sequence[float],
        *,
        sample_weight: Sequence[float] | None = None,
    ) -> "MetaLabelModel":
        matrix = np.asarray(
            features.to_numpy() if isinstance(features, pd.DataFrame) else features,
            dtype=float,
        )
        if matrix.ndim != 2:
            raise ValueError("features must be a 2D array (n_samples, n_features)")
        y = np.asarray(targets, dtype=float)
        if matrix.shape[0] != y.shape[0]:
            raise ValueError("features and targets must have the same number of rows")
        weight = (
            np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, dtype=float)
        )
        weight = weight / weight.mean() if weight.mean() > 0 else np.ones(len(y))

        self.mean_ = matrix.mean(axis=0)
        self.std_ = matrix.std(axis=0)
        self.std_[self.std_ == 0] = 1.0
        scaled = self._standardise(matrix)

        n, d = scaled.shape
        self.weights_ = np.zeros(d)
        self.bias_ = 0.0
        for _ in range(self.epochs):
            proba = _sigmoid(scaled @ self.weights_ + self.bias_)
            error = (proba - y) * weight
            grad_w = scaled.T @ error / n + self.l2 * self.weights_
            grad_b = float(error.mean())
            self.weights_ -= self.learning_rate * grad_w
            self.bias_ -= self.learning_rate * grad_b
        return self

    def predict_proba(self, features: np.ndarray | pd.DataFrame) -> np.ndarray:
        if self.weights_ is None:
            raise RuntimeError("model is not fitted")
        matrix = np.asarray(
            features.to_numpy() if isinstance(features, pd.DataFrame) else features,
            dtype=float,
        )
        return _sigmoid(self._standardise(matrix) @ self.weights_ + self.bias_)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))


def meta_label_decisions(proba: Sequence[float], *, threshold: float = 0.5) -> np.ndarray:
    """Boolean take/skip mask: act on candidates with probability >= threshold."""
    return np.asarray(proba, dtype=float) >= threshold


def expected_value_threshold(
    proba: Sequence[float],
    net_returns: Sequence[float],
    *,
    thresholds: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Pick the probability threshold that maximises total net PnL of taken trades.

    Sweeps thresholds; for each, takes candidates with ``proba >= t`` and sums
    their net returns. Higher thresholds trade coverage for selectivity — this
    finds the balance that keeps the most net edge.
    """
    probabilities = np.asarray(proba, dtype=float)
    returns = np.asarray(net_returns, dtype=float)
    if probabilities.size == 0 or probabilities.size != returns.size:
        raise ValueError("proba and net_returns must be non-empty and the same length")
    grid = np.linspace(0.0, 0.95, 20) if thresholds is None else np.asarray(thresholds, dtype=float)

    best = {
        "threshold": 0.0,
        "total_net": float(returns.sum()),
        "trades": int(returns.size),
        "coverage": 1.0,
        "avg_net": float(returns.mean()),
    }
    for t in grid:
        mask = probabilities >= t
        taken = returns[mask]
        total = float(taken.sum())
        if total > best["total_net"] or (taken.size and best["trades"] == 0):
            best = {
                "threshold": round(float(t), 4),
                "total_net": round(total, 6),
                "trades": int(taken.size),
                "coverage": round(float(taken.size) / returns.size, 4),
                "avg_net": round(float(taken.mean()), 6) if taken.size else 0.0,
            }
    best["total_net"] = round(best["total_net"], 6)
    best["avg_net"] = round(best["avg_net"], 6)
    return best


def meta_label_report(
    targets: Sequence[float],
    proba: Sequence[float],
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Precision / recall / coverage of the meta-filter at a given threshold."""
    y = np.asarray(targets, dtype=float)
    decisions = meta_label_decisions(proba, threshold=threshold)
    taken = decisions.sum()
    true_positive = float(np.sum((decisions) & (y == 1)))
    precision = true_positive / taken if taken else 0.0
    positives = float(np.sum(y == 1))
    recall = true_positive / positives if positives else 0.0
    base_rate = float(np.mean(y == 1)) if len(y) else 0.0
    return {
        "threshold": threshold,
        "coverage": round(float(taken) / len(y), 4) if len(y) else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "base_rate": round(base_rate, 4),
        # How much cleaner the taken set is than acting on every candidate.
        "precision_lift": round(precision - base_rate, 4),
    }
