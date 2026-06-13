from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _load_snapshots(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            row["_timestamp"] = datetime.fromisoformat(row["timestamp"])
            rows.append(row)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return sorted(rows, key=lambda row: row["_timestamp"])


def _return_from_baseline(current: float, rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    baseline = float(rows[0]["account_value_krw"])
    return (current / baseline) - 1.0 if baseline else 0.0


def compute_risk_status(
    snapshots: list[dict[str, Any]],
    *,
    now: datetime,
    account_value_krw: float,
) -> dict[str, float]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)
    prior_day = [row for row in snapshots if row["_timestamp"] < day_start]
    week = [row for row in snapshots if row["_timestamp"] >= week_start]
    month = [row for row in snapshots if row["_timestamp"] >= month_start]
    day_baseline = prior_day[-1:] or snapshots[-1:]
    monthly_peak = max([float(row["account_value_krw"]) for row in month] + [account_value_krw])
    return {
        "daily_return": _return_from_baseline(account_value_krw, day_baseline),
        "weekly_return": _return_from_baseline(account_value_krw, week),
        "monthly_drawdown": (
            (monthly_peak - account_value_krw) / monthly_peak if monthly_peak else 0.0
        ),
    }


def record_portfolio_snapshot(
    path: Path,
    *,
    account_value_krw: float,
    cash_balance_krw: float,
    now: datetime | None = None,
) -> dict[str, float]:
    current_time = now or datetime.now().astimezone()
    snapshots = _load_snapshots(path)
    status = compute_risk_status(
        snapshots,
        now=current_time,
        account_value_krw=account_value_krw,
    )
    row = {
        "timestamp": current_time.isoformat(),
        "account_value_krw": account_value_krw,
        "cash_balance_krw": cash_balance_krw,
        **status,
    }
    should_append = not snapshots
    if snapshots:
        latest = snapshots[-1]
        should_append = (
            latest["_timestamp"].date() != current_time.date()
            or float(latest["account_value_krw"]) != account_value_krw
            or float(latest.get("cash_balance_krw", 0.0)) != cash_balance_krw
        )
    if should_append:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return status
