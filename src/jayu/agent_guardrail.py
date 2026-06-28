"""Guardrail system for enforcing read-only permissions on MCP tools and agent commands."""

from __future__ import annotations

import re
from typing import Any

# Forbidden command patterns for shell injection and dangerous operations
FORBIDDEN_PATTERNS = [
    r"\brm\b",
    r"\bdel\b",
    r"\bformat\b",
    r"\bdrop\b",
    r"\bsh\b",
    r"\bbash\b",
    r"\bcmd\b",
    r"\bpowershell\b",
    r"\bwget\b",
    r"\bcurl\b",
    r"\btruncate\b",
    r"\bpython\s+-c\b",
    r"\bexec\b",
    r"\beval\b"
]

# Explicitly allowed read-only MCP tools
ALLOWED_MCP_TOOLS = {
    "get_status",
    "get_risk_summary",
    "search_artifacts",
    "get_toss_holdings_readonly",
    "view_file",
    "list_dir",
    "grep_search"
}


class AgentGuardrail:
    """Enforces read-only permissions and content validation on agent tool invocations."""

    @staticmethod
    def is_safe_command(command: str) -> tuple[bool, str | None]:
        """Checks if a command string contains any dangerous modification keywords."""
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"위험한 명령어 키워드 감지: {pattern} (보안 정책에 의해 차단됨)"
        return True, None

    @staticmethod
    def validate_tool_invocation(tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str | None]:
        """Verifies if the tool name and its arguments comply with the read-only policy."""
        # 1. Block any non-read-only tool explicitly if it's in the list
        if tool_name not in ALLOWED_MCP_TOOLS and ("write" in tool_name.lower() or "delete" in tool_name.lower() or "run" in tool_name.lower()):
            return False, f"쓰기/실행 권한 차단: 도구 '{tool_name}'은 읽기 전용 모드에서 호출할 수 없습니다."

        # 2. Inspect arguments for command injection
        for k, v in arguments.items():
            if isinstance(v, str):
                is_safe, err = AgentGuardrail.is_safe_command(v)
                if not is_safe:
                    return False, f"인수 '{k}' 검증 실패 - {err}"

        return True, None

    @staticmethod
    def verify_citation_presence(response_text: str) -> bool:
        """Enforces that any agent answer contains at least one file:// citation link."""
        # Search for markdown links containing file:///
        return bool(re.search(r"\[[^\]]+\]\(file:///[^\)]+\)", response_text))
