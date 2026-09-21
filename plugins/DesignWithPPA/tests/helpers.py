"""Shared fixtures and workspace builders for DesignWithPPA workflow tests."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_SOURCE = Path(__file__).resolve().parent.parent / "src"
REPOSITORY_ROOT = PLUGIN_SOURCE.parents[2]
sys.path.insert(0, str(PLUGIN_SOURCE))

import hashlib
import json
import shutil
import subprocess
from types import ModuleType, SimpleNamespace
from typing import Any
import yaml
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
from design_with_ppa.contracts import sha256_file
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





def _config(
    output: str = "output",
    iterations: object = 0,
    *,
    max_iterations: object = 1000,
    patience: object = 3,
    no_regression: object = None,
    score_weights: object = None,
) -> Config:
    """Build the smallest resolved config used by plugin workflow Checkers."""

    design_with_ppa: dict[str, object] = {
        "min_optimization_iterations": iterations,
        "max_optimization_iterations": max_iterations,
        "no_improvement_patience": patience,
        "rtl": {
            "language": "verilog",
            "source_glob": f"{output}/rtl/*.v",
            "source_template": "verilog-2005",
            "language_options": {"standard": "verilog-2005"},
            "python_dut": {
                "interface": "automatic",
                "options": {},
            },
        },
        "ppa": {"waveform_scope": "tb.dut"},
        "score_weights": {"timing": 1.0, "area": 1.0, "power": 1.0},
    }
    if no_regression is not None:
        design_with_ppa["no_regression_metrics"] = no_regression
    if score_weights is not None:
        design_with_ppa["score_weights"] = score_weights
    cfg = Config(
        {
            "design_with_ppa": design_with_ppa,
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": False,
            },
            "tools": {"RunTestCases": {"test_dir": f"{output}/tests"}},
        }
    )
    cfg._temp_cfg = {"DUT": "dut", "OUT": output}
    return cfg




def _chisel_config(output: str = "output", iterations: object = 0) -> Config:
    """Build the pinned Chisel variant of the focused workflow config."""

    cfg = _config(output, iterations)
    cfg.un_freeze()
    cfg.set_value("design_with_ppa.rtl.language", "chisel")
    cfg.set_value(
        "design_with_ppa.rtl.source_glob", f"{output}/rtl/*.scala"
    )
    cfg.set_value("design_with_ppa.rtl.source_template", "chisel-7")
    cfg.set_value(
        "design_with_ppa.rtl.language_options",
        {
            "chisel_version": CHISEL_VERSION,
            "scala_version": CHISEL_SCALA_VERSION,
            "mill_version": CHISEL_MILL_VERSION,
        },
    )
    cfg.freeze()
    return cfg




def _design_batch_checker(
    tmp_path: Path,
    test_names: list[str],
    *,
    batch_size: int = 1,
) -> tuple[DesignAllPassBatchTestsChecker, Any]:
    """Create an initialized all-Pass batch Checker with deterministic stage state."""

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_demo.py").write_text(
        "\n\n".join(
            f"def {name}(env):\n    assert env is not None"
            for name in test_names
        )
        + "\n",
        encoding="utf-8",
    )
    initial_report = {
        "tests": {
            "total": len(test_names),
            "fails": len(test_names),
            "test_cases": {
                f"tests/test_demo.py:{index * 3 + 1}-{index * 3 + 2}::{name}": "FAILED"
                for index, name in enumerate(test_names)
            },
        },
    }

    class Stage:
        """Provide the batch lifecycle callbacks used by UnityChipBatchTask."""

        name = "shared_test_implementation"

        def title(self) -> str:
            """Return the deterministic stage title."""

            return self.name

        def reset_continue_fail_count_with_batch_pass(self) -> None:
            """Record no additional state for this focused fixture."""

    stage = Stage()
    manager = SimpleNamespace(
        data={"DESIGN_TEST_TEMPLATE_REPORT": initial_report},
        stage=stage,
        stage_index=0,
        agent=SimpleNamespace(get_tool_by_name=lambda _name: None),
    )
    manager.get_data = lambda key, default=None: manager.data.get(key, default)
    manager.set_data = lambda key, value: manager.data.__setitem__(key, value)
    manager.get_current_stage = lambda: stage
    cfg = _config()
    checker = DesignAllPassBatchTestsChecker(
        cfg=cfg,
        doc_func_check="functions.md",
        test_dir="tests",
        batch_size=batch_size,
        data_key="DESIGN_TEST_TEMPLATE_REPORT",
        pre_report_file=".DESIGN_TEST_TEMPLATE_REPORT.json",
        ret_std_out=False,
        ret_std_error=False,
    )
    checker.set_workspace(str(tmp_path)).set_stage(stage)
    checker.set_stage_manager(manager)
    checker.on_init()
    return checker, manager




def _template_context(output: str = "output", workspace: str = "") -> dict[str, str]:
    """Return the default workflow's dynamically resolved template values."""

    context = {"DUT": "dut", "OUT": output, "WORKSPACE": workspace}
    context.update(build_rtl_template_context(_config(output), context))
    return context




def _write_json(path: Path, value: dict) -> None:
    """Write one deterministic JSON fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")




def _write_yaml(path: Path, value: dict) -> None:
    """Write one deterministic YAML fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")




def _write_workspace_python_dut(workspace: Path, content: str) -> dict[str, object]:
    """Create one portable generated-DUT fixture and return its content identity."""

    target = _workspace_python_dut_root(workspace) / "dut"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    generated = target / "__init__.py"
    if "class DUTdut" not in content:
        content += "\nclass DUTdut:\n    pass\n"
    generated.write_text(content, encoding="utf-8")
    extension = target / "_UT_dut.so"
    extension.write_bytes(b"fixture-native-extension")
    rows = [
        {"path": path.name, "sha256": sha256_file(path)}
        for path in (extension, generated)
    ]
    return {
        "file_count": len(rows),
        "content_sha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }




def _rtl_rows(workspace: Path) -> list[dict[str, str]]:
    """Return the canonical current RTL path/hash rows."""

    return [
        {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted((workspace / "output" / "rtl").glob("*.v"))
    ]




def _report(
    report_id: str,
    rtl_rows: list[dict[str, str]],
    waveform_path: str,
    waveform_hash: str,
    *,
    area: float,
    power: float = 0.001,
    delay: float = 1.0,
    baseline_report_id: str | None = None,
) -> dict:
    """Build one complete comparable schema-1.1 PPA report fixture."""

    comparison = {
        "status": "not_requested" if baseline_report_id is None else "success",
        "baseline_report_id": baseline_report_id,
        "current_report_id": report_id,
    }
    return {
        "schema_version": "1.1",
        "report_id": report_id,
        "status": "success",
        "summary": {
            "design_type": "combinational",
            "area": {"total": area},
            "timing": {
                "metric_kind": "critical_path_delay",
                "critical_path_delay_ns": delay,
                "maximum_frequency_hz": 1_000_000_000.0,
                "limiting_path": {"startpoint": "a", "endpoint": "y"},
                "clocks": [],
            },
            "power": {"total_w": power},
        },
        "comparison": comparison,
        "waveform_aggregation": {
            "reliable": True,
            "merged_input_bits": [
                {
                    "input_bit": "a",
                    "total_duration_seconds": 1e-8,
                    "transition_count": 1.0,
                    "density_hz": 1e8,
                    "duty_cycle": 0.5,
                    "unknown_fraction": 0.0,
                }
            ],
        },
        "details": {"area_by_cell_type": {"BUF_X1": 1}},
        "diagnostics": [],
        "provenance": {
            "rtl_files": rtl_rows,
            "rtl_libraries": [],
            "waveform_files": [
                {"path": waveform_path, "sha256": waveform_hash}
            ],
            "top_module": "dut",
            "liberty_file": "bundled:NangateOpenCellLibrary_typical.lib",
            "liberty_sha256": "a" * 64,
            "sdc_file": None,
            "sdc_sha256": None,
            "clock_constraint": None,
            "waveform_scope": "tb.dut",
        },
        "cache": {"stored": True, "limit": 100},
        "report_path": "output/reports/ppa/current.json",
    }




def _prepare_iteration_workspace(
    workspace: Path,
    *,
    iterations: int,
    max_iterations: int = 1000,
    patience: int = 3,
    base_area: float = 10.0,
    no_regression: object = None,
    score_weights: object = None,
) -> tuple[PPACandidateOptimizationChecker, str]:
    """Record a complete base and return the candidate-phase Checker."""

    output = workspace / "output"
    (workspace / "dut" / "spec").mkdir(parents=True)
    (workspace / "dut" / "spec" / "performance.md").write_text(
        "Latency must be measured.\n", encoding="utf-8"
    )
    rtl = output / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module dut(input a, output y); assign y = a; endmodule\n", encoding="ascii")
    tests = output / "tests"
    tests.mkdir(parents=True)
    (tests / "test_dut_functional.py").write_text(
        "def test_dut_functional():\n    assert True\n", encoding="utf-8"
    )
    waveform = output / "performance" / "waves" / "tc.vcd"
    waveform.parent.mkdir(parents=True)
    waveform.write_text("$timescale 1ns $end\n#0\n#10\n", encoding="ascii")
    waveform_relative = waveform.relative_to(workspace).as_posix()
    waveform_hash = sha256_file(waveform)
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
                "measurement_test": "output/tests/test_dut_performance.py::test_latency",
                "clock_or_time_base": "waveform-timescale",
            }
        ],
    }
    _write_yaml(output / "dut_performance_contract.yaml", contract)
    performance_manifest = {
        "schema_version": "1.0",
        "tests": [
            {
                "test_case": "output/tests/test_dut_performance.py::test_latency",
                "result_path": "output/performance/results/tc.json",
                "result_sha256": "b" * 64,
                "waveform": {
                    "path": waveform_relative,
                    "sha256": waveform_hash,
                    "format": "vcd",
                },
                "metrics": [
                    {
                        "id": "latency",
                        "kind": "latency",
                        "value": 1.0,
                        "unit": "ns",
                    }
                ],
                "measurement": {
                    "start_time": 0.0,
                    "end_time": 10.0,
                    "duration": 10.0,
                    "time_unit": "ns",
                    "transaction_count": 1,
                },
                "deterministic": True,
                "seed": None,
                "parameters": {"case": "base"},
                "stimulus_sha256": "c" * 64,
                "input_trace_sha256": "d" * 64,
            }
        ],
    }
    _write_json(output / "performance" / "performance_manifest.json", performance_manifest)
    rows = _rtl_rows(workspace)
    generated_content = _write_workspace_python_dut(
        workspace, "DUT = object\n"
    )
    _write_json(
        workspace / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json",
        {
            "schema_version": "1.4",
            "rtl_language": "verilog",
            "rtl_config": resolve_rtl_config(
                _config(
                    iterations=iterations,
                    max_iterations=max_iterations,
                    patience=patience,
                )
            )[0].identity(),
            "top_module": "dut",
            "rtl_sources": rows,
            "rtl_libraries": [],
            "prepared_content": {
                "analysis": {
                    "file_count": 1,
                    "content_sha256": hashlib.sha256(
                        json.dumps(
                            [sha256_file(rtl)], separators=(",", ":")
                        ).encode("ascii")
                    ).hexdigest(),
                },
                "python_dut": {
                    "file_count": 1,
                    "content_sha256": hashlib.sha256(
                        json.dumps(
                            [sha256_file(rtl)], separators=(",", ":")
                        ).encode("ascii")
                    ).hexdigest(),
                },
            },
            "python_dut_import": {"module": "dut", "class": "DUTdut"},
            "python_dut_builder": {
                "coverage": True,
                "waveform_format": "fst",
            },
            "generated_content": generated_content,
            "design_inputs": None,
            "contracts": None,
        },
    )
    base_id = "ppa-" + "1" * 32
    base_report = _report(
        base_id,
        rows,
        waveform_relative,
        waveform_hash,
        area=base_area,
    )
    _write_json(output / "reports" / "ppa" / "current.json", base_report)
    cache = workspace / ".ucagent" / "ppa_reports"
    base_cache_path = cache / f"{base_id}.json"
    _write_json(base_cache_path, base_report)
    _write_json(
        cache / "index.json",
        {
            "schema_version": "1.0",
            "reports": [
                {"report_id": base_id, "sha256": sha256_file(base_cache_path)}
            ],
        },
    )
    checker_args = {
        "test_dir": "output/tests",
        "functional_test_glob": "output/tests/test_dut_*.py",
        "performance_contract_file": "output/dut_performance_contract.yaml",
        "performance_manifest_file": "output/performance/performance_manifest.json",
        "ppa_report_file": "output/reports/ppa/current.json",
        "rtl_backend_manifest_file": ".ucagent/design_with_ppa/rtl_backend_manifest.json",
        "ledger_file": "output/dut_optimization_ledger.yaml",
        "base_report_file": "output/reports/ppa/base.json",
        "iteration_report_dir": "output/reports/ppa/iterations",
        "timeout": 30,
        "cfg": _config(
            iterations=iterations,
            max_iterations=max_iterations,
            patience=patience,
            no_regression=no_regression,
            score_weights=score_weights,
        ),
    }
    base_checker = PPABaseCharacterizationChecker(
        **checker_args,
    ).set_workspace(str(workspace))
    checker = PPACandidateOptimizationChecker(
        **checker_args,
    ).set_workspace(str(workspace))
    commit_values = tuple(character * 40 for character in "efabcd123456789")
    commits = iter(commit_values)
    stage = SimpleNamespace(
        hist_snapshot=lambda message: next(commits),
        hist_has_commit=lambda commit_hash: commit_hash in commit_values,
        meta_data={},
    )
    base_checker.stage = stage
    checker.stage = stage
    from unittest.mock import patch

    with patch(
        "design_with_ppa.checkers.runtime._run_pytest",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    ):
        passed, result = base_checker.do_check()
    assert passed is True, result
    checker.on_init()
    return checker, base_id




def _write_candidate_report(
    workspace: Path,
    base_id: str,
    *,
    area: float,
    power: float = 0.001,
    delay: float = 1.0,
    candidate_index: int = 1,
) -> str:
    """Replace current artifacts with one functionally valid PPA candidate."""

    rtl = workspace / "output" / "rtl" / "dut.v"
    rtl.write_text(
        "module dut(input a, output y); "
        + " ".join(f"wire n{index};" for index in range(candidate_index))
        + " assign n0 = a; "
        + " ".join(
            f"assign n{index} = n{index - 1};"
            for index in range(1, candidate_index)
        )
        + f" assign y = n{candidate_index - 1}; endmodule\n",
        encoding="ascii",
    )
    rows = _rtl_rows(workspace)
    generated_content = _write_workspace_python_dut(
        workspace, f"RTL_SHA256 = {sha256_file(rtl)!r}\nDUT = object\n"
    )
    _write_json(
        workspace / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json",
        {
            **json.loads(
                (
                    workspace
                    / ".ucagent"
                    / "design_with_ppa"
                    / "rtl_backend_manifest.json"
                ).read_text(encoding="utf-8")
            ),
            "rtl_sources": rows,
            "generated_content": generated_content,
            "prepared_content": {
                key: {
                    "file_count": 1,
                    "content_sha256": hashlib.sha256(
                        json.dumps(
                            [sha256_file(rtl)], separators=(",", ":")
                        ).encode("ascii")
                    ).hexdigest(),
                }
                for key in ("analysis", "python_dut")
            },
        },
    )
    hypothesis = {
        "iteration": candidate_index,
        "hypothesis": f"Reduce mapped cell area in candidate {candidate_index}.",
        "target_hotspot": "area_by_cell_type.BUF_X1",
        "expected_metrics": ["ppa.area.total"],
    }
    _write_yaml(
        workspace / "output" / "reports" / "ppa" / "candidate_hypothesis.yaml",
        hypothesis,
    )
    waveform = workspace / "output" / "performance" / "waves" / "tc.vcd"
    candidate_id = f"ppa-{candidate_index + 1:032x}"
    report = _report(
        candidate_id,
        rows,
        waveform.relative_to(workspace).as_posix(),
        sha256_file(waveform),
        area=area,
        power=power,
        delay=delay,
        baseline_report_id=base_id,
    )
    _write_json(workspace / "output" / "reports" / "ppa" / "current.json", report)
    cache = workspace / ".ucagent" / "ppa_reports"
    candidate_cache_path = cache / f"{candidate_id}.json"
    _write_json(candidate_cache_path, report)
    index_path = cache / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["reports"] = [
        row for row in index["reports"] if row["report_id"] != candidate_id
    ]
    index["reports"].append(
        {
            "report_id": candidate_id,
            "sha256": sha256_file(candidate_cache_path),
        }
    )
    _write_json(index_path, index)
    return candidate_id




def _write_observation_fixture(workspace: Path) -> None:
    """Write one complete functional CK and its backend-neutral observation sources."""

    output = workspace / "output"
    tests = output / "tests"
    tests.mkdir(parents=True)
    (output / "dut_functions_and_checks.md").write_text(
        "\n# Functions\n\n<FG-ARITH>\n\n"
        "## Add\n\n<FC-ADD>\n\n"
        "### Result\n\n<CK-RESULT>\n\nObserve the result.\n",
        encoding="utf-8",
    )
    (output / "dut_architecture.md").write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n"
        '  schema_version: "1.0"\n'
        "  ports:\n"
        "    - name: operand_i\n"
        "      direction: input\n"
        "      width: 8\n"
        "      signed: false\n"
        "      role: Public operand.\n"
        "    - name: result_o\n"
        "      direction: output\n"
        "      width: 8\n"
        "      signed: false\n"
        "      role: Public result.\n"
        "```\n",
        encoding="utf-8",
    )
    _write_yaml(
        output / "dut_observation_contract.yaml",
        {
            "observation_contract": {
                "schema_version": "1.0",
                "events": [
                    {
                        "name": "response_observed",
                        "capture": "response",
                        "fields": [
                            {
                                "name": "result",
                                "source": "public_output",
                                "source_refs": ["result_o"],
                                "description": "Result sampled from the public output.",
                            }
                        ],
                    }
                ],
                "checkpoints": [
                    {
                        "id": "FG-ARITH/FC-ADD/CK-RESULT",
                        "observation": "event",
                        "event": "response_observed",
                        "fields": ["result"],
                        "predicate_intent": "Match the specified public result.",
                    }
                ],
            }
        },
    )
    (tests / "dut_adapter.py").write_text(
        "raise RuntimeError('workspace source must not execute during Check')\n\n"
        "class DutAdapter:\n"
        "    def __init__(self):\n"
        "        self.result_o = 0\n\n"
        "    def _record_event(self, event, **data):\n"
        "        self.last_event_data = data\n\n"
        "    def _record_response_observed(self, transaction_id, response_at, **result):\n"
        "        self._record_event('response_observed', **result)\n",
        encoding="utf-8",
    )
    (tests / "dut_api.py").write_text(
        "def api_dut_observe(env, max_cycles=4):\n"
        "    result = env.result_o\n"
        "    env._record_response_observed(1, 1, result=result)\n"
        "    return result\n",
        encoding="utf-8",
    )




def _documentation_sync_fixture(tmp_path: Path) -> tuple[Path, Config, list[Path]]:
    """Create a minimal final-RTL and all-pass receipt fixture for documentation sync."""

    output = tmp_path / "output"
    rtl = output / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module dut(input wire a, output wire y); assign y = a; endmodule\n", encoding="utf-8")
    manifest_path = tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    rows = _hash_rows(tmp_path, [rtl])
    _write_json(
        manifest_path,
        {
            "schema_version": "1.4",
            "rtl_language": "verilog",
            "top_module": "dut",
            "rtl_sources": rows,
        },
    )
    validation_path = output / "reports" / "dut_final_all_tc_validation.json"
    _write_json(
        validation_path,
        {
            "schema_version": "1.0",
            "status": "pass",
            "same_test_cases": True,
            "test_case_count": 2,
            "test_source_sha256": "a" * 64,
            "python": {"status": "pass"},
            "rtl": {"status": "pass"},
            "toffee_report": {
                "all_test_cases": True,
                "report_sha256": "b" * 64,
            },
        },
    )
    documents = [
        output / "dut_architecture.md",
        output / "dut_basic_info.md",
        output / "dut_design_needs_and_plan.md",
        output / "dut_functions_and_checks.md",
        output / "dut_design_summary.md",
    ]
    for document in documents:
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text("# dut\n\nThe final RTL module is dut.\n", encoding="utf-8")
    return tmp_path, _config(), documents
