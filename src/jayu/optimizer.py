from __future__ import annotations

import copy
import random

from .strategy_space import (
    active_parameter_space,
    combined_parameter_space,
    infer_strategy_mode,
    load_strategy_spaces,
    normalize_strategy_params,
    validate_params,
)

TOP_K = 15
STRATEGY_SPACES = load_strategy_spaces()
PARAM_SPACE = combined_parameter_space(STRATEGY_SPACES)


def configure(*, top_k: int = 15) -> None:
    global TOP_K
    TOP_K = top_k


def meta_sample(meta, key, choices, default_weight=0.5):
    """?깃났瑜?湲곕컲 媛以묒튂濡??뚮씪誘명꽣 ?좏깮"""
    if key not in meta:
        return random.choice(choices)  # nosec B311
    weights = []
    for c in choices:
        k = str(c)
        if k in meta[key] and meta[key][k]["total"] >= 5:
            w = meta[key][k]["wins"] / meta[key][k]["total"]
        else:
            w = default_weight
        weights.append(max(w, 0.05))
    total = sum(weights)
    probs = [w / total for w in weights]
    return random.choices(choices, weights=probs, k=1)[0]  # nosec B311


# ?? ?좎쟾 ?뚭퀬由ъ쬁 ????????????????????????????????????????????????
def tournament_select(pool, k=3):
    """?좊꼫癒쇳듃 ?좏깮: k媛??꾨낫 以?理쒓퀬 ?좏깮"""
    candidates = random.sample(pool[: min(len(pool), TOP_K)], min(k, len(pool)))  # nosec B311
    return max(candidates, key=lambda x: x.get("fitness", x.get("sharpe", -999)))


# ?? 硫뷀? ?숈뒿 ?낅뜲?댄듃 ????????????????????????????????????????????
def update_meta(meta, params, success, decay=0.98):
    for key, val in params.items():
        if key not in PARAM_SPACE:
            continue
        if key not in meta:
            meta[key] = {}

        # 湲곗〈 ?꾩쟻 ?곗씠??媛먯뇿 (理쒓렐 ?깃났 ?곗씠?곗쓽 ?곷???鍮꾩쨷 ?뺣?)
        for k in meta[key]:
            meta[key][k]["total"] = float(meta[key][k]["total"]) * decay
            meta[key][k]["wins"] = float(meta[key][k]["wins"]) * decay

        k = str(val)
        if k not in meta[key]:
            meta[key][k] = {"wins": 0.0, "total": 0.0}
        meta[key][k]["total"] = float(meta[key][k]["total"]) + 1.0
        if success:
            meta[key][k]["wins"] = float(meta[key][k]["wins"]) + 1.0
    return meta


# ?? ?곗씠??留덉씠洹몃젅?댁뀡 媛?????????????????????????????????????????
DEFAULT_PARAMS = {
    "strategy_mode": "ensemble",
    "rsi_lo": 40,
    "rsi_hi": 70,
    "ema_span": 20,
    "vol_mult": 1.5,
    "gap_min": 0.0,
    "use_atr_stop": False,
    "atr_mult_stop": 2.0,
    "stop_pct": 0.03,
    "target_pct": 0.06,
    "hold_days": 2,
    "trail_stop": False,
    "trail_pct": 0.03,
    "require_macd": False,
    "require_bb": False,
    "regime_filter": False,
    "ensemble_min": 2,
    "use_adx_filter": False,
    "adx_threshold": 25,
    "use_connors_rsi2": False,
    "connors_rsi2_limit": 10,
    "use_breakeven_stop": False,
    "breakeven_trigger_pct": 0.5,
    "kelly_fraction": 0.5,
    "use_williams_breakout": False,
    "williams_k_multiplier": 1.0,
    "use_atr_target": False,
    "atr_mult_target": 2.0,
    "min_dollar_volume": 10_000_000,
    "use_volatility_sizing": False,
    "max_risk_per_trade_pct": 0.015,
    "use_volume_breakout": False,
    "volume_spike_mult": 2.0,
    "volume_breakout_period": 10,
    "pos_size": 0.20,
}


def fill_missing_params(params):
    if not isinstance(params, dict):
        return normalize_strategy_params(copy.deepcopy(DEFAULT_PARAMS))
    inferred_mode = infer_strategy_mode(params)
    merged = copy.deepcopy(DEFAULT_PARAMS)
    merged.update(params)
    if "strategy_mode" not in params:
        merged["strategy_mode"] = inferred_mode
    return normalize_strategy_params(merged)


def _repair_params(params):
    child = fill_missing_params(params)
    child["pos_size"] = 0.20
    if child.get("rsi_lo", 50) >= child.get("rsi_hi", 70):
        child["rsi_hi"] = child["rsi_lo"] + 15
    if (
        not child.get("use_atr_target")
        and not child.get("use_atr_stop")
        and child.get("target_pct", 0.1) <= child.get("stop_pct", 0.03)
    ):
        child["target_pct"] = child["stop_pct"] * 2
    if child.get("use_atr_target") and child.get("use_atr_stop"):
        if child.get("atr_mult_target", 2.0) <= child.get("atr_mult_stop", 2.0):
            child["atr_mult_target"] = child["atr_mult_stop"] * 1.5
    child = normalize_strategy_params(child)
    validate_params(child)
    return child


def sample_params(meta=None, use_meta=True):
    """Sample one strategy mode and only its active parameters."""
    m = meta if (use_meta and meta) else {}

    def choose(key, choices):
        return meta_sample(m, key, choices) if use_meta else random.choice(choices)  # nosec B311

    params = copy.deepcopy(DEFAULT_PARAMS)
    params["strategy_mode"] = choose("strategy_mode", PARAM_SPACE["strategy_mode"])
    switches = (
        "use_atr_stop",
        "use_atr_target",
        "trail_stop",
        "use_breakeven_stop",
        "use_volatility_sizing",
    )
    for switch in switches:
        params[switch] = choose(switch, PARAM_SPACE[switch])
    active = active_parameter_space(params, STRATEGY_SPACES)
    for key, choices in active.items():
        if key != "strategy_mode" and key not in switches:
            params[key] = choose(key, choices)
    return _repair_params(params)


def mutate(params, rate=0.25):
    child = fill_missing_params(params)
    if random.random() < rate:  # nosec B311
        child["strategy_mode"] = random.choice(PARAM_SPACE["strategy_mode"])  # nosec B311
    child = normalize_strategy_params(child)
    for key, choices in active_parameter_space(child, STRATEGY_SPACES).items():
        if key != "strategy_mode" and random.random() < rate:  # nosec B311
            child[key] = random.choice(choices)  # nosec B311
    return _repair_params(child)


def crossover(p1, p2):
    left = fill_missing_params(p1)
    right = fill_missing_params(p2)
    child = copy.deepcopy(DEFAULT_PARAMS)
    child["strategy_mode"] = random.choice(  # nosec B311
        [left["strategy_mode"], right["strategy_mode"]]
    )
    child = normalize_strategy_params(child)
    for key, choices in active_parameter_space(child, STRATEGY_SPACES).items():
        if key == "strategy_mode":
            continue
        source = left if random.random() < 0.5 else right  # nosec B311
        child[key] = source.get(key, random.choice(choices))  # nosec B311
    return _repair_params(child)
