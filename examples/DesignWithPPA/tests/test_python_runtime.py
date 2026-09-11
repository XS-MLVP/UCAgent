"""Focused DesignWithPPA workflow tests: python runtime."""

from __future__ import annotations

from helpers import (
    PLUGIN_SOURCE,
    REPOSITORY_ROOT,
    _config,
    _write_json,
    _write_workspace_python_dut,
)

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
import pytest
from design_with_ppa.checkers import (  # noqa: E402
    DesignAllPassBatchTestsChecker,
    DesignArchitectureChecker,
    DesignCoverageGroupBatchChecker,
    DesignCoverageStructureChecker,
    DesignDocumentationSyncChecker,
    DesignFinalDeliveryChecker,
    DesignFunctionalContractChecker,
    DesignInputContractChecker,
    DesignDutApiChecker,
    DesignLabelStructureChecker,
    DesignLineMapReferenceChecker,
    DesignMarkdownFileFormatChecker,
    DesignObservationContractChecker,
    DesignObservationInstrumentationChecker,
    DesignRandomTestCasesChecker,
    DesignRefineTestCasesChecker,
    DesignLabelStructureRefineChecker,
    DesignSpecLineMapBatchChecker,
    DesignTestTemplateChecker,
    DesignPythonAllPassChecker,
    PPABaseCharacterizationChecker,
    PPABestVersionChecker,
    PPACandidateOptimizationChecker,
    PPAIterationChecker,
    PPAResultArtifactsChecker,
    PerformanceArtifactChecker,
    PerformanceContractChecker,
    PerformanceTestContractChecker,
    PythonAdapterContractChecker,
    PythonEnvFixtureContractChecker,
    PythonExecutableSpecChecker,
    PythonReferenceContractChecker,
    PythonReferenceRegressionChecker,
    RTLAllPassRegressionChecker,
    RTLBackendBuildChecker,
    RTLLineCoverageChecker,
    RTLSourceEvidenceChecker,
    _api_assertion_quality_violations,
    _actionable_checker_failure,
    _bounded_checker_value,
    _cleanup_transient_coverage_data,
    _coverage_fixture_lifecycle_violations,
    _hash_rows,
    _ppa_selection_score,
    _public_pytest_failure,
    _pytest_evidence,
    _rtl_regression_failure_evidence,
    _run_pytest,
    _run_workflow_ppa,
    select_best_accepted_record,
)
from design_with_ppa.python_dut import (  # noqa: E402
    PinSpec,
    PythonDUTError,
    ReferenceDUT,
    create_dut,
    managed_test_implementation,
    register_managed_test_options,
)
from design_with_ppa.rtl import (  # noqa: E402
    CHISEL_MILL_VERSION,
    CHISEL_SCALA_VERSION,
    CHISEL_VERSION,
    ChiselLanguageBackend,
    PreparedRTL,
    RTLLanguageBackend,
    RTLLanguageError,
    RTLPreparationRequest,
    RTLSourceTemplate,
    RTLSourceValidation,
    available_rtl_languages,
    build_rtl_template_context,
    discover_rtl_libraries,
    discover_rtl_sources,
    _workspace_python_dut_root,
    register_rtl_language,
    resolve_rtl_config,
    unregister_rtl_language,
)
from ucagent.util.config import (  # noqa: E402
    Config,
    build_runtime_config,
    get_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)




def test_python_executable_spec_checker_uses_managed_pytest_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The early executable-spec gate must validate sources and delegate execution."""

    output = tmp_path / "output"
    tests = output / "tests"
    tests.mkdir(parents=True)
    (output / "dut_architecture.md").write_text(
        "\n# Architecture\n\n## Contract\n\n```yaml\n"
        "architecture:\n"
        "  design_intent: combinational\n"
        "  parameters: []\n"
        "  ports:\n"
        "    - {name: data_i, direction: input, width: 8, signed: false}\n"
        "    - {name: ready_o, direction: output, width: 1, signed: false}\n"
        "  clock_reset: {clocks: [], resets: []}\n"
        "```\n",
        encoding="utf-8",
    )
    (tests / "dut_reference.py").write_text(
        '"""Reference."""\n'
        "from design_with_ppa import PinSpec, ReferenceDUT\n\n"
        "class dutReference(ReferenceDUT):\n"
        "    PIN_SPECS = (\n"
        "        PinSpec('data_i', 'input', width=8),\n"
        "        PinSpec('ready_o', 'output'),\n"
        "    )\n"
        "    def reset(self):\n"
        "        self.reset_pins()\n"
        "        self.RefreshComb()\n"
        "    def _refresh_comb(self):\n"
        "        self.drive_output('ready_o', 1)\n",
        encoding="utf-8",
    )
    (tests / "dut_adapter.py").write_text(
        '"""Adapter."""\n'
        "from design_with_ppa import create_dut\n"
        "from dut_reference import dutReference\n\n"
        "class dutAdapter:\n"
        "    def __init__(self, backend):\n"
        "        self._dut = create_dut(backend, dutReference)\n"
        "        self._dut.GetXPort().AsImmWrite()\n"
        "        self._active_transactions = {}\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(self._dut, name)\n"
        "    def bind_coverage(self, groups):\n"
        "        self.groups = groups\n"
        "    def configure_test_artifacts(self, coverage_path, waveform_path):\n"
        "        self.paths = (coverage_path, waveform_path)\n"
        "    def _record_event(self, event, **data):\n"
        "        self.event = (event, data)\n"
        "    def _record_transaction_accepted(self, accepted_at, **identity):\n"
        "        transaction_id = 1\n"
        "        evidence = {\n"
        "            'transaction_id': transaction_id,\n"
        "            'accepted_at': accepted_at,\n"
        "            **identity,\n"
        "        }\n"
        "        self._active_transactions[transaction_id] = evidence\n"
        "        self._record_event('transaction_accepted', **evidence)\n"
        "        return transaction_id\n"
        "    def _record_transaction_observation(\n"
        "        self, transaction_id, observed_at, phase='inflight', **state\n"
        "    ):\n"
        "        accepted = self._active_transactions.get(transaction_id)\n"
        "        evidence = {\n"
        "            **accepted, 'observed_at': observed_at, 'phase': phase, **state\n"
        "        }\n"
        "        self._record_event('transaction_observation', **evidence)\n"
        "    def _record_response_observed(self, transaction_id, response_at, **result):\n"
        "        accepted = self._active_transactions.pop(transaction_id)\n"
        "        evidence = {**accepted, 'response_at': response_at, **result}\n"
        "        self._record_event('response_observed', **evidence)\n"
        "    def reset(self):\n"
        "        self._dut.RefreshComb()\n"
        "    def sample_coverage(self):\n"
        "        return None\n"
        "    def finish(self):\n"
        "        self._dut.Finish()\n\n"
        "def create_adapter(backend):\n"
        "    return dutAdapter(backend)\n",
        encoding="utf-8",
    )
    (tests / "dut_api.py").write_text(
        '"""API."""\n\n'
        "def api_dut_transaction(env, value, max_cycles=4):\n"
        "    if max_cycles < 1:\n"
        "        raise ValueError('positive integer required')\n"
        "    env.data_i.value = value\n"
        "    return value\n",
        encoding="utf-8",
    )
    (tests / "conftest.py").write_text(
        '"""Fixture."""\n'
        "import pytest\n"
        "from design_with_ppa import (\n"
        "    managed_test_implementation,\n"
        "    register_managed_test_options,\n"
        ")\n"
        "from dut_adapter import create_adapter\n\n"
        "def get_coverage_groups(env):\n"
        "    return []\n\n"
        "def pytest_addoption(parser):\n"
        "    register_managed_test_options(parser)\n\n"
        "def pytest_configure(config):\n"
        "    config.addinivalue_line(\n"
        "        'markers', 'performance: deterministic performance evidence'\n"
        "    )\n\n"
        "@pytest.fixture\n"
        "def env(request):\n"
        "    adapter = create_adapter(managed_test_implementation(request.config))\n"
        "    groups = get_coverage_groups(adapter)\n"
        "    adapter.bind_coverage(groups)\n"
        "    adapter.reset()\n"
        "    yield adapter\n"
        "    adapter.finish()\n",
        encoding="utf-8",
    )
    (tests / "test_dut_smoke.py").write_text(
        '"""Smoke."""\n'
        "import pytest\n"
        "from dut_api import api_dut_transaction\n\n"
        "def test_dut_smoke_reset(env):\n"
        "    assert env.ready_o.value == 1\n\n"
        "def test_dut_smoke_transaction(env):\n"
        "    result = api_dut_transaction(env, 7, max_cycles=4)\n"
        "    assert result == 7\n\n"
        "def test_dut_smoke_invalid(env):\n"
        "    before = env.data_i.value\n"
        "    with pytest.raises(ValueError):\n"
        "        api_dut_transaction(env, 1, max_cycles=0)\n"
        "    assert env.data_i.value == before\n",
        encoding="utf-8",
    )
    reference_checker = PythonReferenceContractChecker(
        architecture_file="output/dut_architecture.md",
        reference_file="output/tests/dut_reference.py",
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    adapter_checker = PythonAdapterContractChecker(
        architecture_file="output/dut_architecture.md",
        adapter_file="output/tests/dut_adapter.py",
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    fixture_checker = PythonEnvFixtureContractChecker(
        architecture_file="output/dut_architecture.md",
        conftest_file="output/tests/conftest.py",
    ).set_workspace(str(tmp_path))
    assert reference_checker.do_check()[0] is True
    assert adapter_checker.do_check()[0] is True
    assert fixture_checker.do_check()[0] is True

    reference_source = (tests / "dut_reference.py").read_text(encoding="utf-8")
    (tests / "dut_reference.py").write_text(
        reference_source.replace(
            "self.drive_output('ready_o', 1)", "self.ready_o = 1"
        ),
        encoding="utf-8",
    )
    passed, result = reference_checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_reference_contract_invalid"
    assert "immutable" in result["error"]
    (tests / "dut_reference.py").write_text(reference_source, encoding="utf-8")

    adapter_source = (tests / "dut_adapter.py").read_text(encoding="utf-8")
    (tests / "dut_adapter.py").write_text(
        adapter_source.replace("create_dut(backend", "build_dut(backend"),
        encoding="utf-8",
    )
    passed, result = adapter_checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_adapter_contract_invalid"
    assert "create_dut" in result["error"]
    (tests / "dut_adapter.py").write_text(adapter_source, encoding="utf-8")

    conftest_source = (tests / "conftest.py").read_text(encoding="utf-8")
    (tests / "conftest.py").write_text(
        conftest_source + "\n@pytest.fixture\ndef dut():\n    yield None\n",
        encoding="utf-8",
    )
    passed, result = fixture_checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_env_fixture_contract_invalid"
    assert "exactly one fixture named env" in result["error"]
    (tests / "conftest.py").write_text(conftest_source, encoding="utf-8")

    (tests / "conftest.py").write_text(
        conftest_source.replace("performance:", "performance_without_separator"),
        encoding="utf-8",
    )
    passed, result = fixture_checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_env_fixture_contract_invalid"
    assert "register the performance marker" in result["error"]
    (tests / "conftest.py").write_text(conftest_source, encoding="utf-8")

    (tests / "conftest.py").write_text(
        conftest_source.replace(
            "    register_managed_test_options(parser)", "    pass"
        ),
        encoding="utf-8",
    )
    passed, result = fixture_checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_env_fixture_contract_invalid"
    assert "pytest_addoption must call register_managed_test_options(parser)" in (
        result["error"]
    )
    (tests / "conftest.py").write_text(conftest_source, encoding="utf-8")

    (tests / "conftest.py").write_text(
        conftest_source.replace(
            "managed_test_implementation(request.config)",
            'getattr(request.config, "_backend", "python")',
        ),
        encoding="utf-8",
    )
    passed, result = fixture_checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_env_fixture_contract_invalid"
    assert "managed_test_implementation(request.config)" in result["error"]
    (tests / "conftest.py").write_text(conftest_source, encoding="utf-8")

    calls: list[dict[str, Any]] = []

    def fake_run_pytest(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Capture the managed runner contract without importing fixture modules."""

        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(["pytest"], 0, "3 passed", "")

    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_run_pytest)
    checker = PythonExecutableSpecChecker(
        test_dir="output/tests",
        architecture_file="output/dut_architecture.md",
        reference_file="output/tests/dut_reference.py",
        adapter_file="output/tests/dut_adapter.py",
        api_file="output/tests/dut_api.py",
        conftest_file="output/tests/conftest.py",
        smoke_test_file="output/tests/test_dut_smoke.py",
        summary_file="output/reports/dut_python_smoke.json",
        timeout=30,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    assert len(calls) == 1
    assert calls[0]["args"][2:5] == ("python", 30, [])
    assert calls[0]["kwargs"]["test_files"] == [tests / "test_dut_smoke.py"]
    assert (output / "reports" / "dut_python_smoke.json").is_file()

    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["pytest"],
            4,
            "",
            "pytest: error: unrecognized arguments: --design-backend=python\n",
        ),
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_smoke_backend_option_unregistered"
    assert "register_managed_test_options" in result["next_action"]
    assert result["artifact"] == "output/tests/conftest.py"

    def hanging_run_pytest(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Simulate a hang after one failing node."""

        del args, kwargs
        raise subprocess.TimeoutExpired(
            "pytest", 30, output="..F", stderr="native stall\n"
        )

    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest", hanging_run_pytest
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "python_executable_spec_timeout"
    assert result["observed"]["partial_stdout_tail"] == "..F"
    assert "native stall" in result["observed"]["partial_stderr_tail"]

    smoke = tests / "test_dut_smoke.py"
    smoke.write_text(
        smoke.read_text(encoding="utf-8").replace(
            "result = api_dut_transaction(env, 7, max_cycles=4)\n"
            "    assert result == 7",
            "result = api_dut_transaction(env, 0, max_cycles=4)\n"
            "    assert result == 0",
        ),
        encoding="utf-8",
    )
    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "python_executable_spec_invalid"
    assert "non-default data input" in result["error"]
    assert len(calls) == 1

    smoke.write_text(
        smoke.read_text(encoding="utf-8").replace(
            "result = api_dut_transaction(env, 0, max_cycles=4)\n"
            "    assert result == 0",
            "result = api_dut_transaction(env, 7, max_cycles=4)\n"
            "    assert result == 0",
        ),
        encoding="utf-8",
    )
    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "python_executable_spec_invalid"
    assert "non-default exact expected" in result["error"]
    assert len(calls) == 1

    smoke.write_text(
        smoke.read_text(encoding="utf-8").replace(
            "result = api_dut_transaction(env, 7, max_cycles=4)\n"
            "    assert result == 0",
            "result = api_dut_transaction(env, 7, max_cycles=4)\n"
            "    assert result == 7",
        ),
        encoding="utf-8",
    )
    adapter = tests / "dut_adapter.py"
    adapter.write_text(
        adapter.read_text(encoding="utf-8").replace(
            "evidence = {**accepted, 'response_at': response_at, **result}",
            "evidence = {'response_at': response_at, **result}",
        ),
        encoding="utf-8",
    )
    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "python_executable_spec_invalid"
    assert "must retire accepted identity" in result["error"]
    assert len(calls) == 1




def test_python_dut_contract_is_self_contained_for_stage_llm() -> None:
    """The stage must expose public signatures without implementation discovery."""

    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    ).read_text(encoding="utf-8")
    guide = (
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "python_dut_interface.md"
    ).read_text(encoding="utf-8")

    assert "PinSpec(" in guide
    assert "initial: int = 0" in guide
    assert "ReferenceDUT(pin_specs: Iterable[PinSpec] | None = None)" in guide
    assert "reference_factory: Callable[[], ReferenceDUT]" in guide
    assert "_capture_model_state()" in guide
    assert "InitClock(name: str)" in guide
    assert "本文件定义了编写 reference 和 adapter 所需的完整公共接口" in guide
    assert "不调用内建 Explore/task/subagent" in workflow
    assert "只从 `design_with_ppa` 导入 `PinSpec` 和 `ReferenceDUT`" in workflow




def test_adapter_template_defines_real_backend_neutral_coverage_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generated adapters must expose event evidence without letting tests fake pins."""

    template = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "templates"
        / "unit_design"
        / "tests"
        / "{{DUT}}_adapter.py"
    ).read_text(encoding="utf-8")
    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    ).read_text(encoding="utf-8")
    guide = (
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "design_ut_contract.md"
    ).read_text(encoding="utf-8")
    interface_guide = (
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "python_dut_interface.md"
    ).read_text(encoding="utf-8")
    backend_guide = (
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "rtl_backend.md"
    ).read_text(encoding="utf-8")
    skill = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "skills"
        / "rtl-tdd-backend"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert 'self._last_event = "initialized"' in template
    assert "self._last_event_data = MappingProxyType({})" in template
    assert "self._active_transactions = {}" in template
    assert "def last_event(self):" in template
    assert "def last_event_data(self):" in template
    assert "def _record_event(self, event, **data):" in template
    assert "def _record_transaction_accepted(self, accepted_at, **identity):" in template
    assert "def _record_transaction_observation(" in template
    assert "def _record_response_observed(self, transaction_id, response_at, **result):" in template
    assert "self._active_transactions[transaction_id] = MappingProxyType(evidence)" in template
    assert "accepted = self._active_transactions.get(transaction_id)" in template
    assert "accepted = self._active_transactions.pop(transaction_id, None)" in template
    assert 'self._record_event("response_observed", **evidence)' in template
    assert template.index("self._last_event = event") < template.index(
        "self.sample_coverage()"
    )
    assert "accepted/observation/response 三个 transaction helper" in workflow
    assert "测试不得伪造事件" in workflow
    assert "真实 post-refresh/post-step 等待点" in workflow
    assert "本阶段只修改 `{OUT}/tests/{DUT}_adapter.py` 与 `{OUT}/tests/{DUT}_api.py`" in workflow
    assert "不得直接调用 `_record_event()`" in guide
    for contract in (guide, interface_guide, backend_guide, skill):
        assert "_record_transaction_accepted" in contract
        assert "_record_transaction_observation" in contract
        assert "_record_response_observed" in contract

    parsed = load_yaml_with_env_vars(
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    coverage_stage = next(
        stage
        for parent in parsed["stage"]
        for stage in parent.get("stage", [])
        if stage["name"] == "functional_coverage_checkpoints"
    )
    assert coverage_stage["output_files"] == [
        "{OUT}/tests/{DUT}_function_coverage_def.py",
    ]

    reference_module = ModuleType("dut_reference")

    class dutReference:
        """Stand in for the generated reference during trusted template testing."""

    reference_module.dutReference = dutReference
    monkeypatch.setitem(sys.modules, "dut_reference", reference_module)
    namespace: dict[str, Any] = {"__name__": "trusted_adapter_template"}
    exec(compile(template.replace("{{DUT}}", "dut"), "dut_adapter.py", "exec"), namespace)
    adapter = object.__new__(namespace["dutAdapter"])
    adapter.coverage_groups = []
    adapter._next_transaction_id = 1
    adapter._active_transactions = {}
    adapter._last_event = "initialized"
    adapter._last_event_data = None

    transaction_id = adapter._record_transaction_accepted(
        4, operation="matmul", precision="fp8", input_hash="abc"
    )
    assert adapter.last_event_data["operation"] == "matmul"
    with pytest.raises(TypeError):
        adapter._active_transactions[transaction_id]["operation"] = "other"
    adapter._record_transaction_observation(
        transaction_id, 5, phase="backpressure", ready=0, valid=1
    )
    assert adapter.last_event == "transaction_observation"
    assert adapter.last_event_data["precision"] == "fp8"
    assert adapter.last_event_data["ready"] == 0
    assert transaction_id in adapter._active_transactions
    with pytest.raises(ValueError, match="unknown transaction"):
        adapter._record_transaction_observation(999, 5, ready=0)
    adapter._record_response_observed(
        transaction_id, 7, latency_cycles=3, result_hash="def"
    )
    assert adapter.last_event == "response_observed"
    assert adapter.last_event_data["input_hash"] == "abc"
    assert adapter.last_event_data["latency_cycles"] == 3
    assert transaction_id not in adapter._active_transactions
    with pytest.raises(ValueError, match="unknown transaction"):
        adapter._record_response_observed(transaction_id, 8, result_hash="ghi")




def test_python_regression_executes_workspace_code_only_in_child_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A regression Checker must not import test or DUT modules into UCAgent."""

    pollution_key = "DESIGN_WITH_PPA_PARENT_POLLUTION"
    monkeypatch.delenv(pollution_key, raising=False)
    tests = tmp_path / "output" / "tests"
    tests.mkdir(parents=True)
    (tests / "conftest.py").write_text(
        "def pytest_addoption(parser):\n"
        "    parser.addoption('--design-backend', choices=('python', 'rtl'))\n",
        encoding="utf-8",
    )
    test_file = tests / "test_child_pollution.py"
    test_file.write_text(
        "import os\n"
        f"os.environ[{pollution_key!r}] = 'child-only'\n\n"
        "def test_child_execution():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    checker = PythonReferenceRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_*.py",
        summary_file="output/reports/python.json",
        markdown_summary_file=None,
        timeout=30,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    assert pollution_key not in os.environ
    assert test_file.stem not in sys.modules




@pytest.mark.parametrize(
    ("statement", "expected_reason"),
    [
        ("assert env._dut.valid_o.value == 1", "private_dut_access"),
        ("env._record_event('accepted')", "private_event_injection"),
        (
            "env._record_response_observed(1, 2, result=3)",
            "private_event_injection",
        ),
        (
            "assert not env._active_transactions",
            "private_transaction_evidence_access",
        ),
        ("env.last_event = 'accepted'", "event_evidence_assignment"),
    ],
)
def test_python_regression_rejects_environment_bypasses_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statement: str,
    expected_reason: str,
) -> None:
    """Final regressions must statically reject fabricated environment evidence."""

    tests = tmp_path / "output" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_dut_functional.py").write_text(
        "def test_dut_contract(env):\n"
        f"    {statement}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *_args, **_kwargs: pytest.fail("invalid test must not execute"),
    )
    checker = PythonReferenceRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_*.py",
        summary_file="output/reports/python.json",
        markdown_summary_file=None,
        timeout=30,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "python_environment_bypass"
    assert expected_reason in json.dumps(result["observed"])




def test_plugin_pytest_runner_retains_only_failed_rtl_waveform_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed RTL waves remain debuggable while successful transient data is cleaned."""

    test_dir = tmp_path / "output" / "tests"
    session = test_dir / "data" / "toffee_tmp_20260908090000_001"
    session.mkdir(parents=True)
    waveform = session / "test_dut_case.vcd"
    waveform.write_text("$date\n$end\n", encoding="ascii")
    returncodes = iter((1, 0))

    def fake_run(command, **kwargs):
        """Return one failed then one passing managed RTL run."""

        del kwargs
        return subprocess.CompletedProcess(command, next(returncodes), "", "")

    monkeypatch.setattr("design_with_ppa.checkers.runtime.subprocess.run", fake_run)
    first = _run_pytest(
        tmp_path,
        test_dir,
        "rtl",
        30,
        [],
        rtl_dut_identity=("dut", "DUTdut"),
    )
    assert first.returncode == 1
    assert waveform.is_file()

    second = _run_pytest(
        tmp_path,
        test_dir,
        "rtl",
        30,
        [],
        rtl_dut_identity=("dut", "DUTdut"),
    )
    assert second.returncode == 0
    assert not session.exists()




def test_plugin_pytest_runner_exposes_public_performance_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plugin-managed tests must import helpers in installed and source modes."""

    test_dir = tmp_path / "output" / "tests"
    test_dir.mkdir(parents=True)
    observed: dict[str, Any] = {}

    def fake_run(command, **kwargs):
        """Capture the isolated pytest environment."""

        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "1 passed\n", "")

    monkeypatch.setattr("design_with_ppa.checkers.runtime.subprocess.run", fake_run)

    result = _run_pytest(
        tmp_path,
        test_dir,
        "rtl",
        30,
        [],
        rtl_dut_identity=("dut", "DUTdut"),
    )

    assert result.returncode == 0
    rootdir_index = observed["command"].index("--rootdir")
    assert observed["command"][rootdir_index + 1] == str(tmp_path)
    assert "--design-backend=rtl" in observed["command"]
    import_roots = observed["environment"]["PYTHONPATH"].split(os.pathsep)
    assert str(PLUGIN_SOURCE) in import_roots
    assert str(REPOSITORY_ROOT) in import_roots
    assert import_roots.index(str(PLUGIN_SOURCE)) < import_roots.index(str(tmp_path))
    assert observed["environment"]["_DESIGN_WITH_PPA_RTL_DUT_MODULE"] == "dut"
    assert observed["environment"]["_DESIGN_WITH_PPA_RTL_DUT_CLASS"] == "DUTdut"




def test_managed_test_option_defaults_to_python_and_accepts_rtl() -> None:
    """The public pytest option must keep direct workspace tests reproducible."""

    registration: dict[str, object] = {}

    class Parser:
        """Capture one pytest option registration."""

        def addoption(self, name: str, **kwargs: object) -> None:
            """Store the registered option and its contract."""

            registration.update(name=name, **kwargs)

    class Config:
        """Provide a minimal pytest configuration selector."""

        def __init__(self, value: str) -> None:
            self.value = value

        def getoption(self, name: str) -> str:
            """Return the configured value for the backend option."""

            assert name == "--design-backend"
            return self.value

    register_managed_test_options(Parser())

    assert registration == {
        "name": "--design-backend",
        "choices": ("python", "rtl"),
        "default": "python",
        "help": "Select the executable-spec or RTL test mode.",
    }
    assert managed_test_implementation(Config("python")) == "python"
    assert managed_test_implementation(Config("rtl")) == "rtl"
    with pytest.raises(PythonDUTError, match="managed test implementation"):
        managed_test_implementation(Config("unknown"))




def test_workspace_python_dut_supports_direct_pytest_after_move(
    tmp_path: Path,
) -> None:
    """A complete workspace must retain a directly runnable RTL pytest backend."""

    original = tmp_path / "original-workspace"
    tests = original / "design" / "tests"
    tests.mkdir(parents=True)
    (tests / "dut_reference.py").write_text(
        '"""Minimal reference source used to locate the moved workspace."""\n\n'
        "from design_with_ppa import ReferenceDUT\n\n\n"
        "class DUTReference(ReferenceDUT):\n"
        '    """Provide a reference factory for backend selection."""\n',
        encoding="utf-8",
    )
    (tests / "conftest.py").write_text(
        '"""Select the portable RTL runtime for a direct pytest invocation."""\n\n'
        "import pytest\n\n"
        "from design_with_ppa import create_dut\n"
        "from dut_reference import DUTReference\n\n\n"
        "def pytest_addoption(parser):\n"
        '    """Expose the same backend selector as the workflow template."""\n\n'
        "    parser.addoption(\n"
        '        "--design-backend", choices=("python", "rtl"), default="python"\n'
        "    )\n\n\n"
        "@pytest.fixture\n"
        "def dut(request):\n"
        '    """Create the selected backend through the installed plugin API."""\n\n'
        "    value = create_dut(\n"
        '        request.config.getoption("--design-backend"), DUTReference\n'
        "    )\n"
        "    yield value\n"
        "    value.Finish()\n",
        encoding="utf-8",
    )
    (tests / "test_runtime.py").write_text(
        '"""Exercise the generated package after its workspace moves."""\n\n'
        "def test_rtl_runtime(dut):\n"
        '    """Require the generated implementation rather than the reference."""\n\n'
        '    assert dut.implementation == "rtl"\n'
        "    dut.RefreshComb()\n"
        "    dut.Step()\n",
        encoding="utf-8",
    )
    generated_content = _write_workspace_python_dut(
        original,
        "class DUTdut:\n"
        '    implementation = "rtl"\n\n'
        "    def GetXPort(self):\n"
        "        return self\n\n"
        "    def AsImmWrite(self):\n"
        "        return self\n\n"
        "    def RefreshComb(self):\n"
        "        return None\n\n"
        "    def Step(self, cycles=1):\n"
        "        return cycles\n\n"
        "    def Finish(self):\n"
        "        return None\n",
    )
    _write_json(
        original / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json",
        {
            "schema_version": "1.4",
            "python_dut_import": {"module": "dut", "class": "DUTdut"},
            "generated_content": generated_content,
        },
    )
    moved = tmp_path / "moved-workspace"
    shutil.move(original, moved)
    environment = os.environ.copy()
    environment.pop("_DESIGN_WITH_PPA_RTL_DUT_MODULE", None)
    environment.pop("_DESIGN_WITH_PPA_RTL_DUT_CLASS", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(PLUGIN_SOURCE),
            str(REPOSITORY_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "design/tests",
        "--design-backend=rtl",
    ]

    completed = subprocess.run(
        command,
        cwd=moved,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout
    generated = _workspace_python_dut_root(moved) / "dut" / "__init__.py"
    assert generated.relative_to(moved) == Path(
        "run/design_with_ppa/python-dut/dut/__init__.py"
    )
    generated.write_text(
        generated.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8"
    )
    rejected = subprocess.run(
        command,
        cwd=moved,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert rejected.returncode != 0
    assert "runtime differs from its build receipt" in rejected.stdout


def test_prepare_native_artifact_path_creates_and_validates(tmp_path: Path) -> None:
    """Artifact paths resolve to absolute paths with created parent directories."""

    from design_with_ppa import prepare_native_artifact_path

    resolved = prepare_native_artifact_path(
        tmp_path / "nested" / "run" / "cover.dat", "coverage"
    )
    assert resolved == (tmp_path / "nested" / "run" / "cover.dat").resolve()
    assert resolved.parent.is_dir()

    relative = prepare_native_artifact_path("waves/probe.vcd", "waveform")
    assert relative.is_absolute()
    assert relative.name == "probe.vcd"

    with pytest.raises(PythonDUTError):
        prepare_native_artifact_path(123, "coverage")

    blocked = tmp_path / "blocked"
    blocked.write_text("occupies the path\n", encoding="utf-8")
    with pytest.raises(PythonDUTError):
        prepare_native_artifact_path(blocked / "child" / "a.dat", "coverage")
