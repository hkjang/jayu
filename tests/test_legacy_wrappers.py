from pathlib import Path

import pytest

from jayu.legacy_cli import run_legacy_command


def test_legacy_command_delegates_to_packaged_cli(monkeypatch):
    captured = {}

    def fake_app(*, args, prog_name, standalone_mode):
        captured["args"] = args
        captured["prog_name"] = prog_name
        captured["standalone_mode"] = standalone_mode

    monkeypatch.setattr("jayu.legacy_cli.app", fake_app)

    with pytest.warns(FutureWarning, match="Removal date: 2026-09-30"):
        result = run_legacy_command(
            ("portfolio", "build"),
            ("--portfolio", "fixture.csv"),
            script_name="build_portfolio.py",
            replacement="jayu portfolio build",
        )

    assert result == 0
    assert captured == {
        "args": ["portfolio", "build", "--portfolio", "fixture.csv"],
        "prog_name": "jayu",
        "standalone_mode": False,
    }


def test_all_executable_legacy_wrappers_use_shared_delegator():
    replacements = {
        "danta_simulation.py": "jayu simulate",
        "stock_kakao.py": "jayu notify --channel kakao",
        "build_portfolio.py": "jayu portfolio build",
        "analyze_portfolio.py": "jayu portfolio analyze",
    }

    for filename, replacement in replacements.items():
        content = Path(filename).read_text(encoding="utf-8")
        assert "run_legacy_command" in content
        assert replacement in content
