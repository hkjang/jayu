from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = {"experimental", "beta", "stable", "deprecated"}


@dataclass
class FeatureRecord:
    feature_id: str
    name: str
    status: str
    module: str
    path: str
    description: str = ""
    cli_commands: list[str] = field(default_factory=list)
    dashboard_routes: list[str] = field(default_factory=list)
    dashboard_sections: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    owner: str = "jayu"
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "name": self.name,
            "status": self.status,
            "module": self.module,
            "path": self.path,
            "description": self.description,
            "cli_commands": sorted(set(self.cli_commands)),
            "dashboard_routes": sorted(set(self.dashboard_routes)),
            "dashboard_sections": sorted(set(self.dashboard_sections)),
            "tests": sorted(set(self.tests)),
            "docs": sorted(set(self.docs)),
            "owner": self.owner,
            "notes": self.notes,
        }


def build_feature_inventory(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    modules = _discover_python_modules(root)
    cli_commands = _discover_cli_commands(root / "src" / "jayu" / "cli.py")
    dashboard_routes = _discover_dashboard_routes(root / "src" / "jayu" / "dashboard.py")
    dashboard_sections = _discover_dashboard_sections(root / "src" / "jayu" / "dashboard_static")
    tests = _discover_tests(root / "tests")
    docs = _discover_docs(root / "docs")
    statuses = load_feature_status(root)

    features: list[FeatureRecord] = []
    for module in modules:
        stem = module["stem"]
        status_meta = statuses.get(stem, statuses.get(module["module"], {}))
        record = FeatureRecord(
            feature_id=stem,
            name=_title_from_id(stem),
            status=_normalize_status(status_meta.get("status") or _infer_status(stem)),
            module=module["module"],
            path=module["path"],
            description=module["description"],
            cli_commands=_related_cli_commands(stem, cli_commands),
            dashboard_routes=_related_dashboard_routes(stem, dashboard_routes),
            dashboard_sections=_related_dashboard_sections(stem, dashboard_sections),
            tests=_related_paths(stem, tests),
            docs=_related_paths(stem, docs),
            owner=status_meta.get("owner", "jayu"),
            notes=status_meta.get("notes", ""),
        )
        features.append(record)

    feature_rows = [feature.as_dict() for feature in sorted(features, key=lambda item: item.feature_id)]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "modules": "src/jayu",
            "cli": "src/jayu/cli.py",
            "dashboard": "src/jayu/dashboard.py",
            "dashboard_static": "src/jayu/dashboard_static",
            "status": "configs/feature_status.yaml",
        },
        "summary": {
            "feature_count": len(feature_rows),
            "cli_command_count": len(cli_commands),
            "dashboard_route_count": len(dashboard_routes),
            "dashboard_section_count": len(dashboard_sections),
            "tested_feature_count": sum(1 for row in feature_rows if row["tests"]),
            "documented_feature_count": sum(1 for row in feature_rows if row["docs"]),
        },
        "status_counts": _count_by_status(feature_rows),
        "cli_commands": cli_commands,
        "dashboard_routes": dashboard_routes,
        "dashboard_sections": dashboard_sections,
        "features": feature_rows,
    }


def write_feature_inventory(project_root: Path) -> dict[str, Any]:
    inventory = build_feature_inventory(project_root)
    state_dir = project_root / "state"
    docs_dir = project_root / "docs"
    state_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "feature_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (docs_dir / "FEATURES.md").write_text(render_feature_inventory_markdown(inventory), encoding="utf-8")
    return inventory


def render_feature_inventory_markdown(inventory: dict[str, Any]) -> str:
    summary = inventory.get("summary", {})
    status_counts = inventory.get("status_counts", {})
    lines = [
        "# Jayu Feature Inventory",
        "",
        f"Generated at: `{inventory.get('generated_at', '-')}`",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Features | {summary.get('feature_count', 0)} |",
        f"| CLI commands | {summary.get('cli_command_count', 0)} |",
        f"| Dashboard routes | {summary.get('dashboard_route_count', 0)} |",
        f"| Dashboard sections | {summary.get('dashboard_section_count', 0)} |",
        f"| Tested features | {summary.get('tested_feature_count', 0)} |",
        f"| Documented features | {summary.get('documented_feature_count', 0)} |",
        "",
        "## Status Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status in ("stable", "beta", "experimental", "deprecated"):
        lines.append(f"| {status} | {status_counts.get(status, 0)} |")
    lines.extend(
        [
            "",
            "## Feature Matrix",
            "",
            "| Feature | Status | Module | CLI | Dashboard API | UI Section | Tests | Docs |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for feature in inventory.get("features", []):
        lines.append(
            "| {name} | {status} | `{module}` | {cli} | {api} | {ui} | {tests} | {docs} |".format(
                name=_md(feature.get("name", "")),
                status=_md(feature.get("status", "")),
                module=_md(feature.get("module", "")),
                cli=len(feature.get("cli_commands", [])),
                api=len(feature.get("dashboard_routes", [])),
                ui=len(feature.get("dashboard_sections", [])),
                tests=len(feature.get("tests", [])),
                docs=len(feature.get("docs", [])),
            )
        )
    lines.append("")
    return "\n".join(lines)


def load_feature_status(project_root: Path) -> dict[str, dict[str, str]]:
    path = project_root / "configs" / "feature_status.yaml"
    if not path.exists():
        return {}
    statuses: dict[str, dict[str, str]] = {}
    section = ""
    current = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw.startswith(" "):
            section = line.rstrip(":")
            current = ""
            continue
        if section != "features":
            continue
        feature_match = re.match(r"^\s{2}([A-Za-z0-9_.-]+):\s*$", line)
        if feature_match:
            current = feature_match.group(1)
            statuses.setdefault(current, {})
            continue
        value_match = re.match(r"^\s{4}([A-Za-z0-9_-]+):\s*(.+?)\s*$", line)
        if current and value_match:
            key, value = value_match.groups()
            statuses[current][key] = value.strip().strip('"').strip("'")
    return statuses


def _discover_python_modules(root: Path) -> list[dict[str, str]]:
    src_dir = root / "src" / "jayu"
    modules: list[dict[str, str]] = []
    for path in sorted(src_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(root).as_posix()
        module = "jayu." + path.relative_to(src_dir).with_suffix("").as_posix().replace("/", ".")
        modules.append(
            {
                "stem": path.stem,
                "module": module,
                "path": rel,
                "description": _module_description(path),
            }
        )
    return modules


def _discover_cli_commands(cli_path: Path) -> list[dict[str, str]]:
    if not cli_path.exists():
        return []
    tree = ast.parse(cli_path.read_text(encoding="utf-8"))
    typer_names = {"app": ""}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _call_name(node.value.func) == "typer.Typer":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        typer_names[target.id] = (
                            "" if target.id == "app" else target.id.removesuffix("_app").replace("_", "-")
                        )
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if _call_name(call.func).endswith(".add_typer") and call.args:
                owner = _call_owner(call.func)
                child = call.args[0]
                if isinstance(child, ast.Name):
                    name = _kw_value(call, "name") or typer_names.get(child.id, child.id)
                    typer_names[child.id] = f"{typer_names.get(owner, '').strip()} {name}".strip()

    commands: list[dict[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not _call_name(decorator.func).endswith(".command"):
                continue
            owner = _call_owner(decorator.func)
            name = _literal_arg(decorator, 0) or node.name.replace("_", "-")
            prefix = typer_names.get(owner, owner if owner != "app" else "")
            command = f"{prefix} {name}".strip()
            commands.append(
                {
                    "command": command,
                    "function": node.name,
                    "path": "src/jayu/cli.py",
                    "typer": owner,
                }
            )
    return sorted(commands, key=lambda item: item["command"])


def _discover_dashboard_routes(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    routes: set[str] = set()
    for pattern in (
        r'parsed\.path\s*==\s*"([^"]+)"',
        r'parsed\.path\.startswith\("([^"]+)"\)',
    ):
        routes.update(re.findall(pattern, text))
    return [{"route": route, "path": "src/jayu/dashboard.py"} for route in sorted(routes)]


def _discover_dashboard_sections(static_dir: Path) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    if not static_dir.exists():
        return sections
    for path in sorted(static_dir.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for name in re.findall(r"\bfunction\s+(render[A-Za-z0-9_]+)\s*\(", text):
            sections.append({"section": name, "path": path.relative_to(static_dir.parents[2]).as_posix()})
    return sections


def _discover_tests(tests_dir: Path) -> list[str]:
    if not tests_dir.exists():
        return []
    return sorted(path.relative_to(tests_dir.parents[0]).as_posix() for path in tests_dir.rglob("test_*.py"))


def _discover_docs(docs_dir: Path) -> list[str]:
    if not docs_dir.exists():
        return []
    return sorted(path.relative_to(docs_dir.parents[0]).as_posix() for path in docs_dir.rglob("*.md"))


def _module_description(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree) or ""
        return doc.strip().splitlines()[0] if doc else ""
    except SyntaxError:
        return ""


def _related_cli_commands(stem: str, commands: list[dict[str, str]]) -> list[str]:
    tokens = _tokens(stem)
    related = []
    for command in commands:
        haystack = f"{command['command']} {command['function']}".lower()
        if any(token in haystack for token in tokens):
            related.append(command["command"])
    return related


def _related_dashboard_routes(stem: str, routes: list[dict[str, str]]) -> list[str]:
    tokens = _tokens(stem)
    return [route["route"] for route in routes if any(token in route["route"].lower() for token in tokens)]


def _related_dashboard_sections(stem: str, sections: list[dict[str, str]]) -> list[str]:
    tokens = _tokens(stem)
    return [
        f"{section['section']} ({section['path']})"
        for section in sections
        if any(token in f"{section['section']} {section['path']}".lower() for token in tokens)
    ]


def _related_paths(stem: str, paths: list[str]) -> list[str]:
    tokens = _tokens(stem)
    return [path for path in paths if any(token in path.lower() for token in tokens)]


def _tokens(stem: str) -> list[str]:
    words = [part for part in re.split(r"[_\-.]+", stem.lower()) if len(part) >= 3]
    return sorted(set([stem.lower(), *words]))


def _infer_status(stem: str) -> str:
    if stem.startswith("legacy") or stem in {"legacy_adapter", "legacy_cli"}:
        return "deprecated"
    if stem in {"dashboard", "cli", "settings", "paths", "io", "engine", "risk"}:
        return "stable"
    if any(part in stem for part in ("toss", "portfolio", "report", "backup", "goal")):
        return "beta"
    return "experimental"


def _normalize_status(status: str) -> str:
    return status if status in VALID_STATUSES else "experimental"


def _count_by_status(features: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in ("stable", "beta", "experimental", "deprecated")}
    for feature in features:
        counts[_normalize_status(str(feature.get("status", "")))] += 1
    return counts


def _title_from_id(feature_id: str) -> str:
    return feature_id.replace("_", " ").replace("-", " ").title()


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _call_owner(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return _call_name(node.value)
    return ""


def _literal_arg(call: ast.Call, index: int) -> str | None:
    if len(call.args) <= index:
        return None
    value = call.args[index]
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


def _kw_value(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return None


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
