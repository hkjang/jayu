from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    config_file: Path
    state_dir: Path
    signals_dir: Path
    runs_dir: Path
    cache_dir: Path
    portfolio_file: Path
    portfolio_mapping_file: Path

    @classmethod
    def from_root(
        cls,
        project_root: Path,
        *,
        config_file: Path | None = None,
        state_dir: Path | None = None,
        signals_dir: Path | None = None,
        runs_dir: Path | None = None,
        cache_dir: Path | None = None,
        portfolio_file: Path | None = None,
        portfolio_mapping_file: Path | None = None,
    ) -> "RuntimePaths":
        root = project_root.resolve()

        def resolve(path: Path | None, default: Path) -> Path:
            selected = path or default
            if not selected.is_absolute():
                selected = root / selected
            return selected.resolve()

        return cls(
            project_root=root,
            config_file=resolve(config_file, root / "config.json"),
            state_dir=resolve(state_dir, root / "state"),
            signals_dir=resolve(signals_dir, root / "signals"),
            runs_dir=resolve(runs_dir, root / "runs"),
            cache_dir=resolve(cache_dir, root / "data" / "cache"),
            portfolio_file=resolve(portfolio_file, root / "toss_portfolio.csv"),
            portfolio_mapping_file=resolve(
                portfolio_mapping_file,
                root / "configs" / "portfolio_mapping.json",
            ),
        )

    def ensure_runtime_dirs(self) -> None:
        for path in (self.state_dir, self.signals_dir, self.runs_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)

    def new_run_dir(
        self,
        now: datetime | None = None,
        *,
        label: str | None = None,
    ) -> tuple[str, Path]:
        stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label or "").strip("_")
        run_id = f"{stamp}_{safe_label}" if safe_label else stamp
        candidate = self.runs_dir / run_id
        suffix = 1
        while candidate.exists():
            candidate = self.runs_dir / f"{run_id}_{suffix:02d}"
            suffix += 1
        candidate.mkdir(parents=True)
        return candidate.name, candidate

    @property
    def best_strategy_file(self) -> Path:
        return self.state_dir / "best_strategy.json"

    @property
    def strategy_history_file(self) -> Path:
        return self.state_dir / "strategy_history.json"

    @property
    def gene_pool_file(self) -> Path:
        return self.state_dir / "gene_pool.json"

    @property
    def meta_learning_file(self) -> Path:
        return self.state_dir / "meta_learning.json"

    @property
    def signal_file(self) -> Path:
        return self.signals_dir / "today_signals.json"

    @property
    def signal_status_file(self) -> Path:
        return self.signals_dir / "today_signals.status.json"

    @property
    def operational_lock_file(self) -> Path:
        return self.state_dir / "operational_run.lock"
