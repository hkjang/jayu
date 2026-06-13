"""Deterministic signal replay hashing helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .io import atomic_write_json, stable_hash


def signal_hash_payload(
    signals: Mapping[str, Mapping[str, Any]],
    *,
    config_hash: str,
    data_hashes: Mapping[str, str],
    seed: int,
    signal_date: str,
) -> dict[str, Any]:
    return {
        "config_hash": config_hash,
        "data_hashes": dict(sorted(data_hashes.items())),
        "seed": seed,
        "signal_date": signal_date,
        "signals": {ticker: signals[ticker] for ticker in sorted(signals)},
    }


def compute_signal_hash(
    signals: Mapping[str, Mapping[str, Any]],
    *,
    config_hash: str,
    data_hashes: Mapping[str, str],
    seed: int,
    signal_date: str,
) -> str:
    return stable_hash(
        signal_hash_payload(
            signals,
            config_hash=config_hash,
            data_hashes=data_hashes,
            seed=seed,
            signal_date=signal_date,
        )
    )


def write_signal_replay_artifact(
    path: Path,
    signals: Mapping[str, Mapping[str, Any]],
    *,
    config_hash: str,
    data_hashes: Mapping[str, str],
    seed: int,
    signal_date: str,
    replay: bool,
) -> dict[str, Any]:
    payload = signal_hash_payload(
        signals,
        config_hash=config_hash,
        data_hashes=data_hashes,
        seed=seed,
        signal_date=signal_date,
    )
    payload["signal_hash"] = stable_hash(payload)
    payload["replay"] = replay
    atomic_write_json(path, payload)
    return payload
