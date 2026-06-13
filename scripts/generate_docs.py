from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jayu.settings import Settings
from jayu.strategy_space import CONDITIONAL_PARAMETERS, load_strategy_spaces


ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = ROOT / "docs" / "generated"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _resolve_schema(root: dict[str, Any], field: dict[str, Any]) -> dict[str, Any]:
    reference = field.get("$ref")
    if isinstance(reference, str):
        return root.get("$defs", {}).get(reference.rsplit("/", 1)[-1], field)
    for option in field.get("anyOf", []):
        reference = option.get("$ref")
        if isinstance(reference, str):
            return root.get("$defs", {}).get(reference.rsplit("/", 1)[-1], field)
    return field


def _field_type(field: dict[str, Any]) -> str:
    field_type = field.get("type") or field.get("$ref", "").split("/")[-1]
    if not field_type and "anyOf" in field:
        field_type = " | ".join(
            option.get("type", option.get("$ref", "").split("/")[-1]) for option in field["anyOf"]
        )
    return field_type or "object"


def _settings_rows(
    root: dict[str, Any],
    schema: dict[str, Any],
    *,
    prefix: str = "",
) -> list[str]:
    lines: list[str] = []
    required = set(schema.get("required", []))
    for name, field in schema.get("properties", {}).items():
        full_name = f"{prefix}.{name}" if prefix else name
        default = field.get("default", "<required>" if name in required else None)
        constraints = {
            key: field[key]
            for key in ("minimum", "maximum", "exclusiveMinimum", "enum")
            if key in field
        }
        lines.append(
            f"| `{full_name}` | `{_field_type(field)}` | `{_json(default)}` | "
            f"`{_json(constraints)}` |"
        )
        resolved = _resolve_schema(root, field)
        if resolved is not field and resolved.get("properties"):
            lines.extend(_settings_rows(root, resolved, prefix=full_name))
    return lines


def settings_markdown() -> str:
    schema = Settings.model_json_schema()
    lines = [
        "# Settings Reference",
        "",
        "Generated from `jayu.settings.Settings`. Do not edit manually.",
        "",
        "| Field | Type | Default | Constraints |",
        "|---|---|---|---|",
    ]
    lines.extend(_settings_rows(schema, schema))
    return "\n".join(lines) + "\n"


def parameters_markdown() -> str:
    spaces = load_strategy_spaces()
    lines = [
        "# Strategy Parameter Reference",
        "",
        "Generated from `configs/strategy_spaces/*.json`. Do not edit manually.",
        "",
        "A candidate has exactly one `strategy_mode`: `ensemble`, `connors_rsi2`, "
        "`williams_breakout`, or `volume_breakout`.",
        "",
    ]
    for mode, space in spaces.items():
        lines.extend(
            [
                f"## {mode}",
                "",
                "| Parameter | Choices | Conditional |",
                "|---|---|---|",
            ]
        )
        for name, choices in space.items():
            conditions = [
                f"`{switch}={required}`"
                for switch, dependents in CONDITIONAL_PARAMETERS.items()
                for parameter, required in dependents.items()
                if parameter == name
            ]
            lines.append(
                f"| `{name}` | `{_json(choices)}` | "
                f"{', '.join(conditions) if conditions else '-'} |"
            )
        lines.append("")
    return "\n".join(lines)


def generated_documents() -> dict[Path, str]:
    return {
        GENERATED_DIR / "SETTINGS.md": settings_markdown(),
        GENERATED_DIR / "PARAMETERS.md": parameters_markdown(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    for path, content in generated_documents().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                mismatches.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if mismatches:
        print("Generated documentation is stale: " + ", ".join(mismatches))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
