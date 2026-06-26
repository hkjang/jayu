import json
import pytest
from pathlib import Path
import sys

# Import check_file and PATTERNS from our scripts directory
# We can add the scripts directory to path to import it easily
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
from artifact_redaction_lint import check_file, is_safe_hash

def test_is_safe_hash():
    assert is_safe_hash("a5d3f23b2c1d0e9f8a7b6c5d4e3f2a1b") is True # md5
    assert is_safe_hash("f219d45f3408c66a457497d396a84f3df9b8c7a6e5d4c3b2a1") is True # sha
    assert is_safe_hash("not_a_hash") is False
    assert is_safe_hash("123-45-678901") is False

def test_redaction_lint_detects_leaks(tmp_path):
    # Test Toss Account Number leak in JSON
    leak_json = {
        "account_number": "123-45-6789012",
        "description": "My personal account"
    }
    file_path = tmp_path / "account.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(leak_json, f)
        
    violations = check_file(file_path)
    assert len(violations) > 0
    assert any("Toss Account Number" in v for v in violations)

def test_redaction_lint_detects_token_leak(tmp_path):
    # Test Bearer token leak in raw text/logs
    log_content = "2026-06-26 13:00:00 INFO Sending request with Bearer TOSS_token_value_xyz_123456"
    file_path = tmp_path / "app.log"
    file_path.write_text(log_content, encoding="utf-8")
    
    violations = check_file(file_path)
    assert len(violations) > 0
    assert any("Bearer Token" in v for v in violations)

def test_redaction_lint_ignores_safe_hashes(tmp_path):
    # Test that a safe manifest with git_revision hash is NOT flagged
    safe_manifest = {
        "schema_version": "1.1.0",
        "git_revision": "4bfa336ea5d3f23b2c1d0e9f8a7b6c5d4e3f2a1b",
        "config_hash": "a5d3f23b2c1d0e9f8a7b6c5d4e3f2a1b",
        "normal_text": "This is a completely safe description without any keys"
    }
    file_path = tmp_path / "manifest.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(safe_manifest, f)
        
    violations = check_file(file_path)
    assert len(violations) == 0
