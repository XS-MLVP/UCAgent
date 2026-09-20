"""Focused DesignWithPPA workflow tests: observation."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    _write_observation_fixture,
    _write_yaml,
)

from pathlib import Path
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




def test_observation_contract_and_instrumentation_are_static_and_complete(
    tmp_path: Path,
) -> None:
    """Observation gates cover every CK without importing workspace-authored Python."""

    _write_observation_fixture(tmp_path)
    contract_checker = DesignObservationContractChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
    ).set_workspace(str(tmp_path))
    instrumentation_checker = DesignObservationInstrumentationChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
        adapter_file="output/tests/dut_adapter.py",
        api_file="output/tests/dut_api.py",
    ).set_workspace(str(tmp_path))

    contract_passed, contract_result = contract_checker.do_check()
    instrumentation_passed, instrumentation_result = (
        instrumentation_checker.do_check()
    )

    assert contract_passed is True, contract_result
    assert contract_result["checkpoint_count"] == 1
    assert instrumentation_passed is True, instrumentation_result
    assert instrumentation_result["event_count"] == 1




def test_observation_contract_rejects_missing_ck_and_instrumentation(
    tmp_path: Path,
) -> None:
    """Missing CK mappings and missing event emitters fail with bounded diagnostics."""

    _write_observation_fixture(tmp_path)
    contract_path = tmp_path / "output" / "dut_observation_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    checkpoints = contract["observation_contract"]["checkpoints"]
    contract["observation_contract"]["checkpoints"] = []
    _write_yaml(contract_path, contract)
    contract_checker = DesignObservationContractChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
    ).set_workspace(str(tmp_path))

    passed, result = contract_checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_observation_contract_invalid"
    assert "missing=['FG-ARITH/FC-ADD/CK-RESULT']" in result["error"]

    contract["observation_contract"]["checkpoints"] = checkpoints
    _write_yaml(contract_path, contract)
    (tmp_path / "output" / "tests" / "dut_adapter.py").write_text(
        "class DutAdapter:\n"
        "    def __init__(self):\n"
        "        self.result_o = 0\n",
        encoding="utf-8",
    )
    (tmp_path / "output" / "tests" / "dut_api.py").write_text(
        "def api_dut_observe(env, max_cycles=4):\n"
        "    return env.result_o\n",
        encoding="utf-8",
    )
    instrumentation_checker = DesignObservationInstrumentationChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
        adapter_file="output/tests/dut_adapter.py",
        api_file="output/tests/dut_api.py",
    ).set_workspace(str(tmp_path))

    passed, result = instrumentation_checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_observation_instrumentation_invalid"
    assert "missing_events=['response_observed']" in result["error"]




def test_observation_contract_rejects_output_field_bound_to_input_pin(
    tmp_path: Path,
) -> None:
    """A public-output field cannot cite an architecture input as its source."""

    _write_observation_fixture(tmp_path)
    contract_path = tmp_path / "output" / "dut_observation_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["observation_contract"]["events"][0]["fields"][0][
        "source_refs"
    ] = ["operand_i"]
    _write_yaml(contract_path, contract)
    checker = DesignObservationContractChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_observation_contract_invalid"
    assert "source_refs do not match public_output" in result["error"]
    assert "operand_i" in result["error"]




def test_observation_instrumentation_rejects_docstring_only_event_field(
    tmp_path: Path,
) -> None:
    """Event field names in prose are not evidence of a real emitted keyword."""

    _write_observation_fixture(tmp_path)
    api_path = tmp_path / "output" / "tests" / "dut_api.py"
    api_path.write_text(
        "def api_dut_observe(env, max_cycles=4):\n"
        '    """Mention result=result without emitting an event field."""\n'
        "    return env.result_o\n",
        encoding="utf-8",
    )
    checker = DesignObservationInstrumentationChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
        adapter_file="output/tests/dut_adapter.py",
        api_file="output/tests/dut_api.py",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_observation_instrumentation_invalid"
    assert "missing_event_fields" in result["error"]
    assert "result" in result["error"]




def test_observation_instrumentation_requires_public_cycle_state(
    tmp_path: Path,
) -> None:
    """Cycle observations must bind to the adapter's canonical public cycle."""

    _write_observation_fixture(tmp_path)
    contract_path = tmp_path / "output" / "dut_observation_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    event = contract["observation_contract"]["events"][0]
    event["fields"].append(
        {
            "name": "latency_cycles",
            "source": "cycle_state",
            "source_refs": ["cycle"],
            "description": "Elapsed adapter cycles.",
        }
    )
    contract["observation_contract"]["checkpoints"][0]["fields"].append(
        "latency_cycles"
    )
    _write_yaml(contract_path, contract)
    api_path = tmp_path / "output" / "tests" / "dut_api.py"
    api_path.write_text(
        "def api_dut_observe(env, max_cycles=4):\n"
        "    result = env.result_o\n"
        "    env._record_response_observed(\n"
        "        1, 1, result=result, latency_cycles=1\n"
        "    )\n"
        "    return result\n",
        encoding="utf-8",
    )
    checker = DesignObservationInstrumentationChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
        adapter_file="output/tests/dut_adapter.py",
        api_file="output/tests/dut_api.py",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_observation_instrumentation_invalid"
    assert "source_refs do not match cycle_state" in result["error"]
    assert "cycle" in result["error"]




def test_observation_instrumentation_inherits_accepted_transaction_identity(
    tmp_path: Path,
) -> None:
    """Response evidence inherits accepted identity without duplicate call keywords."""

    _write_observation_fixture(tmp_path)
    contract_path = tmp_path / "output" / "dut_observation_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    events = contract["observation_contract"]["events"]
    events.insert(
        0,
        {
            "name": "transaction_accepted",
            "capture": "transaction_accept",
            "fields": [
                {
                    "name": "operand",
                    "source": "transaction_identity",
                    "source_refs": ["operand_i"],
                    "description": "Operand retained from the accepted request.",
                },
                {
                    "name": "accepted_at",
                    "source": "cycle_state",
                    "source_refs": ["cycle"],
                    "description": "Cycle at request acceptance.",
                },
            ],
        },
    )
    events[1]["fields"].append(
        {
            "name": "operand",
            "source": "transaction_identity",
            "source_refs": ["operand_i"],
            "description": "Operand inherited from the accepted request.",
        }
    )
    contract["observation_contract"]["checkpoints"][0]["fields"].append("operand")
    _write_yaml(contract_path, contract)
    adapter_path = tmp_path / "output" / "tests" / "dut_adapter.py"
    adapter_path.write_text(
        "class DutAdapter:\n"
        "    def __init__(self):\n"
        "        self.operand_i = 1\n"
        "        self.result_o = 2\n"
        "        self.cycle = 0\n\n"
        "    def _record_event(self, event, **data):\n"
        "        self.last_event_data = data\n\n"
        "    def _record_transaction_accepted(self, accepted_at, **identity):\n"
        "        self._record_event('transaction_accepted', **identity)\n"
        "        return 1\n\n"
        "    def _record_response_observed(self, transaction_id, response_at, **result):\n"
        "        self._record_event('response_observed', **result)\n",
        encoding="utf-8",
    )
    api_path = tmp_path / "output" / "tests" / "dut_api.py"
    api_path.write_text(
        "def api_dut_observe(env, max_cycles=4):\n"
        "    transaction_id = env._record_transaction_accepted(\n"
        "        env.cycle, operand=env.operand_i\n"
        "    )\n"
        "    result = env.result_o\n"
        "    env._record_response_observed(\n"
        "        transaction_id, env.cycle, result=result\n"
        "    )\n"
        "    return result\n",
        encoding="utf-8",
    )
    checker = DesignObservationInstrumentationChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
        adapter_file="output/tests/dut_adapter.py",
        api_file="output/tests/dut_api.py",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result




def test_observation_instrumentation_rejects_unaccepted_identity_field(
    tmp_path: Path,
) -> None:
    """A response cannot claim identity that no acceptance call persisted."""

    _write_observation_fixture(tmp_path)
    contract_path = tmp_path / "output" / "dut_observation_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    response = contract["observation_contract"]["events"][0]
    response["fields"].append(
        {
            "name": "operand",
            "source": "transaction_identity",
            "source_refs": ["operand_i"],
            "description": "Operand claimed as accepted identity.",
        }
    )
    contract["observation_contract"]["checkpoints"][0]["fields"].append("operand")
    _write_yaml(contract_path, contract)
    checker = DesignObservationInstrumentationChecker(
        contract_file="output/dut_observation_contract.yaml",
        doc_file="output/dut_functions_and_checks.md",
        architecture_file="output/dut_architecture.md",
        adapter_file="output/tests/dut_adapter.py",
        api_file="output/tests/dut_api.py",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "design_observation_instrumentation_invalid"
    assert "operand" in result["error"]
