"""Static contracts for isolated PostgreSQL and real-LLM workflows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_ROOT = PROJECT_ROOT / ".github/workflows"
DEFAULT_CI_PATH = WORKFLOWS_ROOT / "ci.yml"
POSTGRES_WORKFLOW_PATH = WORKFLOWS_ROOT / "postgres-integration.yml"
LLM_WORKFLOW_PATH = WORKFLOWS_ROOT / "llm-integration.yml"
POSTGRES_DOC_PATH = PROJECT_ROOT / "docs/testing/postgres-integration.md"
LLM_DOC_PATH = PROJECT_ROOT / "docs/testing/llm-integration.md"
DEFAULT_TESTS_DOC_PATH = PROJECT_ROOT / "docs/testing/default-tests.md"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflow(path: Path) -> dict[str, Any]:
    document = yaml.load(_source(path), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _job(path: Path, job_name: str) -> dict[str, Any]:
    job = _workflow(path)["jobs"][job_name]
    assert isinstance(job, dict)
    return job


def _run_commands(job: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(step["run"]).strip()
        for step in job["steps"]
        if "run" in step
    )


def _setup_python_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    ]


def test_postgres_workflow_has_controlled_non_pr_triggers_and_permissions() -> None:
    workflow = _workflow(POSTGRES_WORKFLOW_PATH)
    triggers = workflow["on"]

    assert set(triggers) == {"workflow_dispatch", "push"}
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" not in triggers
    assert "schedule" not in triggers
    assert workflow["permissions"] == {"contents": "read"}


def test_postgres_workflow_uses_python_313_and_project_test_dependencies() -> None:
    job = _job(POSTGRES_WORKFLOW_PATH, "postgres-integration")
    setup_steps = _setup_python_steps(job)
    commands = _run_commands(job)

    assert len(setup_steps) == 1
    assert setup_steps[0]["with"]["python-version"] == "3.13"
    assert job["defaults"]["run"]["working-directory"] == "backend"
    assert "python -m pip install --upgrade pip" in commands
    assert 'python -m pip install -e ".[test]"' in commands


def test_postgres_workflow_uses_an_isolated_postgres_17_service() -> None:
    job = _job(POSTGRES_WORKFLOW_PATH, "postgres-integration")
    services = job["services"]
    postgres = services["postgres"]
    service_environment = postgres["env"]
    job_environment = job["env"]

    assert set(services) == {"postgres"}
    assert postgres["image"].startswith("postgres:17")
    assert "pg_isready" in postgres["options"]
    assert "ci" in service_environment["POSTGRES_USER"]
    assert "ci" in service_environment["POSTGRES_PASSWORD"]
    assert "ci" in service_environment["POSTGRES_DB"]
    assert "127.0.0.1:5432" in job_environment["DATABASE_URL"]
    assert "ci" in job_environment["DATABASE_URL"]
    assert "production" not in job_environment["DATABASE_URL"].lower()


def test_postgres_workflow_runs_only_postgresql_integration_with_mock_llm() -> None:
    job = _job(POSTGRES_WORKFLOW_PATH, "postgres-integration")
    commands = _run_commands(job)
    environment = job["env"]
    source = _source(POSTGRES_WORKFLOW_PATH)

    assert "python -m pytest --run-integration" in commands
    assert all("--run-llm-integration" not in command for command in commands)
    assert environment["LLM_PROVIDER"] == "mock"
    assert environment["LLM_DEFAULT_MODEL"] == "mock-default"
    assert environment["LLM_INTEGRATION_ACKNOWLEDGE_COST"] == "false"
    assert "OPENAI_API_KEY" not in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "${{ secrets." not in source
    assert "deepseek" not in source.lower()
    assert "openai" not in source.lower()


def test_llm_workflow_is_manual_only_and_read_only() -> None:
    workflow = _workflow(LLM_WORKFLOW_PATH)
    triggers = workflow["on"]

    assert set(triggers) == {"workflow_dispatch"}
    assert "push" not in triggers
    assert "pull_request" not in triggers
    assert "schedule" not in triggers
    assert workflow["permissions"] == {"contents": "read"}


def test_llm_workflow_inputs_limit_provider_and_require_cost_acknowledgement() -> None:
    inputs = _workflow(LLM_WORKFLOW_PATH)["on"]["workflow_dispatch"]["inputs"]
    provider = inputs["provider"]
    acknowledge_cost = inputs["acknowledge_cost"]

    assert provider["type"] == "choice"
    assert provider["required"] == "true"
    assert provider["options"] == ["deepseek", "openai"]
    assert acknowledge_cost["type"] == "boolean"
    assert acknowledge_cost["required"] == "true"
    assert acknowledge_cost["default"] == "false"


def test_llm_workflow_fails_closed_without_cost_acknowledgement() -> None:
    workflow = _workflow(LLM_WORKFLOW_PATH)
    authorization_job = workflow["jobs"]["authorize-cost"]
    authorization_source = "\n".join(_run_commands(authorization_job))
    provider_jobs = (
        workflow["jobs"]["deepseek-integration"],
        workflow["jobs"]["openai-integration"],
    )

    assert "inputs.acknowledge_cost != true" in _source(LLM_WORKFLOW_PATH)
    assert "exit 1" in authorization_source
    for job in provider_jobs:
        assert job["needs"] == "authorize-cost"
        assert "inputs.acknowledge_cost == true" in job["if"]
        assert job["env"]["LLM_INTEGRATION_ACKNOWLEDGE_COST"] == "true"


def test_llm_provider_jobs_are_explicit_and_protected() -> None:
    deepseek = _job(LLM_WORKFLOW_PATH, "deepseek-integration")
    openai = _job(LLM_WORKFLOW_PATH, "openai-integration")

    assert deepseek["environment"] == "llm-integration"
    assert openai["environment"] == "llm-integration"
    assert "inputs.provider == 'deepseek'" in deepseek["if"]
    assert "inputs.provider == 'openai'" in openai["if"]
    assert deepseek["env"]["LLM_PROVIDER"] == "deepseek"
    assert openai["env"]["LLM_PROVIDER"] == "openai"
    assert len(_setup_python_steps(deepseek)) == 1
    assert len(_setup_python_steps(openai)) == 1
    assert _setup_python_steps(deepseek)[0]["with"]["python-version"] == "3.13"
    assert _setup_python_steps(openai)[0]["with"]["python-version"] == "3.13"


def test_llm_provider_jobs_receive_only_the_selected_provider_configuration() -> None:
    deepseek_environment = _job(
        LLM_WORKFLOW_PATH,
        "deepseek-integration",
    )["env"]
    openai_environment = _job(
        LLM_WORKFLOW_PATH,
        "openai-integration",
    )["env"]

    assert deepseek_environment["DEEPSEEK_API_KEY"] == (
        "${{ secrets.DEEPSEEK_API_KEY }}"
    )
    assert deepseek_environment["DEEPSEEK_BASE_URL"] == (
        "${{ vars.DEEPSEEK_BASE_URL }}"
    )
    assert deepseek_environment["DEEPSEEK_DEFAULT_MODEL"] == (
        "${{ vars.DEEPSEEK_DEFAULT_MODEL }}"
    )
    assert not any(key.startswith("OPENAI_") for key in deepseek_environment)

    assert openai_environment["OPENAI_API_KEY"] == (
        "${{ secrets.OPENAI_API_KEY }}"
    )
    assert openai_environment["OPENAI_BASE_URL"] == (
        "${{ vars.OPENAI_BASE_URL }}"
    )
    assert openai_environment["OPENAI_DEFAULT_MODEL"] == (
        "${{ vars.OPENAI_DEFAULT_MODEL }}"
    )
    assert not any(key.startswith("DEEPSEEK_") for key in openai_environment)


def test_llm_workflow_runs_only_real_llm_integration_without_fallback() -> None:
    source = _source(LLM_WORKFLOW_PATH)
    lowered_source = source.lower()

    for job_name in ("deepseek-integration", "openai-integration"):
        job = _job(LLM_WORKFLOW_PATH, job_name)
        commands = _run_commands(job)
        assert "python -m pytest --run-llm-integration" in commands
        assert all("--run-integration" not in command for command in commands)
        assert job["defaults"]["run"]["working-directory"] == "backend"

    assert "mock" not in lowered_source
    assert "continue-on-error" not in lowered_source
    assert "strategy:" not in lowered_source
    assert "retry" not in lowered_source


def test_llm_workflow_validates_configuration_without_printing_secrets() -> None:
    source = _source(LLM_WORKFLOW_PATH)
    lowered_source = source.lower()

    assert 'test -n "$DEEPSEEK_API_KEY"' in source
    assert 'test -n "$OPENAI_API_KEY"' in source
    assert "printenv" not in lowered_source
    assert "set -x" not in lowered_source
    assert 'echo "$DEEPSEEK' not in source
    assert 'echo "$OPENAI' not in source
    assert "authorization" not in lowered_source
    assert "prompt" not in lowered_source
    assert "response" not in lowered_source
    assert "chunk" not in lowered_source


def test_default_ci_remains_separate_and_secret_free() -> None:
    source = _source(DEFAULT_CI_PATH)

    assert "python -m pytest" in source
    assert "--run-integration" not in source
    assert "--run-llm-integration" not in source
    assert "${{ secrets." not in source
    assert "OPENAI_API_KEY" not in source
    assert "DEEPSEEK_API_KEY" not in source


def test_integration_workflow_documentation_matches_the_implemented_scope() -> None:
    postgres_doc = _source(POSTGRES_DOC_PATH)
    llm_doc = _source(LLM_DOC_PATH)
    default_doc = _source(DEFAULT_TESTS_DOC_PATH)
    documentation = "\n".join((postgres_doc, llm_doc, default_doc))

    assert "PostgreSQL 17" in postgres_doc
    assert "--run-integration" in postgres_doc
    assert "不是默认 CI" in postgres_doc
    assert "不运行真实 LLM" in postgres_doc
    assert "Phase 7 已取得该 Workflow 在真实 GitHub Runner 通过的证据" in postgres_doc
    assert "后续 Schema 变更仍须重新运行" in postgres_doc
    assert "workflow_dispatch" in llm_doc
    assert "protected environment" in llm_doc
    assert "acknowledge_cost" in llm_doc
    assert "--run-llm-integration" in llm_doc
    assert "不会回退到 Mock" in llm_doc
    assert "未运行" in llm_doc
    assert re.search(
        r"默认 CI 不运行 Integration\s+Workflows",
        default_doc,
    )
    assert "Phase 7 已冻结" not in documentation
    assert "Phase 7 Freeze" not in documentation
