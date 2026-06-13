from __future__ import annotations

import hashlib


def derive_seed(base_seed: int, *parts: object) -> int:
    payload = ":".join([str(base_seed), *(str(part) for part in parts)])
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)


def should_early_stop(
    *,
    evaluated_runs: int,
    no_improvement_runs: int,
    minimum_runs: int,
    patience: int,
) -> bool:
    return evaluated_runs >= minimum_runs and no_improvement_runs >= patience
