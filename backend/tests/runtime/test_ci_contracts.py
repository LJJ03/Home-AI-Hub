"""Static contracts for the default offline GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = PROJECT_ROOT / ".github/workflows/ci.yml"
CONFTEST_PATH = PROJECT_ROOT / "backend/tests/conftest.py"
README_PATH = PROJECT_ROOT / "README.md"
DEFAULT_TESTS_DOC = PROJECT_ROOT / "docs/testing/default-tests.md"
RUNTIME_DOC = PROJECT_ROOT / "docs/operations/runtime.md"


def _workflow_source() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow() -> dict[str, Any]:
    document = yaml.load(_workflow_source(), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _default_job() -> dict[str, Any]:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert set(jobs) == {"default-tests"}
    job = jobs["default-tests"]
    assert isinstance(job, dict)
    return job


def _run_commands() -> tuple[str, ...]:
    return tuple(
        str(step["run"]).strip()
        for step in _default_job()["steps"]
        if "run" in step
    )


def test_default_ci_exists_and_uses_only_push_and_pull_request() -> None:
    workflow = _workflow()
    triggers = workflow["on"]

    assert set(triggers) == {"push", "pull_request"}
    assert "workflow_dispatch" not in triggers


def test_default_ci_has_read_only_repository_permissions() -> None:
    workflow = _workflow()
    checkout_steps = [
        step
        for step in _default_job()["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]

    assert workflow["permissions"] == {"contents": "read"}
    assert "permissions" not in _default_job()
    assert len(checkout_steps) == 1
    assert checkout_steps[0]["with"]["persist-credentials"] == "false"


def test_default_ci_uses_explicit_python_313() -> None:
    setup_steps = [
        step
        for step in _default_job()["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    ]

    assert len(setup_steps) == 1
    assert setup_steps[0]["with"]["python-version"] == "3.13"
    source = _workflow_source().lower()
    assert 'python-version: "3.12"' not in source
    assert 'python-version: "3.14"' not in source
    assert "python-version: latest" not in source


def test_default_ci_installs_project_test_dependencies_from_backend() -> None:
    job = _default_job()
    commands = _run_commands()

    assert job["defaults"]["run"]["working-directory"] == "backend"
    assert "python -m pip install --upgrade pip" in commands
    assert 'python -m pip install -e ".[test]"' in commands


def test_default_ci_runs_only_the_default_pytest_command() -> None:
    commands = _run_commands()
    pytest_commands = tuple(
        command for command in commands if "pytest" in command
    )

    assert pytest_commands == ("python -m pytest",)
    assert all("--run-integration" not in command for command in commands)
    assert all("--run-llm-integration" not in command for command in commands)


def test_default_ci_uses_safe_mock_environment_without_secrets() -> None:
    environment = _default_job()["env"]
    source = _workflow_source()

    assert environment["LLM_PROVIDER"] == "mock"
    assert environment["LLM_DEFAULT_MODEL"] == "mock-default"
    assert environment["LLM_INTEGRATION_ACKNOWLEDGE_COST"] == "false"
    assert environment["APP_ENVIRONMENT"] == "test"
    assert "OPENAI_API_KEY" not in environment
    assert "DEEPSEEK_API_KEY" not in environment
    assert "Authorization" not in source
    assert "${{ secrets." not in source


def test_default_ci_has_no_external_service_or_docker_runtime() -> None:
    job = _default_job()
    commands = _run_commands()

    assert "services" not in job
    assert all("docker" not in command.lower() for command in commands)
    assert all("compose up" not in command.lower() for command in commands)
    assert "deepseek" not in _workflow_source().lower()
    assert "openai" not in _workflow_source().lower()


def test_default_ci_relies_on_the_existing_test_network_gate() -> None:
    conftest = CONFTEST_PATH.read_text(encoding="utf-8")

    assert "block_external_network_by_default" in conftest
    assert "_is_loopback_host" in conftest
    assert "_block_external_network" in conftest
    assert _run_commands()[-1] == "python -m pytest"


def test_ci_documentation_matches_the_implemented_default_scope() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    default_tests = DEFAULT_TESTS_DOC.read_text(encoding="utf-8")
    runtime = RUNTIME_DOC.read_text(encoding="utf-8")
    documentation = "\n".join((readme, default_tests, runtime))

    assert "push" in default_tests
    assert "pull request" in default_tests
    assert "Python 3.13" in default_tests
    assert "python -m pytest" in default_tests
    assert "依赖安装阶段" in default_tests
    assert "测试执行阶段" in default_tests
    assert "不运行 PostgreSQL Integration" in default_tests
    assert "不运行真实 LLM Integration" in default_tests
    assert "Integration Workflows 已独立定义" in default_tests
    assert "动态运行验证尚未执行" in runtime
    assert "PostgreSQL Integration 已在默认 CI 运行" not in documentation
    assert "真实 LLM Integration 已在默认 CI 运行" not in documentation
    assert "Phase 7 已冻结" not in documentation
    assert (
        "Phase 7 — Runtime, Docker, CI and Release Gate 已冻结（Freeze）。"
        not in documentation
    )
