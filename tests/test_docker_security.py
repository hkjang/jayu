from pathlib import Path


def test_docker_runtime_is_non_root_and_uses_external_writable_volumes():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "COPY --chown=app:app src ./src" in dockerfile
    assert "COPY --chown=app:app . ." not in dockerfile
    assert "apt-get install" not in dockerfile
    assert 'VOLUME ["/app/data", "/app/runs", "/app/state", "/app/signals"]' in dockerfile
    assert 'ENTRYPOINT ["jayu"]' in dockerfile


def test_ci_checks_non_root_and_read_only_container_runtime():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'test "$(id -u)" = "10001"' in workflow
    assert "docker run --rm --read-only --tmpfs /tmp jayu-ci --help" in workflow


def test_docker_context_excludes_runtime_secrets():
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()

    assert dockerignore[0] == "*"
    assert "!src/**" in dockerignore
    assert "!configs/config.sample.json" in dockerignore
    assert "config.json" in dockerignore
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "secrets" in dockerignore
