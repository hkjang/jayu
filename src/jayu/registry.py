from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import RunContext


class ExperimentRegistry:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    artifact_dir TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    data_hashes_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    failure_code TEXT,
                    random_seed INTEGER,
                    git_revision TEXT,
                    config_hash TEXT,
                    environment_json TEXT,
                    artifacts_json TEXT,
                    run_type TEXT DEFAULT 'production'
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            migrations = {
                "failure_code": "TEXT",
                "random_seed": "INTEGER",
                "git_revision": "TEXT",
                "config_hash": "TEXT",
                "environment_json": "TEXT",
                "artifacts_json": "TEXT",
                "run_type": "TEXT DEFAULT 'production'",
            }
            for name, sql_type in migrations.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {sql_type}")
            
            # Create experiments table
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    run_id TEXT PRIMARY KEY,
                    objective TEXT,
                    hypothesis TEXT,
                    target_tickers TEXT,
                    strategy_name TEXT,
                    result_metrics TEXT,
                    promoted INTEGER DEFAULT 0,
                    promoted_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_data (
                    run_id TEXT NOT NULL,
                    data_key TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    quality_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, data_key),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )

    def start(self, context: RunContext, run_type: str | None = None) -> None:
        if run_type is None:
            mode = getattr(context.settings, "mode", "signal")
            if mode in {"paper", "shadow", "backtest"}:
                run_type = "experiment"
            else:
                run_type = "production"

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, command, status, started_at, artifact_dir,
                    config_json, data_hashes_json, random_seed, git_revision,
                    config_hash, environment_json, run_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context.run_id,
                    context.command,
                    "running",
                    context.started_at.isoformat(),
                    str(context.run_dir),
                    json.dumps(context.settings.public_dict(), ensure_ascii=False),
                    "{}",
                    context.seed,
                    context.git_revision,
                    context.config_hash,
                    json.dumps(context.environment, ensure_ascii=False),
                    run_type,
                ),
            )

    def finish(
        self,
        context: RunContext,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, data_hashes_json = ?,
                    result_json = ?, error = ?, failure_code = ?, artifacts_json = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    datetime.now(UTC).isoformat(),
                    json.dumps(context.data_hashes, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False, default=str) if result else None,
                    error,
                    failure_code,
                    json.dumps(sorted(set(context.artifacts)), ensure_ascii=False),
                    context.run_id,
                ),
            )
            for key, data_hash in context.data_hashes.items():
                connection.execute(
                    """
                    INSERT OR REPLACE INTO run_data (
                        run_id, data_key, data_hash, quality_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        context.run_id,
                        key,
                        data_hash,
                        json.dumps(
                            context.data_reports.get(key, {}),
                            ensure_ascii=False,
                            default=str,
                        ),
                    ),
                )

    def register_experiment(
        self,
        run_id: str,
        objective: str,
        hypothesis: str,
        target_tickers: list[str] | str,
        strategy_name: str,
    ) -> None:
        tickers_str = json.dumps(target_tickers) if isinstance(target_tickers, list) else target_tickers
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO experiments (
                    run_id, objective, hypothesis, target_tickers, strategy_name, promoted
                ) VALUES (?, ?, ?, ?, ?, 0)
                """,
                (run_id, objective, hypothesis, tickers_str, strategy_name),
            )
            connection.execute(
                "UPDATE runs SET run_type = 'experiment' WHERE run_id = ?",
                (run_id,),
            )

    def record_experiment_result(
        self,
        run_id: str,
        result_metrics: dict[str, Any],
        promoted: bool = False,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE experiments
                SET result_metrics = ?, promoted = ?, promoted_at = ?
                WHERE run_id = ?
                """,
                (
                    json.dumps(result_metrics, ensure_ascii=False),
                    1 if promoted else 0,
                    datetime.now(UTC).isoformat() if promoted else None,
                    run_id,
                ),
            )

    def promote_experiment(self, run_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE experiments
                SET promoted = 1, promoted_at = ?
                WHERE run_id = ?
                """,
                (datetime.now(UTC).isoformat(), run_id),
            )

    def get_experiments(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*, e.objective, e.hypothesis, e.target_tickers, e.strategy_name, e.result_metrics, e.promoted, e.promoted_at
                FROM runs r
                JOIN experiments e ON r.run_id = e.run_id
                ORDER BY r.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None
