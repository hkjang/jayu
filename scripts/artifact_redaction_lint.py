#!/usr/bin/env python3
import re
import sys
import json
from pathlib import Path

# Sensitive patterns to detect
PATTERNS = {
    # Typical Korean account number formats (e.g., 123-45-6789012)
    "Toss Account Number": re.compile(r"\b\d{3,4}-\d{2,3}-\d{5,}\b"),
    # General secret keys and tokens (e.g., Bearer, sec_, key_...)
    "Bearer Token": re.compile(r"\bBearer\s+[a-zA-Z0-9\._-]{20,}\b"),
    "Generic Token/Secret": re.compile(r"(?i)\b(toss_token|app_key|api_key|client_secret|access_token|refresh_token)\b\s*[:=]\s*[\"']([a-zA-Z0-9_-]{16,})[\"']")
}

# Safe fields that commonly contain hashes which are not secret leaks
SAFE_FIELDS = {"git_revision", "config_hash", "data_hash", "hash", "strategy_id", "run_id", "id"}

# Safe keys that might contain descriptions or metadata, not actual secrets
SAFE_KEYS = {
    "message", "action", "detail", "summary", "description", "remediation", 
    "diagnosis", "diagnosed", "title", "label", "headline", "name", 
    "steps", "verification", "occurred_at", "timestamp", "date",
    "api_key_env_names", "env_name", "env_names", "reasons", "reasons_codes",
    "failure_code", "status", "execution_status", "safety_decision", "mode"
}

def is_safe_hash(val: str) -> bool:
    # Check if it looks like a git sha or md5/sha256 hash
    if re.match(r"^[a-fA-F0-9]{32,64}$", val):
        return True
    return False

def check_json_node(node: any, path_str: str) -> list[str]:
    violations = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in SAFE_FIELDS or k in SAFE_KEYS or any(x in k.lower() for x in SAFE_KEYS):
                continue
            violations.extend(check_json_node(v, f"{path_str} -> {k}"))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            violations.extend(check_json_node(item, f"{path_str}[{idx}]"))
    elif isinstance(node, str):
        # Ignore env var names (all-caps with underscores, e.g. JAYU_TIINGO_API_KEY)
        if re.match(r"^[A-Z][A-Z0-9_]*$", node):
            return violations
            
        # Check raw string value against patterns
        for name, regex in PATTERNS.items():
            if name == "Generic Token/Secret":
                # In JSON values we check if the path suggests a sensitive key and length is significant
                if any(x in path_str.lower() for x in ["key", "secret", "token", "password"]):
                    # Ensure it is not a safe hash
                    if len(node) >= 16 and not is_safe_hash(node):
                        violations.append(f"[{name}] Sensitive key/value found at '{path_str}': '{node[:4]}...'")
            else:
                if regex.search(node):
                    violations.append(f"[{name}] Match found at '{path_str}': '{node[:6]}...'")
    return violations

def check_file(file_path: Path) -> list[str]:
    violations = []
    if not file_path.exists():
        return violations

    # Try parsing as JSON first to get field-level precision
    if file_path.suffix == ".json":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return check_json_node(data, file_path.name)
        except json.JSONDecodeError:
            pass

    # Raw text scanning (for logs, reports, and invalid JSONs)
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for name, regex in PATTERNS.items():
            matches = regex.findall(content)
            for match in matches:
                match_str = match[1] if isinstance(match, tuple) else match
                if is_safe_hash(match_str):
                    continue
                if re.match(r"^[A-Z][A-Z0-9_]*$", match_str):
                    continue
                violations.append(f"[{name}] Potential leak in raw text of {file_path.name}: '{match_str[:4]}...'")
    except Exception as e:
        violations.append(f"Error reading {file_path.name}: {e}")

    return violations

def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    scan_dirs = [
        project_root / "runs",
        project_root / "state",
        project_root / "reports",
        project_root / "logs"
    ]
    
    total_violations = 0
    print("==================================================")
    print("      Jayu Artifact Redaction Linter 작동      ")
    print("==================================================")
    
    for sdir in scan_dirs:
        if not sdir.exists():
            continue
        print(f"Scanning directory: {sdir.relative_to(project_root)}...")
        for p in sdir.rglob("*"):
            if p.is_file() and p.suffix in (".json", ".log", ".txt", ".md", ".jsonl"):
                if ".git" in p.parts or "node_modules" in p.parts:
                    continue
                # Skip test files and temp assets
                if "test" in p.name:
                    continue
                violations = check_file(p)
                if violations:
                    print(f"\n❌ Leaks detected in file: {p.relative_to(project_root)}")
                    for v in violations:
                        print(f"   - {v}")
                    total_violations += len(violations)

    print("==================================================")
    if total_violations > 0:
        print(f" 검증 실패: 총 {total_violations}개의 민감정보 노출 감지됨")
        print("==================================================")
        return 1
    else:
        print(" 검증 완료: 민감정보 노출 없음 (무결함)")
        print("==================================================")
        return 0

if __name__ == "__main__":
    sys.exit(main())
