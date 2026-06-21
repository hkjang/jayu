from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json


DEFAULT_WINDOWS = (5, 10, 20)
DEFAULT_LIMIT = 240

SIGNAL_STATE_LABELS = {
    "buy": "매수",
    "blocked_buy": "차단 매수",
    "sell": "매도",
    "hold": "관망",
    "excluded": "제외",
}


def build_signal_stability_report(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
) -> dict[str, Any]:
    reference = now or _latest_snapshot_time(snapshots) or datetime.now(UTC)
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        ticker = str(snapshot.get("ticker") or "").upper()
        occurred_at = _parse_time(snapshot.get("occurred_at"))
        if not ticker or occurred_at is None:
            continue
        by_ticker[ticker].append({**dict(snapshot), "occurred_at": occurred_at.isoformat()})

    items = [
        _stability_item(ticker, rows, reference, windows)
        for ticker, rows in by_ticker.items()
    ]
    items.sort(key=lambda item: (_stability_rank(str(item.get("status"))), str(item["ticker"])))
    unstable_count = sum(item.get("status") == "unstable" for item in items)
    excluded_count = sum(item.get("auto_candidate_excluded") is True for item in items)
    avg_score_values = [
        float(item["signal_stability_score"])
        for item in items
        if item.get("signal_stability_score") is not None
    ]
    return {
        "schema_version": 1,
        "status": "success" if items else "not_evaluated",
        "updated_at": reference.isoformat(),
        "windows": list(windows),
        "summary": {
            "ticker_count": len(items),
            "unstable_count": unstable_count,
            "auto_candidate_excluded_count": excluded_count,
            "average_stability_score": round(sum(avg_score_values) / len(avg_score_values), 2)
            if avg_score_values
            else None,
        },
        "items": items,
        "source": "runs/*/manifest.json · signals_risk.json · signal_stability.py",
    }


def build_signal_stability_from_runs(
    runs_dir: Path,
    *,
    current_signals: Mapping[str, Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    snapshots = _load_run_snapshots(runs_dir, limit=limit)
    if current_signals:
        occurred_at = now or datetime.now(UTC)
        snapshots.extend(
            _snapshots_from_signals(
                current_signals,
                run_id="current",
                occurred_at=occurred_at,
            )
        )
    return build_signal_stability_report(snapshots, now=now, windows=windows)


def write_signal_stability_report(
    runs_dir: Path,
    output_path: Path,
    *,
    now: datetime | None = None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    report = build_signal_stability_from_runs(
        runs_dir,
        now=now,
        windows=windows,
        limit=limit,
    )
    atomic_write_json(output_path, report)
    return report


def _load_run_snapshots(runs_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    if not runs_dir.exists():
        return []
    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    dated = []
    for run_dir in run_dirs:
        manifest = read_json(run_dir / "manifest.json", default={})
        if not isinstance(manifest, Mapping):
            continue
        occurred = _parse_time(manifest.get("finished_at")) or _parse_time(manifest.get("started_at"))
        if occurred is None:
            continue
        dated.append((occurred, run_dir, manifest))
    snapshots: list[dict[str, Any]] = []
    for occurred, run_dir, manifest in sorted(dated, key=lambda item: item[0])[-limit:]:
        signal_path = _first_existing_path(
            run_dir / "signals_risk.json",
            run_dir / "today_signals.json",
            run_dir / "signals.json",
        )
        payload = read_json(signal_path, default={}) if signal_path else {}
        if not isinstance(payload, Mapping):
            continue
        snapshots.extend(
            _snapshots_from_signals(
                payload,
                run_id=str(manifest.get("run_id") or run_dir.name),
                occurred_at=occurred,
            )
        )
    return snapshots


def _snapshots_from_signals(
    signals: Mapping[str, Mapping[str, Any]],
    *,
    run_id: str,
    occurred_at: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker, signal in signals.items():
        if not isinstance(signal, Mapping):
            continue
        state = _signal_state(signal)
        rows.append(
            {
                "ticker": str(signal.get("ticker") or ticker).upper(),
                "run_id": run_id,
                "occurred_at": occurred_at.isoformat(),
                "signal_state": state,
                "signal_state_label": SIGNAL_STATE_LABELS.get(state, state),
                "action": signal.get("action") or signal.get("signal") or "hold",
                "eligible": signal.get("eligible") is True,
                "blocked": _blocked(signal),
            }
        )
    return rows


def _stability_item(
    ticker: str,
    snapshots: Sequence[Mapping[str, Any]],
    reference: datetime,
    windows: Sequence[int],
) -> dict[str, Any]:
    ordered = sorted([dict(item) for item in snapshots], key=lambda item: str(item.get("occurred_at")))
    window_stats = {
        f"{days}d": _window_stats(ordered, reference, days)
        for days in windows
    }
    primary_key = "10d" if "10d" in window_stats else f"{windows[0]}d"
    primary = window_stats.get(primary_key, {})
    score = primary.get("score")
    status, reason = _stability_status(window_stats, primary_key)
    latest = ordered[-1] if ordered else {}
    return {
        "ticker": ticker,
        "status": status,
        "signal_stability_score": score,
        "latest_signal_state": latest.get("signal_state"),
        "latest_signal_label": latest.get("signal_state_label"),
        "latest_run_id": latest.get("run_id"),
        "windows": window_stats,
        "summary": reason,
        "auto_candidate_allowed": status not in {"unstable", "insufficient"},
        "auto_candidate_excluded": status in {"unstable", "insufficient"},
        "exclusion_reason": reason if status in {"unstable", "insufficient"} else None,
        "recent": ordered[-6:],
        "source": "runs/*/manifest.json · signals_risk.json",
    }


def _window_stats(
    snapshots: Sequence[Mapping[str, Any]],
    reference: datetime,
    days: int,
) -> dict[str, Any]:
    cutoff = reference - timedelta(days=days)
    rows = [
        item
        for item in snapshots
        if (_parse_time(item.get("occurred_at")) or reference) >= cutoff
    ]
    transitions = _transition_count(rows)
    denominator = max(len(rows) - 1, 0)
    flip_rate = transitions / denominator if denominator else None
    score = round((1 - flip_rate) * 100, 2) if flip_rate is not None else None
    return {
        "days": days,
        "run_count": len(rows),
        "transition_count": transitions,
        "flip_rate": round(flip_rate, 4) if flip_rate is not None else None,
        "score": score,
        "latest_state": rows[-1].get("signal_state") if rows else None,
        "stable_run_count": _stable_tail_count(rows),
    }


def _transition_count(rows: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    previous: str | None = None
    for row in rows:
        state = str(row.get("signal_state") or "hold")
        if previous is not None and state != previous:
            count += 1
        previous = state
    return count


def _stable_tail_count(rows: Sequence[Mapping[str, Any]]) -> int:
    if not rows:
        return 0
    latest = str(rows[-1].get("signal_state") or "hold")
    count = 0
    for row in reversed(rows):
        if str(row.get("signal_state") or "hold") != latest:
            break
        count += 1
    return count


def _stability_status(
    windows: Mapping[str, Mapping[str, Any]],
    primary_key: str,
) -> tuple[str, str]:
    primary = windows.get(primary_key, {})
    run_count = int(primary.get("run_count") or 0)
    score = primary.get("score")
    five = windows.get("5d", {})
    if run_count < 2:
        return "insufficient", "신호 이력이 부족해 자동매매 후보 보류가 필요합니다."
    if (score is not None and float(score) < 60) or int(five.get("transition_count") or 0) >= 2:
        return "unstable", "최근 신호가 자주 뒤집혀 자동매매 후보에서 제외합니다."
    if (score is not None and float(score) < 80) or int(primary.get("transition_count") or 0) >= 1:
        return "warning", "최근 신호 전환이 있어 주문 전 추가 확인이 필요합니다."
    return "stable", "최근 신호 방향이 안정적으로 유지되었습니다."


def _signal_state(signal: Mapping[str, Any]) -> str:
    action = str(signal.get("action") or signal.get("signal") or "").lower()
    signal_text = str(signal.get("signal") or "")
    if signal.get("excluded") is True or action == "excluded":
        return "excluded"
    buy_like = action in {"buy", "entry", "buy_candidate", "weak_buy"} or "매수" in signal_text
    sell_like = action in {"sell", "exit", "reduce", "sell_candidate", "weak_sell"} or "매도" in signal_text
    if buy_like:
        return "blocked_buy" if _blocked(signal) else "buy"
    if sell_like:
        return "sell"
    return "hold"


def _blocked(signal: Mapping[str, Any]) -> bool:
    risk = signal.get("risk")
    risk_blocked = isinstance(risk, Mapping) and (
        risk.get("blocked") is True
        or str(risk.get("status") or "").lower() in {"blocked", "failed"}
        or bool(risk.get("violation_details"))
    )
    return signal.get("blocked") is True or (
        str(signal.get("action") or "").lower() in {"buy", "entry"}
        and signal.get("eligible") is not True
    ) or risk_blocked


def _latest_snapshot_time(snapshots: Sequence[Mapping[str, Any]]) -> datetime | None:
    times = [
        parsed
        for snapshot in snapshots
        for parsed in [_parse_time(snapshot.get("occurred_at"))]
        if parsed is not None
    ]
    return max(times) if times else None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _stability_rank(status: str) -> int:
    return {
        "unstable": 0,
        "insufficient": 1,
        "warning": 2,
        "stable": 3,
    }.get(status, 99)
