"""Check distinct restored stage gates against actual files and controlled receipts."""

from copy import deepcopy
from pathlib import Path

import pytest

from toffee_ut.audit import audit_project, read_spec
from toffee_ut.checkers import ToffeeUTBatchChecker
from toffee_ut.paths import digest, write_json
from toffee_ut.project import inspect_inputs
from toffee_ut.plugin import get_plugin
from ucagent.core.agent.configuration import resolve_task_configuration
from ucagent.core.plugins import LoadedPlugin


def prepare_design(project, contract_writer):
    """Attach one real fixture source to each original function group and checkpoint."""
    root = project / "ut_project"
    design_path = root / "docs/spec/design/Block.md"
    design = read_spec(design_path, "design", "Block")
    design["behavior_groups"] = [{"id": "G1", "behavior": "Input identity",
                                  "source": "inputs/interface.md", "responsibility": "Block",
                                  "requirements": ["R1"]}]
    design["checkpoints"] = [{"id": "C1", "requirement": "R1",
                              "stimulus": "Offer one input", "observation": "Accepted response",
                              "comparison": "Compare input identity with output"}]
    contract_writer(design_path, design)
    spec_path = root / "docs/spec/verification/Block.md"
    spec = read_spec(spec_path, "verification", "Block")
    spec["behavior_matrix"] = [{"scenario": "S1", "outcome": "normal response", "status": "planned"}]
    contract_writer(spec_path, spec)
    return root


def test_original_design_gates_are_separate_and_fingerprint_current_sources(project, contract_writer):
    """A typed fixture can progress through each gate, but cannot invent missing line mapping."""
    root = project / "ut_project"
    inventory = inspect_inputs(project, "Block", documents=["inputs/interface.md"],
                               rtl_dirs=["inputs/Block.sv"], mode="provided")
    write_json(root / "results/input_inventory.json", inventory)
    assert audit_project(project, "Block", phase="requirements")["ok"]
    assert audit_project(project, "Block", phase="dut")["ok"]
    assert "behavior_groups" in audit_project(project, "Block", phase="groups")["error"]
    root = prepare_design(project, contract_writer)
    for phase in ("groups", "points", "checkpoints", "refine"):
        assert audit_project(project, "Block", phase=phase)["ok"], phase
    assert not audit_project(project, "Block", phase="line_map")["ok"]
    input_file = project / "inputs/interface.md"
    contract_writer(root / "docs/spec/verification/Block-line-map.md", {
        "kind": "line_map", "dut": "Block",
        "sources": [{"path": "inputs/interface.md", "sha256": digest(input_file),
                     "lines": [{"start": 1, "end": len(input_file.read_text().splitlines()),
                                "checkpoint": "C1"}]}]})
    assert audit_project(project, "Block", phase="line_map")["ok"]
    input_file.write_text(input_file.read_text() + "New requirement not mapped\n")
    assert "Input changed" in audit_project(project, "Block", phase="line_map")["error"]


def test_static_review_requires_every_real_rtl_file_and_candidate_disposition(project, contract_writer):
    """Static text is a scoped hypothesis, not an invented DUT failure."""
    root = prepare_design(project, contract_writer)
    inventory = inspect_inputs(project, "Block", documents=[], rtl_dirs=["inputs/Block.sv"], mode="derive")
    write_json(root / "results/input_inventory.json", inventory)
    path = root / "docs/reviews/Block-static-review.md"
    contract_writer(path, {"kind": "static_review", "dut": "Block", "sources": [], "candidates": []})
    assert not audit_project(project, "Block", phase="static")["ok"]
    source = project / "inputs/Block.sv"
    review = {"kind": "static_review", "dut": "Block",
              "sources": [{"path": "inputs/Block.sv", "sha256": digest(source),
                           "review": "No state transition in the controlled fixture"}], "candidates": []}
    contract_writer(path, review)
    assert audit_project(project, "Block", phase="static")["ok"]
    assert audit_project(project, "Block", phase="static_validation")["ok"]
    review["candidates"] = [{"id": "S1", "source": "inputs/Block.sv",
                             "line": 1, "hypothesis": "Potential incorrect output"}]
    contract_writer(path, review)
    assert not audit_project(project, "Block", phase="static_validation")["ok"]
    review["candidates"][0].update(status="unconfirmed", evidence="No RTL execution for this hypothesis")
    contract_writer(path, review)
    assert audit_project(project, "Block", phase="static_validation")["ok"]
    review["sources"][0]["sha256"] = "0" * 64
    contract_writer(path, review)
    assert "stale" in audit_project(project, "Block", phase="static")["error"]
    review["sources"][0]["sha256"] = digest(source)
    review["candidates"][0].update(status="rtl", evidence="This comment looks wrong")
    contract_writer(path, review)
    assert "WaveInfo" in audit_project(project, "Block", phase="static_validation")["error"]
    review["candidates"] = []
    review["sources"].append(dict(review["sources"][0]))
    contract_writer(path, review)
    assert "every inventoried" in audit_project(project, "Block", phase="static")["error"]


def test_original_wrapper_coverage_and_selftest_gates_reject_pure_python_pass(project, contract_writer, checked_evidence):
    """No native fixture, coverage or stage-specific selftests may be inferred from a PASS count."""
    prepare_design(project, contract_writer)
    for phase in ("wrapper", "fixture", "bundle", "environment_impl", "coverage_groups", "coverage_points",
                  "coverage_checks", "env_selftest", "model_fixture", "api_tests"):
        result = audit_project(project, "Block", phase=phase)
        assert not result["ok"], (phase, result)
        assert result["error_code"] and result["next_action"]
    source = project / "ut_project/testbenches/block/tests/test_contract.py"
    source.write_text(source.read_text().replace('pytest.mark.scenario("S1")',
        'pytest.mark.envcheck\n@pytest.mark.scenario("S1")'))
    assert not audit_project(project, "Block", phase="env_selftest")["ok"]


def test_outcome_matrix_requires_each_scenario_and_reasoned_gap(project, contract_writer):
    """A matrix entry cannot silently omit a scenario or call an unknown status passed."""
    root = prepare_design(project, contract_writer)
    path = root / "docs/spec/verification/Block.md"
    value = read_spec(path, "verification", "Block")
    value["behavior_matrix"] = [{"scenario": "S1", "outcome": "failure", "status": "gap"}]
    contract_writer(path, value)
    assert "reason" in audit_project(project, "Block", phase="refine")["error"]
    value["behavior_matrix"][0]["reason"] = "Response domain not exposed; request a producer contract"
    contract_writer(path, value)
    assert audit_project(project, "Block", phase="refine")["ok"]
    value = deepcopy(value)
    value["behavior_matrix"][0]["scenario"] = "unknown"
    contract_writer(path, value)
    assert not audit_project(project, "Block", phase="refine")["ok"]


@pytest.mark.parametrize("enabled", [False, True])
def test_optional_original_stages_remain_present_and_explicit(project, monkeypatch, enabled):
    """Model, Mock, line coverage and human approval are optional, never removed."""
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(project / "home"))
    flags = {f"runtime_options.{name}": enabled for name in (
        "ut_reference_model", "ut_mock_components", "ut_line_coverage",
        "ut_human_env_spec_review", "ut_human_env_review")}
    result = resolve_task_configuration(str(project), "Block", plugins=[LoadedPlugin(get_plugin(), "toffee-ut", "test")],
                                        plugin_workflow="toffee-ut:ut", cfg_override=[flags])
    stages = {stage.name: stage for stage in result.cfg.stage}
    assert stages["reference_model_implementation"].skip is not enabled
    assert stages["reference_model_fixture_imp"].skip is not enabled
    assert stages["line_coverage_analysis_and_improvement"].skip is not enabled
    env = {stage.name: stage for stage in stages["test_environment_implementation"].stage}
    for name in ("mock_design_and_implementation", "mock_fixture_implementation",
                 "mock_functional_test", "human_check_env_specification",
                 "human_check_env_implementation"):
        assert env[name].skip is not enabled
    assert env["mock_functional_test"].stage[0].skip is not enabled
    for name in ("human_check_env_specification", "human_check_env_implementation"):
        assert [gate.clss for gate in env[name].checker] == ["ToffeeUTChecker", "HumanChecker"]
    assert not stages["static_bug_analysis"].has_attr("skip")


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_optional_stage_flags_reject_ambiguous_types(project, monkeypatch, value):
    """Invalid booleans must not silently enable or disable original stages."""
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(project / "home"))
    with pytest.raises(ValueError, match="ut_mock_components must be true or false"):
        resolve_task_configuration(str(project), "Block", plugins=[LoadedPlugin(get_plugin(), "toffee-ut", "test")],
                                   plugin_workflow="toffee-ut:ut", cfg_override=[{"runtime_options.ut_mock_components": value}])


def test_static_batch_tracks_each_source_without_trusting_old_progress(project, contract_writer):
    """A reviewed first RTL file cannot stand in for another or for changed input bytes."""
    second = project / "inputs/Other.sv"
    second.write_text("// Second source for the original static-analysis batch.\n")
    root = project / "ut_project"
    write_json(root / "results/input_inventory.json", inspect_inputs(
        project, "Block", documents=[], rtl_dirs=["inputs/Block.sv", "inputs/Other.sv"], mode="derive"))
    review_path = root / "docs/reviews/Block-static-review.md"
    row = {"path": "inputs/Block.sv", "sha256": digest(project / "inputs/Block.sv"),
           "review": "No state transition in first source; no actual DUT assertion"}
    review = {"kind": "static_review", "dut": "Block", "sources": [row], "candidates": []}
    contract_writer(review_path, review)
    checker = ToffeeUTBatchChecker(phase="static", project="ut_project", dut="Block", batch_size=1)
    checker.set_workspace(str(project))
    initial, completed = checker._current_items()
    assert len(initial) == 2 and completed == ["inputs/Block.sv"]
    passed, progress = checker.do_check(is_complete=True)
    assert not passed and "Other.sv" in str(progress)
    review["sources"].append({"path": "inputs/Other.sv", "sha256": digest(second),
                              "review": "Inspected the second source independently"})
    contract_writer(review_path, review)
    assert checker.do_check(is_complete=True)[0]
    second.write_text(second.read_text() + "// Source changed after review.\n")
    result = checker.do_check(is_complete=True)
    assert not result[0] and "UTProject(action='inspect')" in str(result)


def test_no_document_has_explicit_line_map_skip_and_no_false_batch_success(project, monkeypatch):
    """A missing source leaves a visible stage, not an invented mapping or an empty batch PASS."""
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(project / "home"))
    result = resolve_task_configuration(str(project), "Block", plugins=[LoadedPlugin(get_plugin(), "toffee-ut", "test")],
                                        plugin_workflow="toffee-ut:ut",
                                        cfg_override=[{"runtime_options.ut_documents": [],
                                                       "runtime_options.ut_rtl_dirs": ["inputs/Block.sv"]}])
    parent = next(row for row in result.cfg.stage if row.name == "functional_specification_analysis")
    child = next(row for row in parent.stage if row.name == "functional_line_mapping_gap_analysis")
    assert child.skip is True and parent.checker[0].args.phase == "checkpoints"
    root = project / "ut_project"
    write_json(root / "results/input_inventory.json", inspect_inputs(
        project, "Block", documents=[], rtl_dirs=["inputs/Block.sv"], mode="derive"))
    checker = ToffeeUTBatchChecker(phase="line_map", project="ut_project", dut="Block")
    checker.set_workspace(str(project))
    passed, feedback = checker.do_check(is_complete=True)
    assert not passed and feedback["error_code"] == "UT_LINE_MAP_NO_DOCUMENTS"


def test_native_line_gap_and_random_seed_require_exact_run_evidence(project, checked_evidence, contract_writer, monkeypatch):
    """A controlled receipt tests gate logic, not native hardware or waveform proof."""
    root = prepare_design(project, contract_writer)
    monkeypatch.setattr("toffee_ut.stage_audit.current_run", lambda workspace, project: checked_evidence)
    monkeypatch.setattr("toffee_ut.stage_checks.line_coverage.current_run", lambda workspace, project: checked_evidence)
    source = project / "inputs/interface.md"
    review_file = root / "docs/reviews/Block-stage-evidence.md"
    lcov = root / "results/unit-audit-only/native/coverage.info"
    lcov.parent.mkdir(parents=True, exist_ok=True)
    lcov.write_text("SF:inputs/Block.sv\nDA:1,0\nDA:2,1\nend_of_record\n")
    checked_evidence["manifest"]["artifacts"].append({"kind": "lcov", "path": str(lcov)})
    review = {"kind": "stage_evidence", "dut": "Block", "reviews": {
         "line_coverage": {"source": "inputs/interface.md", "sha256": digest(source),
                          "run": checked_evidence["record"]["run"],
                          "observation": "Line one is not reached in this fixture",
                          "next_action": "Determine whether the line is a legal DUT obligation",
                          "uncovered": []}}}
    contract_writer(review_file, review)
    feedback = audit_project(project, "Block", phase="line_coverage")
    assert feedback["issue_kind"] == "review_incomplete"
    assert feedback["observed"]["unreviewed"]["line"] == 1
    error = feedback["error"]
    assert "Unreviewed native zero points" in error and "line" in error and "inputs/Block.sv" in error
    review["reviews"]["line_coverage"]["uncovered"] = [{"source": "inputs/Block.sv",
        "line": 1, "status": "gap", "reason": "Add a legal directed stimulus and rerun"}]
    contract_writer(review_file, review)
    assert not audit_project(project, "Block", phase="line_coverage")["ok"]
    review["reviews"]["line_coverage"]["uncovered"][0].update(status="justified", reason="Independent fixture contract excludes this path")
    contract_writer(review_file, review)
    assert audit_project(project, "Block", phase="line_coverage")["ok"]
    review["reviews"]["random"] = {"source": "inputs/interface.md", "sha256": digest(source),
        "observation": "Random test may explore identities", "next_action": "Confirm native argv seed",
        "strategies": [{"scenario": "S1", "status": "tested",
                         "nodeid": "testbenches/block/tests/test_contract.py::test_value"}]}
    contract_writer(review_file, review)
    assert not audit_project(project, "Block", phase="random")["ok"]
    case = next(iter(checked_evidence["cases"]["cases"].values()))
    case["roles"] = ["random"]
    case["declared_native_seed"] = checked_evidence["record"]["seed"]
    assert audit_project(project, "Block", phase="random")["ok"]
    case["declared_native_seed"] += 1
    assert not audit_project(project, "Block", phase="random")["ok"]
