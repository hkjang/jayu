"""Backtest-overfitting statistics: PSR, DSR, PBO.

Roadmap module ``jayu.validation.stat_tests`` (#104–#106). A high backtest
Sharpe is not evidence of skill once you account for short samples, non-normal
returns, and the number of configurations you tried. These three statistics put
numbers on that doubt:

* **PSR** — Probabilistic Sharpe Ratio: P(true Sharpe > benchmark) given the
  observed Sharpe, sample length, skew and kurtosis (Bailey & López de Prado).
* **DSR** — Deflated Sharpe Ratio: PSR whose benchmark is the Sharpe you'd
  expect from the *best of N* random trials, i.e. corrected for selection bias.
* **PBO** — Probability of Backtest Overfitting via CSCV: how often the
  in-sample best configuration underperforms the median out-of-sample.

Implemented with numpy + math only (no scipy): a normal CDF via ``math.erf`` and
an inverse-normal via Acklam's approximation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import combinations
from typing import Any, Literal

import numpy as np

ArrayLike = Sequence[float] | np.ndarray

_EULER_MASCHERONI = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF via Acklam's algorithm (abs err < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        if p <= 0.0:
            return -math.inf
        return math.inf
    a = [
        -3.969683028665376e1,
        2.209460984245205e2,
        -2.759285104469687e2,
        1.383577518672690e2,
        -3.066479806614716e1,
        2.506628277459239e0,
    ]
    b = [
        -5.447609879822406e1,
        1.615858368580409e2,
        -1.556989798598866e2,
        6.680131188771972e1,
        -1.328068155288572e1,
    ]
    c = [
        -7.784894002430293e-3,
        -3.223964580411365e-1,
        -2.400758277161838e0,
        -2.549732539343734e0,
        4.374664141464968e0,
        2.938163982698783e0,
    ]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0, 3.754408661907416e0]
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


def observed_sharpe(returns: ArrayLike) -> float:
    """Per-observation (non-annualized) Sharpe ratio of a return series."""
    array = np.asarray(returns, dtype=float)
    if array.size < 2:
        return 0.0
    std = float(np.std(array, ddof=1))
    if std == 0.0:
        return 0.0
    return float(np.mean(array)) / std


def probabilistic_sharpe_ratio(
    returns: ArrayLike,
    benchmark_sharpe: float = 0.0,
    *,
    sharpe: float | None = None,
) -> float:
    """P(true Sharpe > ``benchmark_sharpe``) for a per-observation return series.

    Adjusts for sample length and the skew/kurtosis of returns. Returns a
    probability in [0, 1]; 0.5 means the observed Sharpe equals the benchmark.
    """
    array = np.asarray(returns, dtype=float)
    n = array.size
    if n < 3:
        return 0.0
    sr = observed_sharpe(array) if sharpe is None else float(sharpe)
    std = float(np.std(array, ddof=1))
    if std == 0.0:
        mean = float(np.mean(array))
        if mean > 0.0:
            return 1.0
        if mean < 0.0:
            return 0.0
        return 0.5 if benchmark_sharpe == 0.0 else float(benchmark_sharpe < 0.0)
    centered = (array - np.mean(array)) / std
    skew = float(np.mean(centered**3))
    kurt = float(np.mean(centered**4))  # non-excess (normal == 3)
    denominator = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2
    if denominator <= 0.0:
        return 0.0
    statistic = (sr - benchmark_sharpe) * math.sqrt(n - 1) / math.sqrt(denominator)
    return _norm_cdf(statistic)


def expected_max_sharpe(trials: int, sharpe_variance: float) -> float:
    """Expected maximum Sharpe across ``trials`` independent random strategies.

    ``sharpe_variance`` is the variance of the Sharpe estimates across trials.
    """
    if trials < 2 or sharpe_variance <= 0.0:
        return 0.0
    sigma = math.sqrt(sharpe_variance)
    term = (1.0 - _EULER_MASCHERONI) * _norm_ppf(
        1.0 - 1.0 / trials
    ) + _EULER_MASCHERONI * _norm_ppf(1.0 - 1.0 / (trials * math.e))
    return sigma * term


def deflated_sharpe_ratio(
    returns: ArrayLike,
    *,
    trials: int,
    sharpe_variance: float,
) -> dict[str, Any]:
    """Deflated Sharpe Ratio: PSR against the best-of-``trials`` benchmark.

    Returns the DSR probability, the deflated benchmark, and the observed Sharpe.
    A DSR below ~0.95 means the result is not convincing after accounting for the
    number of configurations tried.
    """
    benchmark = expected_max_sharpe(trials, sharpe_variance)
    dsr = probabilistic_sharpe_ratio(returns, benchmark)
    return {
        "dsr": round(dsr, 6),
        "deflated_benchmark_sharpe": round(benchmark, 6),
        "observed_sharpe": round(observed_sharpe(returns), 6),
        "trials": int(trials),
    }


def candidate_selection_bias(
    candidate_fold_returns: Sequence[Sequence[float]],
    selected_fold_returns: Sequence[float],
    *,
    trials: int,
    minimum_candidates: int = 5,
    pbo_blocks: int = 2,
) -> dict[str, Any]:
    """DSR and PBO evidence for a strategy selected from many candidates.

    Candidate rows must contain returns for the same ordered OOS folds. DSR uses
    all attempted trials for the multiple-testing penalty, while PBO compares
    the candidates that produced complete, finite OOS vectors.
    """
    selected = np.asarray(selected_fold_returns, dtype=float)
    valid_candidates = [
        np.asarray(returns, dtype=float)
        for returns in candidate_fold_returns
        if len(returns) == selected.size and np.isfinite(returns).all()
    ]
    candidate_count = len(valid_candidates)
    fold_count = int(selected.size)
    sufficient = (
        candidate_count >= minimum_candidates
        and fold_count >= max(2, pbo_blocks)
        and pbo_blocks % 2 == 0
    )
    candidate_sharpes = [observed_sharpe(returns) for returns in valid_candidates]
    sharpe_variance = (
        float(np.var(candidate_sharpes, ddof=1)) if len(candidate_sharpes) >= 2 else 0.0
    )
    dsr = deflated_sharpe_ratio(
        selected,
        trials=max(int(trials), candidate_count),
        sharpe_variance=sharpe_variance,
    )
    pbo: dict[str, Any] | None = None
    if sufficient:
        matrix = np.column_stack(valid_candidates)
        pbo = probability_of_backtest_overfitting(
            matrix,
            blocks=pbo_blocks,
            metric="mean",
        )
    return {
        "candidate_count": candidate_count,
        "minimum_candidates": minimum_candidates,
        "evaluated_trials": int(trials),
        "fold_count": fold_count,
        "pbo_blocks": pbo_blocks,
        "sufficient_candidates": sufficient,
        "sharpe_variance": round(sharpe_variance, 8),
        **dsr,
        "pbo": pbo["pbo"] if pbo else None,
        "pbo_combinations": pbo["combinations"] if pbo else 0,
        "pbo_mean_logit": pbo["mean_logit"] if pbo else None,
    }


def _block_metric(block: np.ndarray, metric: Literal["sharpe", "mean"]) -> np.ndarray:
    """Per-strategy performance over a block of observations (rows=time, cols=strategy)."""
    if metric == "mean":
        return block.mean(axis=0)
    mean = block.mean(axis=0)
    std = block.std(axis=0, ddof=1) if block.shape[0] > 1 else np.ones(block.shape[1])
    std = np.where(std == 0.0, np.nan, std)
    return np.nan_to_num(mean / std, nan=0.0)


def probability_of_backtest_overfitting(
    performance: np.ndarray | Sequence[Sequence[float]],
    *,
    blocks: int = 10,
    metric: Literal["sharpe", "mean"] = "sharpe",
) -> dict[str, Any]:
    """PBO via Combinatorial Symmetric Cross-Validation (Bailey et al.).

    ``performance`` is a T×N matrix: T time observations of returns for each of N
    candidate strategies. The timeline is cut into ``blocks`` equal slices; for
    every way of splitting them into half train / half test, the in-sample best
    strategy's out-of-sample rank is turned into a logit. PBO is the fraction of
    splits where the in-sample winner lands below the out-of-sample median
    (logit <= 0) — i.e. the selection did not generalize.
    """
    matrix = np.asarray(performance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2:
        raise ValueError("performance must be a T x N matrix with N >= 2 strategies")
    if blocks < 2 or blocks % 2 != 0:
        raise ValueError("blocks must be an even number >= 2")
    n_obs, n_strategies = matrix.shape
    if n_obs < blocks:
        raise ValueError("need at least one observation per block")

    bounds = np.linspace(0, n_obs, blocks + 1, dtype=int)
    block_slices = [slice(bounds[i], bounds[i + 1]) for i in range(blocks)]

    logits: list[float] = []
    overfit = 0
    for train_block_ids in combinations(range(blocks), blocks // 2):
        train_ids = set(train_block_ids)
        train_rows = np.concatenate(
            [
                np.arange(*sl.indices(n_obs))
                for sl in (block_slices[i] for i in range(blocks) if i in train_ids)
            ]
        )
        test_rows = np.concatenate(
            [
                np.arange(*sl.indices(n_obs))
                for sl in (block_slices[i] for i in range(blocks) if i not in train_ids)
            ]
        )
        train_perf = _block_metric(matrix[train_rows], metric)
        test_perf = _block_metric(matrix[test_rows], metric)
        best = int(np.argmax(train_perf))
        # Out-of-sample relative rank of the in-sample winner (1 = worst, N = best).
        order = np.argsort(np.argsort(test_perf)) + 1
        rank = int(order[best])
        omega = rank / (n_strategies + 1)
        omega = min(max(omega, 1e-9), 1.0 - 1e-9)
        logit = math.log(omega / (1.0 - omega))
        logits.append(logit)
        if logit <= 0.0:
            overfit += 1

    combos = len(logits)
    return {
        "pbo": round(overfit / combos, 6) if combos else 0.0,
        "combinations": combos,
        "blocks": blocks,
        "strategies": n_strategies,
        "mean_logit": round(float(np.mean(logits)), 6) if logits else 0.0,
    }
