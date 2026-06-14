from pathlib import Path


def test_docker_runtime_is_non_root_and_uses_external_writable_volumes():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert 'VOLUME ["/app/data", "/app/runs", "/app/state", "/app/signals"]' in dockerfile
    assert 'ENTRYPOINT ["jayu"]' in dockerfile


def test_docker_context_excludes_runtime_secrets():
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "config.json" in dockerignore
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "secrets" in dockerignore
