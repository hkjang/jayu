from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .feature_inventory import build_feature_inventory


def build_cli_coverage_map(project_root: Path) -> dict[str, Any]:
    inventory = build_feature_inventory(project_root)
    rows = []
    for feature in inventory["features"]:
        commands = feature.get("cli_commands", [])
        rows.append(
            {
                "feature_id": feature["feature_id"],
                "name": feature["name"],
                "status": feature["status"],
                "module": feature["module"],
                "cli_commands": commands,
                "tests": feature.get("tests", []),
                "coverage": "cli_exposed" if commands else "missing_cli",
            }
        )
    missing = [row for row in rows if not row["cli_commands"] and row["status"] != "deprecated"]
    return {
        "source": "feature_inventory",
        "summary": {
            "feature_count": len(rows),
            "features_with_cli": sum(1 for row in rows if row["cli_commands"]),
            "features_missing_cli": len(missing),
            "cli_command_count": len(inventory.get("cli_commands", [])),
        },
        "features_missing_cli": missing,
        "features": rows,
    }


def write_cli_coverage_map(project_root: Path) -> dict[str, Any]:
    coverage = build_cli_coverage_map(project_root)
    state_dir = project_root / "state"
    docs_dir = project_root / "docs"
    state_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "cli_coverage_map.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (docs_dir / "CLI_COVERAGE.md").write_text(render_cli_coverage_markdown(coverage), encoding="utf-8")
    return coverage


def render_cli_coverage_markdown(coverage: dict[str, Any]) -> str:
    summary = coverage.get("summary", {})
    lines = [
        "# CLI Coverage Map",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Features | {summary.get('feature_count', 0)} |",
        f"| Features with CLI | {summary.get('features_with_cli', 0)} |",
        f"| Features missing CLI | {summary.get('features_missing_cli', 0)} |",
        f"| CLI commands | {summary.get('cli_command_count', 0)} |",
        "",
        "## Matrix",
        "",
        "| Feature | Status | CLI Commands | Tests | Coverage |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in coverage.get("features", []):
        lines.append(
            "| {name} | {status} | {commands} | {tests} | {coverage} |".format(
                name=_md(row.get("name", "")),
                status=_md(row.get("status", "")),
                commands=len(row.get("cli_commands", [])),
                tests=len(row.get("tests", [])),
                coverage=_md(row.get("coverage", "")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
