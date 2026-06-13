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
                    artifacts_json TEXT
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
            }
            for name, sql_type in migrations.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {sql_type}")
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

    def start(self, context: RunContext) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, command, status, started_at, artifact_dir,
                    config_json, data_hashes_json, random_seed, git_revision,
                    config_hash, environment_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
