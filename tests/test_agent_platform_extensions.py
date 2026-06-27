from __future__ import annotations

import json
from pathlib import Path
import pytest

# Import our new modules
from jayu.broker_interface import TossBrokerAdapter
from jayu.toss import TossInvestClient
from jayu.strategy_dsl import validate_strategy_dsl, compile_dsl_to_params, evaluate_dsl_rules, StrategyDSLError
from jayu.strategy_card_registry import GLOBAL_STRATEGY_CARD_REGISTRY, StrategyCard
from jayu.local_knowledge_index import LocalKnowledgeIndex
from jayu.llm_explainer import LlmExplainer
from jayu.jayu_mcp_server import JayuMcpServer
from jayu.notebook_export import NotebookExporter
from jayu.notification_deeplink import NotificationDeeplink


class FakeTossClient:
    """Mock for TossInvestClient to test read-only behavior."""
    def accounts(self):
        return [{"account_seq": "acc123", "display_name": "Toss Test Account"}]

    def holdings(self, account=None):
        return [{"symbol": "SOXL", "quantity": 10}]

    def buying_power(self, currency, account=None):
        return {"currency": currency, "value": 5000}

    def sellable_quantity(self, symbol, account=None):
        return {"symbol": symbol, "quantity": 10}

    def commissions(self, account=None):
        return {"rate": 0.001}


# 1. Test Broker Abstraction & Toss Read-Only Guard
def test_broker_abstraction_toss_readonly_guard() -> None:
    fake_client = FakeTossClient()
    adapter = TossBrokerAdapter(fake_client)  # type: ignore

    # Read actions should delegate successfully
    assert adapter.get_account_summary()["data"] == [{"account_seq": "acc123", "display_name": "Toss Test Account"}]
    assert adapter.get_holdings() == [{"symbol": "SOXL", "quantity": 10}]
    assert adapter.get_buying_power("USD")["data"] == {"currency": "USD", "value": 5000}
    assert adapter.get_sellable_quantity("SOXL")["data"] == {"symbol": "SOXL", "quantity": 10}
    assert adapter.get_commissions_rate()["data"] == {"rate": 0.001}

    # Write actions MUST raise NotImplementedError to protect live funds
    with pytest.raises(NotImplementedError) as exc_info:
        adapter.execute_order("SOXL", "BUY", 5, 30.0)
    assert "strictly read-only" in str(exc_info.value)

    with pytest.raises(NotImplementedError) as exc_info:
        adapter.cancel_order("order123")
    assert "strictly read-only" in str(exc_info.value)


# 2. Test Strategy DSL validation & compilation
def test_strategy_dsl_parsing_and_validation() -> None:
    valid_dsl = {
        "name": "CustomMomentum",
        "universe": ["SOXL", "TQQQ"],
        "portfolio_type": "momentum",
        "entry_rules": ["rsi < 30", "Close > ema"],
        "exit_rules": ["rsi > 70"],
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.15,
        "holding_days_limit": 10,
    }

    # Validation should pass
    report = validate_strategy_dsl(valid_dsl)
    assert report["status"] == "valid"
    assert report["name"] == "CustomMomentum"

    # Compilation should yield correct params structure
    params = compile_dsl_to_params(valid_dsl)
    assert params["strategy_name"] == "CustomMomentum"
    assert params["stop_loss_pct"] == 0.05
    assert params["is_dsl"] is True

    # Rule evaluator tests
    mock_row = {"rsi": 25, "Close": 120, "ema": 100}
    assert evaluate_dsl_rules(mock_row, ["rsi < 30", "Close > ema"]) is True
    assert evaluate_dsl_rules(mock_row, ["rsi < 20"]) is False

    # Invalid DSL validation tests
    invalid_dsl = valid_dsl.copy()
    invalid_dsl.pop("name")
    with pytest.raises(StrategyDSLError):
        validate_strategy_dsl(invalid_dsl)

    invalid_type_dsl = valid_dsl.copy()
    invalid_type_dsl["portfolio_type"] = "invalid_style"
    with pytest.raises(StrategyDSLError):
        validate_strategy_dsl(invalid_type_dsl)


# 3. Test Strategy Card Registry
def test_strategy_card_registry() -> None:
    cards = GLOBAL_STRATEGY_CARD_REGISTRY.list_cards()
    assert len(cards) >= 4
    
    # Check default cards metadata
    ensemble_card = GLOBAL_STRATEGY_CARD_REGISTRY.get_card("ensemble")
    assert ensemble_card is not None
    assert ensemble_card.type == "Ensemble"
    assert "앙상블" in ensemble_card.name

    # Custom card registration
    custom_card = StrategyCard(
        strategy_id="custom_dsl_test",
        name="테스트 DSL 전략",
        type="DSL",
        investment_objective="테스트용 목표",
        suitable_portfolio_type="momentum",
        forbidden_market_regimes=["bear"],
        recent_performance={"sharpe_ratio": 1.1},
        risk_description="테스트 위험",
        parameters_summary="N/A",
    )
    GLOBAL_STRATEGY_CARD_REGISTRY.register(custom_card)
    retrieved = GLOBAL_STRATEGY_CARD_REGISTRY.get_card("custom_dsl_test")
    assert retrieved is not None
    assert retrieved.name == "테스트 DSL 전략"


# 4. Test Local RAG Knowledge Index & Search
def test_local_rag_knowledge_index(tmp_path: Path) -> None:
    # Set up a mock project root with docs and signals
    project_root = tmp_path
    readme = project_root / "README.md"
    readme.write_text("# Jayu Trading Platform\nThis is a local manual.", encoding="utf-8")

    signals_dir = project_root / "signals"
    signals_dir.mkdir()
    signal_file = signals_dir / "today_signals.json"
    signal_file.write_text(json.dumps({"signals": {"SOXL": {"action": "BUY", "price": 45.0}}}), encoding="utf-8")

    rag = LocalKnowledgeIndex(project_root)
    indexed_count = rag.build_index()
    assert indexed_count >= 2

    # Query search
    results = rag.search("manual")
    assert len(results) > 0
    assert "README" in results[0]["title"]

    # ask_jayu grounded Korean answer synthesis
    qa = rag.ask_jayu("SOXL")
    assert "SOXL" in qa["answer"]
    assert len(qa["sources"]) > 0


# 5. Test LLM Explainer (Fallback Korean Generation)
def test_llm_explainer_fallback_korean() -> None:
    explainer = LlmExplainer()
    
    # Signal Explanation
    signal_sample = {"ticker": "SOXL", "action": "BUY", "price": 35.5, "strategy_name": "VolumeBreakout", "reason": "거래량 급증 돌파"}
    exp_sig = explainer.explain_signal(signal_sample)
    assert "SOXL" in exp_sig
    assert "매수" in exp_sig
    assert "거래량 급증 돌파" in exp_sig

    # Risk Explanation
    risk_sample = {"ticker": "TQQQ", "rule_name": "일일 최대 손실 한도", "threshold": "2.0%", "value": "2.8%", "reason": "장중 변동성 급증"}
    exp_risk = explainer.explain_risk_block(risk_sample)
    assert "TQQQ" in exp_risk
    assert "차단" in exp_risk
    assert "일일 최대 손실 한도" in exp_risk

    # Disagreement Explanation
    disagreement_sample = {"field": "현재가", "difference": "1.2%", "sources": ["Yahoo", "Toss"]}
    exp_dis = explainer.explain_disagreement(disagreement_sample)
    assert "현재가" in exp_dis
    assert "불일치" in exp_dis or "괴리" in exp_dis


# 6. Test Jayu MCP Server Tool Schema
def test_jayu_mcp_server_schema() -> None:
    server = JayuMcpServer()
    tools = server.get_tools_schema()
    
    assert len(tools) == 7
    tool_names = {t["name"] for t in tools}
    assert "validate_config" in tool_names
    assert "get_status" in tool_names
    assert "run_signal_preview" in tool_names
    assert "search_artifacts" in tool_names

    # Verify tool call output format
    res = server.call_tool("validate_config", {})
    assert "content" in res
    assert "Raw JSON" in res["content"][0]["text"]
    assert "한국어" in res["content"][0]["text"]


# 7. Test Jupyter Notebook Exporter (.ipynb output)
def test_notebook_exporter(tmp_path: Path) -> None:
    exporter = NotebookExporter(tmp_path)
    output_file = tmp_path / "test_report.ipynb"
    
    generated_path = exporter.export("20260626_120000_simulate", output_file=str(output_file))
    assert Path(generated_path).exists()

    # Read and verify JSON structure
    with open(generated_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    assert nb["nbformat"] == 4
    assert len(nb["cells"]) >= 5
    assert nb["cells"][0]["cell_type"] == "markdown"
    assert "Run" in nb["cells"][0]["source"][2]


# 8. Test Notification Deep Link Generator
def test_notification_deeplink() -> None:
    linker = NotificationDeeplink("http://localhost:9088")
    
    # Assert generated SPA hash routes
    assert linker.signal_link("SOXL") == "http://localhost:9088/#/signals?ticker=SOXL"
    assert linker.risk_link("MAX_DRAWDOWN", "TQQQ") == "http://localhost:9088/#/risk?rule=MAX_DRAWDOWN&ticker=TQQQ"
    assert linker.overview_link() == "http://localhost:9088/#/overview"
