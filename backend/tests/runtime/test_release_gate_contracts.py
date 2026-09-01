"""Static contracts for frozen Phase 7 and pending Phase 8 release evidence."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RELEASE_GATE = PROJECT_ROOT / "docs/operations/release-gate.md"
PHASE_8_RELEASE_GATE = PROJECT_ROOT / "docs/operations/phase8-release-gate.md"
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"
ADR = PROJECT_ROOT / "docs/adr/0001-runtime-release-baseline.md"
DEFAULT_CI = PROJECT_ROOT / ".github/workflows/ci.yml"
POSTGRES_CI = PROJECT_ROOT / ".github/workflows/postgres-integration.yml"
LLM_CI = PROJECT_ROOT / ".github/workflows/llm-integration.yml"

HISTORICAL_PENDING_CONCLUSION = (
    "Phase 7 — Runtime, Docker, CI and Release Gate Freeze Pending。"
)
FROZEN_STATUS = "Passed / Freeze"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflow(path: Path) -> dict[str, Any]:
    document = yaml.load(_source(path), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _run_commands(path: Path) -> tuple[str, ...]:
    workflow = _workflow(path)
    return tuple(
        str(step["run"]).strip()
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "run" in step
    )


def test_release_gate_artifacts_exist() -> None:
    assert RELEASE_GATE.is_file()
    assert PHASE_8_RELEASE_GATE.is_file()
    assert CHANGELOG.is_file()
    assert ADR.is_file()


def test_phase_8_release_gate_records_scope_evidence_and_pending_status() -> None:
    release_gate = _source(PHASE_8_RELEASE_GATE)

    assert "当前状态：**Freeze Review Pending**" in release_gate
    for step in range(1, 7):
        assert f"| {step} |" in release_gate
    assert "| 7 |" in release_gate
    assert "`ac11520`" in release_gate
    assert "Default Offline CI" in release_gate
    assert "PostgreSQL Integration CI" in release_gate
    assert "Manual Real LLM Integration：`Not Run`" in release_gate
    assert "Real LLM Cost：`0`" in release_gate
    assert "Phase 8 尚未 Freeze" in release_gate
    assert "当前不得创建新 tag" in release_gate
    assert "Phase 8 已冻结" not in release_gate


def test_phase_8_freeze_review_checklist_is_complete() -> None:
    release_gate = _source(PHASE_8_RELEASE_GATE)

    for required_check in (
        "Git working tree clean",
        "Default Offline CI 在 Step 7 当前 commit",
        "PostgreSQL Integration CI 在 Step 7 当前 commit",
        "本地 Python 3.13",
        "20260901_0002",
        "Phase 3–7 冻结边界",
        "既有无状态 Chat API 契约未改变",
        "独立 Conversation API 契约已完整记录",
        "Real LLM Integration 保持 `Not Run`",
        "Real LLM Cost 为 `0`",
        "真实 API Key",
        "Dockerfile、Compose topology 与 GitHub workflow",
        "Manual LLM workflow deployment",
        "Phase 8 Implementation Step 1–7",
        "独立 Freeze Review 已通过",
    ):
        assert required_check in release_gate

    assert release_gate.count("- [ ]") == 15


def test_release_gate_defines_evidence_statuses() -> None:
    release_gate = _source(RELEASE_GATE)

    for status in ("Passed", "Skipped", "Not Run", "Failed"):
        assert status in release_gate
    assert "未运行不能写成通过" in release_gate
    assert "不得计为 Passed" in release_gate


def test_release_gate_documents_all_test_entry_points() -> None:
    release_gate = _source(RELEASE_GATE)

    assert "python -m pytest" in release_gate
    assert "python -m pytest --run-integration" in release_gate
    assert "python -m pytest --run-llm-integration" in release_gate
    assert "LLM_INTEGRATION_ACKNOWLEDGE_COST=true" in release_gate


def test_release_gate_documents_docker_and_compose_smoke_commands() -> None:
    release_gate = _source(RELEASE_GATE)

    assert "docker build --tag" in release_gate
    assert "docker run --rm" in release_gate
    assert "docker compose --env-file .env.docker config" in release_gate
    assert "docker compose --env-file .env.docker up --build --detach" in release_gate
    assert "curl --fail http://localhost:8000/health" in release_gate
    assert "curl --fail http://localhost:8000/ready" in release_gate
    assert "curl --fail http://localhost:8000/version" in release_gate


def test_release_gate_records_current_dynamic_and_runner_evidence() -> None:
    release_gate = _source(RELEASE_GATE)

    assert "当前云服务器验证记录（Passed）" in release_gate
    assert "Default Offline CI | `5b411cb` | `Passed`" in release_gate
    assert "PostgreSQL Integration CI | `5b411cb` | `Passed`" in release_gate
    assert "DeepSeek job 的最终状态为\n`Cancelled`" in release_gate
    assert "OpenAI job 为 `Skipped`" in release_gate
    assert "Real LLM Cost：`0`" in release_gate
    assert "`v0.7.0` 已创建、推送并指向 commit `5b411cb`" in release_gate

    # Historical Not Run evidence remains auditable but is not the current state.
    assert (
        "Docker dynamic verification: Not Run — "
        "Docker/Podman/nerdctl/buildah unavailable on this machine."
    ) in release_gate
    assert (
        "GitHub Actions runtime execution: Not Run — workflows created but "
        "not triggered on GitHub Runner."
    ) in release_gate
    assert "PostgreSQL Integration workflow: Not Run" in release_gate
    assert "Real LLM Integration: Not Run" in release_gate


def test_phase_7_is_frozen_and_preserves_its_historical_pending_record() -> None:
    release_gate = _source(RELEASE_GATE)
    changelog = _source(CHANGELOG)
    adr = _source(ADR)

    assert FROZEN_STATUS in release_gate
    assert "该 Release 的状态：**Freeze（`v0.7.0`）**" in changelog
    assert "当前状态：**Phase 7 Freeze**" in adr
    assert HISTORICAL_PENDING_CONCLUSION in release_gate
    assert HISTORICAL_PENDING_CONCLUSION in changelog
    assert HISTORICAL_PENDING_CONCLUSION in adr
    assert "`v0.7.0` 不得移动、删除或重建" in release_gate


def test_changelog_records_phase_7_scope_and_current_runtime_evidence() -> None:
    changelog = _source(CHANGELOG)

    for capability in (
        "Git 仓库",
        "Backend Runtime 镜像静态契约",
        "环境模板",
        "Compose 拓扑",
        "Secret Hygiene",
        "默认离线 CI",
        "PostgreSQL Integration Workflow",
        "LLM Integration Workflow",
        "Release Gate",
    ):
        assert capability in changelog
    assert "Docker image dynamic build/run 通过" in changelog
    assert "Default Offline CI 已在真实 GitHub Runner 上执行并通过" in changelog
    assert "PostgreSQL Integration CI 已在真实 GitHub Runner 上执行并通过" in changelog
    assert "Real DeepSeek/OpenAI Integration" in changelog
    assert "Real LLM Integration 已通过" not in changelog


def test_changelog_preserves_the_phase_6_freeze_baseline() -> None:
    changelog = _source(CHANGELOG)

    assert "[v0.6.0] — Phase 6 Freeze baseline" in changelog
    assert "`1afd8a4`" in changelog
    assert "真实 DeepSeek/OpenAI Integration 保持未运行" in changelog


def test_adr_records_the_runtime_and_release_decisions() -> None:
    adr = _source(ADR)

    assert "Python 3.13" in adr
    assert "Migration 使用与 Backend 相同的镜像" in adr
    assert "Backend 不自行执行 Migration" in adr
    assert "默认 Provider 为 `mock`" in adr
    assert "零真实 API Key" in adr
    assert "PostgreSQL Integration 与默认 CI 分离" in adr
    assert "真实 LLM Integration 只能手动触发" in adr
    assert "人工确认成本" in adr
    assert "绝不把 `Not Run` 写成" in adr


def test_release_gate_preserves_phase_3_to_6_boundaries() -> None:
    release_gate = _source(RELEASE_GATE)

    for boundary in (
        "Persistence Layer 不得反向依赖",
        "Provider Interface",
        "无状态 Chat Completions JSON/SSE",
        "Chat API 不感知具体 Provider",
        "ChatService 只调用 LLMService",
        "Bootstrap",
        "Factory",
        "Registry",
        "自动 retry",
        "LLM `/ready` 远程探活",
    ):
        assert boundary in release_gate


def test_default_ci_still_runs_only_default_offline_pytest() -> None:
    workflow = _workflow(DEFAULT_CI)
    commands = _run_commands(DEFAULT_CI)
    source = _source(DEFAULT_CI)

    assert set(workflow["on"]) == {"push", "pull_request"}
    assert commands[-1] == "python -m pytest"
    assert all("--run-integration" not in command for command in commands)
    assert all("--run-llm-integration" not in command for command in commands)
    assert "${{ secrets." not in source


def test_integration_workflows_remain_separate_from_default_ci() -> None:
    postgres = _workflow(POSTGRES_CI)
    llm = _workflow(LLM_CI)
    postgres_commands = _run_commands(POSTGRES_CI)
    llm_commands = _run_commands(LLM_CI)

    assert "pull_request" not in postgres["on"]
    assert set(llm["on"]) == {"workflow_dispatch"}
    assert "python -m pytest --run-integration" in postgres_commands
    assert all("--run-llm-integration" not in command for command in postgres_commands)
    assert "python -m pytest --run-llm-integration" in llm_commands
    assert all("--run-integration" not in command for command in llm_commands)


def test_release_gate_contracts_are_static_and_require_no_docker() -> None:
    tree = ast.parse(_source(Path(__file__)), filename=__file__)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert {"subprocess", "docker", "socket"}.isdisjoint(imported_modules)
