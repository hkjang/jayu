from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .feature_inventory import build_feature_inventory


def build_dashboard_coverage_map(project_root: Path) -> dict[str, Any]:
    inventory = build_feature_inventory(project_root)
    rows = []
    for feature in inventory["features"]:
        route_count = len(feature.get("dashboard_routes", []))
        section_count = len(feature.get("dashboard_sections", []))
        rows.append(
            {
                "feature_id": feature["feature_id"],
                "name": feature["name"],
                "status": feature["status"],
                "module": feature["module"],
                "dashboard_routes": feature.get("dashboard_routes", []),
                "dashboard_sections": feature.get("dashboard_sections", []),
                "tests": feature.get("tests", []),
                "coverage": _coverage_label(route_count, section_count),
            }
        )
    missing_ui = [row for row in rows if row["dashboard_routes"] and not row["dashboard_sections"]]
    missing_api = [row for row in rows if row["dashboard_sections"] and not row["dashboard_routes"]]
    return {
        "source": "feature_inventory",
        "summary": {
            "feature_count": len(rows),
            "features_with_dashboard_api": sum(1 for row in rows if row["dashboard_routes"]),
            "features_with_dashboard_ui": sum(1 for row in rows if row["dashboard_sections"]),
            "api_without_ui_count": len(missing_ui),
            "ui_without_api_count": len(missing_api),
        },
        "api_without_ui": missing_ui,
        "ui_without_api": missing_api,
        "features": rows,
    }


def write_dashboard_coverage_map(project_root: Path) -> dict[str, Any]:
    coverage = build_dashboard_coverage_map(project_root)
    state_dir = project_root / "state"
    docs_dir = project_root / "docs"
    state_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "dashboard_coverage_map.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (docs_dir / "DASHBOARD_COVERAGE.md").write_text(
        render_dashboard_coverage_markdown(coverage),
        encoding="utf-8",
    )
    return coverage


def render_dashboard_coverage_markdown(coverage: dict[str, Any]) -> str:
    summary = coverage.get("summary", {})
    lines = [
        "# Dashboard Coverage Map",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Features | {summary.get('feature_count', 0)} |",
        f"| Features with dashboard API | {summary.get('features_with_dashboard_api', 0)} |",
        f"| Features with dashboard UI | {summary.get('features_with_dashboard_ui', 0)} |",
        f"| API without UI | {summary.get('api_without_ui_count', 0)} |",
        f"| UI without API | {summary.get('ui_without_api_count', 0)} |",
        "",
        "## Matrix",
        "",
        "| Feature | Status | API Routes | UI Sections | Tests | Coverage |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in coverage.get("features", []):
        lines.append(
            "| {name} | {status} | {routes} | {sections} | {tests} | {coverage} |".format(
                name=_md(row.get("name", "")),
                status=_md(row.get("status", "")),
                routes=len(row.get("dashboard_routes", [])),
                sections=len(row.get("dashboard_sections", [])),
                tests=len(row.get("tests", [])),
                coverage=_md(row.get("coverage", "")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _coverage_label(route_count: int, section_count: int) -> str:
    if route_count and section_count:
        return "api_and_ui"
    if route_count:
        return "api_only"
    if section_count:
        return "ui_only"
    return "not_exposed"


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
