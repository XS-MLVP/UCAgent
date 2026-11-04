"""Focused DesignWithPPA workflow tests: performance."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    PLUGIN_SOURCE,
    _config,
    _write_json,
    _write_workspace_python_dut,
    _write_yaml,
)

import json
from pathlib import Path
import subprocess
from types import ModuleType, SimpleNamespace
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
from design_with_ppa.performance import (  # noqa: E402
    get_performance_waveform_path,
    measure_cycle_latency,
    measure_latency,
    measure_throughput,
    write_performance_result,
)
from ucagent.util.config import (  # noqa: E402
    Config,
    build_runtime_config,
    get_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)




def test_measurement_helpers_reject_invalid_time_and_count() -> None:
    """Simulation measurements must reject bools, non-finite values, and zero duration."""

    assert measure_latency(1, 4, "ns") == 3
    assert measure_cycle_latency(3, 9) == 6
    assert measure_throughput(12, 2, 5, "ns") == 4
    with pytest.raises(ValueError, match="greater than zero"):
        measure_throughput(1, 2, 2, "ns")
    with pytest.raises(ValueError, match="finite"):
        measure_latency(0, float("nan"), "ns")
    with pytest.raises(TypeError, match="integers"):
        measure_cycle_latency(False, 2)




def test_performance_sidecar_is_atomic_and_hash_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helper and Checker must bind seed, parameters, trace, waveform, and metrics."""

    cfg = _config()
    save_runtime_config(str(tmp_path), cfg)
    spec = tmp_path / "dut" / "spec" / "performance.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("Latency requirement.\n", encoding="utf-8")
    contract = {
        "schema_version": "1.0",
        "dut": "dut",
        "top_module": "dut",
        "metrics": [
            {
                "id": "latency",
                "kind": "latency",
                "source": {"path": "dut/spec/performance.md", "line": 1},
                "unit": "ns",
                "direction": "min",
                "target": None,
                "hard_requirement": False,
                "aggregation": "max",
                "measurement_test": "output/tests/test_perf.py::test_latency",
                "clock_or_time_base": "waveform-timescale",
            }
        ],
    }
    _write_yaml(tmp_path / "output" / "dut_performance_contract.yaml", contract)
    waveform = tmp_path / "output" / "performance" / "waves" / "latency.vcd"
    waveform.parent.mkdir(parents=True)
    waveform.write_text("$timescale 1ns $end\n#0\n#10\n", encoding="ascii")
    request = SimpleNamespace(
        node=SimpleNamespace(nodeid="output/tests/test_perf.py::test_latency")
    )
    monkeypatch.chdir(tmp_path)
    result_path = write_performance_result(
        request,
        {
            "latency": {
                "value": 10,
                "unit": "ns",
                "kind": "latency",
                "direction": "min",
            }
        },
        waveform,
        {
            "deterministic": True,
            "seed": None,
            "parameters": {"operand": 7},
            "start_time": 0,
            "end_time": 10,
            "time_unit": "ns",
            "transaction_count": 1,
            "input_trace": [{"time": 0, "a": 7}],
        },
    )
    checker = PerformanceArtifactChecker(
        test_dir="output/tests",
        results_glob="output/performance/results/*.json",
        contract_file="output/dut_performance_contract.yaml",
        manifest_file="output/performance/performance_manifest.json",
        timeout=10,
        cfg=cfg,
    ).set_workspace(str(tmp_path))
    (tmp_path / "output" / "tests").mkdir(parents=True)
    passed, result = checker.do_check(run_tests=False)
    assert passed is True
    assert result["test_cases"] == 1
    sidecar = json.loads((tmp_path / result_path).read_text(encoding="utf-8"))
    sidecar["stimulus"]["parameters"]["operand"] = 8
    _write_json(tmp_path / result_path, sidecar)
    passed, result = checker.do_check(run_tests=False)
    assert passed is False
    assert result["error_code"] == "performance_artifact_invalid"
    assert "stimulus hash mismatch" in result["error"]




def test_performance_artifacts_use_workspace_relative_pytest_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pytest rootdir prefixes must not change one performance TC identity."""

    save_runtime_config(str(tmp_path), _config())
    test_file = tmp_path / "output" / "tests" / "test_perf.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_latency():\n    pass\n", encoding="utf-8")
    request = SimpleNamespace(
        node=SimpleNamespace(
            nodeid="parent/workspace/output/tests/test_perf.py::test_latency",
            path=test_file,
        )
    )
    monkeypatch.chdir(tmp_path)

    waveform = get_performance_waveform_path(request)

    assert waveform.relative_to(tmp_path).as_posix() == (
        "output/performance/waves/"
        "output_tests_test_perf.py_test_latency.vcd"
    )
    waveform.write_text("$timescale 1ns $end\n#0\n#10\n", encoding="ascii")
    result_path = write_performance_result(
        request,
        {"latency": {"value": 10, "unit": "ns", "kind": "latency"}},
        waveform,
        {
            "deterministic": True,
            "seed": None,
            "parameters": {"operand": 7},
            "start_time": 0,
            "end_time": 10,
            "time_unit": "ns",
            "transaction_count": 1,
            "input_trace": [{"time": 0, "a": 7}],
        },
    )
    sidecar = json.loads((tmp_path / result_path).read_text(encoding="utf-8"))
    assert sidecar["test_case"] == "output/tests/test_perf.py::test_latency"




def test_performance_guide_captures_waveform_before_stimulus() -> None:
    """A performance TC must capture real RTL activity before writing its sidecar."""

    backend_guide = (
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "rtl_backend.md"
    ).read_text(encoding="utf-8")
    performance_guide = (
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "performance_measurement.md"
    ).read_text(encoding="utf-8")

    assert "self._dut.SetWaveform(str(self.waveform_path))" in backend_guide
    assert "self._dut.ResumeWaveformDump()" in backend_guide
    assert "self._dut.FlushWaveform()" in backend_guide
    assert "start_time, end_time = env.last_transaction_timing" in performance_guide
    example = performance_guide[
        performance_guide.index("def test_Adder_performance_latency") :
    ]
    assert "fixture 已在 reset 和首次 `Step` 前" in performance_guide
    assert example.index("env.flush_waveform()") < example.index(
        "write_performance_result("
    )
    workflow_path = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "禁止手写、拼接或从 Python shadow/reference trace 合成" in workflow

    parsed = load_yaml_with_env_vars(workflow_path)
    performance_stage = next(
        stage
        for stage in parsed["stage"]
        if stage["name"] == "performance_evidence"
    )
    assert [checker["name"] for checker in performance_stage["checker"]] == [
        "performance_backend_sync",
        "performance_artifacts",
    ]
    assert performance_stage["checker"][0]["clss"] == "RTLBackendBuildChecker"




def test_performance_contract_rejects_non_spec_traceability(tmp_path: Path) -> None:
    """Metric source paths must belong to the hashed input Spec set."""

    readme = tmp_path / "dut" / "README.md"
    spec = tmp_path / "dut" / "spec" / "performance.md"
    spec.parent.mkdir(parents=True)
    readme.write_text("Design requirements.\n", encoding="utf-8")
    spec.write_text("Latency must not exceed two cycles.\n", encoding="utf-8")
    input_checker = DesignInputContractChecker(
        readme_file="dut/README.md",
        spec_glob="dut/spec/**/*.md",
        manifest_file="output/reports/design_input_manifest.json",
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, result = input_checker.do_check()
    assert passed is True, result

    generated = tmp_path / "output" / "generated_requirements.md"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("Latency must not exceed two cycles.\n", encoding="utf-8")
    contract = tmp_path / "output" / "dut_performance_contract.yaml"
    _write_yaml(
        contract,
        {
            "schema_version": "1.0",
            "dut": "dut",
            "top_module": "dut",
            "metrics": [
                {
                    "id": "latency",
                    "kind": "latency",
                    "source": {
                        "path": "output/generated_requirements.md",
                        "line": 1,
                    },
                    "unit": "cycles",
                    "direction": "min",
                    "target": 2,
                    "hard_requirement": True,
                    "aggregation": "max",
                    "measurement_test": (
                        "output/tests/test_dut_performance.py::"
                        "test_dut_performance_latency"
                    ),
                    "clock_or_time_base": "clk_i",
                }
            ],
        },
    )
    checker = PerformanceContractChecker(
        contract_file="output/dut_performance_contract.yaml",
        input_manifest_file="output/reports/design_input_manifest.json",
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "performance_contract_invalid"
    assert "design input manifest" in result["error"]




def test_performance_test_contract_requires_multiple_exact_bound_nodes(
    tmp_path: Path,
) -> None:
    """Dedicated performance tests must be marked, executable, and contract-bound."""

    spec = tmp_path / "dut" / "spec" / "performance.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("Latency requirement.\nThroughput requirement.\n", encoding="utf-8")
    contract = tmp_path / "output" / "dut_performance_contract.yaml"
    contract.parent.mkdir(parents=True)
    _write_yaml(
        contract,
        {
            "schema_version": "1.0",
            "dut": "dut",
            "top_module": "dut",
            "metrics": [
                {
                    "id": "latency",
                    "kind": "latency",
                    "source": {"path": "dut/spec/performance.md", "line": 1},
                    "unit": "cycle",
                    "direction": "min",
                    "target": None,
                    "hard_requirement": False,
                    "aggregation": "max",
                    "measurement_test": "output/tests/test_dut_performance.py::test_dut_performance_latency",
                    "clock_or_time_base": "clk",
                },
                {
                    "id": "throughput",
                    "kind": "throughput",
                    "source": {"path": "dut/spec/performance.md", "line": 2},
                    "unit": "transaction/cycle",
                    "direction": "max",
                    "target": None,
                    "hard_requirement": False,
                    "aggregation": "mean",
                    "measurement_test": "output/tests/test_dut_performance.py::test_dut_performance_throughput",
                    "clock_or_time_base": "clk",
                },
            ],
        },
    )
    tests = tmp_path / "output" / "tests" / "test_dut_performance.py"
    tests.parent.mkdir(parents=True)
    tests.write_text(
        "import pytest\n"
        "from design_with_ppa import write_performance_result\n\n"
        "@pytest.mark.performance\n"
        "def test_dut_performance_latency(env, request):\n"
        "    assert env is not None\n"
        "    write_performance_result(request, {}, 'wave.vcd', {})\n\n"
        "@pytest.mark.performance\n"
        "def test_dut_performance_throughput(env, request):\n"
        "    assert env is not None\n"
        "    write_performance_result(request, {}, 'wave.vcd', {})\n",
        encoding="utf-8",
    )
    checker = PerformanceTestContractChecker(
        test_glob="output/tests/test_dut_performance*.py",
        contract_file="output/dut_performance_contract.yaml",
        min_tests=2,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    assert result["test_count"] == 2
    assert checker.get_template_data() == {"PERFORMANCE_TEST_COUNT": 2}




@pytest.mark.parametrize(
    ("source_replacement", "expected_fragment"),
    [
        ("@pytest.mark.performance", "@pytest.mark.other"),
        ("write_performance_result(request, {}, 'wave.vcd', {})", "assert True"),
        ("def test_dut_performance_throughput", "def test_dut_other_throughput"),
    ],
)
def test_performance_test_contract_rejects_invalid_authored_nodes(
    tmp_path: Path,
    source_replacement: str,
    expected_fragment: str,
) -> None:
    """Static performance validation must fail without importing authored modules."""

    spec = tmp_path / "dut" / "spec" / "performance.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("Performance.\n", encoding="utf-8")
    contract = tmp_path / "output" / "dut_performance_contract.yaml"
    contract.parent.mkdir(parents=True)
    _write_yaml(
        contract,
        {
            "schema_version": "1.0",
            "dut": "dut",
            "top_module": "dut",
            "metrics": [
                {
                    "id": metric_id,
                    "kind": "latency",
                    "source": {"path": "dut/spec/performance.md", "line": 1},
                    "unit": "cycle",
                    "direction": "min",
                    "target": None,
                    "hard_requirement": False,
                    "aggregation": "max",
                    "measurement_test": f"output/tests/test_dut_performance.py::test_dut_performance_{metric_id}",
                    "clock_or_time_base": "clk",
                }
                for metric_id in ("latency", "throughput")
            ],
        },
    )
    valid = (
        "import pytest\n\n"
        "@pytest.mark.performance\n"
        "def test_dut_performance_latency(env, request):\n"
        "    write_performance_result(request, {}, 'wave.vcd', {})\n\n"
        "@pytest.mark.performance\n"
        "def test_dut_performance_throughput(env, request):\n"
        "    write_performance_result(request, {}, 'wave.vcd', {})\n"
    )
    test_file = tmp_path / "output" / "tests" / "test_dut_performance.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        valid.replace(source_replacement, expected_fragment, 1), encoding="utf-8"
    )
    checker = PerformanceTestContractChecker(
        test_glob="output/tests/test_dut_performance*.py",
        contract_file="output/dut_performance_contract.yaml",
        min_tests=2,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "performance_test_contract_invalid"




def test_measurement_changes_do_not_change_stimulus_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Improved latency may change end time without changing deterministic stimulus."""

    save_runtime_config(str(tmp_path), _config())
    waveform = tmp_path / "output" / "performance" / "waves" / "tc.vcd"
    waveform.parent.mkdir(parents=True)
    waveform.write_text("$timescale 1ns $end\n#0\n#10\n", encoding="ascii")
    request = SimpleNamespace(
        node=SimpleNamespace(nodeid="output/tests/test_dut_performance.py::test_latency")
    )
    stimulus = {
        "deterministic": True,
        "seed": 7,
        "parameters": {"operand": 3},
        "start_time": 0,
        "end_time": 10,
        "time_unit": "ns",
        "transaction_count": 1,
        "input_trace": [{"time": 0, "a": 3}],
    }
    monkeypatch.chdir(tmp_path)
    first_path = write_performance_result(
        request,
        {"latency": {"value": 10, "unit": "ns", "kind": "latency"}},
        waveform,
        stimulus,
    )
    first = json.loads((tmp_path / first_path).read_text(encoding="utf-8"))
    stimulus["end_time"] = 6
    second_path = write_performance_result(
        request,
        {"latency": {"value": 6, "unit": "ns", "kind": "latency"}},
        waveform,
        stimulus,
    )
    second = json.loads((tmp_path / second_path).read_text(encoding="utf-8"))
    assert first["stimulus_sha256"] == second["stimulus_sha256"]
    assert first["input_trace_sha256"] == second["input_trace_sha256"]
    assert first["measurement"]["duration"] == 10
    assert second["measurement"]["duration"] == 6




def test_performance_rerun_removes_stale_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh performance run must not retain evidence from a removed pytest TC."""

    cfg = _config()
    save_runtime_config(str(tmp_path), cfg)
    spec = tmp_path / "dut" / "spec" / "performance.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("Latency requirement.\n", encoding="utf-8")
    _write_yaml(
        tmp_path / "output" / "dut_performance_contract.yaml",
        {
            "schema_version": "1.0",
            "dut": "dut",
            "top_module": "dut",
            "metrics": [
                {
                    "id": "latency",
                    "kind": "latency",
                    "source": {"path": "dut/spec/performance.md", "line": 1},
                    "unit": "ns",
                    "direction": "min",
                    "target": None,
                    "hard_requirement": False,
                    "aggregation": "max",
                    "measurement_test": (
                        "output/tests/test_dut_performance.py::test_latency"
                    ),
                    "clock_or_time_base": "waveform-timescale",
                }
            ],
        },
    )
    test_dir = tmp_path / "output" / "tests"
    test_dir.mkdir(parents=True)
    stale = tmp_path / "output" / "performance" / "results" / "removed.json"
    _write_json(stale, {"stale": True})
    waveform = tmp_path / "output" / "performance" / "waves" / "latency.vcd"
    waveform.parent.mkdir(parents=True)
    waveform.write_text("$timescale 1ns $end\n#0\n#10\n", encoding="ascii")
    request = SimpleNamespace(
        node=SimpleNamespace(
            nodeid="output/tests/test_dut_performance.py::test_latency"
        )
    )
    monkeypatch.chdir(tmp_path)
    collected_node_ids = [
        "output/tests/test_dut_performance.py::test_latency",
    ]

    def fake_run(*args, **kwargs):
        """Emit only the one TC still selected by the current performance contract."""

        if "--collect-only" in args[4]:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="\n".join(collected_node_ids),
                stderr="",
            )
        waveform.parent.mkdir(parents=True, exist_ok=True)
        waveform.write_text("$timescale 1ns $end\n#0\n#10\n", encoding="ascii")
        write_performance_result(
            request,
            {
                "latency": {
                    "value": 10,
                    "unit": "ns",
                    "kind": "latency",
                    "direction": "min",
                }
            },
            waveform,
            {
                "deterministic": True,
                "seed": None,
                "parameters": {"case": "current"},
                "start_time": 0,
                "end_time": 10,
                "time_unit": "ns",
                "transaction_count": 1,
                "input_trace": [{"time": 0, "a": 1}],
            },
        )
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr("design_with_ppa.checkers.runtime._run_pytest", fake_run)
    generated_content = _write_workspace_python_dut(tmp_path, "")
    rtl_manifest = (
        tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    )
    _write_json(
        rtl_manifest,
        {
            "python_dut_import": {"module": "dut", "class": "DUTdut"},
            "generated_content": generated_content,
        },
    )
    checker = PerformanceArtifactChecker(
        test_dir="output/tests",
        results_glob="output/performance/results/*.json",
        contract_file="output/dut_performance_contract.yaml",
        manifest_file="output/performance/performance_manifest.json",
        rtl_manifest_file=(
            ".ucagent/design_with_ppa/rtl_backend_manifest.json"
        ),
        timeout=10,
        cfg=cfg,
    ).set_workspace(str(tmp_path))
    passed, result = checker.do_check()
    assert passed is True
    assert result["test_cases"] == 1
    assert not stale.exists()
    manifest = json.loads(
        (tmp_path / "output" / "performance" / "performance_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert [row["test_case"] for row in manifest["tests"]] == [
        "output/tests/test_dut_performance.py::test_latency"
    ]

    collected_node_ids.append(
        "output/tests/test_dut_performance.py::test_missing_sidecar"
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "performance_artifact_invalid"
    assert "missing_sidecars" in result["error"]
