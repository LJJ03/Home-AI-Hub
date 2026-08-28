"""Offline contract tests for the backend Docker runtime boundary."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = BACKEND_ROOT / "Dockerfile"
DOCKERIGNORE = BACKEND_ROOT / ".dockerignore"
PYPROJECT = BACKEND_ROOT / "pyproject.toml"


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _dockerignore_patterns() -> set[str]:
    return {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_runtime_pins_python_313_in_both_stages() -> None:
    dockerfile = _dockerfile()
    assert "ARG PYTHON_VERSION=3.13.15" in dockerfile

    from_lines = re.findall(r"(?im)^FROM\s+(.+)$", dockerfile)
    assert from_lines == [
        "python:${PYTHON_VERSION}-slim AS builder",
        "python:${PYTHON_VERSION}-slim AS runtime",
    ]


def test_runtime_uses_a_wheel_based_multi_stage_build() -> None:
    dockerfile = _dockerfile()
    assert "python -m pip wheel --wheel-dir /wheels ." in dockerfile
    assert "COPY --from=builder /wheels /wheels" in dockerfile
    assert "python -m pip install --no-index --find-links=/wheels" in dockerfile
    assert re.search(r"(?im)^\s*COPY\s+\.\s+\.?\s*$", dockerfile) is None


def test_runtime_runs_as_a_non_root_user() -> None:
    dockerfile = _dockerfile()
    assert "ARG APP_UID=10001" in dockerfile
    assert "ARG APP_GID=10001" in dockerfile
    assert "USER app" in dockerfile
    assert dockerfile.index("USER app") < dockerfile.index("CMD [")
    assert "USER root" not in dockerfile


def test_runtime_uses_exec_form_startup_and_liveness_healthcheck() -> None:
    dockerfile = _dockerfile()
    assert 'CMD ["python", "-m", "app"]' in dockerfile
    assert re.search(r"(?im)^\s*CMD\s+(?!\[)", dockerfile) is None
    assert "HEALTHCHECK --interval=10s" in dockerfile
    assert "/health" in dockerfile
    assert "/ready" not in dockerfile


def test_runtime_keeps_migration_assets_without_copying_tests() -> None:
    dockerfile = _dockerfile()
    runtime_stage = dockerfile.split(
        "FROM python:${PYTHON_VERSION}-slim AS runtime", maxsplit=1
    )[1]
    assert "COPY --chown=app:app alembic.ini ./alembic.ini" in runtime_stage
    assert "COPY --chown=app:app alembic ./alembic" in runtime_stage
    assert not re.search(r"(?im)^\s*COPY\s+.*tests", runtime_stage)
    assert not re.search(r"(?im)^\s*COPY\s+.*\.env", runtime_stage)


def test_docker_context_excludes_local_and_sensitive_state() -> None:
    patterns = _dockerignore_patterns()
    required_patterns = {
        ".env",
        ".env.*",
        ".venv/",
        "venv/",
        "__pycache__/",
        "**/__pycache__/",
        ".pytest_cache/",
        "tests/",
        "*.log",
        "logs/",
        "postgres-data/",
        "redis-data/",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "credentials.json",
        "token.json",
    }
    assert required_patterns <= patterns


def test_runtime_dependencies_exclude_vendor_sdks() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    dependencies = "\n".join(project["dependencies"]).lower()
    forbidden_packages = (
        "openai",
        "deepseek",
        "anthropic",
        "google-generativeai",
        "google-genai",
    )
    assert all(package not in dependencies for package in forbidden_packages)


def test_dockerfile_does_not_embed_secret_configuration() -> None:
    dockerfile = _dockerfile().lower()
    forbidden_terms = (
        "api_key",
        "authorization",
        "bearer ",
        "credentials.json",
        "token.json",
        "copy .env",
    )
    assert all(term not in dockerfile for term in forbidden_terms)
