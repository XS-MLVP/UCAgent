"""Focused DesignWithPPA workflow tests: design contract."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    PLUGIN_SOURCE,
    _config,
)

import json
from pathlib import Path
import subprocess
import pytest
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




@pytest.mark.parametrize(
    ("tag", "error_code"),
    [
        ("<FG-FP-1: Precision selection>", "design_label_identifier_invalid"),
        ("<FC-FP/ENCODE>", "design_label_identifier_invalid"),
        ("<CK-VALID>\n\n<CK-VALID>", "design_label_identifier_duplicate"),
    ],
)
def test_design_function_contract_requires_portable_unique_ids(
    tmp_path: Path,
    tag: str,
    error_code: str,
) -> None:
    """Descriptive tag text must be rejected before line-map identities are built."""

    contract = tmp_path / "functions.md"
    contract.write_text(f"\n# Functions\n\n## Entry\n\n{tag}\n", encoding="utf-8")
    checker = DesignFunctionalContractChecker(
        doc_file="functions.md"
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == error_code




def test_design_function_contract_accepts_ids_with_numeric_components(
    tmp_path: Path,
) -> None:
    """Portable dotted IDs remain available for Spec-derived naming schemes."""

    contract = tmp_path / "functions.md"
    contract.write_text(
        "\n# Functions\n\n"
        "## Precision\n\n<FG-FP-1>\n\n"
        "### Encoding\n\n<FC-FP-1.1>\n\n"
        "#### Zero\n\n<CK-FP4-ZERO>\n",
        encoding="utf-8",
    )
    checker = DesignFunctionalContractChecker(
        doc_file="functions.md"
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result




def test_design_function_contract_rejects_process_only_function_ck(
    tmp_path: Path,
) -> None:
    """Test machinery must remain a plan requirement rather than a DUT CK."""

    contract = tmp_path / "functions.md"
    contract.write_text(
        "\n# Functions\n\n"
        "## Arithmetic\n\n<FG-ARITH>\n\n"
        "### Add\n\n<FC-ADD>\n\n"
        "#### Directed vectors\n\n<CK-DIRECTED>\n\n"
        "A directed pytest test compares the backend with the reference.\n\n"
        "## Performance\n\n<FG-PPA>\n\n"
        "### Reports\n\n<FC-PPA-REPORT>\n\n"
        "#### Curve\n\n<CK-PPA-CURVE>\n\n"
        "Performance tests create sidecars and reports.\n",
        encoding="utf-8",
    )
    checker = DesignFunctionalContractChecker(
        doc_file="functions.md"
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_function_ck_describes_verification_process"
    observed = result["observed"]["checkpoints"]
    assert [item["checkpoint"] for item in observed] == [
        "FG-ARITH/FC-ADD/CK-DIRECTED"
    ]
    assert {item["term"] for item in observed[0]["terms"]} == {
        "pytest",
        "test",
    }




def test_refined_line_map_rejects_stale_ck_reference(tmp_path: Path) -> None:
    """A CK rename during refinement must update every affected Spec line map."""

    spec = tmp_path / "dut" / "spec" / "design.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("The public result must be observable.\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    contract = output / "dut_functions_and_checks.md"
    contract.write_text(
        "\n# Functions\n\n<FG-ARITH>\n\n"
        "## Add\n\n<FC-ADD>\n\n"
        "### Result\n\n<CK-RESULT>\n\nObserve the result.\n",
        encoding="utf-8",
    )
    line_map = output / "line_map" / "dut_spec_design_md_line_func_map.txt"
    line_map.parent.mkdir()
    line_map.write_text("FG-ARITH/FC-ADD/CK-RESULT: 1-1\n", encoding="utf-8")
    checker = DesignLineMapReferenceChecker(
        file_list=["dut/spec/**/*.md"],
        func_check_file="output/dut_functions_and_checks.md",
        map_location="output/line_map",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()
    assert passed is True, result

    contract.write_text(
        contract.read_text(encoding="utf-8").replace("CK-RESULT", "CK-FINAL"),
        encoding="utf-8",
    )
    passed, result = checker.do_check()

    assert passed is False
    assert "CK-RESULT" in json.dumps(result)




def test_architecture_checker_enforces_interface_timing_and_synthesis_contract(
    tmp_path: Path,
) -> None:
    """Architecture placeholders must not satisfy deterministic design gates."""

    architecture = {
        "schema_version": "1.0",
        "rtl_language": "verilog",
        "top_module": "dut",
        "parameters": [
            {
                "name": "WIDTH",
                "type": "integer",
                "default": 8,
                "valid_range": "1..64",
            }
        ],
        "ports": [
            {
                "name": "input_i",
                "direction": "input",
                "width": "WIDTH",
                "signed": False,
                "role": "operand",
            },
            {
                "name": "output_o",
                "direction": "output",
                "width": "WIDTH",
                "signed": False,
                "role": "result",
            },
        ],
        "design_intent": "combinational",
        "clock_reset": {
            "clocks": [],
            "resets": [],
            "rationale": "The output is a pure function of the input.",
        },
        "timing": {
            "transaction_accept": "input_i is sampled continuously",
            "response": "output_o settles combinationally",
            "handshake": "none",
            "latency_cycles": 0,
            "backpressure": "none",
        },
        "illegal_inputs": {"policy": "X and Z are outside the contract."},
        "multi_clock_cdc": {"clock_domains": 0, "policy": "No CDC exists."},
        "synthesis_constraints": {
            "synthesizable_only": True,
            "no_latch": True,
            "no_unknown_outputs": True,
            "no_initial_delay": True,
            "forbidden_constructs": [
                "delay",
                "force",
                "release",
                "simulation-system-task",
            ],
        },
        "acceptance_criteria": ["output_o equals input_i"],
    }
    architecture_path = tmp_path / "output" / "dut_architecture.md"
    architecture_path.parent.mkdir(parents=True)
    checker = DesignArchitectureChecker(
        architecture_file="output/dut_architecture.md",
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    def write_contract(value: dict) -> None:
        """Write one complete fenced architecture fixture."""

        architecture_path.write_text(
            "\n# DUT Architecture\n\n```yaml\n"
            + yaml.safe_dump({"architecture": value}, sort_keys=False)
            + "```\n",
            encoding="utf-8",
        )

    write_contract(architecture)
    passed, _ = checker.do_check()
    assert passed is True

    sequential = json.loads(json.dumps(architecture))
    sequential["ports"].extend(
        [
            {
                "name": "clk_i",
                "direction": "input",
                "width": 1,
                "signed": False,
                "role": "clock",
            },
            {
                "name": "rst_ni",
                "direction": "input",
                "width": 1,
                "signed": False,
                "role": "reset",
            },
        ]
    )
    sequential["design_intent"] = "sequential"
    sequential["clock_reset"] = {
        "clocks": [{"name": "clk_i", "edge": "posedge"}],
        "resets": [
            {
                "name": "rst_ni",
                "active_level": "low",
                "synchrony": "synchronous",
                "clock": "clk_i",
                "sample_edge": "posedge",
            }
        ],
        "rationale": "State and reset are sampled on the rising clock edge.",
    }
    sequential["multi_clock_cdc"] = {
        "clock_domains": 1,
        "policy": "All state is in the clk_i domain.",
    }
    write_contract(sequential)
    passed, _ = checker.do_check()
    assert passed is True

    invalid_reset_edge = json.loads(json.dumps(sequential))
    invalid_reset_edge["clock_reset"]["resets"][0]["sample_edge"] = "rising"
    write_contract(invalid_reset_edge)
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "design_architecture_invalid"
    assert "must be posedge or negedge" in result["error"]

    invalid_cases = []
    for label in (
        "missing handshake",
        "missing parameter range",
        "unsafe synthesis setting",
        "sequential without a clock",
    ):
        value = json.loads(json.dumps(architecture))
        if label == "missing handshake":
            value["timing"].pop("handshake")
        elif label == "missing parameter range":
            value["parameters"][0].pop("valid_range")
        elif label == "unsafe synthesis setting":
            value["synthesis_constraints"]["no_latch"] = False
        else:
            value["design_intent"] = "sequential"
            value["multi_clock_cdc"]["clock_domains"] = 1
        invalid_cases.append((label, value))

    for label, value in invalid_cases:
        write_contract(value)
        passed, result = checker.do_check()
        assert passed is False, label
        assert result["error_code"] == "design_architecture_invalid"
        assert result["next_action"]




def test_function_contract_guidance_requires_complete_unique_ck_tree() -> None:
    """Input labels must not be mistaken for an already complete FG/FC/CK tree."""

    guide = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "Guide_Doc"
        / "design_input_and_architecture.md"
    ).read_text(encoding="utf-8")
    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    ).read_text(encoding="utf-8")

    assert "每个 FG 至少包含一个 FC" in guide
    assert "每个 FC 至少包含一个可验证 CK" in guide
    assert "每个标签 ID 在全文唯一" in guide
    assert "不是可脱离原文自由编写的设计说明" in guide
    assert "输入中缺失、复用或不规范的标签必须补齐或拆分" in workflow
    assert "不得手工创建或编辑内部批次状态" in workflow




def test_design_input_change_invalidates_downstream_regression_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed Spec must invalidate later evidence until input analysis is rerun."""

    readme = tmp_path / "dut" / "README.md"
    spec = tmp_path / "dut" / "spec" / "design.md"
    spec.parent.mkdir(parents=True)
    readme.write_text("Design requirements.\n", encoding="utf-8")
    spec.write_text("The output follows the input.\n", encoding="utf-8")
    input_checker = DesignInputContractChecker(
        readme_file="dut/README.md",
        spec_glob="dut/spec/**/*.md",
        manifest_file="output/reports/design_input_manifest.json",
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, _ = input_checker.do_check()
    assert passed is True
    test_dir = tmp_path / "output" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_dut_functional.py").write_text(
        "def test_dut_ok():\n    assert True\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._run_pytest",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed", stderr=""
        ),
    )
    spec.write_text("The output is the inverse of the input.\n", encoding="utf-8")
    regression = PythonReferenceRegressionChecker(
        test_dir="output/tests",
        test_glob="output/tests/test_dut_*.py",
        summary_file="output/reports/python.json",
        markdown_summary_file=None,
        timeout=10,
        input_manifest_file="output/reports/design_input_manifest.json",
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, result = regression.do_check()
    assert passed is False
    assert result["error_code"] == "python_regression_provenance_invalid"
    assert "design input source changed" in result["error"]
