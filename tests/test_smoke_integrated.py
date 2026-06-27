from __future__ import annotations

from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_feature_inventory_and_release_doctor_smoke(tmp_path: Path) -> None:
    from jayu.cli_coverage_map import build_cli_coverage_map
    from jayu.dashboard_coverage_map import build_dashboard_coverage_map
    from jayu.feature_inventory import build_feature_inventory, write_feature_inventory
    from jayu.release_doctor import run_release_doctor

    _write(tmp_path / "src" / "jayu" / "__init__.py", "")
    _write(tmp_path / "src" / "jayu" / "foo_feature.py", '"""Foo feature."""\nVALUE = 1\n')
    _write(
        tmp_path / "src" / "jayu" / "cli.py",
        "\n".join(
            [
                "import typer",
                "app = typer.Typer()",
                '@app.command("foo-feature")',
                "def foo_feature():",
                "    pass",
            ]
        ),
    )
    _write(
        tmp_path / "src" / "jayu" / "dashboard.py",
        'if parsed.path == "/api/v1/foo-feature":\n    pass\n',
    )
    _write(
        tmp_path / "src" / "jayu" / "dashboard_static" / "foo.js",
        "function renderFooFeature() { return ''; }\n",
    )
    _write(tmp_path / "tests" / "test_foo_feature.py", "def test_foo_feature():\n    assert True\n")
    _write(tmp_path / "tests" / "test_smoke_integrated.py", "def test_smoke():\n    assert True\n")
    _write(tmp_path / "docs" / "foo_feature.md", "# Foo Feature\n")
    _write(
        tmp_path / "configs" / "feature_status.yaml",
        "features:\n  foo_feature:\n    status: stable\n    owner: test\n",
    )

    inventory = build_feature_inventory(tmp_path)
    assert inventory["summary"]["feature_count"] >= 3
    feature = next(row for row in inventory["features"] if row["feature_id"] == "foo_feature")
    assert feature["status"] == "stable"
    assert feature["cli_commands"] == ["foo-feature"]
    assert feature["dashboard_routes"] == ["/api/v1/foo-feature"]
    assert feature["dashboard_sections"]

    write_feature_inventory(tmp_path)
    assert (tmp_path / "state" / "feature_inventory.json").exists()
    assert (tmp_path / "docs" / "FEATURES.md").exists()

    dashboard_coverage = build_dashboard_coverage_map(tmp_path)
    cli_coverage = build_cli_coverage_map(tmp_path)
    assert dashboard_coverage["summary"]["features_with_dashboard_api"] >= 1
    assert cli_coverage["summary"]["features_with_cli"] >= 1

    doctor = run_release_doctor(tmp_path)
    assert doctor["status"] == "success"
    assert (tmp_path / "state" / "release_doctor.json").exists()
