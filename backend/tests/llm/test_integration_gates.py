"""Offline tests for explicit, cost-aware LLM integration gates."""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import conftest as suite_config


type ProviderEnvironmentLoader = Callable[
    [str, tuple[str, ...]],
    Mapping[str, str],
]

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"
DEEPSEEK_ENVIRONMENT = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_DEFAULT_MODEL",
)
OPENAI_ENVIRONMENT = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_DEFAULT_MODEL",
)


class _Config:
    def __init__(
        self,
        *,
        run_postgresql: bool,
        run_llm: bool,
    ) -> None:
        self._options = {
            "--run-integration": run_postgresql,
            "--run-llm-integration": run_llm,
        }

    def getoption(self, option_name: str) -> bool:
        return self._options[option_name]


class _Item:
    def __init__(self, *markers: str) -> None:
        self.keywords = dict.fromkeys(markers, True)
        self.added_markers: list[object] = []

    def add_marker(self, marker: object) -> None:
        self.added_markers.append(marker)


def _skip_reasons(item: _Item) -> tuple[str, ...]:
    return tuple(
        str(getattr(marker, "kwargs")["reason"])
        for marker in item.added_markers
    )


def test_llm_integration_requires_its_own_cli_switch() -> None:
    reason = suite_config._llm_integration_skip_reason(
        run_requested=False,
        cost_acknowledged=True,
    )

    assert reason == "requires explicit --run-llm-integration"


def test_llm_integration_requires_explicit_cost_acknowledgement() -> None:
    reason = suite_config._llm_integration_skip_reason(
        run_requested=True,
        cost_acknowledged=False,
    )

    assert reason is not None
    assert "explicit cost acknowledgement" in reason
    assert "LLM_INTEGRATION_ACKNOWLEDGE_COST=true" in reason


@pytest.mark.parametrize(
    (
        "run_postgresql",
        "run_llm",
        "cost_acknowledgement",
        "expected_skip_fragment",
    ),
    (
        (False, False, None, "--run-llm-integration"),
        (True, False, "true", "--run-llm-integration"),
        (False, True, None, "explicit cost acknowledgement"),
        (False, True, "true", None),
    ),
)
def test_collection_hook_applies_only_the_llm_gate(
    monkeypatch: pytest.MonkeyPatch,
    run_postgresql: bool,
    run_llm: bool,
    cost_acknowledgement: str | None,
    expected_skip_fragment: str | None,
) -> None:
    if cost_acknowledgement is None:
        monkeypatch.delenv(
            "LLM_INTEGRATION_ACKNOWLEDGE_COST",
            raising=False,
        )
    else:
        monkeypatch.setenv(
            "LLM_INTEGRATION_ACKNOWLEDGE_COST",
            cost_acknowledgement,
        )
    item = _Item("llm_integration")

    suite_config.pytest_collection_modifyitems(
        _Config(
            run_postgresql=run_postgresql,
            run_llm=run_llm,
        ),
        [item],
    )

    reasons = _skip_reasons(item)
    if expected_skip_fragment is None:
        assert reasons == ()
    else:
        assert len(reasons) == 1
        assert expected_skip_fragment in reasons[0]


def test_llm_switch_does_not_enable_postgresql_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_INTEGRATION_ACKNOWLEDGE_COST", "true")
    item = _Item("integration")

    suite_config.pytest_collection_modifyitems(
        _Config(run_postgresql=False, run_llm=True),
        [item],
    )

    reasons = _skip_reasons(item)
    assert len(reasons) == 1
    assert "PostgreSQL" in reasons[0]


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    (
        (None, False),
        ("", False),
        ("1", False),
        ("yes", False),
        ("false", False),
        ("true", True),
        (" TRUE ", True),
    ),
)
def test_cost_acknowledgement_accepts_only_explicit_true(
    configured_value: str | None,
    expected: bool,
) -> None:
    environment = (
        {}
        if configured_value is None
        else {"LLM_INTEGRATION_ACKNOWLEDGE_COST": configured_value}
    )

    assert suite_config._llm_cost_is_acknowledged(environment) is expected


@pytest.mark.parametrize(
    (
        "is_postgresql",
        "run_postgresql",
        "is_llm",
        "run_llm",
        "cost_acknowledged",
        "expected",
    ),
    (
        (False, False, False, False, False, False),
        (False, True, False, False, False, False),
        (False, False, False, True, True, False),
        (False, True, True, False, True, False),
        (True, False, False, True, True, False),
        (True, True, False, False, False, True),
        (False, False, True, True, False, False),
        (False, False, True, True, True, True),
    ),
)
def test_network_permission_keeps_integration_families_isolated(
    is_postgresql: bool,
    run_postgresql: bool,
    is_llm: bool,
    run_llm: bool,
    cost_acknowledged: bool,
    expected: bool,
) -> None:
    allowed = suite_config._external_network_is_allowed(
        is_postgresql_integration=is_postgresql,
        run_postgresql_integration=run_postgresql,
        is_llm_integration=is_llm,
        run_llm_integration=run_llm,
        cost_acknowledged=cost_acknowledged,
    )

    assert allowed is expected


@pytest.mark.parametrize(
    ("provider_name", "required_environment", "missing_variable"),
    tuple(
        pytest.param(
            "DeepSeek",
            DEEPSEEK_ENVIRONMENT,
            missing_variable,
            id=f"deepseek-{missing_variable.lower()}",
        )
        for missing_variable in DEEPSEEK_ENVIRONMENT
    )
    + tuple(
        pytest.param(
            "OpenAI",
            OPENAI_ENVIRONMENT,
            missing_variable,
            id=f"openai-{missing_variable.lower()}",
        )
        for missing_variable in OPENAI_ENVIRONMENT
    ),
)
def test_missing_provider_configuration_skips_with_variable_names_only(
    monkeypatch: pytest.MonkeyPatch,
    require_llm_provider_environment: ProviderEnvironmentLoader,
    provider_name: str,
    required_environment: tuple[str, ...],
    missing_variable: str,
) -> None:
    for variable_name in required_environment:
        monkeypatch.setenv(variable_name, "sensitive-provider-value-never-render")
    monkeypatch.delenv(missing_variable)

    with pytest.raises(pytest.skip.Exception) as exc_info:
        require_llm_provider_environment(
            provider_name,
            required_environment,
        )

    reason = str(exc_info.value)
    assert provider_name in reason
    assert missing_variable in reason
    assert "sensitive-provider-value-never-render" not in reason
    assert "Authorization" not in reason


def test_provider_environment_gate_requires_only_the_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
    require_llm_provider_environment: ProviderEnvironmentLoader,
) -> None:
    configured_values = {
        "DEEPSEEK_API_KEY": "offline-gate-value",
        "DEEPSEEK_BASE_URL": "https://deepseek.example.test/v1",
        "DEEPSEEK_DEFAULT_MODEL": "offline-gate-model",
    }
    for variable_name, value in configured_values.items():
        monkeypatch.setenv(variable_name, value)
    for variable_name in OPENAI_ENVIRONMENT:
        monkeypatch.delenv(variable_name, raising=False)

    loaded = require_llm_provider_environment(
        "DeepSeek",
        DEEPSEEK_ENVIRONMENT,
    )

    assert set(loaded) == set(DEEPSEEK_ENVIRONMENT)


def test_llm_integration_marker_is_registered_separately() -> None:
    configuration = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    markers = configuration["tool"]["pytest"]["ini_options"]["markers"]

    assert any(marker.startswith("llm_integration:") for marker in markers)
    assert any(marker.startswith("integration:") for marker in markers)
