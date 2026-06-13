from __future__ import annotations

import importlib.metadata
import platform

# Only fixed git commands are executed without a shell.
import subprocess  # nosec B404
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write_json, stable_hash
from .logging_utils import configure_logging
from .paths import RuntimePaths
from .settings import Settings
from .survivorship import audit_survivorship


def current_git_revision(project_root: Path) -> str | None:
    try:
        return subprocess.run(  # nosec B603, B607
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_is_dirty(project_root: Path) -> bool | None:
    try:
        result = subprocess.run(  # nosec B603, B607
            ["git", "status", "--porcelain"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def environment_snapshot() -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for name in (
        "numpy",
        "pandas",
        "pydantic",
        "requests",
        "typer",
        "yfinance",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "os": platform.system(),
        "packages": packages,
    }


@dataclass
class RunContext:
    run_id: str
    run_dir: Path
    settings: Settings
    paths: RuntimePaths
    command: str
    started_at: datetime
    logger: Any
    seed: int
    git_revision: str | None
    git_dirty: bool | None
    config_hash: str
    environment: dict[str, Any]
    survivorship_audit: dict[str, Any]
    data_reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    data_hashes: dict[str, str] = field(default_factory=dict)
    data_sources: list[dict[str, Any]] = field(default_factory=list)
    provider_disagreements: list[dict[str, Any]] = field(default_factory=list)
    price_trust: dict[str, dict[str, Any]] = field(default_factory=dict)
    reference_audits: dict[str, dict[str, Any]] = field(default_factory=dict)
    event_notes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        paths: RuntimePaths,
        settings: Settings,
        command: str,
        *,
        verbose: bool = False,
    ) -> "RunContext":
        paths.ensure_runtime_dirs()
        ticker_label = "-".join(settings.tickers[:2])
        run_id, run_dir = paths.new_run_dir(
            label=f"{command}_{ticker_label}_seed{settings.random_seed}"
        )
        logger = configure_logging(run_dir / "logs" / "events.jsonl", verbose=verbose)
        public_config = settings.public_dict()
        survivorship = audit_survivorship(settings).to_dict()
        context = cls(
            run_id=run_id,
            run_dir=run_dir,
            settings=settings,
            paths=paths,
            command=command,
            started_at=datetime.now(UTC),
            logger=logger,
            seed=settings.random_seed,
            git_revision=current_git_revision(paths.project_root),
            git_dirty=git_is_dirty(paths.project_root),
            config_hash=stable_hash(public_config),
            environment=environment_snapshot(),
            survivorship_audit=survivorship,
        )
        atomic_write_json(run_dir / "config.json", public_config)
        atomic_write_json(run_dir / "environment.json", context.environment)
        atomic_write_json(run_dir / "survivorship.json", survivorship)
        atomic_write_json(run_dir / "data_sources.json", {"sources": []})
        atomic_write_json(
            run_dir / "provider_disagreement_report.json",
            {"disagreements": []},
        )
        atomic_write_json(
            run_dir / "data_trust.json",
            {"price": {}, "reference": {}, "events": {}},
        )
        context.record_artifact(run_dir / "survivorship.json")
        context.record_artifact(run_dir / "data_sources.json")
        context.record_artifact(run_dir / "provider_disagreement_report.json")
        context.record_artifact(run_dir / "data_trust.json")
        context.write_manifest(status="running")
        return context

    def record_data(
        self,
        key: str,
        *,
        data_hash: str,
        quality_report: dict[str, Any],
    ) -> None:
        self.data_hashes[key] = data_hash
        self.data_reports[key] = quality_report
        atomic_write_json(self.run_dir / "data_quality" / f"{key}.json", quality_report)

    def record_artifact(self, path: Path) -> None:
        self.artifacts.append(str(path.relative_to(self.run_dir)))

    def record_data_source(self, record: dict[str, Any]) -> None:
        self.data_sources.append(record)
        path = self.run_dir / "data_sources.json"
        atomic_write_json(path, {"sources": self.data_sources})
        self.record_artifact(path)

    def record_provider_disagreement(self, report: dict[str, Any]) -> None:
        self.provider_disagreements.append(report)
        path = self.run_dir / "provider_disagreement_report.json"
        atomic_write_json(path, {"disagreements": self.provider_disagreements})
        self.record_artifact(path)

    def record_price_trust(self, ticker: str, report: dict[str, Any]) -> None:
        self.price_trust[ticker.upper()] = report
        self._write_data_trust()

    def _write_data_trust(self) -> None:
        path = self.run_dir / "data_trust.json"
        atomic_write_json(
            path,
            {
                "price": self.price_trust,
                "reference": self.reference_audits,
                "events": self.event_notes,
            },
        )
        self.record_artifact(path)

    def record_reference_audit(self, ticker: str, report: dict[str, Any]) -> None:
        self.reference_audits[ticker.upper()] = report
        self._write_data_trust()

    def record_event_notes(self, ticker: str, notes: list[dict[str, Any]]) -> None:
        self.event_notes[ticker.upper()] = notes
        self._write_data_trust()

    def write_manifest(
        self,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        payload = {
            "run_id": self.run_id,
            "command": self.command,
            "status": status,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat() if status != "running" else None,
            "git_revision": self.git_revision,
            "git_dirty": self.git_dirty,
            "config_hash": self.config_hash,
            "random_seed": self.seed,
            "environment": self.environment,
            "survivorship_audit": self.survivorship_audit,
            "data_reports": self.data_reports,
            "data_sources": self.data_sources,
            "provider_disagreements": self.provider_disagreements,
            "price_trust": self.price_trust,
            "reference_audits": self.reference_audits,
            "event_notes": self.event_notes,
            "artifacts": sorted(set(self.artifacts)),
            "data_hashes": self.data_hashes,
            "result": result,
            "error": error,
            "failure_code": failure_code,
        }
        atomic_write_json(self.run_dir / "manifest.json", payload)
