from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_trade_memory_score(
    feature_store: dict[str, Any],
    patterns_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pattern_penalties = _pattern_penalties(patterns_report or {})
    rows = []
    for row in feature_store.get("by_symbol") or []:
        sym = str(row.get("symbol") or "")
        if not sym:
            continue
        round_count = int(row.get("round_count") or 0)
        win_rate = row.get("win_rate_pct")
        pnl = float(row.get("realized_pnl_krw") or 0.0)
        avg_return = row.get("avg_return_pct")
        fee_bps = float(row.get("fee_bps") or 0.0)
        score = 65.0
        if win_rate is not None:
            score += (float(win_rate) - 50.0) * 0.35
        if avg_return is not None:
            score += max(-15.0, min(15.0, float(avg_return) * 0.7))
        score += 8.0 if pnl > 0 else -12.0 if pnl < 0 else 0.0
        score -= min(8.0, fee_bps / 20.0)
        score -= min(25.0, pattern_penalties.get(sym, 0.0))
        if round_count == 0:
            score = min(score, 58.0)
        rows.append(
            {
                "symbol": sym,
                "score": round(max(0.0, min(100.0, score)), 1),
                "grade": _grade(score),
                "decision_bias": _decision_bias(score),
                "round_count": round_count,
                "win_rate_pct": win_rate,
                "avg_return_pct": avg_return,
                "realized_pnl_krw": round(pnl, 2),
                "fee_bps": round(fee_bps, 2),
                "pattern_penalty": round(pattern_penalties.get(sym, 0.0), 1),
            }
        )
    rows = sorted(rows, key=lambda item: item["score"])
    avg_score = sum(item["score"] for item in rows) / len(rows) if rows else None
    return {
        "status": "success" if rows else "not_evaluated",
        "summary": {
            "symbol_count": len(rows),
            "avg_score": round(avg_score, 1) if avg_score is not None else None,
            "weak_symbol_count": sum(1 for item in rows if item["score"] < 50),
            "strong_symbol_count": sum(1 for item in rows if item["score"] >= 80),
        },
        "symbol_scores": rows,
        "source": "toss_order_feature_store.py - trade_memory_score.py",
    }


def _pattern_penalties(patterns_report: dict[str, Any]) -> dict[str, float]:
    penalties: dict[str, float] = defaultdict(float)
    weights = {
        "repeated_loss_symbol": 14.0,
        "quick_loss_reentry": 10.0,
        "averaging_down_loss": 12.0,
        "leveraged_loss": 12.0,
        "early_profit_taking": 5.0,
        "excessive_short_term": 5.0,
    }
    for item in patterns_report.get("patterns") or []:
        sym = str(item.get("symbol") or "")
        code = str(item.get("code") or "")
        penalties[sym] += weights.get(code, 4.0)
    return dict(penalties)


def _grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _decision_bias(score: float) -> str:
    if score >= 80:
        return "history_supports_review"
    if score >= 60:
        return "neutral_review"
    if score >= 45:
        return "needs_size_reduction"
    return "history_blocks_auto"
