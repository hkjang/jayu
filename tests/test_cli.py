from typer.testing import CliRunner

from jayu.artifacts import RunContext
from jayu.cli import (
    _annotate_shadow_signals,
    _compare_experiment_rows,
    _failed_market_tickers,
    _output_policy,
    _record_signal_inputs,
    _resolve_signal_date,
    app,
)
from jayu.io import atomic_write_json
from jayu.paths import RuntimePaths
from jayu.settings import Settings


def test_validate_config_includes_strategy_space_audit():
    result = CliRunner().invoke(app, ["validate-config"])

    assert result.exit_code == 0, result.output
    assert '"strategy_space_audit"' in result.output
    assert '"valid": true' in result.output
    assert "configuration is valid" in result.output


def test_missing_verified_price_is_reported_as_market_data_failure():
    context = object.__new__(RunContext)
    context.data_reports = {
        "SOXL": {
            "ticker": "SOXL",
            "valid": True,
            "price_verified": True,
            "price_usable": True,
        },
        "TQQQ": {
            "ticker": "TQQQ",
            "valid": True,
            "price_verified": False,
            "price_usable": False,
        },
    }

    failed = _failed_market_tickers(Settings(tickers=["SOXL", "TQQQ"]), context)

    assert failed == ["TQQQ"]


def test_shadow_annotation_adds_pending_future_return_fields():
    signals = {
        "SOXL": {"signal": "entry", "action": "buy", "eligible": True},
        "TQQQ": {"signal": "wait", "action": "hold", "eligible": False},
    }

    shadow = _annotate_shadow_signals(signals, reason="mode=shadow")

    assert shadow["SOXL"]["shadow_status"] == "pending"
    assert shadow["SOXL"]["shadow_reason"] == "mode=shadow"
    assert shadow["SOXL"]["future_return_1d"] is None
    assert shadow["SOXL"]["future_return_5d"] is None
    assert shadow["SOXL"]["future_return_20d"] is None
    assert shadow["TQQQ"]["shadow_status"] == "not_applicable"
    assert shadow["TQQQ"]["shadow_reason"] == "not_buy_signal"


def test_signal_date_requires_replay_for_historical_date():
    assert _resolve_signal_date("2026-01-02", replay=True) == "2026-01-02"
    assert _resolve_signal_date("today", replay=True) is None


def test_signal_replay_forces_notification_off(monkeypatch):
    captured = {}

    def fake_run_engine(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)

    monkeypatch.setattr("jayu.cli._run_engine", fake_run_engine)

    result = CliRunner().invoke(
        app,
        ["signal", "--date", "2026-01-02", "--replay", "--notify"],
    )

    assert result.exit_code == 0, result.output
    assert captured["command"] == "signal_replay"
    assert captured["replay"] is True
    assert captured["replay_date"] == "2026-01-02"
    assert captured["notify_user"] is False


def test_replay_and_shadow_do_not_write_primary_signal():
    replay = _output_policy(replay=True, shadow_mode=False)
    shadow = _output_policy(replay=False, shadow_mode=True)

    assert replay == {
        "persist_state": False,
        "persist_signal": False,
        "write_primary_signal": False,
        "update_health": False,
        "prune_runs": False,
    }
    assert shadow["persist_state"] is True
    assert shadow["persist_signal"] is False
    assert shadow["write_primary_signal"] is False
    assert shadow["update_health"] is True


def test_signal_input_hashes_include_strategy_and_mapping(tmp_path):
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    atomic_write_json(paths.best_strategy_file, {"SOXL": {"bull": {"params": {"rsi": 30}}}})
    atomic_write_json(paths.portfolio_mapping_file, {"version": 1, "tickers": {}})

    class Context:
        def __init__(self):
            self.records = {}

        def record_data(self, key, *, data_hash, quality_report):
            self.records[key] = {
                "data_hash": data_hash,
                "quality_report": quality_report,
            }

    context = Context()
    _record_signal_inputs(context, paths)  # type: ignore[arg-type]

    assert context.records["best_strategy_state"]["quality_report"]["available"] is True
    assert context.records["portfolio_mapping"]["quality_report"]["available"] is True
    assert context.records["best_strategy_state"]["data_hash"]


def test_historical_signal_date_requires_replay():
    result = CliRunner().invoke(app, ["signal", "--date", "2026-01-02"])

    assert result.exit_code != 0
    assert "supported only with --replay" in result.output


def test_experiment_compare_reads_hashes_and_statuses(tmp_path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    atomic_write_json(left_dir / "cost_sensitivity.json", {"cost_survival_status": "approved"})
    atomic_write_json(right_dir / "cost_sensitivity.json", {"cost_survival_status": "rejected"})

    comparison = _compare_experiment_rows(
        {
            "run_id": "left",
            "artifact_dir": str(left_dir),
            "config_hash": "config-a",
            "data_hashes_json": '{"SOXL":"data-a"}',
            "result_json": (
                '{"best_fitness":1.0,"signal_hash":"signal-a",'
                '"validation_status":"approved","risk_status":"approved"}'
            ),
        },
        {
            "run_id": "right",
            "artifact_dir": str(right_dir),
            "config_hash": "config-b",
            "data_hashes_json": '{"SOXL":"data-b"}',
            "result_json": (
                '{"best_fitness":0.5,"signal_hash":"signal-b",'
                '"validation_status":"rejected","risk_status":"blocked"}'
            ),
        },
    )

    assert comparison["config_hash"]["changed"] is True
    assert comparison["data_hash"]["changed"] is True
    assert comparison["signal_hash"]["changed"] is True
    assert comparison["cost_survival"]["right"] == "rejected"
