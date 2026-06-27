from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cli_coverage_map import write_cli_coverage_map
from .dashboard_coverage_map import write_dashboard_coverage_map
from .feature_inventory import write_feature_inventory


def run_release_doctor(project_root: Path, *, write_artifacts: bool = True) -> dict[str, Any]:
    root = project_root.resolve()
    inventory = write_feature_inventory(root) if write_artifacts else None
    dashboard_coverage = write_dashboard_coverage_map(root) if write_artifacts else None
    cli_coverage = write_cli_coverage_map(root) if write_artifacts else None

    checks = [
        _check(
            "feature_inventory",
            bool(inventory and inventory.get("features")),
            "Feature inventory was generated.",
            "Run `jayu inventory build` and inspect state/feature_inventory.json.",
        ),
        _check(
            "feature_status_yaml",
            (root / "configs" / "feature_status.yaml").exists(),
            "Feature status matrix exists.",
            "Create configs/feature_status.yaml with stable/beta/experimental/deprecated states.",
        ),
        _check(
            "dashboard_coverage_map",
            bool(dashboard_coverage and dashboard_coverage.get("features")),
            "Dashboard coverage map was generated.",
            "Run `jayu inventory dashboard-coverage`.",
        ),
        _check(
            "cli_coverage_map",
            bool(cli_coverage and cli_coverage.get("features")),
            "CLI coverage map was generated.",
            "Run `jayu inventory cli-coverage`.",
        ),
        _check(
            "cli_commands_available",
            bool(inventory and inventory.get("summary", {}).get("cli_command_count", 0) > 0),
            "CLI commands were discovered from src/jayu/cli.py.",
            "Check Typer command decorators in src/jayu/cli.py.",
        ),
        _check(
            "dashboard_routes_available",
            bool(inventory and inventory.get("summary", {}).get("dashboard_route_count", 0) > 0),
            "Dashboard API routes were discovered.",
            "Check /api/v1 route declarations in src/jayu/dashboard.py.",
        ),
        _check(
            "smoke_tests_present",
            any((root / "tests").glob("test_*smoke*.py")),
            "Integrated smoke tests are present.",
            "Add tests/test_smoke_integrated.py for release-critical flows.",
            severity="warning",
        ),
        _check(
            "docs_written",
            all(
                (root / path).exists()
                for path in ("docs/FEATURES.md", "docs/DASHBOARD_COVERAGE.md", "docs/CLI_COVERAGE.md")
            ),
            "Feature and coverage docs were written.",
            "Run `jayu release doctor` with write access to docs/.",
        ),
    ]
    failed = [check for check in checks if check["status"] == "failed"]
    warnings = [check for check in checks if check["status"] == "warning"]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "failed" if failed else "warning" if warnings else "success",
        "summary": {
            "passed": sum(1 for check in checks if check["status"] == "passed"),
            "warnings": len(warnings),
            "failed": len(failed),
        },
        "checks": checks,
        "next_actions": [check["next_action"] for check in failed + warnings],
    }
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "release_doctor.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _check(
    key: str,
    passed: bool,
    message: str,
    next_action: str,
    *,
    severity: str = "failed",
) -> dict[str, str]:
    return {
        "key": key,
        "status": "passed" if passed else severity,
        "message": message if passed else f"{message} Missing or incomplete.",
        "next_action": "" if passed else next_action,
    }
