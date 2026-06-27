from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from .feature_inventory import build_feature_inventory


def generate_release_notes(project_root: Path, *, release_date: date | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    day = release_date or date.today()
    changed_files = _git_changed_files(root)
    inventory = build_feature_inventory(root)
    touched_features = _touched_features(changed_files, inventory.get("features", []))
    notes = render_release_notes(
        day=day,
        changed_files=changed_files,
        touched_features=touched_features,
        inventory=inventory,
    )
    out_dir = root / "docs" / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{day.isoformat()}.md"
    out_path.write_text(notes, encoding="utf-8")
    return {
        "status": "success",
        "release_date": day.isoformat(),
        "path": str(out_path),
        "changed_file_count": len(changed_files),
        "touched_features": touched_features,
    }


def render_release_notes(
    *,
    day: date,
    changed_files: list[str],
    touched_features: list[dict[str, str]],
    inventory: dict[str, Any],
) -> str:
    summary = inventory.get("summary", {})
    lines = [
        f"# Release Notes - {day.isoformat()}",
        "",
        "## Feature Inventory Summary",
        "",
        f"- Features: {summary.get('feature_count', 0)}",
        f"- CLI commands: {summary.get('cli_command_count', 0)}",
        f"- Dashboard routes: {summary.get('dashboard_route_count', 0)}",
        f"- Dashboard sections: {summary.get('dashboard_section_count', 0)}",
        "",
        "## Touched Features",
        "",
    ]
    if touched_features:
        for feature in touched_features:
            lines.append(f"- `{feature['feature_id']}` ({feature['status']}): {feature['module']}")
    else:
        lines.append("- No feature-mapped files were detected.")
    lines.extend(["", "## Changed Files", ""])
    if changed_files:
        lines.extend(f"- `{path}`" for path in changed_files)
    else:
        lines.append("- No git changes were detected.")
    lines.extend(
        [
            "",
            "## Verification",
            "",
            "- Run `jayu release doctor` before publishing.",
            "- Run targeted tests for changed modules.",
            "",
        ]
    )
    return "\n".join(lines)


def _git_changed_files(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return sorted(path.strip() for path in result.stdout.splitlines() if path.strip())


def _touched_features(changed_files: list[str], features: list[dict[str, Any]]) -> list[dict[str, str]]:
    touched = []
    for feature in features:
        feature_path = str(feature.get("path", ""))
        if feature_path and feature_path in changed_files:
            touched.append(
                {
                    "feature_id": str(feature.get("feature_id", "")),
                    "status": str(feature.get("status", "")),
                    "module": str(feature.get("module", "")),
                }
            )
    return touched
