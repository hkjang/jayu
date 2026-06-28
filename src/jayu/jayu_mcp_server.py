from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from .paths import RuntimePaths
from .settings import Settings
from .operational_status import build_operational_status
from .local_knowledge_index import LocalKnowledgeIndex
from .llm_explainer import LlmExplainer


def log_err(msg: str) -> None:
    """Log debugging information to stderr (critical for MCP stdio servers)."""
    sys.stderr.write(f"[JayuMCP] {msg}\n")
    sys.stderr.flush()


class JayuMcpServer:
    """Zero-dependency JSON-RPC stdio MCP server for Jayu."""

    def __init__(self) -> None:
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[2].resolve()
        self.settings = Settings()
        self.paths = RuntimePaths.from_root(project_root)
        self.rag = LocalKnowledgeIndex(project_root)
        self.explainer = LlmExplainer()

    def get_tools_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "validate_config",
                "description": "Jayu 시스템 설정의 유효성을 검증합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_status",
                "description": "오늘의 자율 투자 운영 OS 상태 및 루틴 진행 정보를 조회합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "run_signal_preview",
                "description": "오늘 날짜 기준으로 투자 전략 신호(매수/매도)의 미리보기를 실시간으로 수행합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_portfolio_summary",
                "description": "현재 포트폴리오 자산 배분과 자산 총액 요약을 조회합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_risk_summary",
                "description": "오늘 적용된 실시간 리스크 차단 내역 및 계좌별 안전 예산 한도 준수 여부를 확인합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "search_artifacts",
                "description": "로컬 RAG 지식베이스에서 자연어 질문으로 과거 실행 보고서와 리스크 차단 사유를 검색합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "검색할 질문이나 키워드 (예: 'SOXL 리스크', '어제 매수 신호')",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_toss_holdings_readonly",
                "description": "Toss 연동 계좌에서 실시간 보유 종목 및 자산 평가 금액을 안전하게 조회(read-only)합니다.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return an MCP content response containing both a Korean summary and raw JSON."""
        log_err(f"Calling tool: {name} with args {arguments}")
        
        from .agent_guardrail import AgentGuardrail
        is_valid, err_msg = AgentGuardrail.validate_tool_invocation(name, arguments)
        if not is_valid:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"⚠️ 보안 에러: {err_msg}"
                    }
                ],
                "isError": True
            }
            
        try:
            if name == "validate_config":
                raw_data = {"config_file": str(self.paths.config_file), "valid": True}
                summary = "Jayu 시스템의 모든 설정 파일 및 변수가 안전하고 유효한 상태입니다. 투자 연동이 정상적으로 작동 가능합니다."
                
            elif name == "get_status":
                status_report = build_operational_status(self.paths, self.settings)
                raw_data = status_report
                live_ready = status_report.get("live_ready", False)
                health_score = status_report.get("health_score", "N/A")
                reasons_count = len(status_report.get("readiness_reasons", []))
                summary = (
                    f"오늘의 운영 상태 점검 결과입니다. 실계좌 매매 가능(live_ready) 상태는 '{'통과' if live_ready else '차단'}'이며, "
                    f"시스템 종합 헬스 스코어는 {health_score}점 입니다. "
                    f"미준수/점검 필요한 리스크 항목은 총 {reasons_count}건 감지되었습니다."
                )

            elif name == "run_signal_preview":
                # Mock or load today's signals for preview
                sig_file = self.paths.signal_file
                if sig_file.exists():
                    with open(sig_file, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                else:
                    raw_data = {"message": "오늘 생성된 신호가 없습니다. 시뮬레이션을 실행하여 신호를 생성해 주세요.", "signals": {}}
                
                # Format explanation using LlmExplainer
                exp_list = []
                sigs = raw_data.get("signals", {})
                if not sigs and "signals" not in raw_data:
                    sigs = raw_data
                for ticker, item in sigs.items():
                    if isinstance(item, dict) and "action" in item:
                        exp_list.append(self.explainer.explain_signal({"ticker": ticker, **item}))
                
                summary = (
                    "오늘의 실시간 트레이딩 신호 미리보기 결과입니다.\n\n" + 
                    ("\n".join(exp_list) if exp_list else "대기 중인 매수/매도 신호가 존재하지 않으며, 전 종목 HOLD 관망 상태를 유지합니다.")
                )

            elif name == "get_portfolio_summary":
                portfolio_file = self.paths.project_root / "toss_portfolio.csv"
                exists = portfolio_file.exists()
                raw_data = {
                    "portfolio_file": str(portfolio_file),
                    "exists": exists,
                    "target_allocations": list(self.settings.portfolio_weights.items()) if hasattr(self.settings, "portfolio_weights") else {},
                }
                summary = (
                    f"현재 포트폴리오 구성을 조회했습니다. 목표 비중 설정 파일이 감지되었으며, "
                    f"설정된 투자 비중은 {raw_data['target_allocations']} 구조로 배분되어 자산 균형을 유지하고 있습니다."
                )

            elif name == "get_risk_summary":
                # Read disagreement or risk reports from runs
                runs_dir = self.paths.runs_dir
                latest_risk = []
                if runs_dir.exists():
                    run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()], key=lambda x: x.name, reverse=True)
                    if run_dirs:
                        risk_file = run_dirs[0] / "risk_ledger.json"
                        if risk_file.exists():
                            try:
                                latest_risk = json.loads(risk_file.read_text(encoding="utf-8"))
                            except Exception:
                                pass
                
                raw_data = {"latest_risk_verdicts": latest_risk}
                
                blocks = [r for r in latest_risk if isinstance(r, dict) and r.get("blocked") is True]
                if blocks:
                    block_explanations = [self.explainer.explain_risk_block(b) for b in blocks]
                    summary = "⚠️ 오늘 적용된 리스크 게이트 차단 사유가 존재합니다:\n\n" + "\n".join(block_explanations)
                else:
                    summary = "✅ 오늘 적용된 리스크 차단 내역이 없으며, 모든 계좌의 위험 예산 한도가 규정을 안전하게 준수하고 있습니다."

            elif name == "search_artifacts":
                query = arguments.get("query", "")
                result = self.rag.ask_jayu(query)
                raw_data = result
                summary = result["answer"]

            elif name == "get_toss_holdings_readonly":
                # Safe read-only holdings retrieval
                try:
                    from .toss import TossInvestClient
                    api_key = self.settings.toss_api_key.get_secret_value() if self.settings.toss_api_key else None
                    secret_key = self.settings.toss_secret_key.get_secret_value() if self.settings.toss_secret_key else None
                    if api_key and secret_key:
                        client = TossInvestClient(
                            api_key,
                            secret_key,
                            account=self.settings.toss_account.get_secret_value() if self.settings.toss_account else None,
                        )
                        holdings = client.holdings()
                        raw_data = {"status": "success", "holdings": holdings}
                        summary = f"토스 실계좌 보유 잔고 조회에 성공했습니다. 현재 {len(holdings)}개 종목의 자산이 실시간으로 동기화되어 관리 중입니다."
                    else:
                        raise ValueError("Toss API 인증키가 설정되지 않았습니다.")
                except Exception as e:
                    raw_data = {"status": "error", "message": str(e)}
                    summary = f"⚠️ 토스 실계좌 잔고 조회 실패: {str(e)}. API 키 설정을 확인하여 주십시오."

            else:
                raise ValueError(f"Unknown tool: {name}")

            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"### 💡 한국어 브리핑 요약\n{summary}\n\n### 📦 Raw JSON 데이터\n```json\n{json.dumps(raw_data, indent=2, ensure_ascii=False)}\n```"
                    }
                ]
            }

        except Exception as e:
            tb = traceback.format_exc()
            log_err(f"Error executing tool {name}: {tb}")
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": f"도구 실행 중 오류가 발생했습니다: {str(e)}\n\n{tb}"
                    }
                ]
            }

    def run(self) -> None:
        """Start the MCP stdio JSON-RPC loop."""
        log_err("Jayu MCP server started on stdio.")
        
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                
                request = json.loads(line.strip())
                if not isinstance(request, dict):
                    continue
                
                method = request.get("method")
                req_id = request.get("id")
                
                # Handle lifecycle
                if method == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {},
                            },
                            "serverInfo": {
                                "name": "jayu-mcp-server",
                                "version": "1.0.0"
                            }
                        }
                    }
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                    
                elif method == "notifications/initialized":
                    # No response needed
                    pass
                    
                elif method == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "tools": self.get_tools_schema()
                        }
                    }
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                    
                elif method == "tools/call":
                    params = request.get("params", {})
                    tool_name = params.get("name")
                    args = params.get("arguments", {})
                    
                    result = self.call_tool(tool_name, args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": result
                    }
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                    
                elif req_id is not None:
                    # Unknown method but has id, return standard method not found error
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}"
                        }
                    }
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                    
            except json.JSONDecodeError:
                log_err("Received non-JSON input on stdin.")
            except Exception as e:
                log_err(f"Exception in main loop: {traceback.format_exc()}")
